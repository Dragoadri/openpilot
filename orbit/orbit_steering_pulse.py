#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Giro Temporal del Volante Orbit
Comunica mqtt_comandos (proceso manager) con controlsd (proceso separado).

IMPORTANTE: mqtt_comandos corre como THREAD dentro del proceso manager, pero
controlsd es un PROCESO distinto. Las variables globales del módulo NO cruzan
esa barrera. Por eso el estado autoritativo se guarda en un Param
("orbit_steering_pulse", formato "direction:start_ms") que ambos procesos
comparten a través del filesystem. Los globales del módulo se mantienen como
fast-path dentro del mismo proceso, pero el Param manda.

Funcionamiento:
1. Fase inicial (0.5s): Gira el volante en la dirección indicada
2. Fase de retorno (0.5s): Gira el volante en la dirección contraria para volver al estado original
"""
import time

from openpilot.common.params import Params

# Variables globales para comandos de giro temporal (fast-path mismo proceso)
orbit_steering_pulse_start = None  # Timestamp del inicio del pulso
orbit_steering_pulse_direction = None  # "left" o "right"
orbit_steering_pulse_initial_duration = 0.5  # Duración de la fase inicial (giro) en segundos
orbit_steering_pulse_return_duration = 0.5  # Duración de la fase de retorno en segundos
orbit_steering_pulse_angle = 3.0  # Grados de giro

# Duración total = fase inicial + fase de retorno
orbit_steering_pulse_duration = orbit_steering_pulse_initial_duration + orbit_steering_pulse_return_duration

# Clave del Param autoritativo (cruza la barrera de proceso). Registrada en
# common/params_keys.h como CLEAR_ON_MANAGER_START | STRING.
_PARAM_KEY = "orbit_steering_pulse"

# Instancia Params perezosa (compartida en el proceso). controlsd llama a
# get_steering_pulse() cada ciclo, así que evitamos recrear Params en cada call.
_params = None

# Caché de la LECTURA del Param: controlsd llama a get_steering_pulse() a 100 Hz
# en un proceso SCHED_FIFO y Params.get abre+lee el fichero en cada llamada.
# TTL de 0.1 s: un pulso dura 1 s y sus fases se calculan desde el timestamp de
# inicio, así que la forma del pulso no se degrada; solo se retrasa <=0.1 s la
# detección del disparo (que ya llega por MQTT, con latencia de red mayor).
_PULSE_PARAM_TTL_S = 0.1
_pulse_param_cache_ts = 0.0
_pulse_param_cache_val = None

def _get_params():
  global _params
  if _params is None:
    _params = Params()
  return _params

def set_steering_pulse(direction):
  """Activa un pulso de giro temporal del volante con dos fases.

  Escribe el Param autoritativo (formato "direction:start_ms") para que
  controlsd (proceso separado) lo vea, y también actualiza los globales del
  módulo como fast-path para el mismo proceso.
  """
  global orbit_steering_pulse_start, orbit_steering_pulse_direction, _pulse_param_cache_ts
  start = time.time()
  orbit_steering_pulse_start = start
  orbit_steering_pulse_direction = direction
  _pulse_param_cache_ts = 0.0  # invalida la caché de lectura para ver el pulso al instante
  # Param autoritativo: dirección + timestamp de inicio (ms epoch). La expiración
  # se deriva de start + duration para preservar la semántica de dos fases.
  # block=True: con el put asíncrono (default) la escritura podía aterrizar DESPUÉS
  # de un clear_steering_pulse() posterior (remove síncrono) y resucitar un pulso
  # viejo en controlsd. Este hilo (manager/MQTT) no es RT: el fsync aquí es seguro.
  try:
    _get_params().put(_PARAM_KEY, f"{direction}:{int(start * 1000)}", block=True)
  except Exception:
    pass  # Error silenciado para reducir uso de memoria

def get_steering_pulse():
  """Obtiene el estado actual del pulso de giro.

  Lee el Param autoritativo (para ver pulsos disparados por mqtt_comandos en
  otro proceso) y calcula fase/expiración con la misma duración de siempre.

  Returns:
    tuple: (pulse_start, direction, is_active, phase, effective_direction)
      - pulse_start: Timestamp del inicio del pulso
      - direction: Dirección original ("left" o "right")
      - is_active: True si el pulso está activo
      - phase: "initial" o "return" según la fase actual
      - effective_direction: Dirección efectiva a aplicar ("left", "right", o None)
  """
  global orbit_steering_pulse_start, orbit_steering_pulse_direction
  global _pulse_param_cache_ts, _pulse_param_cache_val

  # El Param es autoritativo: refleja lo que escribió mqtt_comandos en el
  # proceso manager. Si existe, sobreescribe los globales locales.
  # Lectura cacheada (TTL 0.1 s) para no hacer I/O de disco a 100 Hz en el loop RT.
  now_mono = time.monotonic()
  if now_mono - _pulse_param_cache_ts >= _PULSE_PARAM_TTL_S:
    try:
      _pulse_param_cache_val = _get_params().get(_PARAM_KEY)
    except Exception:
      _pulse_param_cache_val = None
    _pulse_param_cache_ts = now_mono

  pulse_start = None
  direction = None
  try:
    raw = _pulse_param_cache_val
    if raw:
      # raw ya es str desde Params.get()
      part_dir, _, part_start = raw.partition(":")
      if part_dir in ("left", "right") and part_start:
        direction = part_dir
        pulse_start = int(part_start) / 1000.0
  except Exception:
    pulse_start = None
    direction = None

  # Fallback al fast-path del mismo proceso si no había Param válido.
  if pulse_start is None or direction is None:
    pulse_start = orbit_steering_pulse_start
    direction = orbit_steering_pulse_direction

  if pulse_start is None or direction is None:
    return None, None, False, None, None

  current_time = time.time()
  elapsed = current_time - pulse_start

  # Si el pulso ha terminado completamente (expirado), limpiar todo.
  if elapsed >= orbit_steering_pulse_duration or elapsed < 0:
    clear_steering_pulse()
    return None, None, False, None, None

  # Sincronizar globales locales con lo leído (mantiene el fast-path coherente).
  orbit_steering_pulse_start = pulse_start
  orbit_steering_pulse_direction = direction

  # Determinar la fase actual
  if elapsed < orbit_steering_pulse_initial_duration:
    # Fase inicial: girar en la dirección indicada
    phase = "initial"
    effective_direction = direction
  else:
    # Fase de retorno: girar en la dirección contraria
    phase = "return"
    effective_direction = "right" if direction == "left" else "left"

  return pulse_start, direction, True, phase, effective_direction

def clear_steering_pulse():
  """Limpia el pulso de giro temporal (globales + Param autoritativo)."""
  global orbit_steering_pulse_start, orbit_steering_pulse_direction, _pulse_param_cache_ts, _pulse_param_cache_val
  orbit_steering_pulse_start = None
  orbit_steering_pulse_direction = None
  _pulse_param_cache_ts = 0.0
  _pulse_param_cache_val = None  # evita releer un valor ya expirado desde la caché
  try:
    _get_params().remove(_PARAM_KEY)
  except Exception:
    pass  # Error silenciado para reducir uso de memoria
