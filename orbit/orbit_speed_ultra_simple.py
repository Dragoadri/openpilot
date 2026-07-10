#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Control de Velocidad Orbit - Enfoque Ultra Simplificado
Modifica la velocidad de crucero cuando el control longitudinal está activo
"""
import time
from openpilot.common.params import Params

# Variables globales para comandos de velocidad
orbit_speed_increase = False
orbit_speed_decrease = False

class OrbitSpeedUltraSimple:
  """Controlador de velocidad ultra simplificado."""

  def __init__(self):
    self.params = Params()
    # Incremento por defecto: 10 km/h (configurable desde app en el futuro)
    self.speed_increment_default = 10.0  # km/h
    self.last_speed_command = 0
    self.command_duration = 0.5  # segundos

  def get_speed_increment(self):
    """Obtiene el incremento de velocidad desde Params o usa el valor por defecto."""
    try:
      increment_str = self.params.get("orbit_speed_increment")
      if increment_str:
        # Si es bytes, decodificar a string
        if isinstance(increment_str, bytes):
          increment_str = increment_str.decode('utf-8')
        increment = float(increment_str)
        # Validar que esté en un rango razonable (1-50 km/h)
        return max(1.0, min(50.0, increment))
    except (ValueError, TypeError):
      # Si hay un error al leer el incremento, usamos el valor por defecto sin log de debug
      return self.speed_increment_default

  def process_speed_commands(self, car_control, car_state, v_cruise_helper):
    """Procesa comandos de velocidad usando variables globales.

    IMPORTANTE: Solo funciona cuando el control longitudinal está activo (CC.longActive).
    Esto significa que el usuario debe haber activado el control de crucero con el botón del volante.
    """
    global orbit_speed_increase, orbit_speed_decrease

    # Usamos directamente las variables globales; ya están compartidas con mqtt_comandos
    current_time = time.time()

    # Verificar que el control de crucero esté activo
    # Verificamos tanto cruiseState.enabled como que v_cruise_kph esté inicializado
    # También verificamos si el control longitudinal está activo (enabled_long)
    cruise_enabled = False
    if hasattr(car_state, 'cruiseState'):
      cruise_enabled = getattr(car_state.cruiseState, 'enabled', False)

    # Verificar si el control longitudinal está activo (más flexible para simulador)
    long_active = False
    if car_control is not None and hasattr(car_control, 'enabled_long'):
      long_active = car_control.enabled_long
    elif hasattr(car_control, 'longActive'):
      long_active = car_control.longActive

    # También verificamos que v_cruise_kph esté inicializado (no sea V_CRUISE_UNSET = 255)
    v_cruise_initialized = v_cruise_helper.v_cruise_kph != 255 and v_cruise_helper.v_cruise_kph > 0

    # Aceptamos si el crucero está habilitado O si el control longitudinal está activo
    # (esto es más flexible para simuladores y diferentes configuraciones de coches)
    cruise_or_long_active = cruise_enabled or long_active

    if not cruise_or_long_active or not v_cruise_initialized:
      # Si hay comandos pendientes pero el crucero no está activo, limpiarlos sin procesar
      if orbit_speed_increase or orbit_speed_decrease:
        orbit_speed_increase = False
        orbit_speed_decrease = False
      return

    if orbit_speed_increase or orbit_speed_decrease:
      # Obtener velocidad actual desde v_cruise_helper
      current_speed = v_cruise_helper.v_cruise_kph

      if current_speed == 255:  # V_CRUISE_UNSET
        # Intentar obtener desde la velocidad actual del vehículo
        if hasattr(car_state, 'vEgo'):
          current_speed = car_state.vEgo * 3.6  # Convertir m/s a km/h
        else:
          current_speed = 40.0  # Velocidad por defecto

      # Obtener incremento configurable (por ahora 10 km/h por defecto)
      try:
        speed_increment = self.get_speed_increment()
      except Exception:
        speed_increment = 10.0

      # Calcular nueva velocidad
      if orbit_speed_increase:
        new_speed = min(current_speed + speed_increment, 145.0)
      else:
        new_speed = max(current_speed - speed_increment, 8.0)

      # Aplicar cambios directamente al v_cruise_helper
      v_cruise_helper.v_cruise_kph = new_speed
      v_cruise_helper.v_cruise_cluster_kph = new_speed

      # También modificar car_control si es posible
      if car_control is not None and hasattr(car_control, 'hudControl'):
        car_control.hudControl.setSpeed = new_speed / 3.6  # Convertir a m/s
      if car_control is not None and hasattr(car_control, 'vCruise'):
        car_control.vCruise = new_speed

      # Limpiar las variables globales de comando
      orbit_speed_increase = False
      orbit_speed_decrease = False

      self.last_speed_command = current_time

# Instancia global del controlador de velocidad ultra simplificado
orbit_speed_ultra_simple = OrbitSpeedUltraSimple()












