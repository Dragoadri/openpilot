#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import time
import threading
import paho.mqtt.client as mqtt
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
import os

# Importar el módulo de velocidad una sola vez al inicio para evitar problemas de importación
try:
  import openpilot.sicuem.orbit.orbit_speed_ultra_simple as speed_module
  SPEED_MODULE_AVAILABLE = True
except ImportError:
  SPEED_MODULE_AVAILABLE = False

class MQTTComandos:
  def __init__(self):
    self.base_path = os.path.dirname(os.path.abspath(__file__))
    self.jsonConfig = os.path.join(self.base_path, "config_mqtt.json")
    self.params = Params()
    self.DongleID = self.params.get("DongleId") if self.params.get("DongleId") else "DongleID"  # Params.get() ya devuelve str
    self.conectado = False
    self.stop_event = threading.Event()
    # Archivo para guardar mensajes MQTT para modo debug
    self.debug_file = "/tmp/mqtt_debug_messages.txt"
    self.max_messages = 30  # Máximo de mensajes a guardar (reducido para ahorrar memoria)
    self.messages_lock = threading.Lock()
    # Inicializar debug_enabled leyendo el parámetro al inicio
    self.debug_enabled = self.params.get_bool("modo_debug")
    self._last_debug_check = time.time()  # Inicializar timestamp para la primera verificación
    self.camera_sender = None  # Referencia al CameraSender (se establece desde MQTTEnvioGeneral)
    self.load_config()
    self.init_mqtt()

  def load_config(self):
    with open(self.jsonConfig, "r") as f:
      config = json.load(f)
      self.broker_address = config.get("broker", "localhost")

  def init_mqtt(self):
    self.mqttc = mqtt.Client()
    self.mqttc.max_queued_messages_set(0)  # No encolar mensajes en RAM si no hay conexión
    self.mqttc.on_connect = self.on_connect
    self.mqttc.on_disconnect = self.on_disconnect
    self.mqttc.on_message = self.on_message
    self.mqttc.reconnect_delay_set(min_delay=1, max_delay=30)
    threading.Thread(target=self.setup_mqtt, daemon=True).start()

  def setup_mqtt(self):
    while not self.stop_event.is_set():
      try:
        cloudlog.warning(f"[Bemposta] MQTTComandos conectando a broker {self.broker_address}:1883")
        self.mqttc.connect(self.broker_address, 1883, 60)
        if not self.conectado:
          self.mqttc.loop_start()
          self.conectado = True
        break
      except Exception as e:
        cloudlog.warning(f"[Bemposta] MQTTComandos NO pudo conectar a {self.broker_address}:1883: {e}. Reintento en 5s")
        time.sleep(5)

  def reload_broker(self, new_broker):
    """Reconecta a un broker nuevo en caliente (lo llama MQTTEnvioGeneral cuando
    detecta que la IP cambio en config_mqtt.json). Evita tener que reiniciar."""
    if not new_broker or new_broker == self.broker_address:
      return
    cloudlog.warning(f"[Bemposta] MQTTComandos broker {self.broker_address} -> {new_broker}, reconectando")
    self.broker_address = new_broker
    try:
      self.mqttc.loop_stop()
    except Exception:
      pass
    try:
      self.mqttc.disconnect()
    except Exception:
      pass
    self.conectado = False
    threading.Thread(target=self.setup_mqtt, daemon=True).start()

  def on_connect(self, client, userdata, flags, rc):
    if rc == 0:
      self.conectado = True
      # Suscribirse a todos los comandos del sistema Orbit
      topics = [
        f"telemetry_config/{self.DongleID}/left",           # Cambio carril izquierda
        f"telemetry_config/{self.DongleID}/right",          # Cambio carril derecha
        f"telemetry_config/{self.DongleID}/control",        # Control básico (forward, break, tright, tleft)
        f"telemetry_config/{self.DongleID}/speed",          # Comandos de velocidad (formato JSON)
        f"telemetry_config/{self.DongleID}/speed_up",       # Comando aumentar velocidad (formato servidor)
        f"telemetry_config/{self.DongleID}/speed_down",     # Comando disminuir velocidad (formato servidor)
        f"telemetry_config/{self.DongleID}/speed_increment", # Configuración del incremento de velocidad (futuro)
        f"telemetry_config/{self.DongleID}/intervalos",      # Configuración intervalos
        f"telemetry_config/{self.DongleID}/overtake",        # Adelantamiento automático (detecta BSM automáticamente)
        f"telemetry_config/{self.DongleID}/brutebreak",      # Frenado de emergencia brusco
        f"telemetry_config/{self.DongleID}/camera_config",   # Configuración de cámara desde app ORBIT
        f"telemetry_config/{self.DongleID}/jetson_config",   # Configuracion de Jetson (por dongle_id)
        "jetson_config/global",                              # Configuracion de Jetson GLOBAL (desde cualquier app)
        f"telemetry_config/{self.DongleID}/steer_torque_mode", # Modo de torque del volante (por dongle_id)
        "steer_torque_mode/global",                          # Modo de torque del volante GLOBAL
        f"telemetry_config/{self.DongleID}/enroll_ack"       # Ack de enrolamiento ORBIT (backend → firmware)
      ]

      for topic in topics:
        client.subscribe(topic, qos=0)
      cloudlog.warning(f"[Bemposta] MQTTComandos CONECTADO (rc={rc}), suscrito a comandos para dongle={self.DongleID}")

  def on_disconnect(self, client, userdata, rc):
    self.conectado = False
    cloudlog.warning(f"[Bemposta] MQTTComandos DESCONECTADO del broker {self.broker_address} (rc={rc})")
    # print("🔌 MQTT Comandos desconectado. Reintentando...")  # Comentado para reducir uso de memoria

  def save_debug_message(self, topic, payload):
    """Guarda un mensaje MQTT para el modo debug. Optimizado para reducir uso de memoria."""
    # Solo guardar si el modo debug está activo
    try:
      # Verificar el estado del modo debug (cada 2 segundos para respuesta más rápida)
      current_time = time.time()
      if not hasattr(self, '_last_debug_check') or current_time - self._last_debug_check > 2.0:
        self.debug_enabled = self.params.get_bool("modo_debug")
        self._last_debug_check = current_time

      if not self.debug_enabled:
        return  # No guardar si el modo debug no está activo
    except Exception:
      return  # Si hay error, no guardar

    try:
      timestamp = time.strftime("%H:%M:%S", time.localtime())
      # Truncar payload si es muy largo (reducido a 50 caracteres para ahorrar memoria)
      payload_display = payload[:50] if len(payload) > 50 else payload
      # Formato: [timestamp] topic\npayload
      # El panel espera este formato exacto: primera línea con timestamp y topic, segunda línea con payload
      # Los mensajes se separan con \n\n cuando se escriben al archivo
      message = f"[{timestamp}] {topic}\n{payload_display}"

      with self.messages_lock:
        # Método optimizado: leer solo las últimas líneas necesarias
        messages = []
        if os.path.exists(self.debug_file):
          try:
            # Leer el archivo de forma más eficiente con límite de tamaño
            file_size = os.path.getsize(self.debug_file)
            # Si el archivo es muy grande (>100KB), truncarlo
            if file_size > 100 * 1024:
              # Leer solo las últimas líneas sin cargar todo el archivo
              with open(self.debug_file, 'rb') as f:
                f.seek(max(0, file_size - 50 * 1024))  # Leer solo los últimos 50KB
                content = f.read().decode('utf-8', errors='ignore')
                lines = content.split('\n')
            else:
              with open(self.debug_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Procesar desde el final hacia atrás
            i = len(lines) - 1
            temp_messages = []
            while i >= 0 and len(temp_messages) < self.max_messages:
              if lines[i].strip().startswith('['):
                if i > 0:
                  temp_messages.insert(0, (lines[i-1].strip() + '\n' + lines[i].strip()).strip())
                  i -= 2
                else:
                  i -= 1
              else:
                i -= 1
            messages = temp_messages
          except Exception:
            messages = []

        # Agregar nuevo mensaje
        messages.append(message.strip())

        # Mantener solo los últimos max_messages
        if len(messages) > self.max_messages:
          messages = messages[-self.max_messages:]

        # Escribir de vuelta (solo si hay mensajes)
        if messages:
          try:
            with open(self.debug_file, 'w', encoding='utf-8') as f:
              f.write('\n\n'.join(messages))
          except Exception:
            # Si falla la escritura, intentar crear el directorio si no existe
            try:
              os.makedirs(os.path.dirname(self.debug_file), exist_ok=True)
              with open(self.debug_file, 'w', encoding='utf-8') as f:
                f.write('\n\n'.join(messages))
            except Exception:
              pass  # Si sigue fallando, ignorar silenciosamente
    except Exception:
      pass  # Silenciar errores para no afectar el flujo principal

  def on_message(self, client, userdata, msg):
    """Callback que maneja los mensajes MQTT de comandos."""
    try:
      topic = msg.topic
      payload = msg.payload.decode(errors="ignore").strip()

      # Guardar mensaje para modo debug
      self.save_debug_message(topic, payload)

      # Comando de cambio de carril a la izquierda
      if topic.endswith("/left"):
        self.handle_lane_change_left(payload)

      # Comando de cambio de carril a la derecha
      elif topic.endswith("/right"):
        self.handle_lane_change_right(payload)

      # Comando de control básico (forward, break, tright, tleft)
      elif topic.endswith("/control"):
        self.handle_control_commands(payload)

      # Comando de velocidad (increase/decrease) - formato JSON
      elif topic.endswith("/speed"):
        self.handle_speed_commands(payload)

      # Comando de aumentar velocidad - formato servidor
      elif topic.endswith("/speed_up"):
        self.handle_speed_up_server(payload)

      # Comando de disminuir velocidad - formato servidor
      elif topic.endswith("/speed_down"):
        self.handle_speed_down_server(payload)

      # Comando de configuración del incremento de velocidad (para el futuro)
      elif topic.endswith("/speed_increment"):
        self.handle_speed_increment_config(payload)

      # Comando de intervalos
      elif topic.endswith("/intervalos"):
        self.handle_intervalos(payload)

      # Comando de adelantamiento automático (unificado, detecta BSM automáticamente)
      elif topic.endswith("/overtake"):
        self.handle_overtake(payload)

      # Comando de frenado de emergencia brusco
      elif topic.endswith("/brutebreak"):
        self.handle_brutebreak(payload)

      # Configuración de cámara desde app ORBIT
      elif topic.endswith("/camera_config"):
        self.handle_camera_config(payload)

      # Configuracion de Jetson desde app ORBIT
      elif topic.endswith("/jetson_config") or topic == "jetson_config/global":
        print(f"[JETSON SYNC] Recibido jetson_config en topic: {topic}")
        self.handle_jetson_config(payload)

      # Modo de torque del volante desde app ORBIT
      elif topic.endswith("/steer_torque_mode") or topic == "steer_torque_mode/global":
        print(f"[STEER MODE SYNC] Recibido steer_torque_mode en topic: {topic}")
        self.handle_steer_torque_mode(payload)

      # Ack de enrolamiento ORBIT (backend → firmware)
      elif topic.endswith("/enroll_ack"):
        self.handle_enroll_ack(payload)

    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_lane_change_left(self, payload):
    """Maneja el comando de cambio de carril a la izquierda.

    Acepta JSON {"ForceLaneChangeLeft": true/false} (app) o el string plano
    "true"/"false" (backend). Un boolean explícito manda: true activa, false
    cancela (antes la cancelación remota era imposible).
    """
    # NOTA: el gate c_carril se ha eliminado a propósito. La seguridad de
    # conducción (lateral_active, velocidad mínima, blindspot) vive ahora en
    # desire_helper, que sigue aplicando sus propios gates.
    try:
      import json

      # Intentar leer un boolean explícito del JSON de la app
      explicit = None
      try:
        data = json.loads(payload)
        if isinstance(data, dict) and "ForceLaneChangeLeft" in data:
          explicit = bool(data["ForceLaneChangeLeft"])
      except (json.JSONDecodeError, ValueError, TypeError):
        explicit = None

      if explicit is True:
        self.params.put_bool("ForceLaneChangeRight", False)
        self.params.put_bool("ForceLaneChangeLeft", True)
        return
      if explicit is False:
        # Cancelación explícita remota
        self.params.put_bool("ForceLaneChangeLeft", False)
        self.params.put_bool("ForceLaneChangeRight", False)
        return

      # Fallback: string plano del backend
      if payload == "false":
        self.params.put_bool("ForceLaneChangeLeft", False)
        self.params.put_bool("ForceLaneChangeRight", False)
      elif self.params.get_bool("ForceLaneChangeRight"):
        self.params.put_bool("ForceLaneChangeLeft", False)
        self.params.put_bool("ForceLaneChangeRight", False)
      else:
        self.params.put_bool("ForceLaneChangeLeft", True)
    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_lane_change_right(self, payload):
    """Maneja el comando de cambio de carril a la derecha.

    Acepta JSON {"ForceLaneChangeRight": true/false} (app) o el string plano
    "true"/"false" (backend). Un boolean explícito manda: true activa, false
    cancela (antes la cancelación remota era imposible).
    """
    # NOTA: el gate c_carril se ha eliminado a propósito. La seguridad de
    # conducción (lateral_active, velocidad mínima, blindspot) vive ahora en
    # desire_helper, que sigue aplicando sus propios gates.
    try:
      import json

      # Intentar leer un boolean explícito del JSON de la app
      explicit = None
      try:
        data = json.loads(payload)
        if isinstance(data, dict) and "ForceLaneChangeRight" in data:
          explicit = bool(data["ForceLaneChangeRight"])
      except (json.JSONDecodeError, ValueError, TypeError):
        explicit = None

      if explicit is True:
        self.params.put_bool("ForceLaneChangeLeft", False)
        self.params.put_bool("ForceLaneChangeRight", True)
        return
      if explicit is False:
        # Cancelación explícita remota
        self.params.put_bool("ForceLaneChangeLeft", False)
        self.params.put_bool("ForceLaneChangeRight", False)
        return

      # Fallback: string plano del backend
      if payload == "false":
        self.params.put_bool("ForceLaneChangeLeft", False)
        self.params.put_bool("ForceLaneChangeRight", False)
      elif self.params.get_bool("ForceLaneChangeLeft"):
        self.params.put_bool("ForceLaneChangeLeft", False)
        self.params.put_bool("ForceLaneChangeRight", False)
      else:
        self.params.put_bool("ForceLaneChangeRight", True)
    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_control_commands(self, payload):
    """Maneja los comandos de control básico (forward, break, tright, tleft)."""
    try:
      import json

      # Intentar parsear como JSON primero
      try:
        data = json.loads(payload)

        # Comando Forward (Arriba) / Break (Abajo).
        # forward/break se enrutan al MISMO mecanismo de velocidad (ya probado y
        # consumido por card.py en otro proceso) en vez de inyectar código nuevo
        # en el bucle de control. Son empujoncitos suaves de velocidad: el
        # solape semántico con speed_up/speed_down es intencionado por ahora.
        if data.get("forward"):
          self.params.put_bool("orbit_speed_increase", True)
          if SPEED_MODULE_AVAILABLE:
            speed_module.orbit_speed_increase = True

        if data.get("break"):
          self.params.put_bool("orbit_speed_decrease", True)
          if SPEED_MODULE_AVAILABLE:
            speed_module.orbit_speed_decrease = True

        # Comando Tright (Derecha) - formato JSON
        if data.get("tright"):
          # Activar giro temporal usando el nuevo sistema
          try:
            from openpilot.sicuem.orbit.orbit_steering_pulse import set_steering_pulse
            set_steering_pulse("right")
          except Exception as e:
            pass  # Error silenciado para reducir uso de memoria
          # Mantener compatibilidad con código viejo (opcional)
          try:
            from openpilot.sicuem.orbit.orbit_control_ultra_simple import orbit_tright
            orbit_tright = True
          except ImportError:
            pass

        # Comando Tleft (Izquierda) - formato JSON
        if data.get("tleft"):
          # Activar giro temporal usando el nuevo sistema
          try:
            from openpilot.sicuem.orbit.orbit_steering_pulse import set_steering_pulse
            set_steering_pulse("left")
          except Exception as e:
            pass  # Error silenciado para reducir uso de memoria
          # Mantener compatibilidad con código viejo (opcional)
          try:
            from openpilot.sicuem.orbit.orbit_control_ultra_simple import orbit_tleft
            orbit_tleft = True
          except ImportError:
            pass

      except json.JSONDecodeError:
        # Si no es JSON, tratar como string simple (formato servidor: "tleft" o "tright")
        payload_lower = payload.lower().strip()

        if payload_lower == "tright":
          # Activar giro temporal a la derecha usando variables globales
          try:
            from openpilot.sicuem.orbit.orbit_steering_pulse import set_steering_pulse
            set_steering_pulse("right")
          except Exception as e:
            pass  # Error silenciado para reducir uso de memoria

        elif payload_lower == "tleft":
          # Activar giro temporal a la izquierda usando variables globales
          try:
            from openpilot.sicuem.orbit.orbit_steering_pulse import set_steering_pulse
            set_steering_pulse("left")
          except Exception as e:
            pass  # Error silenciado para reducir uso de memoria

    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_speed_commands(self, payload):
    """Maneja los comandos de velocidad (increase/decrease) - formato JSON.

    IMPORTANTE: Solo funciona cuando el control longitudinal está activo (crucero activado).
    """
    try:
      import json
      data = json.loads(payload)

      # Aumentar velocidad
      if data.get("speed_increase"):
        # card.py corre en OTRO proceso y lee el Param, no el global -> siempre
        # ponemos el Param. El global se mantiene como fast-path mismo proceso.
        self.params.put_bool("orbit_speed_increase", True)
        if SPEED_MODULE_AVAILABLE:
          speed_module.orbit_speed_increase = True

      # Reducir velocidad
      if data.get("speed_decrease"):
        self.params.put_bool("orbit_speed_decrease", True)
        if SPEED_MODULE_AVAILABLE:
          speed_module.orbit_speed_decrease = True

    except json.JSONDecodeError:
      pass  # Error silenciado para reducir uso de memoria
    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_speed_up_server(self, payload):
    """Maneja el comando de aumentar velocidad - formato servidor/app.

    El servidor/app envía el comando cuando el usuario pulsa el botón "Aumentar".
    Formatos aceptados:
    - JSON: {'speed_up': true, 'timestamp': ...} (nuevo formato desde app)
    - String: "1", "+1", o cualquier string (formato antiguo del servidor)

    IMPORTANTE: Solo funciona cuando el control longitudinal está activo (crucero activado).
    """
    try:
      # Intentar parsear como JSON primero (nuevo formato desde app)
      try:
        data = json.loads(payload)
        if data.get("speed_up") is True:
          # Formato nuevo: JSON con speed_up: true. card.py corre en OTRO proceso
          # y lee el Param, no el global -> siempre ponemos el Param.
          self.params.put_bool("orbit_speed_increase", True)
          if SPEED_MODULE_AVAILABLE:
            speed_module.orbit_speed_increase = True
          return
      except (json.JSONDecodeError, AttributeError):
        # No es JSON, tratar como string (formato antiguo del servidor)
        # Aceptamos cualquier payload como válido para mantener compatibilidad
        self.params.put_bool("orbit_speed_increase", True)
        if SPEED_MODULE_AVAILABLE:
          speed_module.orbit_speed_increase = True

    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_speed_down_server(self, payload):
    """Maneja el comando de disminuir velocidad - formato servidor/app.

    El servidor/app envía el comando cuando el usuario pulsa el botón "Disminuir".
    Formatos aceptados:
    - JSON: {'speed_down': true, 'timestamp': ...} (nuevo formato desde app)
    - String: "1", "-1", o cualquier string (formato antiguo del servidor)

    IMPORTANTE: Solo funciona cuando el control longitudinal está activo (crucero activado).
    """
    try:
      # Intentar parsear como JSON primero (nuevo formato desde app)
      try:
        data = json.loads(payload)
        if data.get("speed_down") is True:
          # Formato nuevo: JSON con speed_down: true. card.py corre en OTRO proceso
          # y lee el Param, no el global -> siempre ponemos el Param.
          self.params.put_bool("orbit_speed_decrease", True)
          if SPEED_MODULE_AVAILABLE:
            speed_module.orbit_speed_decrease = True
          return
      except (json.JSONDecodeError, AttributeError):
        # No es JSON, tratar como string (formato antiguo del servidor)
        # Aceptamos cualquier payload como válido para mantener compatibilidad
        self.params.put_bool("orbit_speed_decrease", True)
        if SPEED_MODULE_AVAILABLE:
          speed_module.orbit_speed_decrease = True

    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_speed_increment_config(self, payload):
    """Maneja la configuración del incremento de velocidad desde la app.

    La app puede enviar el valor del incremento en km/h (ej: "10", "5", "20").
    Este valor se guarda en Params y será usado por el sistema de control de velocidad.

    Formato esperado: número como string (ej: "10" para 10 km/h)
    Rango válido: 1-50 km/h
    """
    try:
      increment = float(payload.strip())
      # Validar rango (1-50 km/h)
      if 1.0 <= increment <= 50.0:
        self.params.put("orbit_speed_increment", str(increment))
    except (ValueError, Exception):
      pass  # Error silenciado para reducir uso de memoria

  def handle_intervalos(self, payload):
    """Maneja el comando de intervalos."""
    try:
      import json
      data = json.loads(payload)

      if data.get("intervalos_toggle") == "true":
        self.params.put_bool("intervalos_toggle", True)
      elif data.get("intervalos_toggle") == "false":
        self.params.put_bool("intervalos_toggle", False)
      else:
        # Compatibilidad con formato anterior
        if payload.lower() == "true":
          self.params.put_bool("intervalos_toggle", True)
        elif payload.lower() == "false":
          self.params.put_bool("intervalos_toggle", False)
    except json.JSONDecodeError:
      # Fallback para formato simple
      if payload.lower() == "true":
        self.params.put_bool("intervalos_toggle", True)
      elif payload.lower() == "false":
        self.params.put_bool("intervalos_toggle", False)
    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def _apply_overtake(self, enable):
    """C1 (aprobado por el usuario, riesgo asumido, VALIDACION EN PISTA CERRADA
    OBLIGATORIA): 'overtake' == un UNICO cambio de carril a la izquierda, reusando
    el puente ForceLaneChangeLeft que ejecuta el modelo (desire_helper). Hereda
    sus gates (engaged+latActive, velocidad minima, leftBlindspot / ALC timer).

    NO es un adelantamiento completo: no vuelve al carril derecho ni sube la
    velocidad (eso es C2, pendiente). PELIGRO conocido: desire_helper NO comprueba
    trafico en sentido contrario ni si existe carril izquierdo; en doble sentido
    puede tirar hacia el trafico que viene de frente."""
    self.params.put_bool("sic_adelantar", bool(enable))
    if enable:
      # Disparo one-shot a la izquierda; card/desire_helper lo autoconsumen.
      self.params.put_bool("ForceLaneChangeRight", False)
      self.params.put_bool("ForceLaneChangeLeft", True)
    else:
      self.params.put_bool("ForceLaneChangeLeft", False)
      self.params.put_bool("ForceLaneChangeRight", False)

  def handle_overtake(self, payload):
    """Maneja el comando de activar/desactivar adelantamiento automático.

    El sistema detecta automáticamente si el coche tiene BSM disponible.
    Si tiene BSM, lo usa. Si no, funciona sin BSM.

    Formatos aceptados:
    - JSON completo (nuevo formato desde app v2.0):
      {
        "enabled": bool,
        "distancia_activacion": float,  // Metros (20-100, default 50)
        "tiempo_carril_izquierdo": float,  // Segundos (5-30, default 15)
        "incremento_velocidad": float,  // km/h (5-30, default 15)
        "timestamp": ...
      }
    - JSON simple: {'enabled': true, 'timestamp': ...} (formato antiguo)
    - String: "true" o "false" (formato simple)
    """
    try:
      # Intentar parsear como JSON primero (formato desde app)
      try:
        data = json.loads(payload)
        
        # Manejar enabled/disabled (C1: dispara cambio de carril izquierda)
        if data.get("enabled") is True:
          self._apply_overtake(True)
        elif data.get("enabled") is False:
          self._apply_overtake(False)
        
        # Guardar parámetros configurables si vienen en el payload
        # Distancia de activación (20-100 metros)
        if "distancia_activacion" in data:
          distancia = float(data["distancia_activacion"])
          if 20.0 <= distancia <= 100.0:
            self.params.put("overtake_distancia_activacion", str(distancia))
        
        # Tiempo en carril izquierdo (5-30 segundos)
        if "tiempo_carril_izquierdo" in data:
          tiempo = float(data["tiempo_carril_izquierdo"])
          if 5.0 <= tiempo <= 30.0:
            self.params.put("overtake_tiempo_carril_izq", str(tiempo))
        
        # Incremento de velocidad (5-30 km/h)
        if "incremento_velocidad" in data:
          incremento = float(data["incremento_velocidad"])
          if 5.0 <= incremento <= 30.0:
            self.params.put("overtake_incremento_velocidad", str(incremento))
            
      except (json.JSONDecodeError, AttributeError):
        # No es JSON, tratar como string simple (compatibilidad)
        if payload.lower() == "true":
          self._apply_overtake(True)
        elif payload.lower() == "false":
          self._apply_overtake(False)
    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_brutebreak(self, payload):
    """Maneja el comando de frenado de emergencia brusco.

    Cuando se recibe este comando, el coche frenará con la intensidad configurada.
    El frenado se mantiene activo durante un tiempo limitado para seguridad.

    Formatos aceptados:
    - JSON completo (nuevo formato desde app v2.0):
      {
        "brutebreak": true,
        "emergency": true,
        "intensidad_frenado": float  // Valor NEGATIVO (-1.0 a -10.0, default -3.5 m/s²)
        "timestamp": ...
      }
    - JSON simple: {'enabled': true, 'timestamp': ...} (formato antiguo)
    - String: "true" o "1" para activar, "false" o "0" para desactivar
    """
    try:
      # Intentar parsear como JSON primero (formato desde app)
      try:
        data = json.loads(payload)

        # Manejar activación/desactivación
        if data.get("enabled") is True or data.get("brutebreak") is True:
          self.params.put_bool("brutebreak_active", True)
        elif data.get("enabled") is False or data.get("brutebreak") is False:
          self.params.put_bool("brutebreak_active", False)

        # Guardar intensidad de frenado si viene en el payload
        # El valor ya viene negativo desde la app (-1.0 a -10.0 m/s²)
        if "intensidad_frenado" in data:
          intensidad = float(data["intensidad_frenado"])
          # Validar rango (debe ser negativo, entre -10.0 y -1.0)
          if -10.0 <= intensidad <= -1.0:
            self.params.put("brutebreak_intensidad", str(intensidad))
            
      except (json.JSONDecodeError, AttributeError):
        # No es JSON, tratar como string simple
        payload_lower = payload.lower().strip()
        if payload_lower in ("true", "1", "on"):
          self.params.put_bool("brutebreak_active", True)
        elif payload_lower in ("false", "0", "off"):
          self.params.put_bool("brutebreak_active", False)
    except Exception:
      pass  # Error silenciado para reducir uso de memoria

  def handle_jetson_config(self, payload):
    """Maneja la configuracion de Jetson recibida desde la app ORBIT.

    Actualiza config_jetson.json y reinicia el ZMQ client si es necesario.

    Topic: telemetry_config/{dongle_id}/jetson_config

    Payload esperado (campos opcionales):
    {
      "jetson_enabled": true|false,
      "jetson_ip": "192.168.1.50",
      "jetson_img_port": 5555,
      "jetson_torque_port": 5556,
      "jpeg_quality": 80,
      "_version": "1712345678901"   # opcional, ms desde epoch
    }

    Anti-eco en capas:
      1) source == "comma_ui"                  -> ignorar (retained propio).
      2) _version_entrante <= _version_local   -> ignorar (retained viejo).
      3) Sin cambios de campo                  -> no escribir a disco.

    Concurrencia:
      La lectura + escritura se protege con fcntl.flock para que un lector
      en otro proceso (UI Qt via QSaveFile, camera_sender.py) no observe un
      archivo a medio escribir ni haya doble escritura concurrente.
    """
    try:
      import fcntl
      import json as json_mod
      data = json_mod.loads(payload)
      print(f"[JETSON SYNC] handle_jetson_config data: {data}")

      # Anti-eco 1: el propio Comma publica retained al conectar a MQTT con
      # source="comma_ui". Si recibimos nuestro propio retained, ignorar.
      if data.get("source") == "comma_ui":
        print(f"[JETSON SYNC] Ignorado eco de comma_ui (propio retained)")
        return

      # Parsear _version entrante (si existe)
      incoming_version = None
      if "_version" in data:
        try:
          incoming_version = int(data["_version"])
        except (ValueError, TypeError):
          incoming_version = None

      # Lectura + escritura protegidas con filelock exclusivo.
      config_path = os.path.join(self.base_path, "config_jetson.json")
      lock_path = config_path + ".lock"

      # Abrir (o crear) el archivo de lock y adquirir lock exclusivo. Esto
      # bloquea a OTROS PROCESOS Python (mqtt_envio si concurriera) durante
      # la seccion critica. Nota: QSaveFile desde C++ usa tempfile+rename
      # que es atomico en el filesystem, asi que la UI no sufre lock pero
      # si lee durante nuestra escritura vera el contenido anterior completo.
      lock_fd = open(lock_path, 'w')
      try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

        # Leer config actual (dentro del lock)
        current_config = {}
        if os.path.exists(config_path):
          try:
            with open(config_path, 'r') as f:
              current_config = json_mod.load(f)
          except Exception:
            current_config = {}

        print(f"[JETSON SYNC] Config actual: {current_config}")

        # Anti-eco 2: comparar versiones. Si entrante <= local, descartar.
        local_version = 0
        if "_version" in current_config:
          try:
            local_version = int(current_config["_version"])
          except (ValueError, TypeError):
            local_version = 0

        if incoming_version is not None and incoming_version <= local_version:
          print(f"[JETSON SYNC] Ignorado: _version entrante {incoming_version} <= local {local_version} (retained viejo o eco)")
          return

        # Actualizar solo los campos recibidos
        changed = False
        for key in ["jetson_enabled", "jetson_ip", "comma_ip", "jetson_img_port", "jetson_torque_port", "jpeg_quality"]:
          if key in data:
            old_val = current_config.get(key)
            current_config[key] = data[key]
            if old_val != data[key]:
              changed = True
              print(f"[JETSON SYNC] Campo {key}: {old_val} -> {data[key]}")

        if not changed:
          print("[JETSON SYNC] Sin cambios de campo")
          return

        # Persistir _version: si el payload traia una, la conservamos; si no,
        # generamos una local (ms desde epoch) para marcar esta escritura.
        if incoming_version is not None:
          current_config["_version"] = str(incoming_version)
        else:
          current_config["_version"] = str(int(time.time() * 1000))

        # Escritura atomica: escribimos a .tmp y renombramos. Esto evita que
        # un lector vea el archivo a medio escribir.
        tmp_path = config_path + ".tmp"
        with open(tmp_path, 'w') as f:
          json_mod.dump(current_config, f, indent=4)
          f.flush()
          os.fsync(f.fileno())
        os.replace(tmp_path, config_path)
        print(f"[JETSON SYNC] config_jetson.json actualizado: {current_config}")

        # Señalizar al CameraSender que debe recargar la config.
        # NO llamamos reload_jetson_config() directamente desde este hilo
        # (thread de paho-mqtt). El CameraSender corre en su propio hilo y
        # estaria usando self.zmq_client.send_image en paralelo; un reload
        # desde fuera causaba race condition con el socket siendo cerrado
        # a la vez que otro hilo lo usa. En su lugar ponemos un flag y
        # dejamos que el propio loop del CameraSender se recargue en su
        # siguiente iteracion (mismo mecanismo que usa la UI Qt del Comma).
        self.params.put_bool("JetsonConfigChanged", True)
        print("[JETSON SYNC] flag JetsonConfigChanged=True (el CameraSender recargara en su loop)")
      finally:
        try:
          fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except Exception:
          pass
        lock_fd.close()

    except Exception as e:
      print(f"[JETSON SYNC] ERROR handle_jetson_config: {e}")

  def handle_steer_torque_mode(self, payload):
    """Maneja el cambio del modo de torque del volante desde la app ORBIT.

    Topics:
      - telemetry_config/{dongle_id}/steer_torque_mode
      - steer_torque_mode/global

    Payload esperado:
    {
      "dongle_id": "xxx",
      "steer_torque_mode": 0|1|2|3,
      "apply_target": "curvature"|"torque",   # obligatorio cuando mode == 3
      "source": "app" | "comma_ui"
    }

    Modos:
      0 = MODELO COMMA
      1 = JETSON
      2 = TEST MAX
      3 = COMMA + JETSON (esquive obstaculos)

    Para mode == 3, apply_target indica donde se aplica el esquive:
      - "curvature": suma offset a desired_curvature (comportamiento histórico).
      - "torque":    pisa actuators.steer cuando obstacle=true.
    Si mode == 3 llega sin apply_target válido, el payload se descarta.
    """
    try:
      import json as json_mod
      data = json_mod.loads(payload)

      # Evitar eco: si el mensaje viene del propio Comma, ignorarlo
      if data.get("source") == "comma_ui":
        print(f"[STEER MODE SYNC] Ignorado eco de comma_ui")
        return

      if "steer_torque_mode" not in data:
        print(f"[STEER MODE SYNC] Payload sin 'steer_torque_mode', ignorado")
        return

      try:
        mode = int(data["steer_torque_mode"])
      except (ValueError, TypeError):
        print(f"[STEER MODE SYNC] Valor invalido: {data.get('steer_torque_mode')}")
        return

      if mode not in (0, 1, 2, 3):
        print(f"[STEER MODE SYNC] Modo fuera de rango: {mode}")
        return

      # Para modo 3, exigir apply_target válido. Sin él no podemos
      # determinar cómo aplicar el esquive -> rechazo limpio.
      apply_target = None
      if mode == 3:
        apply_target = data.get("apply_target")
        if apply_target not in ("curvature", "torque"):
          print(f"[STEER MODE SYNC] mode=3 sin apply_target válido (recibido={apply_target!r}), payload ignorado")
          return

      # Leer el valor actual para detectar cambios reales
      current = self.params.get("SteerTorqueMode")
      current_str = current if current else ""
      new_str = str(mode)

      # Sub-target: detectar también cambios sobre el mismo modo 3.
      current_target = self.params.get("JetsonObstacleApplyTarget")
      current_target_str = current_target if current_target else ""
      target_changed = (mode == 3) and (apply_target != current_target_str)

      if current_str == new_str and not target_changed:
        print(f"[STEER MODE SYNC] Sin cambios (ya en modo {mode}"
              + (f", apply_target={apply_target}" if mode == 3 else "") + ")")
        return

      if mode == 3:
        self.params.put("JetsonObstacleApplyTarget", apply_target)
        print(f"[STEER MODE SYNC] JetsonObstacleApplyTarget actualizado: {current_target_str!r} -> {apply_target!r}")

      self.params.put("SteerTorqueMode", new_str)
      print(f"[STEER MODE SYNC] SteerTorqueMode actualizado: {current_str} -> {new_str}")

    except Exception as e:
      print(f"[STEER MODE SYNC] ERROR handle_steer_torque_mode: {e}")

  def handle_enroll_ack(self, payload):
    """Maneja el ack de enrolamiento ORBIT enviado por el backend.

    Topic:
      - telemetry_config/{dongle_id}/enroll_ack

    Payload esperado:
    {
      "claimed": true,
      "user_id": <int>,
      "ts": "<iso8601>"
    }

    Al recibir claimed=True marcamos el dispositivo como reclamado
    (OrbitClaimed persiste tras reboot) y borramos el código de emparejamiento
    para dejar de anunciarlo y ocultar el QR. No hace falta anti-eco: el
    firmware nunca publica enroll_ack.
    """
    try:
      import json as json_mod
      data = json_mod.loads(payload)

      if data.get("claimed") is True:
        self.params.put_bool("OrbitClaimed", True)
        self.params.remove("OrbitPairingCode")
        cloudlog.warning(f"[ORBIT ENROLL] Dispositivo reclamado (user_id={data.get('user_id')}, ts={data.get('ts')})")
        print(f"[ORBIT ENROLL] Dispositivo reclamado, OrbitClaimed=True")
      else:
        print(f"[ORBIT ENROLL] enroll_ack sin claimed=True, ignorado: {data}")

    except Exception as e:
      print(f"[ORBIT ENROLL] ERROR handle_enroll_ack: {e}")

  def set_camera_sender(self, camera_sender):
    """Establece la referencia al CameraSender para control remoto desde la app."""
    self.camera_sender = camera_sender

  def handle_camera_config(self, payload):
    """Maneja la configuración de cámara recibida desde la app ORBIT.

    Topic: telemetry_config/{dongle_id}/camera_config

    Payload esperado (campos opcionales):
    {
      "dongle_id": "abc123",
      "timestamp": "2026-03-10T14:30:00.000Z",
      "image_sending_enabled": true|false,
      "send_frequency_seconds": 1|2|5|10|30|60,
      "save_images": true|false  (informativo, no afecta al comma)
    }
    """
    if self.camera_sender is None:
      return

    try:
      data = json.loads(payload)

      # Mensajes descriptivos para el panel debug antes de aplicar
      if "image_sending_enabled" in data:
        enabled = data["image_sending_enabled"]
        self.save_debug_message(
          f"telemetry_config/{self.DongleID}/cam_envio",
          "true" if enabled else "false"
        )

      if "send_frequency_seconds" in data:
        freq = data["send_frequency_seconds"]
        self.save_debug_message(
          f"telemetry_config/{self.DongleID}/cam_freq",
          str(freq) + "s"
        )

      if "save_images" in data:
        save = data["save_images"]
        self.save_debug_message(
          f"telemetry_config/{self.DongleID}/cam_guardar",
          "true" if save else "false"
        )

      if "camera_type" in data:
        ct = data["camera_type"]
        self.save_debug_message(
          f"telemetry_config/{self.DongleID}/cam_tipo",
          str(ct)
        )

      # Mapear preferred_camera_type -> camera_type para compatibilidad con la app
      if "preferred_camera_type" in data and "camera_type" not in data:
        data["camera_type"] = data["preferred_camera_type"]

      self.camera_sender.apply_config(data)
    except (json.JSONDecodeError, Exception):
      pass

  def start(self):
    """Inicia el cliente MQTT de comandos."""
    # El cliente ya se inicia automáticamente en el hilo

  def stop(self):
    """Detiene el cliente MQTT de comandos."""
    self.stop_event.set()
    self.mqttc.disconnect()

if __name__ == "__main__":
  comandos = MQTTComandos()
  comandos.start()

  try:
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    comandos.stop()

