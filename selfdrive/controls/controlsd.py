#!/usr/bin/env python3
import math
import json
import os
import threading
import time
from numbers import Number

from cereal import car, log
import cereal.messaging as messaging
from openpilot.common.constants import CV
from openpilot.common.params import Params, UnknownKeyName
from openpilot.common.realtime import config_realtime_process, DT_CTRL, Priority, Ratekeeper
from openpilot.common.swaglog import cloudlog

from opendbc.car.car_helpers import interfaces
from opendbc.car.vehicle_model import VehicleModel
from openpilot.selfdrive.controls.lib.drive_helpers import clip_curvature
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle, STEER_ANGLE_SATURATION_THRESHOLD
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque
from openpilot.selfdrive.controls.lib.longcontrol import LongControl
from openpilot.selfdrive.modeld.modeld import LAT_SMOOTH_SECONDS
from openpilot.selfdrive.locationd.helpers import PoseCalibrator, Pose

from openpilot.sunnypilot.selfdrive.controls.controlsd_ext import ControlsExt

# [Orbit] Modo 3 (COMMA+JETSON): estado del esquive de obstáculos
try:
  from openpilot.orbit.orbit_obstacle_pulse import ObstaclePulseState, DEFAULT_MAX_ANGLE, DEFAULT_MAX_CURV
  _ORBIT_OBSTACLE = True
except Exception:
  ObstaclePulseState = None
  DEFAULT_MAX_ANGLE, DEFAULT_MAX_CURV = 25.0, 0.030
  _ORBIT_OBSTACLE = False

# [Orbit] Plano de estado del mando remoto v2 (mensaje cereal orbitCommandState, seccion 5
# del diseno). Es lo que dice si hay una orden remota VIVA, en que modo esta el coche, que
# gates estan en verde y cuando caduca la autoridad del actuador (deadman monotono).
# Si el modulo no esta (arbol sin orbit/) el consumidor se queda SIN mando, no sin control:
# _orbit_permiso() devuelve LINK y ningun bloque remoto llega a tocar los actuadores.
try:
  from openpilot.orbit.orbit_control_ultra_simple import OrbitCommandLink
  from openpilot.orbit.command_spec import Gate as OrbitGate, Mode as OrbitMode
  _ORBIT_MANDO = True
except Exception:
  OrbitCommandLink = None
  OrbitGate = OrbitMode = None
  _ORBIT_MANDO = False

# Anti-flicker: cuando JetsonObstacleStatus pasa de activo a "" lo mantenemos
# publicado este tiempo para que la UI (~20 Hz) no pierda dodges muy breves.
OBSTACLE_STATUS_HOLD_S = 0.30

# [Orbit] Watchdog de frescura del torque Jetson (modo 1). Si el ultimo JetsonTorque
# tiene mas de este tiempo, la Jetson se ha caido/desconectado -> forzar torque=0 (volante
# sin fuerza) en vez de aplicar indefinidamente un valor viejo (volante atascado). La Jetson
# real publica a ~5 Hz (200 ms), asi que 1 s es holgado y no falsea cortes en operacion normal.
JETSON_TORQUE_TIMEOUT_S = 1.0

# [Orbit] Dead-zone por defecto del torque Jetson si JetsonDeadZone no se puede leer, y techo
# de la misma: una dead-zone mal configurada solo puede QUITAR autoridad, nunca darla, pero
# por encima de 0.5 anularia de facto la direccion de la Jetson sin que se note por que.
JETSON_DEAD_ZONE_DEFAULT = 0.02
JETSON_DEAD_ZONE_MAX = 0.5

# [Orbit] Pulso de direccion (verbo steering_pulse, seccion 6 -> modo BANCO). El gate de
# velocidad ya NO se define aqui: vive en orbit/orbit_steering_pulse.py (PULSE_MAX_SPEED_MS,
# 20 km/h) para que el consumidor y la tabla de verbos no puedan divergir. En HEAD no habia
# NINGUN gate de velocidad para el pulso (verificado con git show): se anade, no se corrige.
# [Orbit] Cuanto se sostiene la cancelacion remota de crucero. Un solo ciclo de 100 Hz no
# llega a salir por CAN; medio segundo si, y sigue siendo un pulso.
ORBIT_CRUISE_CANCEL_HOLD_S = 0.5

ORBIT_STEERING_PULSE_CURVATURE = 0.008  # 1/m — offset objetivo, luego pasa por clip_curvature

# [Orbit] DECELERACION ASISTIDA (verbo assisted_decel, seccion 6). Sustituye a `brutebreak`,
# que aceptaba [-10,-1] de un escalon, sin modo, sin gate, sin TTL y sin cancelacion.
#   * En via publica la autoridad se acota a [-2.5,-1.0]: una frenada que llega con segundos
#     de latencia, ordenada por alguien que no ve lo que ve el coche, no evita un peligro --
#     lo crea (decision por defecto de la seccion 0 del diseno).
#   * El rango completo solo existe con armado FISICO de banco.
#   * Se entra por RAMPA DE JERK, no de golpe: un escalon de -2.5 m/s2 a 100 Hz es una frenada
#     mas brusca que la del propio ABS y desestabiliza al que va detras.
#   * El hold tiene tope propio ademas del deadman del plano de estado.
ORBIT_DECEL_ACCEL_MIN = -2.5      # m/s2 — techo de autoridad en via publica
ORBIT_DECEL_ACCEL_MAX = -1.0      # m/s2 — por encima de esto no es una deceleracion
ORBIT_DECEL_ACCEL_MIN_BENCH = -10.0  # m/s2 — rango completo, SOLO con benchArmed vigente
ORBIT_DECEL_JERK = 2.5            # m/s3 — pendiente maxima de entrada
ORBIT_DECEL_HOLD_MAX_S = 1.5      # s — tope de hold (seccion 6: hold <= 1500 ms)

# [Orbit] Telemetria de torque (CommaSteerTorque / AppliedSteerTorque) y estado de esquive.
# controlsd corre a 100 Hz en SCHED_FIFO core 4; Params.put() hace 2x fsync + FileLock GLOBAL por
# escritura y su hilo async hereda la prioridad FIFO del que llama. Escribir estos params desde el
# loop saturaba el disco a prioridad RT -> selfdrived veia carControl/controlsState/livePose por
# debajo de frecuencia -> commIssue / locationdTemporaryError al activar OP. Solucion: el loop solo
# ENCOLA (self._defer_param_put) y un hilo a SCHED_OTHER las vuelca a ~10 Hz (ver __init__).
# Sus unicos consumidores (HUD de UI ~2 Hz, emisor MQTT 0.5-2 s) no necesitan mas de ~10 Hz.

State = log.SelfdriveState.OpenpilotState
LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

ACTUATOR_FIELDS = tuple(car.CarControl.Actuators.schema.fields.keys())


class Controls(ControlsExt):
  def __init__(self) -> None:
    self.params = Params()
    cloudlog.info("controlsd is waiting for CarParams")
    self.CP = messaging.log_from_bytes(self.params.get("CarParams", block=True), car.CarParams)
    cloudlog.info("controlsd got CarParams")

    # Initialize sunnypilot controlsd extension and base model state
    ControlsExt.__init__(self, self.CP, self.params)

    self.CI = interfaces[self.CP.carFingerprint](self.CP, self.CP_SP)

    self.sm = messaging.SubMaster(['liveDelay', 'liveParameters', 'liveTorqueParameters', 'modelV2', 'selfdriveState',
                                   'liveCalibration', 'livePose', 'longitudinalPlan', 'lateralManeuverPlan', 'carState', 'carOutput',
                                   'driverMonitoringState', 'onroadEvents', 'driverAssistance', 'liveDelay'] + self.sm_services_ext,
                                  poll='selfdriveState')
    self.pm = messaging.PubMaster(['carControl', 'controlsState'] + self.pm_services_ext)

    self.steer_limited_by_safety = False
    self.curvature = 0.0
    self.desired_curvature = 0.0

    self.pose_calibrator = PoseCalibrator()
    self.calibrated_pose: Pose | None = None

    self.LoC = LongControl(self.CP, self.CP_SP)
    self.VM = VehicleModel(self.CP)
    self.LaC: LatControl
    if self.CP.steerControlType == car.CarParams.SteerControlType.angle:
      self.LaC = LatControlAngle(self.CP, self.CP_SP, self.CI, DT_CTRL)
    elif self.CP.lateralTuning.which() == 'pid':
      self.LaC = LatControlPID(self.CP, self.CP_SP, self.CI, DT_CTRL)
    elif self.CP.lateralTuning.which() == 'torque':
      self.LaC = LatControlTorque(self.CP, self.CP_SP, self.CI, DT_CTRL)

    self.LaC = ControlsExt.initialize_lateral_control(self, self.LaC, self.CI, DT_CTRL)

    # [Orbit] limpiar cualquier pulso de dirección (cruceta MQTT) pendiente al iniciar
    try:
      from openpilot.orbit.orbit_steering_pulse import clear_steering_pulse
      clear_steering_pulse()
    except Exception:
      pass

    # [Orbit] Mando remoto v2: lector del plano de estado (cereal orbitCommandState).
    # Crea su PROPIO SubMaster de un solo servicio (perezoso, en el primer poll y por tanto
    # en ESTE hilo): no se toca self.sm, asi que la lista de servicios que replican
    # process_replay y los logs de referencia queda igual.
    self._orbit_link = OrbitCommandLink(etiqueta="controlsd") if _ORBIT_MANDO else None
    self._orbit_auth = None          # instantanea del ciclo; None = sin autoridad
    self._orbit_now_mono = 0.0       # reloj MONOTONO del ciclo (el mismo marco que deadlineMono)
    self._orbit_cancel_hasta_mono = 0.0   # sostener la cancelacion remota de crucero
    # Deceleracion asistida: valor ya aplicado (para la rampa de jerk) e inicio del hold.
    self._orbit_decel_applied = 0.0
    self._orbit_decel_start_mono = 0.0
    # Deadman del torque Jetson: ultimo sello de PARED visto y el instante MONOTONO en que
    # se vio cambiar. El plazo se mide siempre con el segundo (ver el bloque del modo 1).
    self._jetson_torque_last_ts = 0.0
    self._jetson_torque_seen_mono = 0.0
    # Ultimo motivo registrado por bloque, para no repetir el mismo log a 100 Hz.
    self._orbit_ultimo_motivo: dict[str, str] = {}

    # [Orbit] Modo 3 (COMMA+JETSON): estado del esquive y caché de config.
    # deadman_s > 0 activa el watchdog MONOTONO interno del modulo (seccion 5): si la Jetson
    # deja de publicar, el override vuelve a neutro sin depender de que el caller se acuerde
    # de comprobarlo. El modulo lo deja opt-in porque su test fija por contrato el
    # comportamiento antiguo ("el ultimo valor persiste indefinidamente"); el consumidor real
    # -- este -- SI lo activa.
    self._obstacle_pulse_state = ObstaclePulseState(deadman_s=JETSON_TORQUE_TIMEOUT_S) if _ORBIT_OBSTACLE else None
    self._last_obstacle_status = ""
    self._obstacle_status_hold_until = 0.0   # wall-clock hasta el que mantenemos el último activo
    self._obstacle_status_held_value = ""    # último status activo que estamos manteniendo
    self._obstacle_config_last_read = 0.0    # wall-clock; recachear cada 1s
    self._obstacle_max_angle = DEFAULT_MAX_ANGLE
    self._obstacle_max_curv = DEFAULT_MAX_CURV
    self._obstacle_apply_target = "curvature"  # "curvature" | "torque"
    # [Orbit] Caché de LECTURAS de Params en el loop 100 Hz (mismo criterio que
    # _obstacle_config_last_read): Params.get abre+lee el fichero en cada llamada,
    # y hacerlo a 100 Hz en un proceso SCHED_FIFO es I/O evitable en el core de control.
    self._param_read_cache: dict[str, tuple[float, object]] = {}  # key -> (monotonic_ts, raw)
    # [Orbit/FIX commIssue] Escrituras de Params DIFERIDAS a un hilo NO-RT.
    # controlsd corre en SCHED_FIFO prio 53 fijado al core 4 (junto a card y selfdrived).
    # Params.put(block=False) encola en putNonBlocking, que lanza un std::async cuyo hilo
    # HEREDA (PTHREAD_INHERIT_SCHED) esa prioridad FIFO-53 y afinidad de core 4, y ejecuta
    # fsync(fichero)+flock GLOBAL+fsync(dir) a prioridad de tiempo real sobre el core de
    # control -> retrasa el propio loop 100 Hz y a card/selfdrived -> commIssue. Por eso
    # throttlear la FRECUENCIA (commit anterior) no bastaba: el problema es la PRIORIDAD del
    # fsync. Estas escrituras son SOLO telemetria/UI y estado de esquive, NO control: las
    # encolamos (last-write-wins) y un hilo aparte a SCHED_OTHER las vuelca con block=True,
    # sacando todo el fsync del camino de tiempo real. El loop 100 Hz nunca toca el disco.
    self._pwrite_lock = threading.Lock()
    self._pwrite_pending: dict[str, tuple[str, object]] = {}  # key -> (kind, value), kind: "str"|"bool"
    self._pwrite_stop = threading.Event()
    self._pwrite_thread = threading.Thread(target=self._param_write_worker, daemon=True, name="controlsd-paramwrite")
    self._pwrite_thread.start()

  def _defer_param_put(self, key: str, value, is_bool: bool = False) -> None:
    """Encola una escritura de Params para el hilo NO-RT. Coalescente (last-write-wins).
    Llamar SIEMPRE en lugar de self.params.put*/ en el loop de control: barato (dict + lock),
    nunca toca disco ni lanza fsync a prioridad RT en el core 4."""
    with self._pwrite_lock:
      self._pwrite_pending[key] = ("bool" if is_bool else "str", value)

  def _param_get_cached(self, key: str, ttl: float):
    """Params.get con caché TTL para el loop 100 Hz: evita abrir+leer el fichero del
    param en cada ciclo de control. Devuelve el valor crudo de Params.get (o None si
    la key no existe). Solo para flags/config; NUNCA para datos de control frescos."""
    now = time.monotonic()
    ts, val = self._param_read_cache.get(key, (0.0, None))
    if now - ts >= ttl:
      try:
        val = self.params.get(key)
      except UnknownKeyName:
        val = None
      self._param_read_cache[key] = (now, val)
    return val

  def _orbit_poll(self) -> None:
    """Lee el plano de estado del mando UNA vez por ciclo. Nunca lanza.

    Se llama al principio de state_control(): todos los bloques del mando de este ciclo
    miran la MISMA instantanea y el MISMO instante monotono, para que no puedan discrepar
    entre si a mitad de ciclo (uno concediendo y otro denegando la misma orden).
    """
    self._orbit_now_mono = time.monotonic()
    if self._orbit_link is None:
      self._orbit_auth = None
      return
    try:
      self._orbit_auth = self._orbit_link.poll()
    except Exception:
      self._orbit_auth = None

  def _orbit_log_motivo(self, bloque: str, motivo: str) -> None:
    """Registra el motivo SOLO cuando cambia. A 100 Hz, un log por ciclo es una inundacion
    de swaglog que ademas escribe en disco desde el core de tiempo real."""
    if self._orbit_ultimo_motivo.get(bloque) == motivo:
      return
    self._orbit_ultimo_motivo[bloque] = motivo
    if motivo not in ("", "OK"):
      cloudlog.warning(f"controlsd: [Orbit] {bloque} sin autoridad: {motivo}")

  def _orbit_permiso(self, verb: str, mode_min, gates_req: int, requiere_banco: bool = False) -> tuple[bool, str]:
    """Permiso del plano de estado para mover un actuador por orden remota.

    Fail-closed: sin modulo, sin mensaje o con el mensaje rancio (el publicador de 10 Hz
    muerto), el permiso es NO y el motivo es LINK. Esto es la mitad de la defensa; la otra
    mitad es la reevaluacion LOCAL que hace cada bloque con CS/CC del ciclo en curso
    (seccion 4.2: el GateMonitor filtra pronto, el consumidor decide tarde).

    OJO con SPEED_RANGE: el bit de la mascara publicada usa el rango de MANIOBRA
    (40-130 km/h). Los verbos con rango propio -- los de banco, que quieren velocidad BAJA --
    no deben pedir ese bit aqui; comprueban su velocidad en local contra su propio limite.
    """
    auth = self._orbit_auth
    if auth is None:
      return False, "LINK"
    try:
      return auth.allows(verb, mode_min, int(gates_req), self._orbit_now_mono,
                         requiere_banco=requiere_banco)
    except Exception:
      return False, "INTERNAL"

  def _orbit_banco_armado(self) -> bool:
    """Armado FISICO de banco vigente (pantalla del comma, caducidad de 300 s, seccion 4.1).

    A diferencia de _orbit_permiso() NO se exige la ventana de actuador (deadlineMono): el
    modo de volante se selecciona tambien desde la pantalla del propio comma, donde no hay
    ningun comando MQTT que abra esa ventana. Quien hace de deadman aqui es la caducidad
    del propio armado, que se recomprueba con reloj monotono en cada consulta.
    """
    auth = self._orbit_auth
    if auth is None:
      return False
    try:
      return bool(auth.fresh and auth.clock_synced and auth.bench_ok(self._orbit_now_mono))
    except Exception:
      return False

  def _param_write_worker(self) -> None:
    """Vuelca a Params (a ~10 Hz, solo on-change) las escrituras encoladas por el loop.
    Se baja a SCHED_OTHER para que el fsync NUNCA corra a prioridad de tiempo real en el
    core 4. block=True hace el fsync sincrono EN ESTE hilo (no en el hilo async compartido),
    garantizando que ningun fsync herede la prioridad FIFO de controlsd."""
    try:
      os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))
    except (OSError, AttributeError, ValueError):
      pass  # PC dev / sin privilegios: seguimos igual, solo perdemos el de-priorizado
    last_written: dict[str, tuple[str, object]] = {}
    while not self._pwrite_stop.is_set():
      with self._pwrite_lock:
        batch = self._pwrite_pending
        self._pwrite_pending = {}
      for key, (kind, value) in batch.items():
        if last_written.get(key) == (kind, value):
          continue  # sin cambios: no re-escribir (evita fsync inutil)
        try:
          if kind == "bool":
            self.params.put_bool(key, bool(value), block=True)
          else:
            self.params.put(key, value, block=True)
          last_written[key] = (kind, value)
        except UnknownKeyName:
          pass
        except Exception:
          pass  # nunca propagar desde el hilo de telemetria
      self._pwrite_stop.wait(0.1)  # 10 Hz

  def _refresh_obstacle_config(self, now: float) -> None:
    """Lee los params de configuración del esquive con cache de 1s. Siembra el default si falta."""
    if now - self._obstacle_config_last_read < 1.0:
      return
    self._obstacle_config_last_read = now
    for key, default, attr in (
      ("JetsonObstacleMaxAngle", DEFAULT_MAX_ANGLE, "_obstacle_max_angle"),
      ("JetsonObstacleMaxCurv", DEFAULT_MAX_CURV, "_obstacle_max_curv"),
    ):
      try:
        raw = self.params.get(key)
        if raw is None or raw == b"":
          # Params tipados FLOAT: sembrar el default como float, no str — el
          # worker diferido hacia put(str) -> TypeError tragado y reintentado cada ~1s.
          self._defer_param_put(key, default)
          setattr(self, attr, default)
        else:
          setattr(self, attr, float(raw))
      except (UnknownKeyName, ValueError, TypeError):
        setattr(self, attr, default)

    try:
      raw = self.params.get("JetsonObstacleApplyTarget")
      if raw is None or raw == b"":
        self._defer_param_put("JetsonObstacleApplyTarget", "curvature")
        self._obstacle_apply_target = "curvature"
      else:
        val = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        if val in ("curvature", "torque"):
          self._obstacle_apply_target = val
        else:
          cloudlog.warning(f"controlsd: JetsonObstacleApplyTarget invalido: {val!r}, fallback curvature")
          self._obstacle_apply_target = "curvature"
    except (UnknownKeyName, ValueError, TypeError):
      self._obstacle_apply_target = "curvature"

  def update(self):
    self.sm.update(15)
    if self.sm.updated["liveCalibration"]:
      self.pose_calibrator.feed_live_calib(self.sm['liveCalibration'])
    if self.sm.updated["livePose"]:
      device_pose = Pose.from_live_pose(self.sm['livePose'])
      self.calibrated_pose = self.pose_calibrator.build_calibrated_pose(device_pose)

  def _orbit_assisted_decel(self, CC, CS, accel_base: float, pid_accel_limits) -> float:
    """Verbo `assisted_decel` (seccion 6). Devuelve el accel a mandar en este ciclo.

    Sustituye a brutebreak. Diferencias, todas exigidas por el diseno:
      1. Necesita autoridad VIVA del plano de estado: modo maniobra, gates ENGAGED +
         LONG_ACTIVE + DRIVER_IDLE y, sobre todo, `deadlineMono` sin vencer. Ese deadline es
         el DEADMAN del actuador (seccion 5): en cuanto expira -- porque cayo el enlace,
         porque murio el publicador o porque el TTL de 1.5 s se agoto -- el efecto vuelve a
         NEUTRO sin que nadie tenga que mandar nada.
      2. Reevalua sus gates con CC/CS de ESTE ciclo, no con la mascara de 10 Hz.
      3. Acota el rango a [-2.5,-1.0] salvo con armado fisico de banco.
      4. Entra por rampa de jerk y tiene un hold propio de 1.5 s.
      5. El conductor manda: gas, freno o volante lo cancelan y ADEMAS desarman el flag.
      6. Solo puede FRENAR MAS de lo que ya pedia el control longitudinal, nunca menos: la
         autoridad de una orden remota solo baja (seccion 2).

    El canal de argumentos sigue siendo el par de params `brutebreak_active` (armado) y
    `brutebreak_intensidad` (magnitud) porque es lo que escribe el handler; lo que ha
    cambiado es que ya no bastan por si solos para mover el coche.
    """
    now_mono = self._orbit_now_mono
    armado = bool(self._param_get_cached("brutebreak_active", 0.25))

    if _ORBIT_MANDO:
      ok, motivo = self._orbit_permiso("assisted_decel", OrbitMode.MANEUVER,
                                       int(OrbitGate.ENGAGED | OrbitGate.LONG_ACTIVE | OrbitGate.DRIVER_IDLE))
    else:
      ok, motivo = False, "LINK"

    # --- reevaluacion LOCAL en el ciclo en que se actua (defensa en profundidad)
    if ok and not (CC.enabled and CC.longActive):
      ok, motivo = False, "GATE_LONG_ACTIVE"
    if ok and (CS.gasPressed or CS.brakePressed or CS.steeringPressed):
      ok, motivo = False, "GATE_DRIVER_IDLE"
    if ok and armado and self._orbit_decel_start_mono > 0.0 and \
       (now_mono - self._orbit_decel_start_mono) > ORBIT_DECEL_HOLD_MAX_S:
      ok, motivo = False, "EXPIRED"

    if not (ok and armado):
      # NEUTRO INMEDIATO, sin rampa de salida. La rampa suaviza la ENTRADA; en la salida
      # seria un actuador que sigue frenando despues de perder la autoridad, que es
      # exactamente lo que el deadman existe para impedir.
      self._orbit_decel_applied = 0.0
      self._orbit_decel_start_mono = 0.0
      if armado:
        # El flag se desarma para que no vuelva a disparar solo en cuanto los gates se
        # pongan verdes un rato despues (el fallo original: el unico auto-clear era
        # vEgo<0.5, asi que un brutebreak rechazado quedaba ARMADO hasta el siguiente
        # enganche y entonces frenaba de golpe).
        self._defer_param_put("brutebreak_active", False, is_bool=True)
        self._defer_param_put("brutebreak_intensidad", ORBIT_DECEL_ACCEL_MAX)
        self._orbit_log_motivo("assisted_decel", motivo)
      return accel_base

    self._orbit_log_motivo("assisted_decel", "OK")
    if self._orbit_decel_start_mono <= 0.0:
      self._orbit_decel_start_mono = now_mono
      self._orbit_decel_applied = float(accel_base)  # la rampa arranca de lo que ya se pedia

    # --- magnitud. Sin valor legible se usa la deceleracion MAS SUAVE del rango: de una
    # orden cuya magnitud no se puede leer no se deduce que haya que frenar a tope.
    objetivo = ORBIT_DECEL_ACCEL_MAX
    try:
      crudo = self._param_get_cached("brutebreak_intensidad", 0.25)
      if crudo is not None:
        valor = float(crudo.decode("utf-8") if isinstance(crudo, (bytes, bytearray)) else crudo)
        if math.isfinite(valor):
          objetivo = valor
    except (ValueError, TypeError):
      pass

    minimo = ORBIT_DECEL_ACCEL_MIN_BENCH if self._orbit_banco_armado() else ORBIT_DECEL_ACCEL_MIN
    objetivo = max(minimo, min(ORBIT_DECEL_ACCEL_MAX, objetivo))   # [-2.5,-1.0] en via publica
    objetivo = max(objetivo, float(pid_accel_limits[0]))           # limite del propio coche

    # --- rampa de jerk
    paso = ORBIT_DECEL_JERK * DT_CTRL
    aplicado = self._orbit_decel_applied
    aplicado = max(objetivo, aplicado - paso) if aplicado > objetivo else min(objetivo, aplicado + paso)
    self._orbit_decel_applied = aplicado

    # La autoridad solo baja: nunca soltar el freno que ya pedia el control longitudinal.
    return min(aplicado, float(accel_base))

  def state_control(self):
    CS = self.sm['carState']
    # [Orbit] Instantanea UNICA del plano de estado del mando para todo el ciclo.
    self._orbit_poll()

    # Update VehicleModel
    lp = self.sm['liveParameters']
    x = max(lp.stiffnessFactor, 0.1)
    sr = max(lp.steerRatio, 0.1)
    self.VM.update_params(x, sr)

    steer_angle_without_offset = math.radians(CS.steeringAngleDeg - lp.angleOffsetDeg)
    self.curvature = -self.VM.calc_curvature(steer_angle_without_offset, CS.vEgo, lp.roll)

    # Update Torque Params
    if self.CP.lateralTuning.which() == 'torque':
      torque_params = self.sm['liveTorqueParameters']
      if self.sm.all_checks(['liveTorqueParameters']) and torque_params.useParams:
        self.LaC.update_live_torque_params(torque_params.latAccelFactorFiltered, torque_params.latAccelOffsetFiltered,
                                           torque_params.frictionCoefficientFiltered)

        self.LaC.extension.update_limits()

      self.LaC.extension.update_model_v2(self.sm['modelV2'])

      self.LaC.extension.update_lateral_lag(self.lat_delay)

    long_plan = self.sm['longitudinalPlan']
    model_v2 = self.sm['modelV2']

    CC = car.CarControl.new_message()
    CC.enabled = self.sm['selfdriveState'].enabled

    # Check which actuators can be enabled
    standstill = abs(CS.vEgo) <= max(self.CP.minSteerSpeed, 0.3) or CS.standstill

    # Get which state to use for active lateral control
    _lat_active = self.get_lat_active(self.sm)

    CC.latActive = _lat_active and not CS.steerFaultTemporary and not CS.steerFaultPermanent and \
                   (not standstill or self.CP.steerAtStandstill)
    CC.longActive = CC.enabled and not any(e.overrideLongitudinal for e in self.sm['onroadEvents']) and \
                    (self.CP.openpilotLongitudinalControl or not self.CP_SP.pcmCruiseSpeed)

    actuators = CC.actuators
    actuators.longControlState = self.LoC.long_control_state

    # Enable blinkers while lane changing
    if model_v2.meta.laneChangeState != LaneChangeState.off:
      CC.leftBlinker = model_v2.meta.laneChangeDirection == LaneChangeDirection.left
      CC.rightBlinker = model_v2.meta.laneChangeDirection == LaneChangeDirection.right

    if not CC.latActive:
      self.LaC.reset()
    if not CC.longActive:
      self.LoC.reset()

    # accel PID loop
    pid_accel_limits = self.CI.get_pid_accel_limits(self.CP, self.CP_SP, CS.vEgo, CS.vCruise * CV.KPH_TO_MS)
    actuators.accel = float(self.LoC.update(CC.longActive, CS, long_plan.aTarget, long_plan.shouldStop, pid_accel_limits))

    # [Orbit] DECELERACION ASISTIDA (verbo assisted_decel). El camino viejo -- `brutebreak`,
    # que leia dos params y pisaba actuators.accel con [-10,-1] sin modo, sin gate, sin TTL
    # y sin cancelacion -- queda CERRADO: la magnitud sigue viniendo por el mismo param, pero
    # sin autoridad viva en el plano de estado no se toca el acelerador.
    try:
      actuators.accel = self._orbit_assisted_decel(CC, CS, actuators.accel, pid_accel_limits)
    except Exception:
      pass  # hot-path: nunca propagar

    # Steering PID loop and lateral MPC
    # Reset desired curvature to current to avoid violating the limits on engage
    if self.sm.valid['lateralManeuverPlan']:
      new_desired_curvature = self.sm['lateralManeuverPlan'].desiredCurvature if CC.latActive else self.curvature
    else:
      new_desired_curvature = model_v2.action.desiredCurvature if CC.latActive else self.curvature
    self.desired_curvature, curvature_limited = clip_curvature(CS.vEgo, self.desired_curvature, new_desired_curvature, lp.roll)
    lat_delay = self.sm["liveDelay"].lateralDelay + LAT_SMOOTH_SECONDS

    actuators.curvature = self.desired_curvature
    steer, steeringAngleDeg, lac_log = self.LaC.update(CC.latActive, CS, self.VM, lp,
                                                       self.steer_limited_by_safety, self.desired_curvature,
                                                       self.calibrated_pose, curvature_limited, lat_delay)
    actuators.torque = float(steer)
    actuators.steeringAngleDeg = float(steeringAngleDeg)

    # ════════════════════════════════════════════════════════════════
    # [Orbit] SELECTOR DE FUENTE DE TORQUE LATERAL (param SteerTorqueMode)
    #   0=Comma (sin tocar)  1=Jetson (JetsonTorque)  2=TEST MAX (-1.0)  3=Comma+Jetson (esquive)
    # NOTA: en este sunnypilot el campo es actuators.torque (antes actuators.steer).
    # ════════════════════════════════════════════════════════════════
    steer_mode = 0
    if CC.latActive:
      # CommaSteerTorque = torque del modelo Comma ANTES del override de modo (diagnostico UI).
      # Se ENCOLA cada ciclo (barato); el hilo NO-RT lo vuelca a ~10 Hz y solo si cambia, de
      # modo que el loop de control 100 Hz nunca hace fsync (era la causa del commIssue al activar).
      self._defer_param_put("CommaSteerTorque", f"{float(actuators.torque):.4f}")
      # Lectura cacheada 1 s: el modo se cambia desde UI/MQTT (no es dato de control),
      # y leer el param a 100 Hz mientras latActive metía I/O de disco en el loop RT.
      mode_raw = self._param_get_cached("SteerTorqueMode", 1.0)
      try:
        steer_mode = int(mode_raw) if mode_raw else 0
      except (ValueError, TypeError):
        steer_mode = 0

      # [Orbit] MODOS 1 y 2 = verbo `torque_mode`, que la seccion 6 clasifica como modo
      # BANCO: "armado local". Sin armado FISICO vigente en la pantalla del comma no hay
      # override y manda Comma.
      #
      # No es una precaucion teorica: handle_steer_torque_mode SI exige OrbitBenchArmed para
      # el modo 2 (TEST MAX) pero NO para el 1, asi que hoy un solo mensaje MQTT en
      # telemetry_config/<dongle>/steer_torque_mode entrega el volante entero a la Jetson sin
      # armado, sin caducidad y sin gate. Ademas SteerTorqueMode es PERSISTENT: el modo
      # sobrevive al reinicio (por eso manager.py tuvo que anadir un fail-safe de arranque).
      # Aqui se cierra por el lado del actuador, que es el unico sitio donde no se puede
      # esquivar. El armado caduca a los 300 s y se recomprueba con reloj monotono, asi que
      # hace ademas de deadman del propio modo.
      if steer_mode in (1, 2):
        # DOS autorizaciones distintas, y mezclarlas fue un error con consecuencias:
        #  - OrbitBenchArmed: armado de banco, que habilita los verbos FISICOS POR MQTT.
        #  - OrbitSteerModeLocal: alguien ha elegido el modo en la pantalla del coche,
        #    estando delante. Es presencial y NO habilita nada remoto.
        # Antes, para que el selector de la pantalla volviera a funcionar, la UI armaba el
        # BANCO (y lo renovaba sin fin), asi que elegir "Jetson" delante del coche dejaba
        # torque_mode/steering_pulse/physical_control alcanzables por cualquiera que
        # publicara en el broker. Se separan.
        if self._orbit_banco_armado() or bool(self._param_get_cached("OrbitSteerModeLocal", 0.5)):
          self._orbit_log_motivo("torque_mode", "OK")
        else:
          self._orbit_log_motivo("torque_mode", "MODE")
          steer_mode = 0

      if steer_mode == 1:
        # FUENTE JETSON: torque ya normalizado [-1,1] que publica zmq_client.py en JetsonTorque.
        # FAIL-SAFE: si no se puede leer -> 0.0 (volante sin fuerza), nunca dejar pasar Comma en silencio.
        # WATCHDOG: si el ultimo torque tiene mas de JETSON_TORQUE_TIMEOUT_S, la Jetson se ha
        # caido -> 0.0, para no aplicar un valor viejo indefinidamente (volante atascado).
        # DEADMAN MONOTONO del override de torque (seccion 5). El sello que escribe
        # zmq_client es de PARED porque es lo unico que cruza hoy la barrera de proceso, y
        # en un comma sin NTP el reloj de pared salta minutos en cuanto sincroniza: medido
        # asi, el watchdog o no caduca nunca o caduca siempre. Aqui el sello se usa SOLO
        # como detector de CAMBIO y el plazo se mide con time.monotonic() local.
        # Lecturas cacheadas 50 ms: la Jetson publica a ~5 Hz, asi que a 100 Hz se estaban
        # abriendo y leyendo dos ficheros de params por ciclo en el core de tiempo real
        # para ver veinte veces el mismo valor.
        jt = 0.0
        try:
          ts_raw = self._param_get_cached("JetsonTorqueTimestamp", 0.05)
          ts = float(ts_raw) if ts_raw else 0.0
        except (ValueError, TypeError):
          ts = 0.0
        if ts != self._jetson_torque_last_ts:
          self._jetson_torque_last_ts = ts
          self._jetson_torque_seen_mono = self._orbit_now_mono
        if ts > 0.0 and self._jetson_torque_seen_mono > 0.0 and \
           (self._orbit_now_mono - self._jetson_torque_seen_mono) <= JETSON_TORQUE_TIMEOUT_S:
          try:
            jt = float(self._param_get_cached("JetsonTorque", 0.05) or 0.0)
          except (ValueError, TypeError):
            jt = 0.0
        # CLAMP al contrato de cereal/car.capnp (actuators.torque en [-1,1]). No confiamos en
        # el saneado del emisor: un fallo de escala en la Jetson (mandar 37.5 en vez de 0.375)
        # llegaba entero al carcontroller. NaN/Inf -> 0.0 (aqui, no al final del ciclo, para
        # que no se propaguen a los bloques de esquive de mas abajo).
        if not math.isfinite(jt):
          jt = 0.0
        jt = max(-1.0, min(1.0, jt))
        # DEAD-ZONE (JetsonDeadZone, default 0.02): el param existia documentado como
        # salvaguarda y NO lo leia nadie. Sin el, el ruido de la red neuronal alrededor de 0
        # llegaba al volante como microcorrecciones continuas en recta. Lectura cacheada 1 s:
        # es configuracion, no dato de control, y el loop va a 100 Hz en SCHED_FIFO.
        try:
          dz_raw = self._param_get_cached("JetsonDeadZone", 1.0)
          dz = JETSON_DEAD_ZONE_DEFAULT if dz_raw is None else abs(float(dz_raw))
        except (ValueError, TypeError):
          dz = JETSON_DEAD_ZONE_DEFAULT
        if abs(jt) < min(dz, JETSON_DEAD_ZONE_MAX):
          jt = 0.0
        actuators.torque = jt
      elif steer_mode == 2:
        actuators.torque = -1.0  # TEST MAX (banco), tras confirmación en la UI
      elif steer_mode == 3:
        pass  # COMMA+JETSON: el torque base lo deja Comma; abajo se aplican los offsets de esquive

      # AppliedSteerTorque = torque final aplicado TRAS el override de modo (diagnostico UI).
      self._defer_param_put("AppliedSteerTorque", f"{float(actuators.torque):.4f}")

    # [Orbit] PULSO TEMPORAL DE DIRECCION (verbo `steering_pulse`, seccion 6 -> modo BANCO).
    #
    # ANTES hacia `self.desired_curvature += 0.008`, que NO es un offset: self.desired_curvature es
    # el ESTADO PREVIO del limitador y se realimenta a clip_curvature en el ciclo siguiente. Como el
    # pulso se aplica en cada uno de los ~50 ciclos de sus 0.5 s y clip_curvature solo deja moverse
    # ~8e-5 por ciclo a 90 km/h, en 2-3 ciclos la curvatura entraba SATURADA y se quedaba ahi, y la
    # fase de retorno la lanzaba a la saturacion contraria. Ahora el offset vive en una LOCAL que
    # solo alimenta actuators.curvature, pasa por clip_curvature igual que el camino normal (respeta
    # el limite ISO de jerk/accel lateral, por eso a mas velocidad el pulso queda mas atenuado) y
    # self.desired_curvature no se toca.
    #
    # DOS DEADMAN INDEPENDIENTES, los dos MONOTONOS y los dos obligatorios:
    #   * el del propio modulo (ventana [inicio, inicio+2*duracion) del param), y
    #   * el del plano de estado (deadlineMono del comando), via _orbit_permiso.
    # Si cualquiera de los dos vence, el offset desaparece y manda el modelo. Dos relojes para
    # el mismo plazo porque el fallo que se quiere evitar -- un override lateral pegado -- es
    # justo el que ocurre cuando el unico que vigila deja de correr.
    #
    # El gate de velocidad NO se pide como bit SPEED_RANGE de la mascara: ese bit usa el rango
    # de MANIOBRA (40-130 km/h) y este verbo quiere lo contrario (<=20 km/h). Se comprueba en
    # local contra la constante del propio modulo del pulso.
    try:
      from openpilot.orbit.orbit_steering_pulse import (get_steering_pulse_state, clear_steering_pulse,
                                                        orbit_steering_pulse_angle, PULSE_MAX_SPEED_MS)
      pulso = get_steering_pulse_state()
      if pulso.active and pulso.effective_direction in ("right", "left"):
        ok_pulso, motivo_pulso = self._orbit_permiso("steering_pulse", OrbitMode.BENCH, 0,
                                                     requiere_banco=True) if _ORBIT_MANDO else (False, "LINK")
        if not CC.latActive:
          ok_pulso, motivo_pulso = False, "GATE_LAT_ACTIVE"
        elif CS.steeringPressed or CS.brakePressed or CS.gasPressed:
          # Cancelación por conductor: el modulo de esquive (modo 3) ya la tenia y el pulso no,
          # asi que un pulso remoto seguia peleandose con el volante durante su segundo entero.
          # Se BORRA el pulso, no solo se ignora: si solo se ignorara, soltar el volante medio
          # segundo despues lo reanudaria.
          ok_pulso, motivo_pulso = False, "GATE_DRIVER_IDLE"
          clear_steering_pulse()
        elif CS.vEgo > PULSE_MAX_SPEED_MS:
          ok_pulso, motivo_pulso = False, "GATE_SPEED_RANGE"

        self._orbit_log_motivo("steering_pulse", motivo_pulso if not ok_pulso else "OK")
        if ok_pulso:
          sign = 1.0 if pulso.effective_direction == "right" else -1.0
          sign *= max(0.0, min(1.0, float(pulso.magnitude)))  # |torque| del verbo, en [0,1]
          actuators.steeringAngleDeg = float(actuators.steeringAngleDeg) + sign * orbit_steering_pulse_angle
          pulse_curvature, _ = clip_curvature(CS.vEgo, self.desired_curvature,
                                              self.desired_curvature + sign * ORBIT_STEERING_PULSE_CURVATURE,
                                              lp.roll)
          actuators.curvature = pulse_curvature
    except ImportError:
      pass
    except Exception:
      pass

    # [Orbit] MODO 3 (COMMA+JETSON): offsets de esquive por obstáculo (override absoluto)
    try:
      if CC.latActive and steer_mode == 3 and self._obstacle_pulse_state is not None:
        # now_pulse es MONOTONO (el mismo instante que ya leyo _orbit_poll para todo el
        # ciclo). Antes era time.time(): se usaba para el TTL de la config, para el hold del
        # status y para sellar la telemetria, y las dos primeras cosas son PLAZOS -- con el
        # reloj de pared saltando al sincronizar el NTP, el hold del status podia quedarse
        # pegado minutos o no durar nada. El unico sitio donde de verdad hace falta el reloj
        # de pared es el sello que viaja por MQTT, y ahi se lee aparte.
        now_pulse = self._orbit_now_mono
        self._refresh_obstacle_config(now_pulse)
        try:
          payload_ts_raw = self.params.get("JetsonObstacleTimestamp")
          payload_ts = float(payload_ts_raw) if payload_ts_raw else 0.0
        except (UnknownKeyName, ValueError, TypeError):
          payload_ts = 0.0

        if payload_ts > self._obstacle_pulse_state.last_payload_ts:
          try:
            payload_raw = self.params.get("JetsonObstaclePulse")
            if payload_raw:
              payload = json.loads(payload_raw)
              if isinstance(payload, dict):
                # Se guarda el sello DEL PAYLOAD, no el instante de ingesta: last_payload_ts
                # es el detector de "mensaje nuevo" y compararlo contra el instante de
                # ingesta (que siempre es posterior) exigia que el siguiente payload fuera
                # mas nuevo que la lectura anterior, no que el payload anterior.
                self._obstacle_pulse_state.ingest_new_message(payload, payload_ts)
              else:
                cloudlog.error(f"controlsd: ObstaclePulse JSON no es dict: {payload!r}")
          except (UnknownKeyName, ValueError, TypeError, AttributeError) as e:
            cloudlog.error(f"controlsd: ObstaclePulse JSON inválido: {e}")

        # DEADMAN DE ACTUADOR (seccion 5). JetsonObstacleTimestamp solo servia para detectar
        # mensajes NUEVOS, nunca para caducar el estado: con la Jetson colgada tras un
        # {"obstacle":true,"intensity":-1.0}, cada ciclo a 100 Hz seguia aplicando el offset
        # maximo INDEFINIDAMENTE (es el "override lateral pegado" que cita el diseno).
        #
        # El plazo lo mide ahora el propio modulo con reloj MONOTONO (deadman_s del
        # constructor) y no con el sello de PARED del payload: en un comma sin NTP el reloj de
        # pared salta minutos en cuanto sincroniza, y un watchdog medido con un reloj que salta
        # o no caduca nunca o caduca siempre. stale() solo es True si habia algo activo, asi
        # que el log salta una vez por caducidad y no a 100 Hz.
        if self._obstacle_pulse_state.stale():
          self._obstacle_pulse_state._reset()
          cloudlog.warning("controlsd: esquive Jetson caducado (deadman monotono), vuelta a neutro")

        angle_tgt, curv_tgt, status = self._obstacle_pulse_state.get_offsets(
          now_pulse, CS, CC.latActive,
          max_angle=self._obstacle_max_angle,
          max_curv=self._obstacle_max_curv,
        )
        bsm_blocked = status in ("BSM_BLOCKED_LEFT", "BSM_BLOCKED_RIGHT")
        if self._obstacle_pulse_state.active and not bsm_blocked:
          if self._obstacle_apply_target == "torque":
            intensity = self._obstacle_pulse_state.intensity
            if math.isnan(intensity):
              intensity = 0.0
            actuators.torque = max(-1.0, min(1.0, intensity))
          else:
            actuators.steeringAngleDeg = angle_tgt
            self.desired_curvature = curv_tgt
            actuators.curvature = self.desired_curvature

        if status in ("DODGING_LEFT", "DODGING_RIGHT", "DODGING_HOLD", "BSM_BLOCKED_LEFT", "BSM_BLOCKED_RIGHT"):
          self._obstacle_status_held_value = status
          self._obstacle_status_hold_until = now_pulse + OBSTACLE_STATUS_HOLD_S
          published = status
        elif self._obstacle_status_held_value and now_pulse < self._obstacle_status_hold_until:
          published = self._obstacle_status_held_value
        else:
          self._obstacle_status_held_value = ""
          published = status

        if published != self._last_obstacle_status:
          # El sello que viaja por MQTT SI es de pared (es lo unico que el backend y la app
          # pueden interpretar). time_ns() y no time.time(): este arbol prohibe time.time
          # justamente para que nadie lo use por descuido para medir un plazo.
          self._defer_param_put("JetsonObstacleStatus", published)
          self._defer_param_put("JetsonObstacleStatusMqttPayload",
                                json.dumps({"status": published, "ts": time.time_ns() / 1e9, "source": "comma"}))
          self._last_obstacle_status = published

      elif self._obstacle_pulse_state is not None and \
           (self._obstacle_pulse_state.active or self._obstacle_status_held_value or self._last_obstacle_status):
        self._obstacle_pulse_state._reset()
        self._obstacle_status_held_value = ""
        self._obstacle_status_hold_until = 0.0
        if self._last_obstacle_status:
          self._defer_param_put("JetsonObstacleStatus", "")
          self._defer_param_put("JetsonObstacleStatusMqttPayload",
                                json.dumps({"status": "", "ts": time.time_ns() / 1e9, "source": "comma"}))
          self._last_obstacle_status = ""
    except Exception as e:
      cloudlog.error(f"controlsd: excepcion inesperada en bloque modo 3: {e}")

    # Ensure no NaNs/Infs
    for p in ACTUATOR_FIELDS:
      attr = getattr(actuators, p)
      if not isinstance(attr, Number):
        continue

      if not math.isfinite(attr):
        cloudlog.error(f"actuators.{p} not finite {actuators.to_dict()}")
        setattr(actuators, p, 0.0)

    return CC, lac_log

  def publish(self, CC, lac_log):
    CS = self.sm['carState']

    # Orientation and angle rates can be useful for carcontroller
    # Only calibrated (car) frame is relevant for the carcontroller
    CC.currentCurvature = self.curvature
    if self.calibrated_pose is not None:
      CC.orientationNED = self.calibrated_pose.orientation.xyz.tolist()
      CC.angularVelocity = self.calibrated_pose.angular_velocity.xyz.tolist()

    CC.cruiseControl.override = CC.enabled and not CC.longActive and (self.CP.openpilotLongitudinalControl or not self.CP_SP.pcmCruiseSpeed)
    CC.cruiseControl.cancel = CS.cruiseState.enabled and (not CC.enabled or not self.CP.pcmCruise)

    # [Orbit] BOTON DE PANICO REMOTO (verbo cruise_button {button:"cancel"}).
    #
    # Es el unico mando de la app que puede hacer esto, y se deja pasar precisamente
    # porque BAJA autoridad: desengancha, igual que si el conductor pulsara cancelar en el
    # volante. Por eso no exige ventana de actuador ni modo maniobra.
    #
    # Se SOSTIENE ~0.5 s: un solo ciclo a 100 Hz no basta para que el mensaje salga por
    # CAN y el coche lo atienda. El plazo es MONOTONO (un salto del reloj de pared no
    # puede alargar una cancelacion, ni acortarla). El param se limpia en cuanto se
    # engancha, con escritura diferida: en el hot path no se toca el disco.
    try:
      if self._orbit_cancel_hasta_mono > self._orbit_now_mono:
        CC.cruiseControl.cancel = True
      elif self._param_get_cached("OrbitCruiseCancel", 0.2):
        self._orbit_cancel_hasta_mono = self._orbit_now_mono + ORBIT_CRUISE_CANCEL_HOLD_S
        self._defer_param_put("OrbitCruiseCancel", False, is_bool=True)
        self._param_read_cache.pop("OrbitCruiseCancel", None)
        CC.cruiseControl.cancel = True
        self._orbit_log_motivo("cruise_button", "OK")
    except Exception:
      pass  # hot path: una cancelacion que falla no puede tumbar el control
    CC.cruiseControl.resume = CC.enabled and CS.cruiseState.standstill and not self.sm['longitudinalPlan'].shouldStop

    hudControl = CC.hudControl
    hudControl.setSpeed = float(CS.vCruiseCluster * CV.KPH_TO_MS)
    hudControl.speedVisible = CC.enabled
    hudControl.lanesVisible = CC.enabled
    hudControl.leadVisible = self.sm['longitudinalPlan'].hasLead
    hudControl.leadDistanceBars = self.sm['selfdriveState'].personality.raw + 1
    hudControl.visualAlert = self.sm['selfdriveState'].alertHudVisual

    hudControl.rightLaneVisible = True
    hudControl.leftLaneVisible = True
    if self.sm.valid['driverAssistance']:
      hudControl.leftLaneDepart = self.sm['driverAssistance'].leftLaneDeparture
      hudControl.rightLaneDepart = self.sm['driverAssistance'].rightLaneDeparture

    if self.get_lat_active(self.sm):
      CO = self.sm['carOutput']
      if self.CP.steerControlType == car.CarParams.SteerControlType.angle:
        self.steer_limited_by_safety = abs(CC.actuators.steeringAngleDeg - CO.actuatorsOutput.steeringAngleDeg) > \
                                              STEER_ANGLE_SATURATION_THRESHOLD
      else:
        self.steer_limited_by_safety = abs(CC.actuators.torque - CO.actuatorsOutput.torque) > 1e-2

    # TODO: both controlsState and carControl valids should be set by
    #       sm.all_checks(), but this creates a circular dependency

    # controlsState
    dat = messaging.new_message('controlsState')
    dat.valid = CS.canValid
    cs = dat.controlsState

    cs.curvature = self.curvature
    cs.longitudinalPlanMonoTime = self.sm.logMonoTime['longitudinalPlan']
    cs.lateralPlanMonoTime = self.sm.logMonoTime['modelV2']
    cs.desiredCurvature = self.desired_curvature
    cs.longControlState = self.LoC.long_control_state
    cs.upAccelCmd = float(self.LoC.pid.p)
    cs.uiAccelCmd = float(self.LoC.pid.i)
    cs.ufAccelCmd = float(self.LoC.pid.f)
    cs.forceDecel = bool((self.sm['driverMonitoringState'].alertLevel == log.DriverMonitoringState.AlertLevel.three) or
                         (self.sm['selfdriveState'].state == State.softDisabling))

    lat_tuning = self.CP.lateralTuning.which()
    if self.CP.steerControlType == car.CarParams.SteerControlType.angle:
      cs.lateralControlState.angleState = lac_log
    elif lat_tuning == 'pid':
      cs.lateralControlState.pidState = lac_log
    elif lat_tuning == 'torque':
      cs.lateralControlState.torqueState = lac_log

    self.pm.send('controlsState', dat)

    # carControl
    cc_send = messaging.new_message('carControl')
    cc_send.valid = CS.canValid
    cc_send.carControl = CC
    self.pm.send('carControl', cc_send)

  def run(self):
    rk = Ratekeeper(100, print_delay_threshold=None)
    while True:
      self.update()
      CC, lac_log = self.state_control()
      self.publish(CC, lac_log)
      self.get_params_sp(self.sm)
      self.run_ext(self.sm, self.pm)
      rk.monitor_time()


def main():
  config_realtime_process(4, Priority.CTRL_HIGH)
  controls = Controls()
  controls.run()


if __name__ == "__main__":
  main()
