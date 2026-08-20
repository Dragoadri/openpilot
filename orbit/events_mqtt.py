#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import time
from datetime import datetime, UTC
import os
import threading
from typing import Optional, Dict

import paho.mqtt.client as mqtt

from openpilot.common.params import Params


# Cooldown en segundos antes de re-enviar el mismo evento
EVENT_COOLDOWN_SECONDS = 12  # 12 segundos (entre 10-15 como se discutió)

# Cooldown más largo para eventos críticos de "TAKE CONTROL" para evitar spam
TAKE_CONTROL_COOLDOWN_SECONDS = 30  # 30 segundos para eventos de "TAKE CONTROL"

# Diccionario para trackear último envío de cada evento (basado en alert_type)
_event_last_sent: Dict[str, float] = {}  # alert_type -> timestamp último envío
_MAX_EVENT_HISTORY = 50  # Máximo de eventos en el historial para evitar crecimiento indefinido

# Cliente MQTT persistente
_mqtt_client: Optional[mqtt.Client] = None
_mqtt_connected = False
_mqtt_client_lock = threading.Lock()
_mqtt_broker: Optional[str] = None
_mqtt_port: Optional[int] = None
_mqtt_username: Optional[str] = None
_mqtt_password: Optional[str] = None


# Caché de la config del broker: _ensure_mqtt_client (que llama a _load_broker)
# se ejecuta en el hilo RT de selfdrived a 100 Hz por cada alerta que pasa el
# filtro, y leer+parsear el JSON en cada llamada metía I/O de disco en el loop
# de tiempo real (patrón commIssue). Con TTL de 5 s los cambios de config se
# siguen recogiendo casi en tiempo real sin tocar disco a 100 Hz.
_BROKER_CFG_TTL_S = 5.0
_broker_cfg_cache: Optional[tuple[str, int, Optional[str], Optional[str]]] = None
_broker_cfg_cache_ts = 0.0


def _load_broker() -> tuple[str, int, Optional[str], Optional[str]]:
  global _broker_cfg_cache, _broker_cfg_cache_ts
  now = time.monotonic()
  if _broker_cfg_cache is not None and (now - _broker_cfg_cache_ts) < _BROKER_CFG_TTL_S:
    return _broker_cfg_cache

  base_path = os.path.dirname(os.path.abspath(__file__))
  cfg_path = os.path.join(base_path, "config_mqtt.json")
  try:
    with open(cfg_path, "r") as f:
      cfg = json.load(f)
    broker = cfg.get("broker", "localhost")
    port = int(cfg.get("broker_port", 1883))
    # Credenciales MQTT opcionales (broker con auth). Vacio/ausente = anonimo.
    username = (cfg.get("username") or "").strip() or None
    password = cfg.get("password") or None
    result = (broker, port, username, password)
  except Exception:
    result = ("localhost", 1883, None, None)

  _broker_cfg_cache = result
  _broker_cfg_cache_ts = now
  return result


_dongle_id_cache: Optional[str] = None


def _get_dongle_id() -> str:
  # El DongleId no cambia durante una sesión; cacheamos para no construir un Params()
  # ni leer disco en cada alerta (send_alert se llama por ciclo de selfdrived a 100 Hz).
  global _dongle_id_cache
  if _dongle_id_cache is None:
    raw = Params().get("DongleId")
    _dongle_id_cache = raw if raw else "UnregisteredDevice"
  return _dongle_id_cache


def _on_mqtt_connect(client, userdata, flags, rc):
  global _mqtt_connected
  _mqtt_connected = (rc == 0)


def _on_mqtt_disconnect(client, userdata, rc):
  global _mqtt_connected
  _mqtt_connected = False


def _ensure_mqtt_client():
  """Inicializa (o reutiliza) un cliente MQTT persistente."""
  # _mqtt_connected debe estar en la declaracion global: sin ella, el
  # `_mqtt_connected = False` del except creaba una variable LOCAL muerta
  # y el flag global quedaba sin resetear.
  global _mqtt_client, _mqtt_connected, _mqtt_broker, _mqtt_port, _mqtt_username, _mqtt_password

  broker, port, username, password = _load_broker()

  with _mqtt_client_lock:
    needs_reinit = (
      _mqtt_client is None or
      broker != _mqtt_broker or
      port != _mqtt_port or
      username != _mqtt_username or
      password != _mqtt_password
    )

    if needs_reinit:
      try:
        if _mqtt_client is not None:
          _mqtt_client.loop_stop()
          _mqtt_client.disconnect()
      except Exception:
        pass

      client = mqtt.Client()
      client.max_queued_messages_set(0)  # No encolar mensajes en RAM si no hay conexión
      client.on_connect = _on_mqtt_connect
      client.on_disconnect = _on_mqtt_disconnect
      client.reconnect_delay_set(min_delay=1, max_delay=30)
      # Credenciales MQTT opcionales (broker con auth). None = anonimo.
      if username:
        client.username_pw_set(username, password)
      try:
        client.connect_async(broker, port, keepalive=60)
        client.loop_start()
        _mqtt_broker = broker
        _mqtt_port = port
        _mqtt_username = username
        _mqtt_password = password
        _mqtt_client = client
      except Exception:
        _mqtt_connected = False
        _mqtt_client = None

  return _mqtt_client


def _should_filter_event(title: str, message: str, priority: int, event_name: Optional[str], alert_type: Optional[str]) -> bool:
  """Filtra eventos según criterios específicos para reducir saturación MQTT.

  Solo se envían eventos que cumplan AL MENOS UNA de estas condiciones:
  1. Título contiene "TAKE CONTROL" o "Take Control"
  2. Título contiene "BRAKE" o "Pay Attention"
  3. Evento relacionado con cambio de carril (event_name contiene "laneChange")
  4. Prioridad >= 3 (MID, HIGH, HIGHEST)

  Args:
    title: Título del evento
    message: Mensaje del evento
    priority: Prioridad del evento (0-5)
    event_name: Nombre del evento (ej: "laneChange")
    alert_type: Tipo completo de alerta (ej: "laneChange/warning")

  Returns:
    True si el evento debe enviarse, False si debe filtrarse
  """
  # Normalizar strings para comparación case-insensitive
  title_upper = (title or "").upper()
  message_upper = (message or "").upper()
  event_name_lower = (event_name or "").lower()
  alert_type_lower = (alert_type or "").lower()

  # 1. Verificar eventos de "TAKE CONTROL"
  if "TAKE CONTROL" in title_upper:
    return True

  # 2. Verificar eventos de "BRAKE" o "Pay Attention"
  if "BRAKE" in title_upper or "PAY ATTENTION" in title_upper:
    return True

  # 3. Verificar eventos de cambio de carril
  if "lanechange" in event_name_lower or "lanechange" in alert_type_lower:
    return True

  # 4. Verificar prioridad >= 3 (MID, HIGH, HIGHEST)
  if priority >= 3:
    return True

  # Si no cumple ninguna condición, filtrar el evento
  return False


def _should_send_event(alert_type: str, title: Optional[str] = None) -> bool:
  """Verifica si se debe enviar un evento basado en el cooldown.

  Los eventos de "TAKE CONTROL" tienen un cooldown más largo para evitar spam.

  Args:
    alert_type: Tipo de alerta (ej: "controlsLagging/warning")
    title: Título del evento (opcional, para detectar eventos de "TAKE CONTROL")

  Returns:
    True si se debe enviar, False si está en cooldown
  """
  if not alert_type:
    return False

  current_time = time.time()
  last_sent = _event_last_sent.get(alert_type, 0)

  # Determinar el cooldown apropiado según el tipo de evento
  title_upper = (title or "").upper()
  is_take_control = "TAKE CONTROL" in title_upper

  # Usar cooldown más largo para eventos de "TAKE CONTROL"
  cooldown_seconds = TAKE_CONTROL_COOLDOWN_SECONDS if is_take_control else EVENT_COOLDOWN_SECONDS

  # Si nunca se ha enviado o ha pasado el cooldown, permitir envío
  if last_sent == 0 or (current_time - last_sent) >= cooldown_seconds:
    _event_last_sent[alert_type] = current_time

    # Limpiar eventos antiguos para evitar crecimiento indefinido de memoria
    if len(_event_last_sent) > _MAX_EVENT_HISTORY:
      # Eliminar los eventos más antiguos (más de 1 hora)
      cutoff_time = current_time - 3600
      keys_to_remove = [k for k, v in _event_last_sent.items() if v < cutoff_time]
      for k in keys_to_remove:
        del _event_last_sent[k]
    return True

  return False


def send_event_full(title: str,
                    message: str,
                    priority: int,
                    dongle_id: Optional[str] = None,
                    event_name: Optional[str] = None,
                    event_type: Optional[str] = None,
                    alert_type: Optional[str] = None) -> None:
  """Envía un evento completo por MQTT con toda su información.

  Args:
    title: Título del evento
    message: Mensaje del evento
    priority: Prioridad del evento (0-5)
    dongle_id: ID del dispositivo (opcional)
    event_name: Nombre del evento (ej: "controlsLagging")
    event_type: Tipo del evento (ej: "warning")
    alert_type: Tipo completo de alerta (ej: "controlsLagging/warning")
  """
  did = dongle_id or _get_dongle_id()
  topic = f"telemetry_mqtt/{did}/event"

  # VALIDACIÓN: No enviar eventos sin título ni mensaje
  title_stripped = (title or "").strip()
  message_stripped = (message or "").strip()
  if not title_stripped and not message_stripped:
    # Evento sin contenido, no enviar
    return

  # Construir alert_type si no se proporciona
  if not alert_type:
    if event_name and event_type:
      alert_type = f"{event_name}/{event_type}"
    elif event_name:
      alert_type = event_name
    else:
      alert_type = "unknown/unknown"

  # FILTRO: Solo enviar eventos que cumplan los criterios específicos
  if not _should_filter_event(title, message, priority, event_name, alert_type):
    # Evento filtrado, no enviar (reduce saturación MQTT)
    return

  client = _ensure_mqtt_client()

  # Si no hay cliente o la conexión aún no está establecida, no enviar para
  # evitar colas. IMPORTANTE: este check va ANTES de consumir el cooldown —
  # antes, un evento ocurrido sin conexión (siempre el primero tras arrancar,
  # porque connect_async es asíncrono) se perdía Y además suprimía los
  # reenvíos del mismo alert_type durante 12/30 s.
  if client is None or not _mqtt_connected:
    return

  # Verificar cooldown antes de enviar (con cooldown extendido para "TAKE CONTROL")
  if not _should_send_event(alert_type, title=title):
    # Evento en cooldown, no enviar
    return

  # Payload completo con toda la información del evento
  payload = {
    "dongle_id": did,
    "event_name": event_name or "",
    "event_type": event_type or "",
    "alert_type": alert_type,
    "title": title or "",
    "message": message or "",
    "priority": priority,
    # Mismo formato de cable que utcnow().isoformat()+"Z" (utcnow está deprecado en 3.12)
    "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
  }

  try:
    # Publicar utilizando el cliente persistente (QoS 0 para máximo rendimiento)
    client.publish(topic, json.dumps(payload), qos=0)
  except Exception:
    # Error silencioso para no afectar el loop de control
    pass


def send_alert(alert) -> None:
  """Send an Events.Alert-like object (envía evento completo con cooldown).

  Expects attributes: alert_text_1, alert_text_2, priority, alert_type, event_name, event_type
  """
  try:
    # Obtener información del alert
    alert_type = getattr(alert, "alert_type", "") or ""
    title = getattr(alert, "alert_text_1", "") or ""
    message = getattr(alert, "alert_text_2", "") or ""
    priority = getattr(alert, "priority", 0)

    # Extraer event_name y event_type desde alert_type si está en formato "eventName/eventType"
    event_name = None
    event_type = None
    if alert_type and "/" in alert_type:
      parts = alert_type.split("/", 1)
      event_name = parts[0] if len(parts) > 0 else None
      event_type = parts[1] if len(parts) > 1 else None
    elif alert_type:
      event_name = alert_type

    # Validar que tenemos alert_type
    if not alert_type:
      return

    # Enviar evento completo con cooldown
    send_event_full(
      title=title,
      message=message,
      priority=priority,
      event_name=event_name,
      event_type=event_type,
      alert_type=alert_type
    )

  except Exception:
    # No re-lanzar para no afectar el loop de control
    pass