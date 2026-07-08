#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de simulación del sistema Orbit
Simula el comportamiento del sistema para verificar funcionamiento
"""
import time
import sys
import os

# Agregar el directorio de orbit al path
sys.path.append(os.path.join(os.path.dirname(__file__)))

def simulate_speed_control():
  """Simula el control de velocidad."""
  print("🧪 Simulando control de velocidad...")
  print("="*50)

  try:
    # Importar el controlador de velocidad
    from orbit_speed_ultra_simple import orbit_speed_ultra_simple

    # Simular car_control y car_state
    class MockCarControl:
      def __init__(self):
        self.hudControl = MockHudControl()
        self.vCruise = 40.0

    class MockHudControl:
      def __init__(self):
        self.setSpeed = 40.0 / 3.6  # 40 km/h en m/s

    class MockCarState:
      pass

    class MockVCruiseHelper:
      def __init__(self):
        self.v_cruise_kph = 40.0
        self.v_cruise_cluster_kph = 40.0

    # Crear objetos mock
    car_control = MockCarControl()
    car_state = MockCarState()
    v_cruise_helper = MockVCruiseHelper()

    print(f"📊 Velocidad inicial: {v_cruise_helper.v_cruise_kph} km/h")

    # Simular comando de aumento de velocidad
    print("\n⬆️ Simulando comando SPEED INCREASE...")
    import orbit_speed_ultra_simple
    orbit_speed_ultra_simple.orbit_speed_increase = True

    # Procesar comando
    orbit_speed_ultra_simple.process_speed_commands(car_control, car_state, v_cruise_helper)

    print(f"📊 Velocidad después de INCREASE: {v_cruise_helper.v_cruise_kph} km/h")
    print(f"📊 hudControl.setSpeed: {car_control.hudControl.setSpeed:.2f} m/s")
    print(f"📊 vCruise: {car_control.vCruise} km/h")

    # Simular comando de reducción de velocidad
    print("\n⬇️ Simulando comando SPEED DECREASE...")
    orbit_speed_ultra_simple.orbit_speed_decrease = True

    # Procesar comando
    orbit_speed_ultra_simple.process_speed_commands(car_control, car_state, v_cruise_helper)

    print(f"📊 Velocidad después de DECREASE: {v_cruise_helper.v_cruise_kph} km/h")
    print(f"📊 hudControl.setSpeed: {car_control.hudControl.setSpeed:.2f} m/s")
    print(f"📊 vCruise: {car_control.vCruise} km/h")

    print("\n✅ Simulación de control de velocidad completada")

  except Exception as e:
    print(f"❌ Error en simulación de velocidad: {e}")

def simulate_control_commands():
  """Simula los comandos de control."""
  print("\n🧪 Simulando comandos de control...")
  print("="*50)

  try:
    # Importar el controlador de control
    from orbit_control_ultra_simple import orbit_control_ultra_simple

    # Simular car_control y car_state
    class MockCarControl:
      def __init__(self):
        self.actuators = MockActuators()

    class MockActuators:
      def __init__(self):
        self.gas = 0.0
        self.brake = 0.0
        self.steer = 0.0

    class MockCarState:
      pass

    class MockSM:
      pass

    # Crear objetos mock
    car_control = MockCarControl()
    car_state = MockCarState()
    sm = MockSM()

    print("📊 Estado inicial de actuators:")
    print(f"   gas: {car_control.actuators.gas}")
    print(f"   brake: {car_control.actuators.brake}")
    print(f"   steer: {car_control.actuators.steer}")

    # Simular comando forward
    print("\n🚀 Simulando comando FORWARD...")
    import orbit_control_ultra_simple
    orbit_control_ultra_simple.orbit_forward = True

    # Procesar comando
    orbit_control_ultra_simple.process_commands(car_control, car_state, sm)

    print(f"📊 Estado después de FORWARD:")
    print(f"   gas: {car_control.actuators.gas}")
    print(f"   brake: {car_control.actuators.brake}")
    print(f"   steer: {car_control.actuators.steer}")

    # Simular comando break
    print("\n🛑 Simulando comando BREAK...")
    orbit_control_ultra_simple.orbit_break = True

    # Procesar comando
    orbit_control_ultra_simple.process_commands(car_control, car_state, sm)

    print(f"📊 Estado después de BREAK:")
    print(f"   gas: {car_control.actuators.gas}")
    print(f"   brake: {car_control.actuators.brake}")
    print(f"   steer: {car_control.actuators.steer}")

    print("\n✅ Simulación de comandos de control completada")

  except Exception as e:
    print(f"❌ Error en simulación de control: {e}")

def main():
  print("🚀 Simulación del Sistema Orbit")
  print("="*60)

  # Simular control de velocidad
  simulate_speed_control()

  # Simular comandos de control
  simulate_control_commands()

  print("\n" + "="*60)
  print("✅ Simulación completada")
  print("💡 Si las simulaciones funcionan, el problema puede estar en:")
  print("   - Los comandos MQTT no llegan al comma")
  print("   - El sistema MQTT no está procesando los comandos")
  print("   - Las variables globales no se están actualizando")

if __name__ == "__main__":
  main()












