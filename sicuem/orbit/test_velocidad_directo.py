#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba específico para control de velocidad Orbit
Simula: 40 km/h + comando -1 = 39 km/h, 40 km/h + comando +1 = 41 km/h
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

def send_speed_command(command_type, value=True):
    """Envía comando de velocidad."""
    topic = f"telemetry_config/{DONGLE_ID}/speed"
    message = {command_type: value, "timestamp": str(int(time.time()))}
    print(f"🧪 Enviando comando {command_type.upper()}: {topic} -> {json.dumps(message)}")
    publish.single(topic, json.dumps(message), hostname=BROKER_ADDRESS, port=BROKER_PORT)

def main():
    print("🚀 Prueba de control de velocidad Orbit")
    print("📋 Simulando: 40 km/h + comando -1 = 39 km/h")
    print("📋 Simulando: 40 km/h + comando +1 = 41 km/h")
    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print("="*60)

    try:
        # Simular que el vehículo está a 40 km/h (setSpeed: 11.11 m/s)
        print("\n--- SIMULACIÓN: Vehículo a 40 km/h ---")
        print("📊 Velocidad actual simulada: 40 km/h (setSpeed: 11.11 m/s)")

        # Comando de reducción (-1 km/h)
        print("\n--- COMANDO: Reducir velocidad (-1 km/h) ---")
        print("🎯 Esperado: 40 km/h → 39 km/h (setSpeed: 10.83 m/s)")
        send_speed_command("speed_decrease")
        time.sleep(5)

        # Comando de aumento (+1 km/h)
        print("\n--- COMANDO: Aumentar velocidad (+1 km/h) ---")
        print("🎯 Esperado: 39 km/h → 40 km/h (setSpeed: 11.11 m/s)")
        send_speed_command("speed_increase")
        time.sleep(5)

        # Comando de aumento (+1 km/h) otra vez
        print("\n--- COMANDO: Aumentar velocidad (+1 km/h) ---")
        print("🎯 Esperado: 40 km/h → 41 km/h (setSpeed: 11.39 m/s)")
        send_speed_command("speed_increase")
        time.sleep(5)

        # Comando de reducción (-1 km/h) otra vez
        print("\n--- COMANDO: Reducir velocidad (-1 km/h) ---")
        print("🎯 Esperado: 41 km/h → 40 km/h (setSpeed: 11.11 m/s)")
        send_speed_command("speed_decrease")
        time.sleep(5)

        print("\n" + "="*60)
        print("✅ Pruebas de velocidad completadas")
        print("📋 Revisa los logs del comma para verificar:")
        print("   - 📥 MQTT recibido: telemetry_config/{dongle_id}/speed")
        print("   - ⬆️/⬇️ Comando SPEED INCREASE/DECREASE ejecutado")
        print("   - 🎯 Velocidad Orbit aplicada: XX km/h")
        print("   - 📊 Cambios en setSpeed en los logs de carControl:")
        print("     * setSpeed: 11.11 m/s = 40 km/h")
        print("     * setSpeed: 10.83 m/s = 39 km/h")
        print("     * setSpeed: 11.39 m/s = 41 km/h")

    except KeyboardInterrupt:
        print("\n⏹️  Pruebas interrumpidas por el usuario")
    except Exception as e:
        print(f"❌ Error durante las pruebas: {e}")

if __name__ == "__main__":
    main()












