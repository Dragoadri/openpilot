#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba final para control de velocidad Orbit
Verifica que los cambios se apliquen correctamente
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
    print("🚀 Prueba Final de Control de Velocidad Orbit")
    print("📋 Verificando múltiples enfoques de control de velocidad")
    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print("="*60)

    try:
        print("\n--- PRUEBA 1: Reducir velocidad (-1 km/h) ---")
        print("🎯 Esperado: Cambio en setSpeed, vCruise, y parámetros")
        send_speed_command("speed_decrease")
        time.sleep(8)

        print("\n--- PRUEBA 2: Aumentar velocidad (+1 km/h) ---")
        print("🎯 Esperado: Cambio en setSpeed, vCruise, y parámetros")
        send_speed_command("speed_increase")
        time.sleep(8)

        print("\n--- PRUEBA 3: Múltiples aumentos ---")
        for i in range(3):
            print(f"   Aumento {i+1}/3")
            send_speed_command("speed_increase")
            time.sleep(3)

        print("\n--- PRUEBA 4: Múltiples reducciones ---")
        for i in range(3):
            print(f"   Reducción {i+1}/3")
            send_speed_command("speed_decrease")
            time.sleep(3)

        print("\n" + "="*60)
        print("✅ Pruebas completadas")
        print("📋 Revisa los logs del comma para verificar:")
        print("   - 📥 MQTT recibido correctamente")
        print("   - 🎯 Comando SPEED INCREASE/DECREASE ejecutado")
        print("   - 📊 Cambios en hudControl.setSpeed")
        print("   - 📊 Cambios en vCruise")
        print("   - 📊 Cambios en parámetros")
        print("   - 🚫 Sin errores de 'get_int' o 'controlsState'")

    except KeyboardInterrupt:
        print("\n⏹️  Pruebas interrumpidas por el usuario")
    except Exception as e:
        print(f"❌ Error durante las pruebas: {e}")

if __name__ == "__main__":
    main()












