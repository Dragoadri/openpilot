#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostico MQTT Orbit — EJECUTAR EN EL COMMA.

  cd /data/openpilot && python3 tools/sicuem/diag_mqtt_orbit.py

Comprueba, en orden, por que el dispositivo no aparece "conectado" en la app:
  1) Que las librerias (paho, cereal, numpy, zmq, cv2, requests) importan.
  2) Que el stack MQTT (MQTTEnvioGeneral) IMPORTA como lo hace manager.py.
     -> Si esto falla, manager lo traga en silencio y NO arranca NADA de MQTT.
  3) La IP del broker configurada (config_mqtt.json).
  4) El DongleId (parte de los topics).
  5) Conectividad real al broker (TCP + CONNACK MQTT).
  6) Ultimas lineas [Bemposta] del swaglog (dicen si conecto/fallo).

Interpretacion al final.
"""
import importlib
import json
import os
import socket
import subprocess
import time
import traceback


def ok(m):   print(f"  \033[32mOK\033[0m   {m}")
def bad(m):  print(f"  \033[31mFAIL\033[0m {m}")
def info(m): print(f"  --   {m}")


def main() -> int:
  print("=" * 64)
  print("DIAGNOSTICO MQTT ORBIT  (ejecutar en el comma)")
  print("=" * 64)

  # 1) Librerias -----------------------------------------------------------
  print("\n1) LIBRERIAS")
  for mod in ["paho.mqtt.client", "cereal.messaging", "numpy", "zmq", "cv2", "requests"]:
    try:
      m = importlib.import_module(mod)
      ok(f"{mod}  ({getattr(m, '__file__', '?')})")
    except Exception as e:
      bad(f"{mod}  -> {type(e).__name__}: {e}")

  # 2) Import del stack MQTT (identico a manager.py) -----------------------
  print("\n2) IMPORT DEL STACK MQTT (como manager.py)")
  try:
    from openpilot.orbit.mqtt_envio_general import MQTTEnvioGeneral  # noqa: F401
    ok("import MQTTEnvioGeneral OK  -> el stack MQTT PUEDE arrancar")
  except Exception as e:
    bad(f"import MQTTEnvioGeneral FALLA -> manager NO arranca MQTT: {type(e).__name__}: {e}")
    traceback.print_exc()

  # 3) Config del broker ---------------------------------------------------
  print("\n3) CONFIG BROKER")
  broker, port = None, 1883
  candidates = [
    os.path.join("/data/openpilot", "sicuem/orbit/config_mqtt.json"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                 "sicuem/orbit/config_mqtt.json"),
  ]
  cfgpath = next((p for p in candidates if os.path.exists(p)), candidates[0])
  try:
    cfg = json.load(open(cfgpath))
    broker = cfg.get("broker")
    port = int(cfg.get("broker_port", 1883))
    info(f"archivo: {cfgpath}")
    ok(f"broker = {broker}:{port}")
  except Exception as e:
    bad(f"no se pudo leer {cfgpath}: {e}")

  # 4) DongleId ------------------------------------------------------------
  print("\n4) DONGLE ID (parte de los topics)")
  try:
    from openpilot.common.params import Params
    d = Params().get("DongleId")
    ok(f"DongleId = {d!r}  (tipo {type(d).__name__})")
  except Exception as e:
    bad(f"Params/DongleId: {e}")

  # 5) Conectividad real ---------------------------------------------------
  if broker:
    print("\n5) CONECTIVIDAD AL BROKER")
    try:
      socket.create_connection((broker, port), timeout=6).close()
      ok(f"TCP {broker}:{port} alcanzable")
    except Exception as e:
      bad(f"TCP {broker}:{port} NO alcanzable: {e}  (IP del broker o red del comma)")
    try:
      import paho.mqtt.client as mqtt
      res = {"rc": None}
      cl = mqtt.Client()
      cl.on_connect = lambda c, u, f, rc: res.update(rc=rc)
      cl.connect(broker, port, 10)
      cl.loop_start(); time.sleep(3); cl.loop_stop(); cl.disconnect()
      if res["rc"] == 0:
        ok("MQTT CONNACK rc=0  (el broker acepta la conexion)")
      else:
        bad(f"MQTT CONNACK rc={res['rc']}  (broker rechaza)")
    except Exception as e:
      bad(f"MQTT connect fallo: {e}")

  # 6) Logs [Bemposta] -----------------------------------------------------
  print("\n6) LOGS [Bemposta] (ultimas lineas del swaglog)")
  logdirs = []
  try:
    from openpilot.system.hardware.hw import Paths
    logdirs.append(Paths.swaglog_root())
  except Exception:
    pass
  logdirs += ["/data/log", "/tmp/openpilot/log"]
  shown = False
  for logdir in logdirs:
    if logdir and os.path.isdir(logdir):
      out = subprocess.run(f"grep -rhoa 'Bemposta[^\"]*' {logdir} 2>/dev/null | tail -15",
                           shell=True, capture_output=True, text=True).stdout
      if out.strip():
        print(out)
        shown = True
        break
  if not shown:
    info("sin lineas [Bemposta] en logs (¿el stack no arranco? ¿logs en otra ruta?)")

  print("\n" + "=" * 64)
  print("INTERPRETACION:")
  print("  (2) FALLA          -> falta libreria / error de import -> arreglar deps/entorno.")
  print("  (2) OK, (5) TCP no -> IP del broker o red del comma (revisa config_mqtt.json).")
  print("  (5) CONNACK!=0     -> broker rechaza (auth?).")
  print("  todo OK, no publica-> REINICIA openpilot: config_mqtt.json se lee 1 sola vez.")
  print("=" * 64)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
