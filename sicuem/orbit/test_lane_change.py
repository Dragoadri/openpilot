#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba para verificar el sistema de cambio de carril MQTT
"""
import paho.mqtt.publish as publish
import time
import json

def test_lane_change_commands(dongle_id="test_device"):
    """Prueba los comandos de cambio de carril"""

    broker_host = "80.29.2.242"
    broker_port = 1883

    print(f"🧪 Probando comandos de cambio de carril para {dongle_id}")
    print(f"📡 Broker: {broker_host}:{broker_port}")

    # Comando de cambio a la izquierda
    print("\n🔄 Enviando comando cambio carril IZQUIERDA...")
    try:
        publish.single(
            f"telemetry_config/{dongle_id}/left",
            "true",
            hostname=broker_host,
            port=broker_port
        )
        print("✅ Comando izquierda enviado")
    except Exception as e:
        print(f"❌ Error enviando comando izquierda: {e}")

    time.sleep(2)

    # Comando de cambio a la derecha
    print("\n🔄 Enviando comando cambio carril DERECHA...")
    try:
        publish.single(
            f"telemetry_config/{dongle_id}/right",
            "true",
            hostname=broker_host,
            port=broker_port
        )
        print("✅ Comando derecha enviado")
    except Exception as e:
        print(f"❌ Error enviando comando derecha: {e}")

    time.sleep(2)

    # Comando de cancelar
    print("\n🛑 Enviando comando CANCELAR...")
    try:
        publish.single(
            f"telemetry_config/{dongle_id}/left",
            "false",
            hostname=broker_host,
            port=broker_port
        )
        publish.single(
            f"telemetry_config/{dongle_id}/right",
            "false",
            hostname=broker_host,
            port=broker_port
        )
        print("✅ Comando cancelar enviado")
    except Exception as e:
        print(f"❌ Error enviando comando cancelar: {e}")

    print("\n🎯 Prueba completada")

def test_with_real_dongle_id():
    """Prueba con un dongle_id real"""
    # Cambia esto por un dongle_id real
    real_dongle_id = "UnregisteredDevice"  # o el dongle_id real

    print(f"🧪 Probando con dongle_id real: {real_dongle_id}")
    test_lane_change_commands(real_dongle_id)

if __name__ == "__main__":
    print("🚗 Sistema de Prueba de Cambio de Carril MQTT")
    print("=" * 50)

    # Prueba con dongle_id de prueba
    test_lane_change_commands("test_device")

    print("\n" + "=" * 50)

    # Prueba con dongle_id real (cambiar por uno real)
    test_with_real_dongle_id()














