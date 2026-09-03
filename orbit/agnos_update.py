#!/usr/bin/env python3
"""Fase de actualización de AGNOS del arranque, narrada en pantalla y sin bucles.

Sustituye al bloque de launch_chffrplus.sh que hacía, a ciegas:

    if agnos.py --verify manifest; then sudo reboot; fi
    updater agnos.py manifest

Ese bloque es el ÚNICO punto del arranque que reinicia el dispositivo, y lo
hace sin decir nada: si el AGNOS que la rama exige no arranca en esa unidad
(o el swap de slot no termina bien), el bootloader vuelve al slot viejo, la
comprobación se repite y el coche se queda para siempre alternando entre el
logo de comma y un reinicio, sin que nada en pantalla explique qué pasa.

Aquí se hace lo mismo pero:

  * se cuenta en pantalla (spinner del arranque) qué AGNOS tiene el
    dispositivo, cuál exige la rama y qué se va a hacer;
  * se deja constancia en el registro persistente (boot_log);
  * se cuentan los intentos por versión objetivo en /data y, pasados
    MAX_ATTEMPTS, se deja de reintentar y se sigue arrancando con el AGNOS
    actual, para que el fallo sea visible en vez de infinito;
  * si el actualizador gráfico de comma (`updater`, un zipapp que necesita
    `pyray`) no puede correr en el AGNOS actual, se flashea SIN interfaz con
    `agnos.py --swap` y se reinicia. Caso real: un comma 3 con AGNOS 10.1 no
    tiene pyray, el updater muere con ModuleNotFoundError, nada actualiza
    AGNOS y el dispositivo se queda en el logo para siempre.

Uso:  agnos_update.py <agnos.py> <manifest.json> <version_requerida>

Nunca falla hacia arriba: código de salida 0 siempre.
"""
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
try:
  from openpilot.orbit import install_repair
except ImportError:  # ejecutado como script suelto, sin el PYTHONPATH del repo
  sys.path.insert(0, _HERE)
  import install_repair  # type: ignore[no-redef]

VERSION_FILE = "/VERSION"
ATTEMPTS_FILE = "/data/orbit_agnos_attempts.json"
MAX_ATTEMPTS = 3
VERIFY_TIMEOUT_S = 900.0     # leer y hashear las particiones del otro slot
UPDATER_TIMEOUT_S = 3600.0   # descarga (~1 GB) + flasheo
REBOOT_HOLD_S = 60.0         # tras pedir el reinicio, no dejar que el arranque siga


def read_version(version_file: str | None = None) -> str:
  try:
    with open(version_file or VERSION_FILE, encoding="utf-8") as f:
      return f.read().strip()
  except OSError:
    return ""


def load_attempts(attempts_file: str | None = None) -> dict:
  try:
    with open(attempts_file or ATTEMPTS_FILE, encoding="utf-8") as f:
      data = json.load(f)
    if isinstance(data, dict):
      return data
  except Exception:
    pass
  return {}


def save_attempts(data: dict, attempts_file: str | None = None) -> None:
  attempts_file = attempts_file or ATTEMPTS_FILE
  try:
    tmp = attempts_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
      json.dump(data, f)
    os.replace(tmp, attempts_file)
  except Exception:
    pass


def clear_attempts(attempts_file: str | None = None) -> None:
  try:
    os.remove(attempts_file or ATTEMPTS_FILE)
  except OSError:
    pass


def bump_attempts(current: str, target: str, attempts_file: str | None = None) -> int:
  """Incrementa el contador de intentos hacia `target` (se reinicia si cambia el objetivo)."""
  data = load_attempts(attempts_file)
  if data.get("target") != target:
    data = {"target": target, "count": 0}
  data["count"] = int(data.get("count", 0)) + 1
  data["from"] = current
  data["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
  save_attempts(data, attempts_file)
  return data["count"]


def pyray_available() -> bool:
  """¿Puede correr algo gráfico (updater, spinner) en el AGNOS actual?"""
  try:
    return subprocess.run(["python3", "-c", "import pyray"], timeout=60,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
  except Exception:
    return False


def reboot(log) -> None:
  log("reiniciando…")
  try:
    subprocess.run(["sudo", "reboot"], timeout=60, check=False)
  except Exception as e:
    log(f"no se pudo pedir el reinicio: {e!r}")
    return
  time.sleep(REBOOT_HOLD_S)


def update(agnos_py: str, manifest: str, target: str, log, feedback,
           current: str | None = None, attempts_file: str | None = None,
           run=install_repair.run_logged, do_reboot=reboot, graphics_ok=pyray_available) -> str:
  """Ejecuta la fase. Devuelve lo que hizo: 'ok', 'reboot', 'updater', 'skipped' o 'failed'."""
  current = read_version() if current is None else current
  if current == target:
    clear_attempts(attempts_file)
    return "ok"

  updater = os.path.join(os.path.dirname(agnos_py), "updater")
  count = bump_attempts(current, target, attempts_file)
  log(f"AGNOS: el dispositivo tiene {current or '?'} y la rama exige {target} (intento {count}/{MAX_ATTEMPTS})")

  if count > MAX_ATTEMPTS:
    log(f"AGNOS: {MAX_ATTEMPTS} intentos sin conseguir arrancar con {target}; se deja de reintentar "
        + f"y se sigue con AGNOS {current or '?'} para que el fallo se vea en pantalla")
    feedback.text(f"ORBIT: AGNOS {target} no ha arrancado tras {MAX_ATTEMPTS} intentos; sigo con AGNOS {current}", force=True)
    time.sleep(8.0)
    return "skipped"

  feedback.text(f"ORBIT: AGNOS {current} → {target}. Comprobando el otro slot…", force=True)
  rc = run([agnos_py, "--verify", manifest], cwd=os.path.dirname(agnos_py), timeout=VERIFY_TIMEOUT_S, log=log)
  if rc == 0:
    log(f"AGNOS: el otro slot ya tiene {target}; slot cambiado, toca reiniciar")
    feedback.text(f"ORBIT: AGNOS {target} listo en el otro slot. Reiniciando…", force=True)
    time.sleep(3.0)
    feedback.close()
    do_reboot(log)
    return "reboot"

  log(f"AGNOS: el otro slot no tiene {target} (rc={rc}); hay que descargar y flashear (10-25 min)")
  if graphics_ok():
    feedback.text(f"ORBIT: descargando AGNOS {target}. Va a salir la pantalla del actualizador…", force=True)
    time.sleep(3.0)
    feedback.close()  # el updater pinta su propia UI
    rc = run([updater, agnos_py, manifest], cwd=os.path.dirname(agnos_py), timeout=UPDATER_TIMEOUT_S, log=log)
    if rc == 0:
      log("AGNOS: updater terminó rc=0 sin reiniciar; el arranque sigue")
      return "updater"
    log(f"AGNOS: el updater gráfico falló (rc={rc}); se pasa al flasheo sin interfaz")
  else:
    log(f"AGNOS: este AGNOS ({current or '?'}) no tiene pyray: el updater gráfico no puede correr, flasheo sin interfaz")
    feedback.close()

  # Sin interfaz: agnos.py descarga y flashea el otro slot hasta que verifica, y lo
  # activa. Solo necesita requests y abctl, que existen en cualquier AGNOS. La
  # pantalla seguirá en el logo mientras dure; la baliza y el registro cuentan el progreso.
  log(f"AGNOS: flasheando {target} sin interfaz con agnos.py --swap (la pantalla no cambiará hasta el reinicio)")
  rc = run([agnos_py, "--swap", manifest], cwd=os.path.dirname(agnos_py), timeout=UPDATER_TIMEOUT_S, log=log)
  if rc == 0:
    log(f"AGNOS: {target} flasheado y slot activado; reiniciando")
    do_reboot(log)
    return "reboot"
  log(f"AGNOS: el flasheo sin interfaz FALLÓ (rc={rc}); el arranque sigue con AGNOS {current or '?'}")
  return "failed"


def main(argv: list[str]) -> int:
  log = install_repair.Log()
  if len(argv) != 4:
    log(f"agnos_update.py: uso incorrecto {argv[1:]}")
    return 0
  feedback = install_repair.Feedback()
  try:
    update(argv[1], argv[2], argv[3], log, feedback)
  except BaseException as e:  # noqa: B036 -- este script no puede romper el arranque
    try:
      log(f"error inesperado en la fase AGNOS (se ignora): {e!r}")
    except Exception:
      pass
  finally:
    feedback.close()
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv))
