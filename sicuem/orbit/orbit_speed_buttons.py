#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Control de Velocidad Orbit - Enfoque con Simulación de Botones
Simula los botones de velocidad como lo hace openpilot internamente
"""
import time
from openpilot.common.params import Params
from cereal import car

class OrbitSpeedButtons:
  """Controlador de velocidad que simula botones como openpilot."""

  def __init__(self):
    self.params = Params()
    self.speed_increment = 1.0  # km/h

  def process_speed_commands(self, car_control, car_state):
    """Procesa comandos de velocidad simulando botones."""

    # Verificar comandos de velocidad
    speed_increase = self.params.get_bool("orbit_speed_increase")
    speed_decrease = self.params.get_bool("orbit_speed_decrease")

    if speed_increase or speed_decrease:
      # Simular evento de botón
      if speed_increase:
        button_event = car.CarState.ButtonEvent(
          type=car.CarState.ButtonEvent.Type.accelCruise,
          pressed=False  # False = botón soltado (evento de cambio)
        )
        command_type = "INCREASE"
      else:
        button_event = car.CarState.ButtonEvent(
          type=car.CarState.ButtonEvent.Type.decelCruise,
          pressed=False  # False = botón soltado (evento de cambio)
        )
        command_type = "DECREASE"

      # Agregar evento de botón al car_state
      if not hasattr(car_state, 'buttonEvents') or car_state.buttonEvents is None:
        car_state.buttonEvents = []
      car_state.buttonEvents.append(button_event)

      # Limpiar comandos
      self.params.put_bool("orbit_speed_increase", False)
      self.params.put_bool("orbit_speed_decrease", False)

      print(f"🎯 Comando SPEED {command_type} ejecutado: Simulando botón {button_event.type}")

# Instancia global del controlador de velocidad con botones
orbit_speed_buttons = OrbitSpeedButtons()












