#!/usr/bin/env python3
"""Auto-reparación de la instalación ORBIT en el arranque del dispositivo.

Se ejecuta desde launch_chffrplus.sh ANTES de la comprobación de AGNOS y del
build, y solo hace algo si install_check detecta un despliegue roto:

  * punteros git-lfs sin descargar (modelos, fuentes, iconos, sonidos, el
    updater de AGNOS): `git lfs pull`, excluyendo los modelos big_* de USB-GPU
    que el comma no usa (310 de 437 MB).
  * submódulos sin inicializar: `git submodule update --init --recursive`.

Va antes de la comprobación de AGNOS porque el binario `updater` que esa
comprobación ejecuta es él mismo un fichero LFS.

REGLAS QUE NO SE NEGOCIAN

  1. Nunca falla hacia arriba: devuelve 0 y no lanza. Si no sabe arreglar algo
     lo deja escrito en el log y se aparta; el arranque sigue y la UI mostrará
     la alerta offroad de install_check.
  2. Todo lo que toca la red tiene timeout y mata al hijo si se pasa. Antes de
     tirar de red espera a que haya red (el wifi tarda unos segundos tras el
     arranque), pero con tope.
  3. Cuenta lo que hace EN PANTALLA, por el spinner del arranque. Un `git lfs
     pull` mudo de varios minutos es indistinguible de un dispositivo colgado.
  4. En una instalación sana no ejecuta ni un comando externo ni escribe log.

Registro: stdout (acaba en el log de tmux / /tmp/launch_log) y
/tmp/orbit_install_repair.log.
"""
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

# orbit/ está un nivel por debajo de la raíz del repo (mismo criterio que
# install_check: realpath por la granja de symlinks openpilot/ del PC).
_HERE = os.path.dirname(os.path.realpath(__file__))
BASEDIR = os.path.dirname(_HERE)
try:
  from openpilot.orbit import install_check
except ImportError:  # ejecutado como script suelto, sin el PYTHONPATH del repo
  sys.path.insert(0, _HERE)
  import install_check  # type: ignore[no-redef]

LOG_PATH = "/tmp/orbit_install_repair.log"
DEFAULT_LFS_URL = "https://gitlab.com/sunnypilot/public/sunnypilot-new-lfs.git/info/lfs"

# Presupuestos de tiempo (segundos). La suma cabe en el `timeout` externo de
# launch_chffrplus.sh, que es la última red de seguridad.
NETWORK_WAIT_S = 90.0
LFS_INSTALL_TIMEOUT_S = 60.0
LFS_PULL_TIMEOUT_S = 900.0
SUBMODULE_TIMEOUT_S = 600.0
SPINNER_MIN_INTERVAL_S = 0.5

TIMEOUT_RC = -1

_LFS_PROGRESS_RE = re.compile(r"Downloading LFS objects:\s+\d+% \((\d+)/(\d+)\), ([\d.]+ [KMG]?i?B)")


# --- registro y feedback -----------------------------------------------------

class Log:
  """Escribe en stdout (tmux) y en LOG_PATH. Nunca lanza."""

  def __init__(self, path: str | None = None):
    self.path = path or LOG_PATH

  def __call__(self, msg: str) -> None:
    line = f"[ORBIT repair] {msg}"
    try:
      print(line, flush=True)
    except Exception:
      pass
    try:
      with open(self.path, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
      pass


def spinner_enabled() -> bool:
  """Spinner solo en el dispositivo (o si se fuerza), nunca en tests ni en PC."""
  forced = os.environ.get("ORBIT_REPAIR_SPINNER")
  if forced is not None:
    return forced == "1"
  return os.path.isfile("/AGNOS")


def _default_spinner_factory():
  from openpilot.common.spinner import Spinner  # import tardío: puede no ser importable
  return Spinner()


class Feedback:
  """Texto de progreso en el spinner del arranque. Cualquier fallo interno se traga."""

  def __init__(self, spinner_factory: Callable | None = None, enabled: bool | None = None,
               min_interval: float = SPINNER_MIN_INTERVAL_S, clock: Callable[[], float] = time.monotonic):
    self._factory = spinner_factory or _default_spinner_factory
    self._enabled = spinner_enabled() if enabled is None else enabled
    self._min_interval = min_interval
    self._clock = clock
    self._spinner = None
    self._last = -1e9

  def _ensure(self):
    if self._spinner is None and self._enabled:
      try:
        self._spinner = self._factory()
      except Exception:
        self._enabled = False
    return self._spinner

  def text(self, msg: str, force: bool = False) -> None:
    if not self._enabled:
      return
    now = self._clock()
    if not force and now - self._last < self._min_interval:
      return
    self._last = now
    spinner = self._ensure()
    if spinner is None:
      return
    try:
      spinner.update(msg)
    except Exception:
      pass

  def close(self) -> None:
    spinner, self._spinner = self._spinner, None
    if spinner is not None:
      try:
        spinner.close()
      except Exception:
        pass


# --- utilidades --------------------------------------------------------------

def parse_lfs_progress(line: str) -> str | None:
  """'Downloading LFS objects:  45% (118/263), 60 MB | ...' -> '118/263 (60 MB)'."""
  m = _LFS_PROGRESS_RE.search(line)
  if not m:
    return None
  return f"{m.group(1)}/{m.group(2)} ({m.group(3)})"


def run_logged(cmd: list[str], cwd: str, timeout: float, log: Callable[[str], None],
               on_line: Callable[[str], None] | None = None, env: dict | None = None) -> int:
  """Ejecuta cmd volcando cada línea (separada por \\n o \\r) a on_line (por defecto log).

  Devuelve el código de salida, TIMEOUT_RC si hubo que matarlo, o 127 si no se
  pudo lanzar. Nunca lanza.
  """
  on_line = on_line or log
  try:
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  except Exception as e:
    log(f"no se pudo ejecutar {' '.join(cmd)}: {e}")
    return 127

  def _pump():
    buf = b""
    assert proc.stdout is not None
    while True:
      chunk = os.read(proc.stdout.fileno(), 4096)
      if not chunk:
        break
      buf += chunk
      parts = re.split(rb"[\r\n]", buf)
      buf = parts.pop()
      for part in parts:
        text = part.decode("utf-8", "replace").strip()
        if text:
          on_line(text)
    if buf.strip():
      on_line(buf.decode("utf-8", "replace").strip())

  reader = threading.Thread(target=_pump, daemon=True)
  reader.start()
  try:
    rc = proc.wait(timeout=timeout)
  except subprocess.TimeoutExpired:
    log(f"timeout ({timeout:.0f} s) ejecutando {' '.join(cmd)}: matando el proceso")
    proc.kill()
    proc.wait(timeout=10)
    rc = TIMEOUT_RC
  except BaseException:
    proc.kill()
    raise
  finally:
    try:
      proc.stdout.close()  # type: ignore[union-attr]
    except Exception:
      pass
  reader.join(timeout=5)
  return rc


def lfs_url(basedir: str) -> str:
  """URL del servidor LFS según .lfsconfig del repo (o la de sunnypilot por defecto)."""
  try:
    with open(os.path.join(basedir, ".lfsconfig"), encoding="utf-8") as f:
      for line in f:
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == "url" and value.strip():
          return value.strip()
  except OSError:
    pass
  return DEFAULT_LFS_URL


def wait_for_network(url: str, deadline_s: float, feedback: Feedback, log: Callable[[str], None],
                     opener=urllib.request.urlopen, clock: Callable[[], float] = time.monotonic,
                     sleep: Callable[[float], None] = time.sleep) -> bool:
  """Espera a que el servidor LFS conteste (cualquier respuesta HTTP vale). Con tope."""
  t0 = clock()
  attempt = 0
  while True:
    attempt += 1
    try:
      opener(url, timeout=5)
      return True
    except urllib.error.HTTPError:
      return True  # 4xx/5xx: el servidor está ahí, luego hay red
    except Exception as e:
      err = e
    elapsed = clock() - t0
    if elapsed >= deadline_s:
      log(f"sin red tras {elapsed:.0f} s ({err}); no se puede descargar nada en este arranque")
      return False
    feedback.text(f"ORBIT: esperando conexión de red para completar la instalación… ({int(elapsed)} s)")
    sleep(3.0)


def git_lfs_available(basedir: str) -> bool:
  try:
    return subprocess.run(["git", "lfs", "version"], cwd=basedir, timeout=30,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
  except Exception:
    return False


# --- reparación --------------------------------------------------------------

def repair_lfs(basedir: str, log: Callable[[str], None], feedback: Feedback) -> None:
  if not git_lfs_available(basedir):
    log("git-lfs no está disponible en el dispositivo: no se pueden descargar los ficheros que faltan")
    return

  url = lfs_url(basedir)
  if not wait_for_network(url, NETWORK_WAIT_S, feedback, log):
    return

  # Filtros LFS en el .git/config de ESTE clon (sin tocar el ~/.gitconfig del
  # sistema ni instalar hooks), para que tras el pull git vea el árbol limpio.
  run_logged(["git", "lfs", "install", "--local", "--skip-repo"], cwd=basedir, timeout=LFS_INSTALL_TIMEOUT_S, log=log)

  excludes = ",".join(install_check.LFS_IGNORE_GLOBS)
  log(f"descargando objetos git-lfs desde {url} (excluidos: {excludes})")
  feedback.text("ORBIT: completando la instalación… descargando ficheros", force=True)

  def on_line(line: str) -> None:
    progress = parse_lfs_progress(line)
    if progress is not None:
      feedback.text(f"ORBIT: completando la instalación… descargando {progress}")
    else:
      log(line)

  env = {**os.environ, "GIT_LFS_FORCE_PROGRESS": "1"}
  rc = run_logged(["git", "lfs", "pull", f"--exclude={excludes}"], cwd=basedir, timeout=LFS_PULL_TIMEOUT_S,
                  log=log, on_line=on_line, env=env)
  log("git lfs pull: OK" if rc == 0 else f"git lfs pull: FALLO (rc={rc})")


def repair_submodules(basedir: str, log: Callable[[str], None], feedback: Feedback) -> None:
  if not wait_for_network("https://github.com/", NETWORK_WAIT_S, feedback, log):
    return
  log("sincronizando submódulos…")
  feedback.text("ORBIT: completando la instalación… submódulos", force=True)
  run_logged(["git", "submodule", "sync", "--recursive"], cwd=basedir, timeout=60, log=log)
  rc = run_logged(["git", "submodule", "update", "--init", "--recursive"], cwd=basedir,
                  timeout=SUBMODULE_TIMEOUT_S, log=log)
  log("submódulos: OK" if rc == 0 else f"submódulos: FALLO (rc={rc})")


def repair(basedir: str, log: Callable[[str], None], feedback: Feedback) -> list[str]:
  """Repara solo lo roto. Devuelve los problemas que siguen tras intentarlo (vacío = sano)."""
  status = install_check.inspect_install(basedir)
  if status.ok():
    return []

  log("instalación incompleta detectada:")
  for problem in install_check.run_install_check(basedir):
    log("  " + problem)

  if not os.path.isdir(os.path.join(basedir, ".git")):
    log("no hay repositorio git: hay que reinstalar a mano")
    return install_check.run_install_check(basedir)

  if status.lfs_pointers:
    repair_lfs(basedir, log, feedback)
  if status.missing_submodules:
    repair_submodules(basedir, log, feedback)

  remaining = install_check.run_install_check(basedir)
  if remaining:
    log("la instalación SIGUE INCOMPLETA:")
    for problem in remaining:
      log("  " + problem)
    log("arreglo manual por SSH:  cd /data/openpilot && git lfs pull && git submodule update --init --recursive && sudo reboot")
  else:
    log("instalación REPARADA; sigue el arranque normal")
  return remaining


def main() -> int:
  log = Log()
  feedback = Feedback(enabled=spinner_enabled())
  # launch_chffrplus.sh nos envuelve en `timeout`: si nos mata, cerramos el spinner
  # para no dejarlo pintado encima del spinner del build.
  signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
  try:
    repair(BASEDIR, log, feedback)
  except BaseException as e:  # noqa: B036 -- aquí sí: este script no puede romper el arranque
    try:
      log(f"error inesperado en la auto-reparación (se ignora): {e!r}")
    except Exception:
      pass
  finally:
    feedback.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
