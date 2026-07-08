#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba para verificar que el setSpeed fijo a 34 km/h se está enviando correctamente.

Uso:
    python test_setspeed_fijo.py
"""

import json
import time
import paho.mqtt.client as mqtt
from openpilot.common.params import Params

class TestSetSpeedFijo:
    def __init__(self):
        self.params = Params()
        self.DongleID = self.params.get("DongleId").decode("utf-8") if self.params.get("DongleId") else "TestDevice"

        # Cargar configuración MQTT
        with open("config_mqtt.json", "r") as f:
            config = json.load(f)
            self.broker_address = config.get("broker", "localhost")

        self.mqttc = mqtt.Client()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message

        self.setspeed_recibido = False
        self.ultimo_setspeed = None
        self.contador_mensajes = 0
        self.velocidad_esperada = 34.0  # km/h

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("✅ Conectado al broker MQTT para verificar setSpeed fijo")
            # Suscribirse específicamente a los topics de setSpeed
            topics_setspeed = [
                f"telemetry_mqtt/{self.DongleID}/carControl",
                f"telemetry_mqtt/{self.DongleID}/controlsState",
                f"telemetry_mqtt/{self.DongleID}/resumen_principal"
            ]

            for topic in topics_setspeed:
                self.mqttc.subscribe(topic, qos=0)
                print(f"📡 Suscrito a: {topic}")
        else:
            print(f"❌ Error de conexión MQTT: {rc}")

    def on_disconnect(self, client, userdata, rc):
        print("🔌 Desconectado del broker MQTT")

    def on_message(self, client, userdata, msg):
        """Procesa los mensajes MQTT recibidos."""
        try:
            topic = msg.topic
            payload = msg.payload.decode()
            self.contador_mensajes += 1

            print(f"\n📨 Mensaje #{self.contador_mensajes} recibido en: {topic}")

            if topic.endswith("/carControl"):
                self.procesar_car_control(payload)
            elif topic.endswith("/controlsState"):
                self.procesar_controls_state(payload)
            elif topic.endswith("/resumen_principal"):
                self.procesar_resumen(payload)
            else:
                print(f"📦 Otro mensaje: {payload[:100]}...")

        except Exception as e:
            print(f"❌ Error al procesar mensaje: {e}")

    def procesar_car_control(self, payload):
        """Procesa datos de carControl para extraer setSpeed."""
        try:
            data = json.loads(payload)
            print("🔍 Analizando carControl...")

            # Buscar setSpeed en hudControl
            hud_control = data.get("hudControl", {})
            if isinstance(hud_control, dict):
                set_speed_ms = hud_control.get("setSpeed")
                if set_speed_ms is not None:
                    set_speed_kmh = set_speed_ms * 3.6
                    self.ultimo_setspeed = {
                        "setSpeed_ms": set_speed_ms,
                        "setSpeed_kmh": set_speed_kmh,
                        "timestamp": time.time()
                    }

                    print(f"   📊 setSpeed (HUD): {set_speed_ms:.2f} m/s = {set_speed_kmh:.1f} km/h")

                    # Verificar si es 34 km/h
                    if abs(set_speed_kmh - self.velocidad_esperada) < 0.1:
                        print(f"✅ SETSPEED CORRECTO: {set_speed_kmh:.1f} km/h (esperado: {self.velocidad_esperada} km/h)")
                        self.setspeed_recibido = True
                    else:
                        print(f"⚠️ SETSPEED INCORRECTO: {set_speed_kmh:.1f} km/h (esperado: {self.velocidad_esperada} km/h)")
                else:
                    print("❌ No se encontró setSpeed en hudControl")
            else:
                print("❌ hudControl no es un diccionario")

            # Mostrar todas las claves disponibles
            print(f"   🔑 Claves disponibles: {list(data.keys())}")

        except json.JSONDecodeError as e:
            print(f"❌ Error al decodificar carControl: {e}")

    def procesar_controls_state(self, payload):
        """Procesa datos de controlsState para extraer vCruise."""
        try:
            data = json.loads(payload)
            print("🔍 Analizando controlsState...")

            v_cruise = data.get("vCruise")
            if v_cruise is not None:
                print(f"   📊 vCruise: {v_cruise:.1f} km/h")

                # Verificar si es 34 km/h
                if abs(v_cruise - self.velocidad_esperada) < 0.1:
                    print(f"✅ VCRUISE CORRECTO: {v_cruise:.1f} km/h (esperado: {self.velocidad_esperada} km/h)")
                else:
                    print(f"⚠️ VCRUISE INCORRECTO: {v_cruise:.1f} km/h (esperado: {self.velocidad_esperada} km/h)")

        except json.JSONDecodeError as e:
            print(f"❌ Error al decodificar controlsState: {e}")

    def procesar_resumen(self, payload):
        """Procesa el resumen principal."""
        try:
            data = json.loads(payload)
            print("🔍 Analizando resumen principal...")

            if "control" in data:
                control = data["control"]
                set_speed = control.get("setSpeed")
                set_speed_kmh = control.get("setSpeed_kmh")

                print(f"   📊 Resumen - setSpeed: {set_speed}")
                print(f"   📊 Resumen - setSpeed_kmh: {set_speed_kmh}")

                if set_speed_kmh is not None:
                    if abs(set_speed_kmh - self.velocidad_esperada) < 0.1:
                        print(f"✅ RESUMEN SETSPEED CORRECTO: {set_speed_kmh:.1f} km/h")
                    else:
                        print(f"⚠️ RESUMEN SETSPEED INCORRECTO: {set_speed_kmh:.1f} km/h")

        except json.JSONDecodeError as e:
            print(f"❌ Error al decodificar resumen: {e}")

    def conectar(self):
        """Conecta al broker MQTT."""
        try:
            self.mqttc.connect(self.broker_address, 1883, 60)
            self.mqttc.loop_start()
            time.sleep(1)
            return True
        except Exception as e:
            print(f"❌ Error al conectar: {e}")
            return False

    def ejecutar_prueba(self, duracion=30):
        """Ejecuta la prueba por un tiempo determinado."""
        print(f"🧪 Iniciando prueba de setSpeed fijo por {duracion} segundos...")
        print(f"🎯 DongleID: {self.DongleID}")
        print(f"🎯 Velocidad esperada: {self.velocidad_esperada} km/h")
        print("⏱️  Presiona Ctrl+C para detener antes del tiempo")

        try:
            time.sleep(duracion)
        except KeyboardInterrupt:
            print("\n⏹️  Prueba interrumpida por el usuario")

        # Mostrar resultados
        print("\n" + "="*60)
        print("📊 RESULTADOS DE LA PRUEBA DE SETSPEED FIJO")
        print("="*60)
        print(f"📈 Total de mensajes recibidos: {self.contador_mensajes}")
        print(f"✅ SetSpeed recibido: {'SÍ' if self.setspeed_recibido else 'NO'}")

        if self.ultimo_setspeed:
            print(f"🚗 Último setSpeed: {self.ultimo_setspeed['setSpeed_kmh']:.1f} km/h")
            if abs(self.ultimo_setspeed['setSpeed_kmh'] - self.velocidad_esperada) < 0.1:
                print("✅ ¡PRUEBA EXITOSA! El setSpeed está fijo a 34 km/h")
            else:
                print("❌ PRUEBA FALLIDA: El setSpeed no está en 34 km/h")
        else:
            print("❌ No se recibió ningún setSpeed")

        print("="*60)

    def cerrar(self):
        """Cierra la conexión MQTT."""
        self.mqttc.loop_stop()
        self.mqttc.disconnect()

def main():
    """Función principal."""
    print("🚀 Iniciando prueba de setSpeed fijo a 34 km/h")

    tester = TestSetSpeedFijo()

    if not tester.conectar():
        print("❌ No se pudo conectar al broker MQTT")
        return

    try:
        # Preguntar duración de la prueba
        try:
            duracion = int(input("⏱️  Duración de la prueba en segundos (default: 30): ") or "30")
        except ValueError:
            duracion = 30

        tester.ejecutar_prueba(duracion)

    except KeyboardInterrupt:
        print("\n👋 Interrumpido por el usuario")
    finally:
        tester.cerrar()

if __name__ == "__main__":
    main()






























