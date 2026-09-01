#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import glob
import os

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
# Un puntero LFS son ~130 bytes de texto; cualquier modelo real pesa >> 1 KB.
_LFS_POINTER_MAX_SIZE = 1024

# Patrones de modelos que modeld/dmonitoringd necesitan en el dispositivo.
_MODEL_GLOBS = (
  "selfdrive/modeld/models/*.onnx",
  "selfdrive/modeld/models/*.pkl",
  "selfdrive/modeld/models/*.chunk*",
  "selfdrive/monitoring/assets/*.onnx",
)


def _is_lfs_pointer(path: str) -> bool:
  try:
    if os.path.getsize(path) > _LFS_POINTER_MAX_SIZE:
      return False
    with open(path, "rb") as f:
      return f.read(len(_LFS_POINTER_PREFIX)) == _LFS_POINTER_PREFIX
  except OSError:
    return False


def run_install_check() -> list[str]:
  """Devuelve la lista de problemas de instalación detectados (vacía = OK)."""
  problems: list[str] = []

  # 1) Submódulos
  missing = [name for sentinel, name in _SUBMODULE_SENTINELS.items()
             if not os.path.exists(os.path.join(_BASEDIR, sentinel))]
  if missing:
    problems.append(
      "Submódulos sin inicializar: " + ", ".join(missing) +
      ". Ejecuta: git submodule update --init --recursive")

  # 2) Punteros LFS sin descargar
  pointers = []
  for pattern in _MODEL_GLOBS:
    for path in glob.glob(os.path.join(_BASEDIR, pattern)):
      if _is_lfs_pointer(path):
        pointers.append(os.path.relpath(path, _BASEDIR))
  if pointers:
    shown = ", ".join(pointers[:5]) + ("…" if len(pointers) > 5 else "")
    problems.append(
      f"Modelos sin descargar de git-lfs ({len(pointers)}): {shown}. "
      "Ejecuta: git lfs pull")

  return problems


if __name__ == "__main__":
  found = run_install_check()
  print("\n".join(found) if found else "instalación OK")
