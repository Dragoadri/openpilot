#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba para todos los comandos Orbit
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
    """Envía comando de control básico."""
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

def send_lane_change_command(direction, value=True):
    """Envía comando de cambio de carril."""
    topic = f"telemetry_config/{DONGLE_ID}/{direction}"
    message = {"ForceLaneChangeLeft" if direction == "left" else "ForceLaneChangeRight": value, "timestamp": str(int(time.time()))}
    print(f"🧪 Enviando comando {direction.upper()}: {topic} -> {json.dumps(message)}")
    publish.single(topic, json.dumps(message), hostname=BROKER_ADDRESS, port=BROKER_PORT)

def send_intervalos_command(value=True):
    """Envía comando de intervalos."""
    topic = f"telemetry_config/{DONGLE_ID}/intervalos"
    message = {"intervalos_toggle": str(value).lower(), "timestamp": str(int(time.time()))}
    print(f"🧪 Enviando comando INTERVALOS: {topic} -> {json.dumps(message)}")
    publish.single(topic, json.dumps(message), hostname=BROKER_ADDRESS, port=BROKER_PORT)

def main():
    print("🚀 Iniciando prueba completa de comandos Orbit")
    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print("="*60)

    # Asegurar que el toggle c_carril esté activado
    params.put_bool("c_carril", True)
    print("✅ c_carril toggle activado")

    try:
        # 1. Prueba de comandos de control básico
        print("\n--- 1. PRUEBA: Comandos de Control Básico ---")
        send_control_command("forward")
        time.sleep(2)
        send_control_command("break")
        time.sleep(2)
        send_control_command("tright")
        time.sleep(2)
        send_control_command("tleft")
        time.sleep(2)

        # 2. Prueba de comandos de velocidad
        print("\n--- 2. PRUEBA: Comandos de Velocidad ---")
        send_speed_command("speed_increase")
        time.sleep(2)
        send_speed_command("speed_decrease")
        time.sleep(2)

        # 3. Prueba de comandos de cambio de carril
        print("\n--- 3. PRUEBA: Comandos de Cambio de Carril ---")
        send_lane_change_command("left")
        time.sleep(3)
        send_lane_change_command("right")
        time.sleep(3)

        # 4. Prueba de comandos de configuración
        print("\n--- 4. PRUEBA: Comandos de Configuración ---")
        send_intervalos_command(True)
        time.sleep(2)
        send_intervalos_command(False)
        time.sleep(2)

        print("\n" + "="*60)
        print("✅ Pruebas completadas. Revisa los logs del comma para verificar la ejecución.")
        print("📋 Comandos enviados:")
        print("   - Control: forward, break, tright, tleft")
        print("   - Velocidad: speed_increase, speed_decrease")
        print("   - Cambio carril: left, right")
        print("   - Configuración: intervalos (true/false)")

    except KeyboardInterrupt:
        print("\n⏹️  Pruebas interrumpidas por el usuario")
    except Exception as e:
        print(f"❌ Error durante las pruebas: {e}")

if __name__ == "__main__":
    main()












