#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Control de Velocidad Orbit - Enfoque Directo
Modifica directamente v_cruise_helper sin usar parámetros problemáticos
"""
import time
from openpilot.common.params import Params

class OrbitSpeedDirect:
  """Controlador de velocidad directo sin parámetros problemáticos."""

  def __init__(self):
    self.params = Params()
    self.speed_increment = 1.0  # km/h
    self.last_speed_command = 0
    self.command_duration = 0.5  # segundos

  def process_speed_commands(self, car_control, car_state, v_cruise_helper):
    """Procesa comandos de velocidad directamente."""
    current_time = time.time()

    # Verificar comandos de velocidad
    speed_increase = self.params.get_bool("orbit_speed_increase")
    speed_decrease = self.params.get_bool("orbit_speed_decrease")

    if speed_increase or speed_decrease:
      # Obtener velocidad actual
      current_speed = v_cruise_helper.v_cruise_kph
      if current_speed == 255:  # V_CRUISE_UNSET
        current_speed = 40.0  # Velocidad por defecto

      # Calcular nueva velocidad
      if speed_increase:
        new_speed = min(current_speed + self.speed_increment, 145.0)
        command_type = "INCREASE"
      else:
        new_speed = max(current_speed - self.speed_increment, 8.0)
        command_type = "DECREASE"

      # Aplicar cambios directamente al v_cruise_helper
      v_cruise_helper.v_cruise_kph = new_speed
      v_cruise_helper.v_cruise_cluster_kph = new_speed

      # También modificar car_control si es posible
      if hasattr(car_control, 'hudControl'):
        car_control.hudControl.setSpeed = new_speed / 3.6  # Convertir a m/s
      if hasattr(car_control, 'vCruise'):
        car_control.vCruise = new_speed

      # Limpiar comandos
      self.params.put_bool("orbit_speed_increase", False)
      self.params.put_bool("orbit_speed_decrease", False)

      self.last_speed_command = current_time

      print(f"🎯 Comando SPEED {command_type} ejecutado: {current_speed:.1f} → {new_speed:.1f} km/h")
      print(f"   📊 v_cruise_helper.v_cruise_kph: {new_speed:.1f} km/h")
      print(f"   📊 v_cruise_helper.v_cruise_cluster_kph: {new_speed:.1f} km/h")

# Instancia global del controlador de velocidad directo
orbit_speed_direct = OrbitSpeedDirect()












