#!/usr/bin/env bash
# Auto-reparacion de la instalacion ORBIT en el arranque del dispositivo.
#
# EL FALLO QUE CIERRA
#
# El instalador de software custom del comma clona el repo, pero no garantiza
# un `git lfs pull`. Y en este fork .gitattributes marca como LFS mucho mas que
# los modelos: *.ttf, *.png, *.wav y system/hardware/tici/updater. Ademas
# .lfsconfig apunta el endpoint al GitLab publico de sunnypilot y NO a GitHub
# --el push del fork va con --no-verify, asi que en GitHub no hay ni un objeto
# LFS--, de modo que el coche tiene que ir a buscarlos a un tercero.
#
# Cuando eso no ocurre, en /data/openpilot quedan punteros de ~130 bytes donde
# deberian estar las FUENTES y los ICONOS de la UI. Sin fuentes la UI no
# arranca: la pantalla se queda con el logo del comma para siempre, sin menu y
# sin ajustes. Y ahi esta lo peor: install_check.py sabe detectar exactamente
# esto, pero avisa por una alerta offroad que pinta... la UI que no ha podido
# arrancar. El unico diagnostico que teniamos era inalcanzable justo cuando
# hacia falta.
#
# Por eso esto corre ANTES de compilar, desde launch_chffrplus.sh, y no depende
# de nada grafico: escribe por stdout, que acaba en el log de tmux y en
# /tmp/launch_log, y deja copia en /tmp/orbit_install_repair.log.
#
# DOS REGLAS QUE NO SE NEGOCIAN
#
#   1. NUNCA devuelve error. Este script no puede ser el motivo de que un coche
#      no arranque; si no sabe arreglar algo, lo dice y se aparta.
#   2. Todo lo que toca la red va con timeout. Un `git lfs pull` colgado en un
#      garaje sin cobertura dejaria el arranque esperando indefinidamente, que
#      es exactamente el sintoma que este script existe para quitar.
#
# En una instalacion sana el coste es una ejecucion de python de unos ms: si el
# chequeo pasa, no se ejecuta ni un comando mas.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG=/tmp/orbit_install_repair.log

log() { echo "[ORBIT repair] $*" | tee -a "$LOG"; }

cd "$DIR" || exit 0

# Camino rapido: instalacion sana, no se toca nada.
if python3 orbit/install_check.py >/dev/null 2>&1; then
  exit 0
fi

log "instalacion incompleta detectada:"
python3 orbit/install_check.py 2>&1 | sed 's/^/[ORBIT repair]   /' | tee -a "$LOG"

if [ ! -d .git ]; then
  log "no hay repositorio git aqui: hay que reinstalar a mano"
  exit 0
fi

# --- objetos LFS -------------------------------------------------------------
if git lfs version >/dev/null 2>&1; then
  log "descargando objetos git-lfs desde $(git config --get lfs.url || echo 'el remoto por defecto')"
  log "son varios cientos de MB: puede tardar entre 5 y 20 minutos con wifi"
  # --local: escribe los filtros en .git/config de ESTE clon y no en el
  # ~/.gitconfig del sistema, que en AGNOS es de solo lectura segun el arranque.
  timeout 300 git lfs install --local >>"$LOG" 2>&1
  if timeout 1800 git lfs pull >>"$LOG" 2>&1; then
    log "git lfs pull: OK"
  else
    log "git lfs pull: FALLO (¿sin red, o GitLab inaccesible?). Detalle en $LOG"
  fi
else
  log "git-lfs NO esta disponible en el dispositivo: no se pueden traer modelos ni assets"
fi

# --- submodulos --------------------------------------------------------------
if [ -f .gitmodules ]; then
  log "sincronizando submodulos..."
  if timeout 900 git submodule update --init --recursive >>"$LOG" 2>&1; then
    log "submodulos: OK"
  else
    log "submodulos: FALLO. Detalle en $LOG"
  fi
fi

# --- veredicto ---------------------------------------------------------------
if python3 orbit/install_check.py >/dev/null 2>&1; then
  log "instalacion REPARADA; sigue el arranque normal"
else
  log "la instalacion SIGUE INCOMPLETA:"
  python3 orbit/install_check.py 2>&1 | sed 's/^/[ORBIT repair]   /' | tee -a "$LOG"
  log "arreglo manual por SSH:  cd /data/openpilot && git lfs pull && git submodule update --init --recursive && sudo reboot"
fi

exit 0
