#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Control Orbit - Enfoque Ultra Simplificado
Sin parámetros problemáticos, solo variables globales
"""
import time

# Variables globales para comandos de control
orbit_forward = False
orbit_break = False
orbit_tright = False
orbit_tleft = False

class OrbitControlUltraSimple:
  """Controlador Orbit ultra simplificado."""

  def __init__(self):
    self.last_command_time = 0
    self.command_duration = 0.5  # Duración del comando en segundos
    self.steering_angle = 0.0
    self.steering_speed = 2.0  # Grados por segundo

  def process_commands(self, car_control, car_state, sm):
    """Procesa todos los comandos de Orbit usando variables globales."""
    global orbit_forward, orbit_break, orbit_tright, orbit_tleft
    current_time = time.time()

    # Crear un controlsState dummy simple
    class DummyControlsState:
      def __init__(self):
        self.active = True
        self.vCruise = 40.0

    controls_state = DummyControlsState()

    # Procesar comandos de control básico
    self.process_control_commands(car_control, car_state, controls_state, current_time)

    # Limpiar comandos expirados
    self.clear_expired_commands(current_time)

  def process_control_commands(self, car_control, car_state, controls_state, current_time):
    """Procesa comandos de control básico (forward, break, tright, tleft)."""
    global orbit_forward, orbit_break, orbit_tright, orbit_tleft

    # Comando Forward (Aceleración)
    if orbit_forward:
      self.handle_forward_command(car_control, car_state, controls_state)
      orbit_forward = False  # Limpiar comando

    # Comando Break (Frenado)
    if orbit_break:
      self.handle_break_command(car_control, car_state, controls_state)
      orbit_break = False  # Limpiar comando

    # Comando Tright (Giro a la derecha)
    if orbit_tright:
      self.handle_tright_command(car_control, car_state, controls_state)
      orbit_tright = False  # Limpiar comando

    # Comando Tleft (Giro a la izquierda)
    if orbit_tleft:
      self.handle_tleft_command(car_control, car_state, controls_state)
      orbit_tleft = False  # Limpiar comando

  def handle_forward_command(self, car_control, car_state, controls_state):
    """Maneja el comando de aceleración."""
    if not controls_state.active:
      print("⚠️ Comando FORWARD ignorado: controles no activos")
      return

    # Aplicar aceleración suave
    if hasattr(car_control, 'actuators'):
      car_control.actuators.gas = 0.3  # Aceleración suave
      print(f"🚀 Comando FORWARD ejecutado: aceleración 0.3")

  def handle_break_command(self, car_control, car_state, controls_state):
    """Maneja el comando de frenado."""
    if not controls_state.active:
      print("⚠️ Comando BREAK ignorado: controles no activos")
      return

    # Aplicar frenado suave
    if hasattr(car_control, 'actuators'):
      car_control.actuators.brake = 0.3  # Frenado suave
      print(f"🛑 Comando BREAK ejecutado: frenado 0.3")

  def handle_tright_command(self, car_control, car_state, controls_state):
    """Maneja el comando de giro a la derecha."""
    if not controls_state.active:
      print("⚠️ Comando TRIGHT ignorado: controles no activos")
      return

    # Aplicar giro suave a la derecha
    if hasattr(car_control, 'actuators'):
      self.steering_angle = min(self.steering_angle + self.steering_speed, 30.0)
      car_control.actuators.steer = self.steering_angle / 30.0  # Normalizar a -1,1
      print(f"↗️ Comando TRIGHT ejecutado: ángulo {self.steering_angle:.1f}°")

  def handle_tleft_command(self, car_control, car_state, controls_state):
    """Maneja el comando de giro a la izquierda."""
    if not controls_state.active:
      print("⚠️ Comando TLEFT ignorado: controles no activos")
      return

    # Aplicar giro suave a la izquierda
    if hasattr(car_control, 'actuators'):
      self.steering_angle = max(self.steering_angle - self.steering_speed, -30.0)
      car_control.actuators.steer = self.steering_angle / 30.0  # Normalizar a -1,1
      print(f"↖️ Comando TLEFT ejecutado: ángulo {self.steering_angle:.1f}°")

  def clear_expired_commands(self, current_time):
    """Limpia comandos que han expirado."""
    if current_time - self.last_command_time > self.command_duration:
      # Resetear ángulo de dirección gradualmente
      if self.steering_angle > 0:
        self.steering_angle = max(self.steering_angle - self.steering_speed, 0.0)
      elif self.steering_angle < 0:
        self.steering_angle = min(self.steering_angle + self.steering_speed, 0.0)

# Instancia global del controlador ultra simplificado
orbit_control_ultra_simple = OrbitControlUltraSimple()












