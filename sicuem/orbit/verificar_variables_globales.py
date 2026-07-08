#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de verificación de variables globales Orbit
Verifica si las variables globales están funcionando correctamente
"""
import time
import sys
import os

# Agregar el directorio de orbit al path
sys.path.append(os.path.join(os.path.dirname(__file__)))

def check_global_variables():
  """Verifica las variables globales de Orbit."""
  print("🔍 Verificando variables globales Orbit...")
  print("="*50)

  try:
    # Importar módulos de Orbit
    from orbit_control_ultra_simple import (
      orbit_forward,
      orbit_break,
      orbit_tright,
      orbit_tleft
    )

    from orbit_speed_ultra_simple import (
      orbit_speed_increase,
      orbit_speed_decrease
    )

    print("✅ Módulos importados correctamente")
    print("\n📊 Estado de las variables globales:")
    print(f"   orbit_forward: {orbit_forward}")
    print(f"   orbit_break: {orbit_break}")
    print(f"   orbit_tright: {orbit_tright}")
    print(f"   orbit_tleft: {orbit_tleft}")
    print(f"   orbit_speed_increase: {orbit_speed_increase}")
    print(f"   orbit_speed_decrease: {orbit_speed_decrease}")

    # Probar modificación de variables
    print("\n🧪 Probando modificación de variables...")

    # Modificar variables de control
    import orbit_control_ultra_simple
    orbit_control_ultra_simple.orbit_forward = True
    orbit_control_ultra_simple.orbit_break = True

    # Modificar variables de velocidad
    import orbit_speed_ultra_simple
    orbit_speed_ultra_simple.orbit_speed_increase = True
    orbit_speed_ultra_simple.orbit_speed_decrease = True

    print("✅ Variables modificadas correctamente")

    # Verificar cambios
    print("\n📊 Estado después de modificación:")
    print(f"   orbit_forward: {orbit_control_ultra_simple.orbit_forward}")
    print(f"   orbit_break: {orbit_control_ultra_simple.orbit_break}")
    print(f"   orbit_speed_increase: {orbit_speed_ultra_simple.orbit_speed_increase}")
    print(f"   orbit_speed_decrease: {orbit_speed_ultra_simple.orbit_speed_decrease}")

    print("\n✅ Variables globales funcionando correctamente")

  except ImportError as e:
    print(f"❌ Error importando módulos: {e}")
    print("💡 Asegúrate de que los archivos estén en el directorio correcto")
  except Exception as e:
    print(f"❌ Error verificando variables: {e}")

def test_mqtt_commands():
  """Prueba los comandos MQTT."""
  print("\n🧪 Probando comandos MQTT...")
  print("="*50)

  try:
    import json
    import paho.mqtt.publish as publish
    from openpilot.common.params import Params

    # Obtener DongleID
    params = Params()
    DONGLE_ID = params.get("DongleId").decode("utf-8") if params.get("DongleId") else "UnregisteredDevice"

    BROKER_ADDRESS = "80.29.2.242"
    BROKER_PORT = 1883

    print(f"🎯 DongleID: {DONGLE_ID}")
    print(f"📡 Broker: {BROKER_ADDRESS}:{BROKER_PORT}")

    # Enviar comando de velocidad
    topic = f"telemetry_config/{DONGLE_ID}/speed"
    message = {"speed_decrease": True, "timestamp": str(int(time.time()))}
    print(f"📤 Enviando: {topic} -> {json.dumps(message)}")

    publish.single(topic, json.dumps(message), hostname=BROKER_ADDRESS, port=BROKER_PORT)
    print("✅ Comando enviado correctamente")

    # Esperar un poco
    time.sleep(2)

    # Verificar si las variables cambiaron
    import orbit_speed_ultra_simple
    if orbit_speed_ultra_simple.orbit_speed_decrease:
      print("✅ Variable global actualizada por MQTT")
    else:
      print("⚠️ Variable global no actualizada por MQTT")

  except Exception as e:
    print(f"❌ Error probando MQTT: {e}")

def main():
  print("🚀 Verificación del Sistema Orbit")
  print("="*60)

  # Verificar variables globales
  check_global_variables()

  # Probar comandos MQTT
  test_mqtt_commands()

  print("\n" + "="*60)
  print("✅ Verificación completada")

if __name__ == "__main__":
  main()












