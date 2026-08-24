#!/usr/bin/env python3
"""Pulso temporal de direccion (verbo `steering_pulse`, seccion 6 -- modo BANCO).

Comunica el hilo del mando (proceso manager) con controlsd (proceso distinto). Las
globales del modulo NO cruzan esa barrera, asi que el estado autoritativo vive en el
param `orbit_steering_pulse` y las globales solo son fast-path dentro del mismo proceso.

Forma del pulso: dos fases simetricas -- una inicial que empuja hacia `direction` y una
de retorno que empuja al lado contrario para devolver el volante a donde estaba.

DOS ARREGLOS DE ESTA VERSION
1) DEADMAN MONOTONO. Antes el instante de inicio se sellaba con time.time() en el
   manager y controlsd calculaba `elapsed = time.time() - start`. Son dos procesos
   leyendo el reloj DE PARED: en un comma sin fix GPS ni NTP el reloj salta varios
   minutos en cuanto sincroniza, y ese salto cae justo en el primer trayecto. Con un
   salto hacia atras el pulso se reactivaba (elapsed negativo) y con uno hacia delante
   moria a medias. Ahora el plazo se mide con time.monotonic(), que es CLOCK_MONOTONIC
   -- de SISTEMA, comparable entre procesos, y no lo mueve ningun ajuste de hora
   (seccion 3.2: "los plazos internos se miden con reloj monotono, nunca con epoch").
   El sello de pared se conserva en el param solo para la UI y la telemetria.
2) DURACION Y MAGNITUD EXPLICITAS. El verbo v2 lleva `duration_ms` y `torque`; antes
   la duracion y el angulo eran constantes del modulo y el mando no podia acotarlos.

El param sigue llamandose igual y sigue siendo una cadena; el overlay de la UI solo
mira si cambia, asi que anadir campos al final no le afecta. Formato:

    "<direction>:<start_ms_pared>:<start_mono>:<dur_inicial_ms>:<magnitud>"

Los tres ultimos campos son opcionales al LEER (un param escrito por una version
anterior se sigue entendiendo, con la duracion y la magnitud de siempre).
"""
import time

from openpilot.common.params import Params

# Variables globales (fast-path dentro del mismo proceso)
orbit_steering_pulse_start = None       # instante MONOTONO de inicio
orbit_steering_pulse_direction = None   # "left" o "right"
orbit_steering_pulse_initial_duration = 0.5  # fase inicial (s), por defecto
orbit_steering_pulse_return_duration = 0.5   # fase de retorno (s), por defecto
orbit_steering_pulse_angle = 3.0        # grados de giro a magnitud 1.0

# Duracion total por defecto = fase inicial + fase de retorno
orbit_steering_pulse_duration = orbit_steering_pulse_initial_duration + orbit_steering_pulse_return_duration

# Tope de la fase inicial: el verbo declara duration_ms en [0, 500] (command_spec).
PULSE_INITIAL_MAX_MS = 500.0
PULSE_INITIAL_MIN_MS = 50.0

# Gate de velocidad del verbo. command_spec declara limits v_max_kph=20 para
# steering_pulse; la constante vive AQUI para que el consumidor (controlsd) y la tabla
# de verbos no puedan divergir. Antes controlsd usaba 8.0 m/s (~29 km/h), por encima de
# lo que declara el contrato: a esa velocidad un escalon de curvatura ya es una guinada.
PULSE_MAX_SPEED_KPH = 20.0
PULSE_MAX_SPEED_MS = PULSE_MAX_SPEED_KPH / 3.6

# Clave del Param autoritativo (cruza la barrera de proceso). Registrada en
# common/params_keys.h como CLEAR_ON_MANAGER_START | STRING.
_PARAM_KEY = "orbit_steering_pulse"

# Instancia Params perezosa (compartida en el proceso).
_params = None

# Cache de la LECTURA del param: controlsd llama a get_steering_pulse() a 100 Hz en un
# proceso SCHED_FIFO y Params.get abre+lee el fichero en cada llamada. TTL de 0.1 s: la
# forma del pulso se deriva del instante de inicio, asi que no se degrada; solo se
# retrasa <=0.1 s la deteccion del disparo (que ya llega por red, con mas latencia).
_PULSE_PARAM_TTL_S = 0.1
_pulse_param_cache_ts = 0.0
_pulse_param_cache_val = None


class PulseState:
  """Estado del pulso en un instante. Lo consume controlsd."""
  __slots__ = ("active", "direction", "effective_direction", "phase", "magnitude",
               "start_mono", "expiry_mono", "start_wall_ms")

  def __init__(self, active=False, direction=None, effective_direction=None, phase=None,
               magnitude=0.0, start_mono=0.0, expiry_mono=0.0, start_wall_ms=0):
    self.active = active
    self.direction = direction
    self.effective_direction = effective_direction
    self.phase = phase
    self.magnitude = magnitude
    self.start_mono = start_mono
    self.expiry_mono = expiry_mono
    self.start_wall_ms = start_wall_ms


_INACTIVO = PulseState()


def _get_params():
  global _params
  if _params is None:
    _params = Params()
  return _params


def set_steering_pulse(direction, duration_ms: float = 500.0, magnitude: float = 1.0):
  """Arma un pulso de giro temporal. Lo llama el handler del verbo `steering_pulse`.

  `duration_ms` es la fase INICIAL; la de retorno la refleja, asi que el pulso entero
  dura como mucho 2 * PULSE_INITIAL_MAX_MS. `magnitude` es |torque| del verbo, en [0,1].

  Este handler corre en el hilo del mando (no es tiempo real), asi que el fsync de
  block=True es seguro aqui. Y es NECESARIO: con el put asincrono la escritura podia
  aterrizar DESPUES de un clear_steering_pulse() posterior (remove sincrono) y resucitar
  un pulso ya cancelado dentro de controlsd.
  """
  global orbit_steering_pulse_start, orbit_steering_pulse_direction, _pulse_param_cache_ts

  if direction not in ("left", "right"):
    return False

  try:
    dur_ms = float(duration_ms)
  except (TypeError, ValueError):
    dur_ms = PULSE_INITIAL_MAX_MS
  dur_ms = max(PULSE_INITIAL_MIN_MS, min(PULSE_INITIAL_MAX_MS, dur_ms))

  try:
    mag = abs(float(magnitude))
  except (TypeError, ValueError):
    mag = 1.0
  mag = max(0.0, min(1.0, mag))

  start_mono = time.monotonic()
  start_ms = time.time_ns() // 1_000_000  # solo para la UI/telemetria, nunca para plazos
  orbit_steering_pulse_start = start_mono
  orbit_steering_pulse_direction = direction
  _pulse_param_cache_ts = 0.0  # invalida la cache para ver el pulso al instante

  try:
    _get_params().put(_PARAM_KEY, f"{direction}:{start_ms}:{start_mono:.3f}:{dur_ms:.0f}:{mag:.3f}", block=True)
  except Exception:
    return False
  return True


def _parse(raw):
  """Descompone el param. Devuelve (direction, start_mono, dur_s, mag, start_wall_ms) o None.

  Tolera el formato viejo de dos campos ("dir:start_ms"): en ese caso no hay sello
  monotono y se reconstruye uno a partir del reloj de pared, que es lo unico que hay.
  Es un camino de compatibilidad para el param que quede escrito durante una
  actualizacion, no el camino normal.
  """
  if not raw:
    return None
  partes = str(raw).split(":")
  if len(partes) < 2:
    return None
  direction = partes[0]
  if direction not in ("left", "right"):
    return None

  try:
    start_wall_ms = int(partes[1])
  except (TypeError, ValueError):
    return None

  start_mono = None
  if len(partes) >= 3:
    try:
      start_mono = float(partes[2])
    except (TypeError, ValueError):
      start_mono = None
  if start_mono is None:
    # Compat: reconstruir el instante monotono equivalente. Si el reloj de pared saltó
    # entre la escritura y esta lectura, el pulso saldra caducado -- que es la direccion
    # segura (no se mueve el volante) y no la contraria.
    edad_s = (time.time_ns() / 1e6 - start_wall_ms) / 1000.0
    start_mono = time.monotonic() - edad_s

  dur_s = orbit_steering_pulse_initial_duration
  if len(partes) >= 4:
    try:
      dur_s = max(PULSE_INITIAL_MIN_MS, min(PULSE_INITIAL_MAX_MS, float(partes[3]))) / 1000.0
    except (TypeError, ValueError):
      dur_s = orbit_steering_pulse_initial_duration

  mag = 1.0
  if len(partes) >= 5:
    try:
      mag = max(0.0, min(1.0, abs(float(partes[4]))))
    except (TypeError, ValueError):
      mag = 1.0

  return direction, start_mono, dur_s, mag, start_wall_ms


def get_steering_pulse_state() -> PulseState:
  """Estado del pulso AHORA, con el deadman monotono ya aplicado.

  Es la API que usa controlsd: trae ademas la magnitud y el instante de expiracion, que
  el 5-tuple historico no podia llevar.
  """
  global orbit_steering_pulse_start, orbit_steering_pulse_direction
  global _pulse_param_cache_ts, _pulse_param_cache_val

  now_mono = time.monotonic()
  if now_mono - _pulse_param_cache_ts >= _PULSE_PARAM_TTL_S:
    try:
      _pulse_param_cache_val = _get_params().get(_PARAM_KEY)
    except Exception:
      _pulse_param_cache_val = None
    _pulse_param_cache_ts = now_mono

  datos = None
  try:
    datos = _parse(_pulse_param_cache_val)
  except Exception:
    datos = None

  if datos is None:
    # Fallback al fast-path del mismo proceso (el manager, que acaba de armarlo).
    if orbit_steering_pulse_start is None or orbit_steering_pulse_direction is None:
      return _INACTIVO
    datos = (orbit_steering_pulse_direction, orbit_steering_pulse_start,
             orbit_steering_pulse_initial_duration, 1.0, 0)

  direction, start_mono, dur_s, mag, start_wall_ms = datos
  elapsed = now_mono - start_mono
  total = 2.0 * dur_s

  # DEADMAN: fuera de la ventana [0, total) el efecto vuelve a neutro y el param se
  # borra. `elapsed < 0` incluye el caso de un param escrito por otro arranque.
  if elapsed >= total or elapsed < 0:
    clear_steering_pulse()
    return _INACTIVO

  # Sincronizar el fast-path con lo leido.
  orbit_steering_pulse_start = start_mono
  orbit_steering_pulse_direction = direction

  if elapsed < dur_s:
    phase = "initial"
    effective_direction = direction
  else:
    phase = "return"
    effective_direction = "right" if direction == "left" else "left"

  return PulseState(active=True, direction=direction, effective_direction=effective_direction,
                    phase=phase, magnitude=mag, start_mono=start_mono,
                    expiry_mono=start_mono + total, start_wall_ms=start_wall_ms)


def get_steering_pulse():
  """Compat historica: (pulse_start, direction, is_active, phase, effective_direction).

  `pulse_start` pasa a ser el instante MONOTONO de inicio (antes era de pared). Se
  mantiene la firma para no romper a quien la llame; el consumidor nuevo usa
  get_steering_pulse_state(), que ademas trae magnitud y expiracion.
  """
  st = get_steering_pulse_state()
  if not st.active:
    return None, None, False, None, None
  return st.start_mono, st.direction, True, st.phase, st.effective_direction


def clear_steering_pulse():
  """Limpia el pulso (globales + param autoritativo)."""
  global orbit_steering_pulse_start, orbit_steering_pulse_direction, _pulse_param_cache_ts, _pulse_param_cache_val
  orbit_steering_pulse_start = None
  orbit_steering_pulse_direction = None
  _pulse_param_cache_ts = 0.0
  _pulse_param_cache_val = None  # evita releer desde la cache un pulso ya expirado
  try:
    _get_params().remove(_PARAM_KEY)
  except Exception:
    pass
