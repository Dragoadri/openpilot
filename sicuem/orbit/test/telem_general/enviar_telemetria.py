import json
import paho.mqtt.client as mqtt
import time

# Configuración
BROKER = "79.146.241.243"  # IP pública del servidor
TOPIC = "telemetry_mqtt/abc123/carControl"  # reemplaza abc123 por tu dongle_id real
PORT = 1883

# Cliente MQTT
client = mqtt.Client()
client.connect(BROKER, PORT, 60)

# Datos de prueba
data = {
    "dongle_id": "abc123",
    "nombre": "XXXXXXXX",
    "vEgo": 14.2,
    "gas": 0.37
}

# Publicar
payload = json.dumps(data)
client.publish(TOPIC, payload)
print("📤 Datos enviados:", payload)
client.disconnect()
