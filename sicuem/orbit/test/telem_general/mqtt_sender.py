import os
import json
import time
import threading
import paho.mqtt.client as mqtt

class MqttSender(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self._cargar_configuracion()
        self._conectar_mqtt()
        self._detener = threading.Event()

    def _cargar_configuracion(self):
        base_path = os.path.dirname(__file__)
        with open(os.path.join(base_path, "config_mqtt.json")) as f:
            self.config = json.load(f)

        with open(os.path.join(base_path, "canales.json")) as f:
            self.canales_config = json.load(f)["canales"]

        self.broker_ip = self.config.get("broker_ip", "localhost")
        self.broker_port = self.config.get("broker_port", 1883)
        self.nombre_coche = self.config.get("nombre_coche", "sin_nombre")
        self.intervalo_envio = self.config.get("intervalo_envio", 2)
        self.canales_activos = [c for c in self.canales_config if c["enable"] == 1]

    def _conectar_mqtt(self):
        self.client = mqtt.Client()
        self.client.connect(self.broker_ip, self.broker_port)
        self.client.loop_start()

    def _obtener_datos_simulados(self):
        # Aquí pondrás los datos reales en producción
        return {
            "carControl": {
                "actuators": {"gas": 0.5, "brake": 0.0},
                "hudControl": {"setSpeed": 90.0}
            },
            "carState": {
                "aEgo": 1.1, "cruiseState": "enabled",
                "leftBlinker": False, "rightBlinker": True,
                "vCruise": 27.8, "vCruiseCluster": 28.0,
                "vEgo": 26.0, "vEgoCluster": 26.5,
                "leftBlindspot": False, "rightBlindspot": False
            },
            "gpsLocationExternal": {
                "latitude": 40.4168, "longitude": -3.7038, "altitude": 667
            },
            "navInstruction": {
                "distanceRemaining": 150.0, "maneuverDistance": 20.0,
                "speedLimit": 90.0, "timeRemaining": 60
            },
            "radarState": {
                "aRel": 0.3, "dRel": 25.5, "vRel": -3.0, "vLead": 22.0
            },
            "drivingModelData": {
                "laneLineMeta": "simple_json_demo"
            }
        }

    def detener(self):
        self._detener.set()

    def run(self):
        print(f"🚗 Enviando datos de '{self.nombre_coche}' cada {self.intervalo_envio}s a {self.broker_ip}:{self.broker_port}...\n")
        while not self._detener.is_set():
            datos = self._obtener_datos_simulados()
            for canal in self.canales_activos:
                canal_id = canal["canal"]
                topic = canal["topic"].format(self.nombre_coche)
                keys = canal["keys_importantes"]

                if canal_id in datos:
                    payload = {k: datos[canal_id].get(k) for k in keys if k in datos[canal_id]}
                    self.client.publish(topic, json.dumps(payload))
                    print(f"📤 Enviado a {topic}: {json.dumps(payload)}")

            time.sleep(self.intervalo_envio)

# Si quieres ejecutarlo directamente para pruebas:
if __name__ == "__main__":
    sender = MqttSender()
    sender.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sender.detener()
        print("🛑 Envío MQTT detenido.")
