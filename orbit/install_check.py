#!/usr/bin/env python3
"""Chequeo de instalación ORBIT al arrancar manager.

Detecta los dos despliegues rotos más comunes en el comma 3X, que antes se
manifestaban como dashcam mode o procesos caídos SIN ningún aviso claro:

1. Submódulos vacíos o incompletos (clon sin `--recurse-submodules`, o un
   `git pull` que dejó los submódulos atrás): faltan opendbc/msgq/panda/...
   y el build o los imports fallan.
2. Modelos sin descargar de git-lfs: los .onnx/.pkl son punteros de texto de
   ~130 bytes ("version https://git-lfs...") en vez del binario real, y modeld
   no puede arrancar.

`run_install_check()` devuelve la lista de problemas (vacía = todo OK) y
manager_init los muestra como alerta offroad Offroad_OrbitInstallIncomplete.
Es de SOLO LECTURA y nunca debe lanzar excepciones hacia manager.
"""
import fnmatch
import glob
import os
from typing import NamedTuple

# orbit/ está un nivel por debajo de la raíz del repo.
# realpath y NO abspath: en PC el paquete se importa por la granja de symlinks
# de `openpilot/` (openpilot/orbit -> ../orbit), asi que abspath dejaba el
# BASEDIR en `<repo>/openpilot`, donde no hay ningun submodulo, y el chequeo
# denunciaba los seis como ausentes en cada arranque del simulador. Es el mismo
# criterio que common/basedir.py. En el dispositivo no hay symlinks y realpath
# es un no-op.
_BASEDIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Fichero centinela por submódulo: si existe, el submódulo está inicializado.
_SUBMODULE_SENTINELS = {
  "opendbc_repo/opendbc/__init__.py": "opendbc_repo",
  "msgq_repo/msgq/__init__.py": "msgq_repo",
  "panda/python/__init__.py": "panda",
  "rednose_repo/rednose/__init__.py": "rednose_repo",
  "tinygrad_repo/tinygrad/__init__.py": "tinygrad_repo",
  "cereal/car.capnp": "cereal",
}

_LFS_POINTER_PREFIX = b"version https://git-lfs"
# Un puntero LFS son ~130 bytes de texto; cualquier fichero real pesa >> 1 KB.
_LFS_POINTER_MAX_SIZE = 1024

# Ficheros que .gitattributes marca como LFS y que el dispositivo NECESITA.
#
# No son solo los modelos: en este fork *.ttf, *.png y *.wav tambien van por
# LFS, asi que sin descargar quedan FUENTES, ICONOS y SONIDOS de la UI en 130
# bytes. Y sin fuentes la UI NO ARRANCA: el coche se queda en el logo, sin menu
# y sin ajustes -- es decir, sin ningun sitio donde mostrar la alerta offroad
# que genera este mismo chequeo. Por eso los assets de UI cuentan como problema
# de instalacion igual que los modelos, y por eso install_repair.py lo usa
# desde el arranque, antes de que exista UI alguna.
_LFS_GLOBS = (
  # Modelos: sin ellos modeld no arranca ("openpilot unavailable").
  "selfdrive/modeld/models/*.onnx",
  "selfdrive/modeld/models/*.pkl",
  "selfdrive/modeld/models/*.chunk*",
  "selfdrive/monitoring/assets/*.onnx",
  # Assets de la UI: sin ellos no hay pantalla.
  "selfdrive/assets/fonts/*.ttf",
  "selfdrive/assets/fonts/*.otf",
  "selfdrive/assets/*.png",
  "selfdrive/assets/**/*.png",
  "selfdrive/assets/sounds/*.wav",
  # Binario del actualizador de AGNOS, que launch_chffrplus.sh ejecuta en
  # agnos_init cuando la version del dispositivo no coincide con la de la rama.
  "system/hardware/tici/updater",
)

# Ficheros LFS que el comma NO usa y que por tanto ni se descargan ni cuentan
# como instalacion incompleta: los modelos big_* son solo para la GPU USB del
# banco (USBGPU) y suman 310 MB de los 437 MB totales de LFS. install_repair
# los excluye del `git lfs pull` con el mismo patron.
LFS_IGNORE_GLOBS = (
  "selfdrive/modeld/models/big_*",
)


def _is_lfs_pointer(path: str) -> bool:
  try:
    if os.path.getsize(path) > _LFS_POINTER_MAX_SIZE:
      return False
    with open(path, "rb") as f:
      return f.read(len(_LFS_POINTER_PREFIX)) == _LFS_POINTER_PREFIX
  except OSError:
    return False


class InstallStatus(NamedTuple):
  missing_submodules: list[str]  # nombres de submodulo sin inicializar
  lfs_pointers: list[str]        # rutas relativas que siguen siendo punteros git-lfs

  def ok(self) -> bool:
    return not self.missing_submodules and not self.lfs_pointers


def _ignored(rel: str) -> bool:
  return any(fnmatch.fnmatch(rel, pat) for pat in LFS_IGNORE_GLOBS)


def inspect_install(basedir: str | None = None) -> InstallStatus:
  """Estado estructurado de la instalación; install_repair decide con él QUÉ reparar."""
  basedir = basedir or _BASEDIR

  missing = [name for sentinel, name in _SUBMODULE_SENTINELS.items()
             if not os.path.exists(os.path.join(basedir, sentinel))]

  pointers: set[str] = set()
  for pattern in _LFS_GLOBS:
    for path in glob.glob(os.path.join(basedir, pattern), recursive=True):
      rel = os.path.relpath(path, basedir)
      if not _ignored(rel) and _is_lfs_pointer(path):
        pointers.add(rel)

  return InstallStatus(missing, sorted(pointers))


def run_install_check(basedir: str | None = None) -> list[str]:
  """Devuelve la lista de problemas de instalación detectados (vacía = OK)."""
  status = inspect_install(basedir)
  problems: list[str] = []

  if status.missing_submodules:
    problems.append(
      "Submódulos sin inicializar: " + ", ".join(status.missing_submodules) +
      ". Ejecuta: git submodule update --init --recursive")

  if status.lfs_pointers:
    pointers = status.lfs_pointers
    shown = ", ".join(pointers[:5]) + ("…" if len(pointers) > 5 else "")
    problems.append(f"Ficheros sin descargar de git-lfs ({len(pointers)}): {shown}. Ejecuta: git lfs pull")

  return problems


if __name__ == "__main__":
  # Codigo de salida != 0 con problemas, para poder consultarlo desde un shell
  # sin parsear texto (`python3 orbit/install_check.py && echo sano`).
  found = run_install_check()
  print("\n".join(found) if found else "instalación OK")
  raise SystemExit(1 if found else 0)
