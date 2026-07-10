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

# Anti-flicker: cuando JetsonObstacleStatus pasa de activo a "" lo mantenemos
# publicado este tiempo para que la UI (~20 Hz) no pierda dodges muy breves.
OBSTACLE_STATUS_HOLD_S = 0.30

# [Orbit] Watchdog de frescura del torque Jetson (modo 1). Si el ultimo JetsonTorque
# tiene mas de este tiempo, la Jetson se ha caido/desconectado -> forzar torque=0 (volante
# sin fuerza) en vez de aplicar indefinidamente un valor viejo (volante atascado). La Jetson
# real publica a ~5 Hz (200 ms), asi que 1 s es holgado y no falsea cortes en operacion normal.
JETSON_TORQUE_TIMEOUT_S = 1.0

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

    # [Orbit] Modo 3 (COMMA+JETSON): estado del esquive y caché de config
    self._obstacle_pulse_state = ObstaclePulseState() if _ORBIT_OBSTACLE else None
    self._last_obstacle_status = ""
    self._obstacle_status_hold_until = 0.0   # wall-clock hasta el que mantenemos el último activo
    self._obstacle_status_held_value = ""    # último status activo que estamos manteniendo
    self._obstacle_config_last_read = 0.0    # wall-clock; recachear cada 1s
    self._obstacle_max_angle = DEFAULT_MAX_ANGLE
    self._obstacle_max_curv = DEFAULT_MAX_CURV
    self._obstacle_apply_target = "curvature"  # "curvature" | "torque"
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
          self._defer_param_put(key, str(default))
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

  def state_control(self):
    CS = self.sm['carState']

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

    # [Orbit] Brutebreak: frenado de emergencia brusco por comando MQTT.
    # Solo tiene efecto si CC.longActive (Comma controla longitudinal). Auto-clear con vEgo<0.5.
    try:
      if self.params.get_bool("brutebreak_active"):
        intensidad_frenado = -3.5
        try:
          intensidad_raw = self.params.get("brutebreak_intensidad")
          if intensidad_raw:
            intensidad = float(intensidad_raw.decode("utf-8") if isinstance(intensidad_raw, bytes) else intensidad_raw)
            if -10.0 <= intensidad <= -1.0:
              intensidad_frenado = intensidad
        except Exception:
          pass
        actuators.accel = max(intensidad_frenado, pid_accel_limits[0])
        if CS.vEgo < 0.5:
          self._defer_param_put("brutebreak_active", False, is_bool=True)
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
      try:
        mode_raw = self.params.get("SteerTorqueMode")
      except UnknownKeyName:
        cloudlog.error("SteerTorqueMode no registrado en params_keys.h.")
        mode_raw = None
      try:
        steer_mode = int(mode_raw) if mode_raw else 0
      except (ValueError, TypeError):
        steer_mode = 0

      if steer_mode == 1:
        # FUENTE JETSON: torque ya normalizado [-1,1] que publica zmq_client.py en JetsonTorque.
        # FAIL-SAFE: si no se puede leer -> 0.0 (volante sin fuerza), nunca dejar pasar Comma en silencio.
        # WATCHDOG: si el ultimo torque tiene mas de JETSON_TORQUE_TIMEOUT_S, la Jetson se ha
        # caido -> 0.0, para no aplicar un valor viejo indefinidamente (volante atascado).
        jt = 0.0
        try:
          ts_raw = self.params.get("JetsonTorqueTimestamp")
          ts = float(ts_raw) if ts_raw else 0.0
          if ts > 0.0 and (time.time() - ts) <= JETSON_TORQUE_TIMEOUT_S:
            jt = float(self.params.get("JetsonTorque") or 0.0)
        except (UnknownKeyName, ValueError, TypeError):
          jt = 0.0
        actuators.torque = jt
      elif steer_mode == 2:
        actuators.torque = -1.0  # TEST MAX (banco), tras confirmación en la UI
      elif steer_mode == 3:
        pass  # COMMA+JETSON: el torque base lo deja Comma; abajo se aplican los offsets de esquive

      # AppliedSteerTorque = torque final aplicado TRAS el override de modo (diagnostico UI).
      self._defer_param_put("AppliedSteerTorque", f"{float(actuators.torque):.4f}")

    # [Orbit] Pulso temporal de dirección (cruceta MQTT): +/- ángulo y curvatura mientras está activo
    try:
      from openpilot.orbit.orbit_steering_pulse import get_steering_pulse, orbit_steering_pulse_angle
      pulse_start, original_direction, is_active, phase, effective_direction = get_steering_pulse()
      if is_active and effective_direction in ("right", "left") and CC.latActive:
        if effective_direction == "right":
          actuators.steeringAngleDeg = float(actuators.steeringAngleDeg) + orbit_steering_pulse_angle
          self.desired_curvature += 0.008
        else:
          actuators.steeringAngleDeg = float(actuators.steeringAngleDeg) - orbit_steering_pulse_angle
          self.desired_curvature -= 0.008
        actuators.curvature = self.desired_curvature
    except ImportError:
      pass
    except Exception:
      pass

    # [Orbit] MODO 3 (COMMA+JETSON): offsets de esquive por obstáculo (override absoluto)
    try:
      if CC.latActive and steer_mode == 3 and self._obstacle_pulse_state is not None:
        now_pulse = time.time()
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
                self._obstacle_pulse_state.ingest_new_message(payload, now_pulse)
              else:
                cloudlog.error(f"controlsd: ObstaclePulse JSON no es dict: {payload!r}")
          except (UnknownKeyName, ValueError, TypeError, AttributeError) as e:
            cloudlog.error(f"controlsd: ObstaclePulse JSON inválido: {e}")

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
          self._defer_param_put("JetsonObstacleStatus", published)
          self._defer_param_put("JetsonObstacleStatusMqttPayload",
                                json.dumps({"status": published, "ts": now_pulse, "source": "comma"}))
          self._last_obstacle_status = published

      elif self._obstacle_pulse_state is not None and \
           (self._obstacle_pulse_state.active or self._obstacle_status_held_value or self._last_obstacle_status):
        self._obstacle_pulse_state._reset()
        self._obstacle_status_held_value = ""
        self._obstacle_status_hold_until = 0.0
        if self._last_obstacle_status:
          self._defer_param_put("JetsonObstacleStatus", "")
          self._defer_param_put("JetsonObstacleStatusMqttPayload",
                                json.dumps({"status": "", "ts": time.time(), "source": "comma"}))
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
