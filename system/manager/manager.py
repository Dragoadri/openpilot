#!/usr/bin/env python3
import datetime
import os
import signal
import sys
import time
import traceback

from cereal import log
import cereal.messaging as messaging
import openpilot.system.sentry as sentry
from openpilot.common.utils import atomic_write, sudo_write
from openpilot.common.params import Params, ParamKeyFlag, UnknownKeyName
from openpilot.common.text_window import TextWindow
from openpilot.system.hardware import HARDWARE
from openpilot.system.manager.helpers import unblock_stdout, write_onroad_params, save_bootlog, restore_car_params_for_bench
from openpilot.system.manager.process import ensure_running
from openpilot.system.manager.process_config import managed_processes
from openpilot.system.athena.registration import register, UNREGISTERED_DONGLE_ID
from openpilot.common.swaglog import cloudlog, add_file_handler
from openpilot.system.version import get_build_metadata
from openpilot.system.hardware.hw import Paths
from openpilot.system.hardware import PC

from openpilot.sunnypilot.system.params_migration import run_migration

# [Start Bemposta] SIC-UEM / Orbit — hilo MQTT (import guardado: nunca debe brickear el arranque)
# Telemetria legacy retirada; solo Orbit MQTTEnvioGeneral.
try:
  from openpilot.orbit.mqtt_envio_general import MQTTEnvioGeneral
except Exception:
  cloudlog.exception("[Bemposta] no se pudieron importar los hilos MQTT SIC-UEM")
  MQTTEnvioGeneral = None
# Plano de mando remoto v2: GateMonitor + estado + publicador de orbitCommandState a
# 10 Hz. Import guardado aparte del de MQTT a proposito: si el mando no se puede
# importar, la telemetria tiene que seguir arrancando (y al reves).
try:
  from openpilot.orbit.command_state import get_command_plane
except Exception:
  cloudlog.exception("[Orbit] no se pudo importar el plano de mando remoto")
  get_command_plane = None
# [End Bemposta]


def manager_init() -> None:
  save_bootlog()

  # [FIX commIssue] Desactivar el RT bandwidth throttling del kernel.
  # Con el default (sched_rt_period_us=1s, sched_rt_runtime_us=950000 => 95%), si las tareas
  # SCHED_FIFO de la tuberia (sensord/locationd/paramsd/radard/plannerd/dmonitoringd/torqued/
  # lagd/calibrationd...) superan el 95% de CPU de su core, el kernel las CONGELA ~50 ms UNA VEZ
  # POR SEGUNDO. Eso hace que radard/plannerd/paramsd/dmonitoringd fallen su all_checks() a la vez
  # (valid=False durante ese hueco) -> selfdrived ve varios servicios "invalid" -> EventName.commIssue
  # (TAKE CONTROL IMMEDIATELY) al activar OP, con periodicidad de exactamente 1 s (ver logs).
  # El sensord migrado a Python es mas pesado que el C++ y empuja la carga FIFO por encima del umbral.
  # openpilot corre con el throttling DESACTIVADO (-1); si AGNOS no lo pone, lo forzamos aqui.
  # No-op inofensivo si ya estaba en -1. Solo tiene efecto en el device (root); en PC falla y se ignora.
  # [FIX sim/PC] En PC NO llamar a sudo_write: su fallback es `sudo chmod` INTERACTIVO (os.system),
  # que CUELGA el arranque esperando contrasena (sin TTY en el sim) -> manager congelado, no arranca
  # NINGUN proceso (ni el hilo MQTT) -> el dispositivo nunca sale conectado. El throttling RT solo
  # importa en el device; en PC se salta. En el comma (not PC) sigue ejecutandose como antes.
  if not PC:
    try:
      sudo_write("-1", "/proc/sys/kernel/sched_rt_runtime_us")
    except Exception:
      cloudlog.exception("no se pudo desactivar sched_rt_runtime_us")

  build_metadata = get_build_metadata()

  params = Params()
  params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)
  # if build_metadata.release_channel:
  #   params.clear_all(ParamKeyFlag.DEVELOPMENT_ONLY)

  # device boot mode
  if params.get("DeviceBootMode") == 1:  # start in Always Offroad mode
    params.put_bool("OffroadMode", True, block=True)

  # quick boot
  if params.get_bool("QuickBootToggle") and not PC:
    prebuilt_path = "/data/openpilot/prebuilt"
    if not os.path.exists(prebuilt_path):
      open(prebuilt_path, 'x').close()

  if params.get_bool("RecordFrontLock"):
    params.put_bool("RecordFront", True, block=True)

  if not PC:
    run_migration(params)

  # set unset params to their default value
  for k in params.all_keys():
    default_value = params.get_default_value(k)
    if default_value is not None and params.get(k) is None:
      params.put(k, default_value, block=True)

  # [Orbit] FAIL-SAFE: SteerTorqueMode=2 es "TEST MAX" (torque -1.0 constante, solo banco).
  # El param es PERSISTENT porque los modos Jetson (1/3) deben sobrevivir al reinicio,
  # pero el modo 2 NUNCA debe quedar activo tras un reinicio: en la primera activacion
  # el volante tiraria a tope. Se resetea a 0 (Comma) en cada arranque de manager.
  try:
    if params.get("SteerTorqueMode") == 2:
      cloudlog.warning("[Orbit] SteerTorqueMode=2 (TEST MAX) detectado al arrancar: reseteado a 0 (Comma)")
      params.put("SteerTorqueMode", 0, block=True)
  except UnknownKeyName:
    pass

  # [Orbit] chequeo de instalacion: submodulos vacios o modelos LFS sin descargar
  # se manifestaban como dashcam/procesos caidos sin aviso claro. Ahora sale una
  # alerta offroad explicita con el problema y el comando para arreglarlo.
  try:
    from openpilot.orbit.install_check import run_install_check
    from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
    _install_problems = run_install_check()
    set_offroad_alert("Offroad_OrbitInstallIncomplete", len(_install_problems) > 0,
                      extra_text="\n".join(_install_problems))
    if _install_problems:
      cloudlog.warning(f"[Orbit] instalacion incompleta: {_install_problems}")
  except Exception:
    cloudlog.exception("[Orbit] install_check fallo (no bloquea el arranque)")

  # Create folders needed for msgq
  try:
    os.mkdir(Paths.shm_path())
  except FileExistsError:
    pass
  except PermissionError:
    print(f"WARNING: failed to make {Paths.shm_path()}")

  # set params
  serial = HARDWARE.get_serial()
  params.put("Version", build_metadata.openpilot.version, block=True)
  params.put("GitCommit", build_metadata.openpilot.git_commit, block=True)
  params.put("GitCommitDate", build_metadata.openpilot.git_commit_date, block=True)
  params.put("GitBranch", build_metadata.channel, block=True)
  params.put("GitRemote", build_metadata.openpilot.git_origin, block=True)
  params.put_bool("IsDevelopmentBranch", build_metadata.development_channel, block=True)
  params.put_bool("IsTestedBranch", build_metadata.tested_channel, block=True)
  params.put_bool("IsReleaseBranch", build_metadata.release_channel, block=True)
  params.put_bool("IsReleaseSpBranch", build_metadata.release_sp_channel, block=True)
  params.put("HardwareSerial", serial, block=True)

  # set dongle id
  reg_res = register(show_spinner=True)
  if reg_res:
    dongle_id = reg_res
  else:
    raise Exception(f"Registration failed for device {serial}")
  os.environ['DONGLE_ID'] = dongle_id  # Needed for swaglog
  os.environ['GIT_ORIGIN'] = build_metadata.openpilot.git_normalized_origin # Needed for swaglog
  os.environ['GIT_BRANCH'] = build_metadata.channel # Needed for swaglog
  os.environ['GIT_COMMIT'] = build_metadata.openpilot.git_commit # Needed for swaglog

  if not build_metadata.openpilot.is_dirty:
    os.environ['CLEAN'] = '1'

  # init logging
  sentry.init(sentry.SentryProject.SELFDRIVE)
  cloudlog.bind_global(dongle_id=dongle_id,
                       version=build_metadata.openpilot.version,
                       origin=build_metadata.openpilot.git_normalized_origin,
                       branch=build_metadata.channel,
                       commit=build_metadata.openpilot.git_commit,
                       dirty=build_metadata.openpilot.is_dirty,
                       device=HARDWARE.get_device_type())

  # preimport all processes
  for p in managed_processes.values():
    p.prepare()


def manager_cleanup() -> None:
  # send signals to kill all procs
  for p in managed_processes.values():
    p.stop(block=False)

  # ensure all are killed
  for p in managed_processes.values():
    p.stop(block=True)

  cloudlog.info("everything is dead")


def manager_thread() -> None:
  cloudlog.bind(daemon="manager")
  cloudlog.info("manager start")
  cloudlog.info({"environ": os.environ})

  params = Params()

  ignore: list[str] = []
  if params.get("DongleId") in (None, UNREGISTERED_DONGLE_ID):
    ignore += ["manage_athenad", "uploader"]
  if os.getenv("NOBOARD") is not None:
    ignore.append("pandad")
  ignore += [x for x in os.getenv("BLOCK", "").split(",") if len(x) > 0]

  sm = messaging.SubMaster(['deviceState', 'carParams', 'pandaStates'], poll='deviceState')
  pm = messaging.PubMaster(['managerState'])

  write_onroad_params(False, params)
  ensure_running(managed_processes.values(), False, params=params, CP=sm['carParams'], not_run=ignore)

  # [Start Bemposta] hilos MQTT SIC-UEM / Orbit con SUPERVISION.
  # Antes: arranque fire-and-forget; si el hilo moria por una excepcion quedaba
  # muerto hasta reiniciar el dispositivo (telemetria/ordenes/camara caidas sin
  # sintoma visible). Ahora el bucle principal los vigila y los resucita con
  # backoff (30 s) para no hacer restart-flapping si el fallo es permanente.
  ORBIT_THREAD_RESTART_S = 30.0
  orbit_threads: dict[str, dict] = {}  # name -> {"cls", "inst", "next_retry"}
  # El plano de mando va PRIMERO: es quien publica los gates y el deadman que leen
  # controlsd, card y desire_helper, y quien atiende el boton fisico de desarme. Tiene
  # que estar ticando antes de que el enlace MQTT acepte el primer comando.
  #
  # OJO con "cls": es la FABRICA DEL SINGLETON, no la clase. El supervisor hace
  # stop() + cls() + start() al resucitar, y si esto construyera un objeto nuevo, el
  # CommandRouter seguiria consultando el GateMonitor viejo -- una mascara que ya nadie
  # refresca. Con el singleton se releva el HILO y el objeto sigue siendo el mismo; y
  # mientras no tique, su mascara se declara rancia y todos los gates valen ROJO (ver
  # GateMonitor.stale y CommandPlane.healthy).
  if get_command_plane is not None:
    orbit_threads["OrbitCommandPlane"] = {"cls": get_command_plane, "inst": None, "next_retry": 0.0}
  if MQTTEnvioGeneral is not None:
    orbit_threads["MQTTEnvioGeneral"] = {"cls": MQTTEnvioGeneral, "inst": None, "next_retry": 0.0}
  # [End Bemposta]

  started_prev = False
  ignition_prev = False

  while True:
    sm.update(1000)

    started = sm['deviceState'].started

    if started and not started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
      # ORBIT modo banco: hardwared fuerza la ignicion sin coche (ForceOnroad). CarParams y
      # CarParamsSP acaban de borrarse (CLEAR_ON_ONROAD_TRANSITION) y card no los va a
      # reponer porque nunca recibira CAN: se restauran de las copias de la ultima conduccion.
      if params.get_bool("ForceOnroad"):
        if restore_car_params_for_bench(params):
          cloudlog.warning("ForceOnroad: sin CarParamsPersistent, arrancando con coche MOCK (dashcam)")
    elif not started and started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)

    ignition = any(ps.ignitionLine or ps.ignitionCan for ps in sm['pandaStates'] if ps.pandaType != log.PandaState.PandaType.unknown)
    if ignition and not ignition_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)

    # update onroad params, which drives pandad's safety setter thread
    if started != started_prev:
      write_onroad_params(started, params)

    started_prev = started
    ignition_prev = ignition

    ensure_running(managed_processes.values(), started, params=params, CP=sm['carParams'], not_run=ignore)

    # [Start Bemposta] supervisor de hilos orbit: resucita los que hayan muerto
    for _name, _st in orbit_threads.items():
      _inst = _st["inst"]
      if _inst is not None and _inst.is_alive() and _inst.healthy():
        continue
      _now = time.monotonic()
      if _now < _st["next_retry"]:
        continue
      if _inst is not None:
        cloudlog.warning(f"[Bemposta] {_name} caido o enfermo; reiniciando")
        # parada limpia de la instancia vieja (para sub-hilos: comandos, camara, setup_mqtt)
        try:
          _inst.stop()
        except Exception:
          pass
        try:
          _inst.join(timeout=2)
        except Exception:
          pass
      try:
        _inst = _st["cls"]()
        _inst.start()
        _st["inst"] = _inst
        cloudlog.info(f"[Bemposta] {_name} iniciado")
      except Exception:
        cloudlog.exception(f"[Bemposta] fallo iniciando {_name}")
      _st["next_retry"] = time.monotonic() + ORBIT_THREAD_RESTART_S
    # [End Bemposta]

    running = ' '.join("{}{}\u001b[0m".format("\u001b[32m" if p.proc.is_alive() else "\u001b[31m", p.name)
                       for p in managed_processes.values() if p.proc)
    print(running)
    cloudlog.debug(running)

    # send managerState
    msg = messaging.new_message('managerState', valid=True)
    msg.managerState.processes = [p.get_process_state_msg() for p in managed_processes.values()]
    pm.send('managerState', msg)

    # kick AGNOS power monitoring watchdog
    try:
      if sm.all_checks(['deviceState']):
        with atomic_write("/var/tmp/power_watchdog", "w", overwrite=True) as f:
          f.write(str(time.monotonic()))
    except Exception:
      pass

    # Exit main loop when uninstall/shutdown/reboot is needed
    shutdown = False
    for param in ("DoUninstall", "DoShutdown", "DoReboot"):
      if params.get_bool(param):
        shutdown = True
        params.put("LastManagerExitReason", f"{param} {datetime.datetime.now()}", block=True)
        cloudlog.warning(f"Shutting down manager - {param} set")

    if shutdown:
      break


def main() -> None:
  manager_init()
  if os.getenv("PREPAREONLY") is not None:
    return

  # SystemExit on sigterm
  signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(1))

  try:
    manager_thread()
  except Exception:
    traceback.print_exc()
    sentry.capture_exception()
  finally:
    manager_cleanup()

  params = Params()
  if params.get_bool("DoUninstall"):
    cloudlog.warning("uninstalling")
    HARDWARE.uninstall()
  elif params.get_bool("DoReboot"):
    cloudlog.warning("reboot")
    HARDWARE.reboot()
  elif params.get_bool("DoShutdown"):
    cloudlog.warning("shutdown")
    HARDWARE.shutdown()


if __name__ == "__main__":
  unblock_stdout()

  try:
    main()
  except KeyboardInterrupt:
    print("got CTRL-C, exiting")
  except Exception:
    add_file_handler(cloudlog)
    cloudlog.exception("Manager failed to start")

    try:
      managed_processes['ui'].stop()
    except Exception:
      pass

    # Show last 3 lines of traceback
    error = traceback.format_exc(-3)
    error = "Manager failed to start\n\n" + error
    with TextWindow(error) as t:
      t.wait_for_exit()

    raise

  # manual exit because we are forked
  sys.exit(0)
