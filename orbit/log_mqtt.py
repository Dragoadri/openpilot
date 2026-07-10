# log_mqtt.py — MODULO DORMIDO: ningun fichero del arbol lo importa hoy
# (auditoria 2026-07-10). Se conserva como utilidad de log puntual por MQTT.
import json
import os
from datetime import datetime

import paho.mqtt.publish as publish

# IMPORTANTE: nada de I/O ni Params() a nivel de modulo.
# (Historico: se importaba transitivamente desde selfdrive/car/interfaces.py via
# desire_helper.py — ya no. La regla se mantiene por si se reimporta en el futuro:
# si abrimos archivos o creamos Params() aqui, scons falla al compilar long_mpc
# en un subproceso con $HOME limpio, errno=13 en /.comma/params.)

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_PATH, "config_mqtt.json")

_BROKER = None
_PORT = None
_AUTH = None  # dict {'username','password'} para publish.single, o None (anonimo)
_DONGLE_ID = None


def _ensure_loaded():
  global _BROKER, _PORT, _AUTH, _DONGLE_ID
  if _BROKER is not None:
    return
  try:
    with open(CONFIG_FILE, "r") as f:
      config = json.load(f)
    _BROKER = config.get("broker", "localhost")
    _PORT = config.get("broker_port", 1883)
    # Credenciales MQTT opcionales (broker con auth). Vacio/ausente = anonimo.
    username = (config.get("username") or "").strip()
    _AUTH = {"username": username, "password": config.get("password") or ""} if username else None
  except Exception:
    _BROKER = "localhost"
    _PORT = 1883
    _AUTH = None
  try:
    from openpilot.common.params import Params
    dongle = Params().get("DongleId")
    _DONGLE_ID = dongle if dongle else "UnregisteredDevice"
  except Exception:
    _DONGLE_ID = "UnregisteredDevice"


def enviar_log(mensaje, nivel="INFO", origen="desconocido"):
  _ensure_loaded()
  topic = f"telemetry_mqtt/{_DONGLE_ID}/logs"
  payload = {
    "log": mensaje,
    "level": nivel,
    "timestamp": datetime.now().isoformat(),
    "origen": origen,
  }
  try:
    publish.single(topic, json.dumps(payload), hostname=_BROKER, port=_PORT, auth=_AUTH)
  except Exception:
    pass


def enviar_log_test(dongle_id_manual, mensaje, nivel="INFO", origen="desconocido"):
  _ensure_loaded()
  topic = f"telemetry_mqtt/{dongle_id_manual}/logs"
  payload = {
    "log": mensaje,
    "level": nivel,
    "timestamp": datetime.now().isoformat(),
    "origen": origen,
  }
  publish.single(topic, json.dumps(payload), hostname=_BROKER, port=_PORT, auth=_AUTH)
  print(f"Log de test enviado a {topic}")
