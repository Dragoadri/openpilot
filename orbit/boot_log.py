#!/usr/bin/env python3
"""Registro persistente del arranque ORBIT.

Los scripts de arranque (launch_chffrplus.sh, agnos_update.py, install_repair.py)
dejan aquí una línea por fase, con hora. Vive en /data para sobrevivir al
reinicio: si el dispositivo se queda en el logo, la pantalla de emergencia
(failsafe_screen.py) lo muestra y el usuario puede fotografiarlo sin SSH.

Uso desde shell:   python3 orbit/boot_log.py "mensaje"
Uso desde Python:  from openpilot.orbit import boot_log; boot_log.append("mensaje")

Nunca lanza: un log que rompe el arranque es peor que no tener log.
"""
import os
import sys
import time

DEFAULT_PATH = "/data/orbit_boot.log"
FALLBACK_PATH = "/tmp/orbit_boot.log"
MAX_LINES = 400


def path() -> str:
  """Ruta del log: ORBIT_BOOT_LOG si está definida, /data si se puede escribir, si no /tmp."""
  env = os.environ.get("ORBIT_BOOT_LOG")
  if env:
    return env
  if os.path.isdir(os.path.dirname(DEFAULT_PATH)) and os.access(os.path.dirname(DEFAULT_PATH), os.W_OK):
    return DEFAULT_PATH
  return FALLBACK_PATH


def append(msg: str, log_path: str | None = None) -> None:
  """Añade una línea con hora y recorta el fichero a MAX_LINES. Nunca lanza."""
  log_path = log_path or path()
  line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg.rstrip("\n") + "\n"
  try:
    with open(log_path, "a", encoding="utf-8") as f:
      f.write(line)
  except Exception:
    return
  try:
    with open(log_path, encoding="utf-8", errors="replace") as f:
      lines = f.readlines()
    if len(lines) > MAX_LINES:
      tmp = log_path + ".tmp"
      with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines[-MAX_LINES:])
      os.replace(tmp, log_path)
  except Exception:
    pass


def tail(log_path: str, n: int) -> list[str]:
  """Últimas n líneas (sin salto final). Fichero ausente o ilegible = lista vacía."""
  try:
    with open(log_path, encoding="utf-8", errors="replace") as f:
      return [ln.rstrip("\n") for ln in f.readlines()[-n:]]
  except Exception:
    return []


if __name__ == "__main__":
  msg = " ".join(sys.argv[1:]).strip()
  if msg:
    append(msg)
    try:
      print(f"[ORBIT boot] {msg}", flush=True)
    except Exception:
      pass
  sys.exit(0)
