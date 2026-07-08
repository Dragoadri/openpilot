#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de diagnóstico para verificar el sistema Orbit
Verifica si los comandos MQTT están llegando y procesándose
"""
import json
import time
import paho.mqtt.publish as publish
import paho.mqtt.client as mqtt
from openpilot.common.params import Params

# Obtener DongleID del sistema
params = Params()
DONGLE_ID = params.get("DongleId").decode("utf-8") if params.get("DongleId") else "UnregisteredDevice"

BROKER_ADDRESS = "80.29.2.242"
BROKER_PORT = 1883

class MQTTDiagnostic:
  """Diagnóstico del sistema MQTT Orbit."""

  def __init__(self):
    self.client = mqtt.Client()
    self.client.on_connect = self.on_connect
    self.client.on_message = self.on_message
    self.commands_received = []

  def on_connect(self, client, userdata, flags, rc):
    if rc == 0:
      print("🔌 MQTT Diagnostic conectado")
      # Suscribirse a todos los comandos Orbit
      topics = [
        f"telemetry_config/{DONGLE_ID}/left",
        f"telemetry_config/{DONGLE_ID}/right",
        f"telemetry_config/{DONGLE_ID}/control",
        f"telemetry_config/{DONGLE_ID}/speed",
        f"telemetry_config/{DONGLE_ID}/intervalos"
      ]

      for topic in topics:
        client.subscribe(topic, qos=0)
        print(f"📡 Suscrito a: {topic}")
    else:
      print(f"❌ Error conexión MQTT: {rc}")

  def on_message(self, client, userdata, msg):
    """Callback que maneja los mensajes MQTT."""
    topic = msg.topic
    payload = msg.payload.decode(errors="ignore").strip()

    command_info = {
      "timestamp": time.time(),
      "topic": topic,
      "payload": payload
    }
    self.commands_received.append(command_info)

    print(f"📥 MQTT recibido: {topic} -> {payload}")

    # Verificar si es un comando de velocidad
    if topic.endswith("/speed"):
      try:
        data = json.loads(payload)
        if data.get("speed_increase"):
          print("✅ Comando SPEED INCREASE detectado")
        elif data.get("speed_decrease"):
          print("✅ Comando SPEED DECREASE detectado")
      except:
        print("⚠️ Error decodificando comando de velocidad")

    # Verificar si es un comando de control
    elif topic.endswith("/control"):
      try:
        data = json.loads(payload)
        if data.get("forward"):
          print("✅ Comando FORWARD detectado")
        elif data.get("break"):
          print("✅ Comando BREAK detectado")
        elif data.get("tright"):
          print("✅ Comando TRIGHT detectado")
        elif data.get("tleft"):
          print("✅ Comando TLEFT detectado")
      except:
        print("⚠️ Error decodificando comando de control")

    # Verificar si es un comando de cambio de carril
    elif topic.endswith("/left"):
      print("✅ Comando LANE CHANGE LEFT detectado")
    elif topic.endswith("/right"):
      print("✅ Comando LANE CHANGE RIGHT detectado")

  def start_listening(self, duration=30):
    """Inicia la escucha de comandos MQTT."""
    print(f"🔍 Iniciando diagnóstico MQTT por {duration} segundos...")
    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print("="*60)

    try:
      self.client.connect(BROKER_ADDRESS, BROKER_PORT, 60)
      self.client.loop_start()

      print("⏳ Esperando comandos... (Envía comandos desde la app ahora)")
      time.sleep(duration)

      self.client.loop_stop()
      self.client.disconnect()

      print("\n" + "="*60)
      print("📊 RESUMEN DEL DIAGNÓSTICO")
      print(f"📥 Comandos recibidos: {len(self.commands_received)}")

      if self.commands_received:
        print("\n📋 Comandos detectados:")
        for i, cmd in enumerate(self.commands_received, 1):
          print(f"  {i}. {cmd['topic']} -> {cmd['payload']}")
      else:
        print("❌ No se recibieron comandos MQTT")
        print("💡 Posibles causas:")
        print("   - La app no está enviando comandos")
        print("   - Problema de conectividad MQTT")
        print("   - DongleID incorrecto")
        print("   - Broker MQTT no disponible")

    except Exception as e:
      print(f"❌ Error en diagnóstico: {e}")

def send_test_command():
  """Envía un comando de prueba."""
  topic = f"telemetry_config/{DONGLE_ID}/speed"
  message = {"speed_decrease": True, "timestamp": str(int(time.time()))}
  print(f"🧪 Enviando comando de prueba: {topic} -> {json.dumps(message)}")
  publish.single(topic, json.dumps(message), hostname=BROKER_ADDRESS, port=BROKER_PORT)

def main():
  print("🚀 Diagnóstico del Sistema Orbit")
  print("="*60)

  # Crear diagnosticador
  diagnostic = MQTTDiagnostic()

  # Enviar comando de prueba
  print("🧪 Enviando comando de prueba...")
  send_test_command()
  time.sleep(2)

  # Iniciar escucha
  diagnostic.start_listening(30)

if __name__ == "__main__":
  main()












