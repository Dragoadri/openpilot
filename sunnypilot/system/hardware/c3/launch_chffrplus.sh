#!/usr/bin/env bash

SP_C3_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
DIR="$( cd "$SP_C3_DIR/../../../.." >/dev/null 2>&1 && pwd )"

source "$SP_C3_DIR/launch_env.sh"

function agnos_init {
  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta

  # set success flag for current boot slot
  sudo abctl --set_success

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
}

function agnos_update {
  # Check if AGNOS update is required
  if [ $(< /VERSION) != "$AGNOS_VERSION" ]; then
    AGNOS_PY="$DIR/system/hardware/tici/agnos.py"
    # [ORBIT] manifiesto de AGNOS 18.4 (el mismo del 3X); el agnos.json de este
    # directorio es el de 12.8 y se conserva solo como referencia.
    MANIFEST="$DIR/system/hardware/tici/agnos.json"
    # [ORBIT] Fase narrada en pantalla y con cortafuegos anti-bucle (orbit/agnos_update.py).
    # Si el script no esta, se hace exactamente lo que hacia upstream.
    if [ -f "$DIR/orbit/agnos_update.py" ]; then
      python3 "$DIR/orbit/agnos_update.py" "$AGNOS_PY" "$MANIFEST" "$AGNOS_VERSION" || true
    else
      if $AGNOS_PY --verify $MANIFEST; then
        sudo reboot
      fi
      $DIR/system/hardware/tici/updater $AGNOS_PY $MANIFEST
    fi
  else
    rm -f /data/orbit_agnos_attempts.json
  fi
}

# [ORBIT] Registro persistente del arranque (/data/orbit_boot.log): una linea por
# fase. Si el arranque muere, failsafe_screen.py lo ensena en pantalla.
function orbit_log {
  if [ -f "$DIR/orbit/boot_log.py" ]; then
    python3 "$DIR/orbit/boot_log.py" "$@" || true
  else
    echo "[ORBIT boot] $*"
  fi
}

function launch {
  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f $DIR/.git/index.lock

  # Check to see if there's a valid overlay-based update available. Conditions
  # are as follows:
  #
  # 1. The DIR init file has to exist, with a newer modtime than anything in
  #    the DIR Git repo. This checks for local development work or the user
  #    switching branches/forks, which should not be overwritten.
  # 2. The FINALIZED consistent file has to exist, indicating there's an update
  #    that completed successfully and synced to disk.

  if [ -f "${DIR}/.overlay_init" ]; then
    find ${DIR}/.git -newer ${DIR}/.overlay_init | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d /data/safe_staging/old_openpilot ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"

          mv $DIR /data/safe_staging/old_openpilot
          mv "${STAGING_ROOT}/finalized" $DIR
          cd $DIR

          echo "Restarting launch script ${LAUNCHER_LOCATION}"
          unset AGNOS_VERSION
          exec "${LAUNCHER_LOCATION}"
        else
          echo "openpilot backup found, not updating"
          # TODO: restore backup? This means the updater didn't start after swapping
        fi
      fi
    fi
  fi

  # handle pythonpath
  ln -sfn $(pwd) /data/pythonpath
  export PYTHONPATH="$PWD"

  # [ORBIT] Baliza de arranque: durante 30 min emite por UDP/WiFi el estado del
  # dispositivo (fase, procesos, tmux, AGNOS) para verlo desde un PC cuando la
  # pantalla se queda en el logo. Segundo plano, nunca bloquea (orbit/boot_beacon.py).
  if [ -f "$DIR/orbit/boot_beacon.py" ]; then
    (python3 "$DIR/orbit/boot_beacon.py" >/dev/null 2>&1 &) || true
  fi

  orbit_log "arranque comma 3: commit $(git -C "$DIR" rev-parse --short HEAD 2>/dev/null) | AGNOS del dispositivo: $(cat /VERSION 2>/dev/null) | exigido: $AGNOS_VERSION"

  # hardware specific init
  if [ -f /AGNOS ]; then
    agnos_init
    orbit_log "agnos_init OK"
  fi

  # [ORBIT] Auto-reparacion de la instalacion (orbit/install_repair.py), igual
  # que en el launch_chffrplus.sh de la raiz (comma 3X): solo actua si hay
  # punteros git-lfs o submodulos vacios, informa por el spinner y acota la red
  # con timeout. Va ANTES de agnos_update porque el `updater` es un fichero LFS.
  if [ -f "$DIR/orbit/install_repair.py" ]; then
    timeout -k 15 1800 python3 "$DIR/orbit/install_repair.py" || true
  fi

  if [ -f /AGNOS ]; then
    agnos_update
    orbit_log "agnos_update terminado sin reiniciar"
  fi

  # write tmux scrollback to a file
  tmux capture-pane -pq -S-1000 > /tmp/launch_log

  # start manager
  cd $DIR/system/manager
  if [ ! -f $DIR/prebuilt ]; then
    orbit_log "build.py: inicio"
    ./build.py
    orbit_log "build.py: terminado rc=$?"
  fi
  orbit_log "manager.py: inicio"
  ./manager.py
  orbit_log "manager.py: terminado rc=$?"

  # if broken, keep on screen error
  # [ORBIT] ...y ensenar el registro del arranque en pantalla (solo pyray).
  if [ -f "$DIR/orbit/failsafe_screen.py" ]; then
    python3 "$DIR/orbit/failsafe_screen.py" /data/orbit_boot.log /tmp/launch_log || true
  fi
  while true; do sleep 1; done
}

launch
