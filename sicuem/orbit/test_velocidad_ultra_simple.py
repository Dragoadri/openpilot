#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba final para control de velocidad Orbit
Enfoque ultra simplificado - sin controlsState, sin parámetros problemáticos
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
    print("📋 Enfoque ultra simplificado - sin controlsState, sin parámetros problemáticos")
    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print("="*60)

    try:
        print("\n--- PRUEBA 1: Reducir velocidad (-1 km/h) ---")
        print("🎯 Esperado: Cambio en v_cruise_helper.v_cruise_kph")
        send_speed_command("speed_decrease")
        time.sleep(5)

        print("\n--- PRUEBA 2: Aumentar velocidad (+1 km/h) ---")
        print("🎯 Esperado: Cambio en v_cruise_helper.v_cruise_kph")
        send_speed_command("speed_increase")
        time.sleep(5)

        print("\n--- PRUEBA 3: Múltiples aumentos ---")
        for i in range(2):
            print(f"   Aumento {i+1}/2")
            send_speed_command("speed_increase")
            time.sleep(3)

        print("\n--- PRUEBA 4: Múltiples reducciones ---")
        for i in range(2):
            print(f"   Reducción {i+1}/2")
            send_speed_command("speed_decrease")
            time.sleep(3)

        print("\n" + "="*60)
        print("✅ Pruebas completadas")
        print("📋 Revisa los logs del comma para verificar:")
        print("   - 📥 MQTT recibido correctamente")
        print("   - 🎯 Comando SPEED INCREASE/DECREASE ejecutado")
        print("   - 📊 Cambios en v_cruise_helper.v_cruise_kph")
        print("   - 📊 Cambios en v_cruise_helper.v_cruise_cluster_kph")
        print("   - 🚫 Sin errores de controlsState o parámetros")

    except KeyboardInterrupt:
        print("\n⏹️  Pruebas interrumpidas por el usuario")
    except Exception as e:
        print(f"❌ Error durante las pruebas: {e}")

if __name__ == "__main__":
    main()












