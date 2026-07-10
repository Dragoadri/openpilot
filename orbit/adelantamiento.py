"""MODULO DORMIDO — sin importadores en el arbol actual.

Conservado a proposito como material para el adelantamiento C2 (secuenciador
completo: ida + retorno al carril + bump de velocidad; ver el catalogo en
docs/superpowers/specs/2026-07-10-orbit-root-move-and-menu-redesign-design.md).
Sus params historicos `adelantamiento_vel_diff` / `adelantamiento_distancia` se
retiraron de common/params_keys.h: si C2 reutiliza esta logica, debe leer los
params `overtake_*` que ya escribe orbit/mqtt_comandos.py (_apply_overtake).
"""
from cereal import log
from openpilot.common.params import Params

LaneChangeDirection = log.LaneChangeDirection
LaneChangeState = log.LaneChangeState

params = Params()  # dispositivo Comma (antes Params("/tmp"), solo-desarrollo)

def get_param_float(name: str, default: float) -> float:
  # API moderna de Params: get() ya no acepta kwarg 'encoding' (TypeError) y las
  # keys historicas adelantamiento_* no estan registradas (UnknownKeyName); ambos
  # casos caian al default siempre. Si C2 revive este modulo, migrar a las keys overtake_*.
  try:
    val = params.get(name)
    return float(val) if val is not None else default
  except Exception:
    return default

def should_start_overtake(carstate, radarstate):
  """
  Decide si se debe iniciar el adelantamiento automático.
  - Diferencia de velocidad (v_ref - v_ego) > umbral (por defecto 15 km/h)
  - Distancia al lead < umbral (por defecto 50 m)
  - Si está activado BSM, también requiere que no haya ángulo muerto izquierdo
  """
  if not params.get_bool("sic_adelantar"):
    return False

  # 🚘 Lead válido
  lead = radarstate.leads[0] if len(radarstate.leads) > 0 else None
  if lead is None or not lead.status:
    return False

  # 🧠 Datos relevantes
  v_ego = carstate.vEgo
  v_ref = carstate.cruiseSpeed
  d_rel = lead.dRel

  # 🛠 Parámetros ajustables
  vel_diff_threshold = get_param_float("adelantamiento_vel_diff", 15.0) / 3.6  # km/h → m/s
  distancia_threshold = get_param_float("adelantamiento_distancia", 50.0)

  diff_vel_ok = (v_ref - v_ego) > vel_diff_threshold
  distancia_ok = d_rel < distancia_threshold
  sin_bsm = not carstate.leftBlindspot if params.get_bool("sic_adelantar_bsm") else True

  return diff_vel_ok and distancia_ok and sin_bsm

def get_overtake_command():
  return LaneChangeDirection.left, LaneChangeState.laneChangeStarting
