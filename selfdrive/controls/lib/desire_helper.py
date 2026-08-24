import json
import time

from cereal import log, custom
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.selfdrive.controls.lib.auto_lane_change import AutoLaneChangeController, AutoLaneChangeMode
from openpilot.sunnypilot.selfdrive.controls.lib.lane_turn_desire import LaneTurnController

# [Orbit] Mando remoto v2: verbo `lane_change` (seccion 6 -> modo MANIOBRA). Import
# defensivo: sin orbit/ el cambio de carril del modelo funciona igual, simplemente no hay
# cambio de carril remoto.
try:
  from openpilot.orbit.orbit_control_ultra_simple import OrbitCommandLink
  from openpilot.orbit.command_spec import Gate as OrbitGate, Mode as OrbitMode, Phase as OrbitPhase
  _ORBIT_MANDO = True
except Exception:
  OrbitCommandLink = None
  OrbitGate = OrbitMode = OrbitPhase = None
  _ORBIT_MANDO = False

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection
TurnDirection = custom.ModelDataV2SP.TurnDirection

LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.

# ---------------------------------------------------------------- [Orbit] lane_change v2
# Contrato del verbo (orbit/command_spec.py -> COMMANDS["lane_change"]). Los limites se
# repiten aqui a proposito y con el mismo valor: este proceso (modeld) no puede depender de
# que orbit/ este importable, y un limite que solo vive en el emisor no es un limite.
ORBIT_LC_VERB = "lane_change"
ORBIT_LC_V_MIN = 40.0 / 3.6    # m/s
ORBIT_LC_V_MAX = 130.0 / 3.6   # m/s

# Cada cuanto se releen los flags one-shot. update() corre a 20 Hz y hacia DOS get_bool por
# ciclo, es decir 40 open()+read() de /data/params por segundo para ver casi siempre False.
# 0.2 s es indistinguible para una orden que llega por red, y la cache se invalida a mano en
# cuanto se consume un flag (si no, el mismo flag ya borrado se volveria a leer como activo).
ORBIT_LC_FLAG_TTL_S = 0.2

# Canal de RESULTADO hacia el router (auditoria del diseno, "el cierre real lo da el
# CONSUMIDOR, no el router"). Es un param STRING con un JSON dentro; se escribe SOLO en los
# tres eventos de una maniobra (rechazo / aceptacion / final), nunca por ciclo.
ORBIT_LC_PARAM_RESULT = "OrbitCmdResult"

DESIRES = {
  LaneChangeDirection.none: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.none,
    LaneChangeState.laneChangeFinishing: log.Desire.none,
  },
  LaneChangeDirection.left: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.laneChangeLeft,
    LaneChangeState.laneChangeFinishing: log.Desire.laneChangeLeft,
  },
  LaneChangeDirection.right: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.laneChangeRight,
    LaneChangeState.laneChangeFinishing: log.Desire.laneChangeRight,
  },
}

TURN_DESIRES = {
  TurnDirection.none: log.Desire.none,
  TurnDirection.turnLeft: log.Desire.turnLeft,
  TurnDirection.turnRight: log.Desire.turnRight,
}


class DesireHelper:
  def __init__(self):
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.lane_change_ll_prob = 1.0
    self.keep_pulse_timer = 0.0
    self.prev_one_blinker = False
    self.desire = log.Desire.none
    self.alc = AutoLaneChangeController(self)
    self.lane_turn_controller = LaneTurnController(self)
    self.lane_turn_direction = TurnDirection.none
    self.params = Params()  # [Orbit] cambio de carril forzado por MQTT

    # [Orbit] Mando remoto v2. El SubMaster de orbitCommandState se crea perezosamente en el
    # primer poll y por tanto en el hilo que llama a update() (msgq no es thread-safe).
    self._orbit_link = OrbitCommandLink(etiqueta="desire_helper") if _ORBIT_MANDO else None
    self._orbit_auth = None
    self._orbit_now_mono = 0.0
    self._orbit_flags = (False, False)      # (izquierda, derecha) ya leidos
    self._orbit_flags_hasta = 0.0           # instante MONOTONO antes del cual no se relee
    self._orbit_lc_en_curso = False         # hay una maniobra REMOTA viva (para reportar el final)
    self._orbit_lc_corte = ""               # motivo por el que se corto, anotado donde se sabe
    self._orbit_lc_cmd_id = ""              # id del comando que la disparo, si se pudo ver
    self._orbit_result_roto = False         # el param de resultado no existe en este build
    self._orbit_ultimo_error_mono = 0.0     # acota el log de excepciones (20 Hz)

  # ------------------------------------------------------------------ [Orbit] mando v2

  def _orbit_poll(self) -> None:
    """Lee el plano de estado del mando UNA vez por ciclo. Nunca lanza."""
    self._orbit_now_mono = time.monotonic()
    if self._orbit_link is None:
      self._orbit_auth = None
      return
    try:
      self._orbit_auth = self._orbit_link.poll()
    except Exception:
      self._orbit_auth = None

  def _orbit_reportar(self, phase: str, reason: str, detail: str = "") -> None:
    """Publica el RESULTADO real de la maniobra para que el router cierre el ACK.

    Hoy la orden se lanza y nadie sabe que paso: desire_helper consumia el flag y lo
    descartaba en silencio, asi que un cambio de carril bloqueado por velocidad, por BSM o
    por tener el asistente apagado era indistinguible de uno ejecutado.

    Se escribe en un evento, no por ciclo. Si la clave no esta registrada en
    common/params_keys.h (build sin recompilar `common`) se marca rota y no se reintenta:
    un UnknownKeyName por ciclo en el proceso de modeld no ayuda a nadie.
    """
    if self._orbit_result_roto:
      return
    payload = {
      "v": 2,
      "verb": ORBIT_LC_VERB,
      "id": self._orbit_lc_cmd_id,
      "phase": phase,
      "reason": reason,
      "detail": detail,
      "ts_ms": time.time_ns() // 1_000_000,
      "mono_ms": int(self._orbit_now_mono * 1000),
    }
    try:
      self.params.put(ORBIT_LC_PARAM_RESULT, json.dumps(payload, separators=(",", ":")))
    except Exception:
      self._orbit_result_roto = True
      cloudlog.error(f"desire_helper: [Orbit] resultado NO publicado: falta {ORBIT_LC_PARAM_RESULT} en common/params_keys.h; el ACK se queda sin cerrar")
    if reason not in ("OK",):
      cloudlog.warning(f"desire_helper: [Orbit] lane_change {phase}/{reason}: {detail}")

  def _orbit_leer_flags(self) -> tuple[bool, bool]:
    """(izquierda, derecha), releyendo del disco como mucho cada ORBIT_LC_FLAG_TTL_S."""
    if self._orbit_now_mono < self._orbit_flags_hasta:
      return self._orbit_flags
    self._orbit_flags_hasta = self._orbit_now_mono + ORBIT_LC_FLAG_TTL_S
    try:
      self._orbit_flags = (bool(self.params.get_bool("ForceLaneChangeLeft")),
                           bool(self.params.get_bool("ForceLaneChangeRight")))
    except Exception:
      self._orbit_flags = (False, False)
    return self._orbit_flags

  def _orbit_consumir_flag(self):
    """Consume el flag one-shot. Devuelve (direccion|None, motivo).

    El flag se limpia SIEMPRE, se ejecute la orden o no. Un flag que sobrevive a un rechazo
    es una orden que se dispara sola en cuanto los gates se ponen verdes un rato despues,
    que es exactamente lo que el TTL existe para impedir.

    SE BORRA LA CLAVE, no se escribe False. Params.put_bool(..., block=False) encola en un
    hilo async: la escritura puede aterrizar DESPUES de que el router arme la SIGUIENTE
    orden, y entonces el False tardio se come un cambio de carril que el router ya dio por
    aceptado. Params.remove es sincrono (unlink + fsync del directorio bajo el FileLock) y
    get_bool sobre una clave que no existe devuelve False, que es justo lo que se quiere.
    Ademas la cache queda en (False, False) hasta el proximo vencimiento del TTL: aunque el
    borrado fallara, el mismo flag no puede volver a disparar la maniobra en el ciclo
    siguiente. Pasado el TTL se relee, asi que una SEGUNDA orden legitima se ve y se
    contesta (BUSY si la primera sigue en marcha) en vez de perderse en silencio.
    """
    izq, der = self._orbit_leer_flags()
    if not (izq or der):
      return None, ""
    try:
      if izq:
        self.params.remove("ForceLaneChangeLeft")
      if der:
        self.params.remove("ForceLaneChangeRight")
    except Exception:
      pass
    self._orbit_flags = (False, False)
    self._orbit_flags_hasta = self._orbit_now_mono + ORBIT_LC_FLAG_TTL_S
    if izq and der:
      # Las dos direcciones a la vez es una contradiccion, no una orden: no se ejecuta
      # ninguna. Antes el orden del if/elif decidia por su cuenta que ganaba la izquierda.
      return None, "TYPE"
    if _ORBIT_MANDO and self._orbit_auth is not None:
      # cmdId solo esta puesto MIENTRAS corre el handler, asi que casi nunca se ve; se
      # guarda si esta y el router correlaciona por verbo cuando no.
      self._orbit_lc_cmd_id = self._orbit_auth.cmd_id or ""
    return (LaneChangeDirection.left if izq else LaneChangeDirection.right), ""

  def _orbit_evaluar(self, carstate, lateral_active: bool, direccion) -> str:
    """Reevalua el permiso EN EL CICLO EN QUE SE ACTUA. Devuelve 'OK' o el motivo.

    El GateMonitor filtra pronto (mascara de 10 Hz) y aqui se decide tarde, con el carState
    de este ciclo: entre que el router acepta y que modeld actua puede haberse desenganchado
    el lateral, haber pisado el conductor o haber cambiado la velocidad.
    """
    if not _ORBIT_MANDO or self._orbit_auth is None:
      return "LINK"

    gates = int(OrbitGate.ENGAGED | OrbitGate.LAT_ACTIVE | OrbitGate.DRIVER_IDLE |
                OrbitGate.DRIVER_PRESENT | OrbitGate.SPEED_RANGE | OrbitGate.LINK_FRESH)
    try:
      ok, motivo = self._orbit_auth.allows(ORBIT_LC_VERB, OrbitMode.MANEUVER, gates, self._orbit_now_mono)
    except Exception:
      return "INTERNAL"
    if not ok:
      return motivo

    # --- reevaluacion local
    if not lateral_active:
      return "GATE_LAT_ACTIVE"
    # Una maniobra por orden: no se encadenan (seccion 6). Tampoco se pisa una del modelo.
    if self.lane_change_state != LaneChangeState.off:
      return "BUSY"
    # El asistente de cambio de carril apagado por el dueno manda sobre cualquier orden
    # remota. Antes esto no se comprobaba aqui: la orden entraba en el `else` y el guard de
    # arriba la borraba en el mismo ciclo, asi que el coche no hacia nada y nadie se
    # enteraba. Codigo GATE_* propio del consumidor: reason_valido() los acepta, y decir
    # "no se puede" sin decir por que es justo lo que el diseno prohibe.
    if self.alc.lane_change_set_timer == AutoLaneChangeMode.OFF:
      return "GATE_AUTO_LANE_CHANGE_OFF"
    v_ego = float(carstate.vEgo)
    if not (ORBIT_LC_V_MIN <= v_ego <= ORBIT_LC_V_MAX):
      return "GATE_SPEED_RANGE"
    if carstate.gasPressed or carstate.brakePressed or carstate.steeringPressed:
      return "GATE_DRIVER_IDLE"
    # DRIVER_PRESENT: la cara la aporta la mascara del plano (driverMonitoringState no llega
    # a este proceso); cinturon y puertas se comprueban aqui, que es donde estan.
    if carstate.seatbeltUnlatched or carstate.doorOpen:
      return "GATE_DRIVER_PRESENT"
    if (carstate.leftBlindspot and direccion == LaneChangeDirection.left) or \
       (carstate.rightBlindspot and direccion == LaneChangeDirection.right):
      return "GATE_BLINDSPOT"
    return "OK"

  def _orbit_cerrar_maniobra(self) -> None:
    """Emite el resultado FINAL de una maniobra remota: aplicada o abortada.

    NOTA DE DISENO. Una maniobra ya empezada NO se aborta porque venza el deadman del
    comando: el watchdog de actuador de la seccion 5 existe para que un override lateral no
    se quede pegado, y un cambio de carril no es un override sostenido -- es una maniobra
    discreta que se termina sola y que ya tiene su propio tope (LANE_CHANGE_TIME_MAX).
    Cortarla a mitad, con el coche entre dos carriles, seria mas peligroso que acabarla.
    Lo que el deadman SI impide es EMPEZARLA sin autoridad viva.
    """
    estado = self.lane_change_state
    if estado == LaneChangeState.laneChangeStarting:
      return  # sigue en marcha
    self._orbit_lc_en_curso = False
    if estado in (LaneChangeState.laneChangeFinishing, LaneChangeState.preLaneChange):
      self._orbit_reportar(OrbitPhase.APPLIED if _ORBIT_MANDO else "applied", "OK",
                           "cambio de carril completado")
    else:
      motivo = self._orbit_lc_corte or "INTERNAL"
      self._orbit_reportar(OrbitPhase.FAILED if _ORBIT_MANDO else "failed", motivo,
                           "la maniobra se interrumpio antes de terminar")
    self._orbit_lc_corte = ""

  @staticmethod
  def get_lane_change_direction(CS):
    return LaneChangeDirection.left if CS.leftBlinker else LaneChangeDirection.right

  def update(self, carstate, lateral_active, lane_change_prob):
    self.alc.update_params()
    self.lane_turn_controller.update_params()
    v_ego = carstate.vEgo
    one_blinker = carstate.leftBlinker != carstate.rightBlinker
    below_lane_change_speed = v_ego < LANE_CHANGE_SPEED_MIN

    # Lane turn controller update
    self.lane_turn_controller.update_lane_turn(blindspot_left=carstate.leftBlindspot, blindspot_right=carstate.rightBlindspot,
                                               left_blinker=carstate.leftBlinker, right_blinker=carstate.rightBlinker, v_ego=v_ego)
    self.lane_turn_direction = self.lane_turn_controller.get_turn_direction()

    # [Orbit] VERBO `lane_change` (seccion 6 -> modo MANIOBRA). El emisor solo pone en pie el
    # flag one-shot ForceLaneChangeLeft/Right; quien decide si el coche obedece es ESTE
    # ciclo, con el plano de estado delante (modo, gates, deadman) y reevaluando ademas
    # cada precondicion contra el carState de ahora mismo.
    #
    # Lo que ya no puede pasar:
    #  * que la orden se ejecute con el enlace muerto, fuera de modo maniobra o con el TTL
    #    vencido -- antes bastaba con que el flag estuviera puesto, viniera de donde viniera;
    #  * que se pise una maniobra en curso (una orden = una maniobra, sin encadenar);
    #  * que se ejecute con el conductor pisando, sin cinturon, con una puerta abierta o sin
    #    cara detectada -- el gate DRIVER_PRESENT no se usaba en NINGUNA precondicion;
    #  * que el rechazo sea mudo: cada salida escribe su motivo en el canal de resultado.
    forced_dir = None
    try:
      self._orbit_poll()
      forced_dir, motivo = self._orbit_consumir_flag()
      if forced_dir is not None:
        motivo = self._orbit_evaluar(carstate, lateral_active, forced_dir)
      if motivo and motivo != "OK":
        self._orbit_reportar(OrbitPhase.REJECTED if _ORBIT_MANDO else "rejected", motivo,
                             "precondicion en rojo al ejecutar")
        forced_dir = None
    except Exception:
      # Acotado en el tiempo: update() corre a 20 Hz y una excepcion que se repita cada
      # ciclo llenaria swaglog desde el proceso del modelo.
      if (self._orbit_now_mono - self._orbit_ultimo_error_mono) > 5.0:
        self._orbit_ultimo_error_mono = self._orbit_now_mono
        cloudlog.exception("desire_helper: [Orbit] excepcion evaluando lane_change (orden descartada)")
      forced_dir = None

    if not lateral_active or self.lane_change_timer > LANE_CHANGE_TIME_MAX or self.alc.lane_change_set_timer == AutoLaneChangeMode.OFF:
      if self._orbit_lc_en_curso:
        # Se anota AQUI por que se corta: el temporizador se pone a cero mas abajo, asi que
        # despues ya no se puede distinguir un corte por tiempo de uno por desenganche.
        self._orbit_lc_corte = ("GATE_LAT_ACTIVE" if not lateral_active else
                                "EXPIRED" if self.lane_change_timer > LANE_CHANGE_TIME_MAX else
                                "GATE_AUTO_LANE_CHANGE_OFF")
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
    else:
      # [Orbit] inyectar el inicio del cambio de carril remoto. Todas las precondiciones
      # (velocidad, BSM, conductor, modo, deadman) ya se han comprobado arriba: aqui solo se
      # arranca la maquina de estados y se anota que la maniobra en curso es REMOTA, para
      # poder decir despues si termino o si se aborto.
      if forced_dir is not None:
        self.lane_change_direction = forced_dir
        self.lane_change_state = LaneChangeState.laneChangeStarting
        self.lane_change_ll_prob = 1.0
        self._orbit_lc_en_curso = True
        self._orbit_reportar(OrbitPhase.EXECUTING if _ORBIT_MANDO else "executing", "OK",
                             "maniobra iniciada")

      # LaneChangeState.off
      if self.lane_change_state == LaneChangeState.off and one_blinker and not self.prev_one_blinker and not below_lane_change_speed:
        self.lane_change_state = LaneChangeState.preLaneChange
        self.lane_change_ll_prob = 1.0
        # Initialize lane change direction to prevent UI alert flicker
        self.lane_change_direction = self.get_lane_change_direction(carstate)

      # LaneChangeState.preLaneChange
      elif self.lane_change_state == LaneChangeState.preLaneChange:
        # Update lane change direction
        self.lane_change_direction = self.get_lane_change_direction(carstate)

        torque_applied = carstate.steeringPressed and \
                         ((carstate.steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.left) or
                          (carstate.steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.right))

        blindspot_detected = ((carstate.leftBlindspot and self.lane_change_direction == LaneChangeDirection.left) or
                              (carstate.rightBlindspot and self.lane_change_direction == LaneChangeDirection.right))

        self.alc.update_lane_change(blindspot_detected, carstate.brakePressed)

        if not one_blinker or below_lane_change_speed:
          self.lane_change_state = LaneChangeState.off
          self.lane_change_direction = LaneChangeDirection.none
        elif (torque_applied or self.alc.auto_lane_change_allowed) and not blindspot_detected:
          self.lane_change_state = LaneChangeState.laneChangeStarting

      # LaneChangeState.laneChangeStarting
      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        # fade out over .5s
        self.lane_change_ll_prob = max(self.lane_change_ll_prob - 2 * DT_MDL, 0.0)

        # 98% certainty
        if lane_change_prob < 0.02 and self.lane_change_ll_prob < 0.01:
          self.lane_change_state = LaneChangeState.laneChangeFinishing

      # LaneChangeState.laneChangeFinishing
      elif self.lane_change_state == LaneChangeState.laneChangeFinishing:
        # fade in laneline over 1s
        self.lane_change_ll_prob = min(self.lane_change_ll_prob + DT_MDL, 1.0)

        if self.lane_change_ll_prob > 0.99:
          self.lane_change_direction = LaneChangeDirection.none
          if one_blinker:
            self.lane_change_state = LaneChangeState.preLaneChange
          else:
            self.lane_change_state = LaneChangeState.off

    if self.lane_change_state in (LaneChangeState.off, LaneChangeState.preLaneChange):
      self.lane_change_timer = 0.0
    else:
      self.lane_change_timer += DT_MDL

    # [Orbit] Cierre del ACK con el RESULTADO real de la maniobra remota.
    if self._orbit_lc_en_curso:
      try:
        self._orbit_cerrar_maniobra()
      except Exception:
        self._orbit_lc_en_curso = False

    self.prev_one_blinker = one_blinker

    if self.lane_turn_direction != TurnDirection.none:
      self.desire = TURN_DESIRES[self.lane_turn_direction]
    else:
      self.desire = DESIRES[self.lane_change_direction][self.lane_change_state]

    # Send keep pulse once per second during LaneChangeStart.preLaneChange
    if self.lane_change_state in (LaneChangeState.off, LaneChangeState.laneChangeStarting):
      self.keep_pulse_timer = 0.0
    elif self.lane_change_state == LaneChangeState.preLaneChange:
      self.keep_pulse_timer += DT_MDL
      if self.keep_pulse_timer > 1.0:
        self.keep_pulse_timer = 0.0
      elif self.desire in (log.Desire.keepLeft, log.Desire.keepRight):
        self.desire = log.Desire.none

    self.alc.update_state()
