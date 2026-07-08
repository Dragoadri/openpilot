#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba que simula exactamente lo que envía el servidor
Basado en los logs del servidor
"""
import time
import paho.mqtt.publish as publish

# Configuración basada en los logs del servidor
DONGLE_ID = "UnregisteredDevice"
BROKER_ADDRESS = "79.146.243.188"  # Broker del servidor
BROKER_PORT = 1883

def send_speed_down():
    """Envía comando de disminuir velocidad como lo hace el servidor."""
    topic = f"telemetry_config/{DONGLE_ID}/speed_down"
    message = "-1"
    print(f"🐌 ===== COMANDO DISMINUIR VELOCIDAD ===== 🐌")
    print(f"📱 Dispositivo: {DONGLE_ID}")
    print(f"📡 Topic MQTT: {topic}")
    print(f"📤 Mensaje: {message}")
    print(f"🌐 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print(f"⏰ Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🐌 ========================================= 🐌")

    publish.single(topic, message, hostname=BROKER_ADDRESS, port=BROKER_PORT)

def send_speed_up():
    """Envía comando de aumentar velocidad como lo hace el servidor."""
    topic = f"telemetry_config/{DONGLE_ID}/speed_up"
    message = "+1"
    print(f"🚀 ===== COMANDO AUMENTAR VELOCIDAD ===== 🚀")
    print(f"📱 Dispositivo: {DONGLE_ID}")
    print(f"📡 Topic MQTT: {topic}")
    print(f"📤 Mensaje: {message}")
    print(f"🌐 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print(f"⏰ Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🚀 ========================================= 🚀")

    publish.single(topic, message, hostname=BROKER_ADDRESS, port=BROKER_PORT)

def main():
    print("🚀 Prueba de Comandos del Servidor Orbit")
    print("📋 Simulando exactamente lo que envía el servidor")
    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")
    print("="*60)

    try:
        print("\n--- PRUEBA 1: Comando Disminuir Velocidad ---")
        print("🎯 Enviando: telemetry_config/UnregisteredDevice/speed_down -> -1")
        send_speed_down()
        time.sleep(5)

        print("\n--- PRUEBA 2: Comando Aumentar Velocidad ---")
        print("🎯 Enviando: telemetry_config/UnregisteredDevice/speed_up -> +1")
        send_speed_up()
        time.sleep(5)

        print("\n--- PRUEBA 3: Múltiples comandos ---")
        for i in range(3):
            print(f"\n   Comando {i+1}/3 - Disminuir")
            send_speed_down()
            time.sleep(2)

            print(f"   Comando {i+1}/3 - Aumentar")
            send_speed_up()
            time.sleep(2)

        print("\n" + "="*60)
        print("✅ Pruebas completadas")
        print("📋 Revisa los logs del comma para verificar:")
        print("   - 📥 MQTT recibido correctamente")
        print("   - ⬇️ Comando SPEED DOWN (-1) activado")
        print("   - ⬆️ Comando SPEED UP (+1) activado")
        print("   - 🎯 Comando SPEED INCREASE/DECREASE ejecutado")
        print("   - 📊 Cambios en v_cruise_helper.v_cruise_kph")

    except KeyboardInterrupt:
        print("\n⏹️  Pruebas interrumpidas por el usuario")
    except Exception as e:
        print(f"❌ Error durante las pruebas: {e}")

if __name__ == "__main__":
    main()












