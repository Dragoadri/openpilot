#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de diagnóstico para verificar la conectividad MQTT
"""
import paho.mqtt.client as mqtt
import time
import json

def test_mqtt_connection():
    """Prueba la conexión MQTT al broker."""
    print("🧪 Iniciando diagnóstico de conectividad MQTT...")

    # Cargar configuración
    with open("sicuem/orbit/config_mqtt.json", "r") as f:
        config = json.load(f)
        broker_address = config.get("broker", "localhost")
        broker_port = config.get("broker_port", 1883)

    print(f"📡 Broker configurado: {broker_address}:{broker_port}")

    # Usar DongleID fijo para la prueba
    dongle_id = "UnregisteredDevice"
    print(f"🆔 DongleID de prueba: {dongle_id}")

    # Crear cliente MQTT
    client = mqtt.Client()

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("✅ Conexión MQTT exitosa")
            # Suscribirse a los topics de comandos
            topics = [
                f"telemetry_config/{dongle_id}/left",
                f"telemetry_config/{dongle_id}/right",
                f"telemetry_config/{dongle_id}/intervalos"
            ]
            for topic in topics:
                client.subscribe(topic, qos=0)
                print(f"📡 Suscrito a: {topic}")
        else:
            print(f"❌ Error de conexión MQTT: {rc}")

    def on_disconnect(client, userdata, rc):
        print("🔌 Desconectado del broker MQTT")

    def on_message(client, userdata, msg):
        print(f"📥 Mensaje recibido: {msg.topic} -> {msg.payload.decode()}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    try:
        print("🔄 Intentando conectar...")
        client.connect(broker_address, broker_port, 60)
        client.loop_start()

        print("⏱️  Esperando 10 segundos para recibir mensajes...")
        time.sleep(10)

        print("🧪 Enviando mensaje de prueba...")
        client.publish(f"telemetry_config/{dongle_id}/left", "true")
        time.sleep(2)

        client.loop_stop()
        client.disconnect()
        print("✅ Diagnóstico completado")

    except Exception as e:
        print(f"❌ Error durante el diagnóstico: {e}")

if __name__ == "__main__":
    test_mqtt_connection()
