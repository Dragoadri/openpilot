#!/usr/bin/env bash

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

# [ORBIT] El arbol de 2026 obtiene sus librerias C (acados, capnproto, zeromq...)
# de paquetes Python del venv de AGNOS >= 17; en AGNOS 12.8 (el pin original de
# sunnypilot para el comma 3, hoy abandonado) scons no puede ni empezar. Se usa
# el mismo AGNOS que el comma 3X. EXPERIMENTAL: fuera de lo validado por comma.
if [ -z "$AGNOS_VERSION" ]; then
  export AGNOS_VERSION="18.4"
fi

export STAGING_ROOT="/data/safe_staging"
