#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba final para todos los comandos Orbit
Enfoque ultra simplificado - sin parámetros problemáticos
"""
import json
import time
import paho.mqtt.publish as publish
from openpilot.common.params import Params

# Obtener DongleID del sistema
params = Params()
DONGLE_ID = params.get("DongleId").decode("utf-8") if params.get("DongleId") else "UnregisteredDevice"

BROKER_ADDRESS = "80.29.2.242"
BROKER_PORT = 1883

def send_control_command(command_type, value=True):
    """Envía comando de control."""
    topic = f"telemetry_config/{DONGLE_ID}/control"
    message = {command_type: value, "timestamp": str(int(time.time()))}
    print(f"🧪 Enviando comando {command_type.upper()}: {topic} -> {json.dumps(message)}")
    publish.single(topic, json.dumps(message), hostname=BROKER_ADDRESS, port=BROKER_PORT)

def send_speed_command(command_type, value=True):
    """Envía comando de velocidad."""
    topic = f"telemetry_config/{DONGLE_ID}/speed"
    message = {command_type: value, "timestamp": str(int(time.time()))}
    print(f"🧪 Enviando comando {command_type.upper()}: {topic} -> {json.dumps(message)}")
    publish.single(topic, json.dumps(message), hostname=BROKER_ADDRESS, port=BROKER_PORT)

def send_lane_change_command(direction):
    """Envía comando de cambio de carril."""
    topic = f"telemetry_config/{DONGLE_ID}/{direction}"
    message = "true"
    print(f"🧪 Enviando comando LANE CHANGE {direction.upper()}: {topic} -> {message}")
    publish.single(topic, message, hostname=BROKER_ADDRESS, port=BROKER_PORT)

def main():
    print("🚀 Prueba Final de Todos los Comandos Orbit")
    print("📋 Enfoque ultra simplificado - sin parámetros problemáticos")
    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print("="*60)

    try:
        print("\n--- PRUEBA 1: Comandos de Control Básico ---")
        print("🎯 Esperado: Cambios en actuators")

        print("   Forward (Aceleración)")
        send_control_command("forward")
        time.sleep(3)

        print("   Break (Frenado)")
        send_control_command("break")
        time.sleep(3)

        print("   Tright (Giro derecha)")
        send_control_command("tright")
        time.sleep(3)

        print("   Tleft (Giro izquierda)")
        send_control_command("tleft")
        time.sleep(3)

        print("\n--- PRUEBA 2: Comandos de Velocidad ---")
        print("🎯 Esperado: Cambios en v_cruise_helper")

        print("   Speed Decrease")
        send_speed_command("speed_decrease")
        time.sleep(3)

        print("   Speed Increase")
        send_speed_command("speed_increase")
        time.sleep(3)

        print("\n--- PRUEBA 3: Cambio de Carril ---")
        print("🎯 Esperado: Cambios de carril")

        print("   Lane Change Left")
        send_lane_change_command("left")
        time.sleep(3)

        print("   Lane Change Right")
        send_lane_change_command("right")
        time.sleep(3)

        print("\n" + "="*60)
        print("✅ Pruebas completadas")
        print("📋 Revisa los logs del comma para verificar:")
        print("   - 📥 MQTT recibido correctamente")
        print("   - 🎯 Comandos ejecutados sin errores")
        print("   - 📊 Cambios en actuators y v_cruise_helper")
        print("   - 🚫 Sin errores de parámetros o bytes")

    except KeyboardInterrupt:
        print("\n⏹️  Pruebas interrumpidas por el usuario")
    except Exception as e:
        print(f"❌ Error durante las pruebas: {e}")

if __name__ == "__main__":
    main()












