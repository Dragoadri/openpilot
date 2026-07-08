#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba específico para comandos de velocidad Orbit
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
    print("🚀 Prueba de comandos de velocidad Orbit")
    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print("="*60)

    try:
        # Prueba de aumento de velocidad
        print("\n--- PRUEBA: Aumentar velocidad ---")
        send_speed_command("speed_increase")
        time.sleep(3)

        # Prueba de reducción de velocidad
        print("\n--- PRUEBA: Reducir velocidad ---")
        send_speed_command("speed_decrease")
        time.sleep(3)

        # Prueba múltiple
        print("\n--- PRUEBA: Múltiples aumentos ---")
        for i in range(3):
            send_speed_command("speed_increase")
            time.sleep(2)

        print("\n--- PRUEBA: Múltiples reducciones ---")
        for i in range(3):
            send_speed_command("speed_decrease")
            time.sleep(2)

        print("\n" + "="*60)
        print("✅ Pruebas de velocidad completadas")
        print("📋 Revisa los logs del comma para verificar:")
        print("   - Comandos recibidos")
        print("   - Cambios de velocidad aplicados")
        print("   - Valores de vCruise actualizados")

    except KeyboardInterrupt:
        print("\n⏹️  Pruebas interrumpidas por el usuario")
    except Exception as e:
        print(f"❌ Error durante las pruebas: {e}")

if __name__ == "__main__":
    main()












