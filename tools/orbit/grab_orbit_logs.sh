#!/usr/bin/env bash
# ============================================================================
# grab_orbit_logs.sh
#   Extrae del comma (por SSH) los logs que muestran POR QUE se desactiva OP:
#     - "Communication Issue Between Processes"  -> evento commIssue
#     - "locationd - Temporary Error"            -> evento locationdTemporaryError
#
#   El evento commIssue que escribe selfdrived (selfdrived.py:418) incluye los
#   arrays not_alive / not_freq_ok / invalid -> dice EXACTAMENTE que servicio
#   (y por tanto que proceso) llego tarde en el instante de la desactivacion.
#   Esa es la pista decisiva para confirmar/afinar el fix de contension de I/O.
#
# USO:
#   tools/orbit/grab_orbit_logs.sh pull            # modo offline (tras reproducir el fallo)
#   tools/orbit/grab_orbit_logs.sh live            # modo en vivo (mientras reproduces)
#   tools/orbit/grab_orbit_logs.sh pull comma@IP   # host explicito
#
# VARIABLES DE ENTORNO (opcionales):
#   HOST=comma@192.168.43.1   Host SSH. Tethering USB -> 192.168.43.1.
#                             comma prime -> usar  HOST=comma-<dongleid>  (proxy ssh.comma.ai)
#   KEY=~/.ssh/mi_github_key  Clave privada SSH (la que registraste en el comma).
#   PORT=22                   Puerto SSH.
#   OUTDIR=./orbit_logs      Carpeta local de salida (modo pull).
#   SECS=40                   Duracion de captura en modo live (segundos).
# ============================================================================
set -uo pipefail

MODE="${1:-pull}"
HOST="${2:-${HOST:-comma@192.168.43.1}}"
PORT="${PORT:-22}"
OUTDIR="${OUTDIR:-./orbit_logs/$(date +%Y%m%d_%H%M%S)}"
SECS="${SECS:-40}"
REMOTE_OP="/data/openpilot"

SSH_OPTS=(-p "$PORT" -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
if [ -n "${KEY:-}" ]; then SSH_OPTS+=(-i "$KEY"); fi

ssh_do()  { ssh "${SSH_OPTS[@]}" "$HOST" "$@"; }
# rsync sobre el mismo ssh (puerto/clave)
RSH="ssh ${SSH_OPTS[*]}"

banner() { printf '\n\033[1;36m==== %s ====\033[0m\n' "$*"; }
err()    { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }

check_conn() {
  banner "Probando conexion SSH a $HOST"
  if ! ssh_do "echo conectado_ok" 2>/dev/null | grep -q conectado_ok; then
    err "No se pudo conectar a $HOST por SSH (puerto $PORT)."
    err "  - Tethering USB: el comma suele ser 192.168.43.1"
    err "  - comma prime:   HOST=comma-<dongleid> (config ssh.comma.ai)"
    err "  - Clave:         KEY=~/.ssh/tu_clave (la registrada en Settings del comma)"
    exit 1
  fi
  echo "OK"
}

# ----------------------------------------------------------------------------
pull_mode() {
  mkdir -p "$OUTDIR/swaglog" "$OUTDIR/route"
  check_conn

  banner "1/4  swaglog (logs de texto: commIssue, process_not_running, [Bemposta])"
  # swaglog son ficheros JSON-por-linea en /data/log/swaglog.NNNNNNNNNN. Traemos los
  # ultimos por mtime (los mas recientes) para no descargar miles.
  ssh_do "ls -1t /data/log/swaglog.* 2>/dev/null | head -n 8" > "$OUTDIR/swaglog_list.txt" || true
  if [ -s "$OUTDIR/swaglog_list.txt" ]; then
    # rsync de la lista
    while read -r f; do
      [ -n "$f" ] && rsync -az -e "$RSH" "$HOST:$f" "$OUTDIR/swaglog/" 2>/dev/null || true
    done < "$OUTDIR/swaglog_list.txt"
  else
    err "No se encontraron swaglog en /data/log/ (¿el comma esta onroad/encendido?)."
  fi

  banner "2/4  Eventos relevantes en swaglog (analisis LOCAL, no carga el comma)"
  if ls "$OUTDIR/swaglog/"* >/dev/null 2>&1; then
    # Lineas crudas con los marcadores. swaglog puede estar comprimido o no.
    cat "$OUTDIR/swaglog/"* 2>/dev/null \
      | grep -aE 'commIssue|process_not_running|locationd|Bemposta|exception|cameraMalfunction|selfdrivedLagging' \
      > "$OUTDIR/eventos_swaglog.txt" || true
    echo "  -> $OUTDIR/eventos_swaglog.txt ($(wc -l < "$OUTDIR/eventos_swaglog.txt" 2>/dev/null || echo 0) lineas)"
    # Pretty-print de los commIssue: extraer not_alive / not_freq_ok / invalid.
    python3 - "$OUTDIR/eventos_swaglog.txt" > "$OUTDIR/commissue_resumen.txt" 2>/dev/null <<'PY' || true
import json, sys
src = sys.argv[1]
print("Resumen de commIssue (servicio que llego tarde -> proceso culpable):")
print("  carControl/controlsState -> controlsd | carState/carOutput -> card")
print("  modelV2/cameraOdometry -> modeld | livePose -> locationd | *sensor* -> sensord\n")
n=0
for line in open(src, errors='ignore'):
    if 'commIssue' not in line:
        continue
    try:
        # cada linea de swaglog es un JSON; el msg puede llevar los arrays
        obj = json.loads(line)
    except Exception:
        # buscar el primer { ... } de la linea
        i=line.find('{');
        try: obj=json.loads(line[i:])
        except Exception:
            print("RAW:", line.strip()[:300]); n+=1; continue
    msg = obj.get('msg', obj)
    na = msg.get('not_alive') if isinstance(msg, dict) else None
    nf = msg.get('not_freq_ok') if isinstance(msg, dict) else None
    iv = msg.get('invalid') if isinstance(msg, dict) else None
    ts = obj.get('created') or obj.get('time') or ''
    print(f"[{ts}] not_alive={na} not_freq_ok={nf} invalid={iv}")
    n+=1
print(f"\nTotal commIssue encontrados: {n}")
PY
    echo "  -> $OUTDIR/commissue_resumen.txt"
    echo
    sed -n '1,40p' "$OUTDIR/commissue_resumen.txt" 2>/dev/null || true
  fi

  banner "3/4  Desfase de reloj (env-free) + VEREDICTO de la ruta"
  # (a) Chequeo ENV-FREE del desfase BOOTTIME-MONOTONIC: solo stdlib, NUNCA falla por entorno.
  #     Es la prueba directa de la causa #1 (sensord MONOTONIC vs camara BOOTTIME tras suspender).
  echo "  -> Desfase de reloj actual en el comma (causa #1 si > 0.8):"
  ssh_do "python3 -c \"import time; g=(time.clock_gettime_ns(time.CLOCK_BOOTTIME)-time.monotonic_ns())/1e9; print('     gap BOOTTIME-MONOTONIC = %.3f s'%g); print('     >>> >0.8 = sensord descolgado de la camara -> locationdTemporaryError. El fix lo resuelve.' if g>0.8 else '     >>> ~0 = sin suspension ahora; si aun asi falla, la causa no es el reloj (mira el commIssue array).')\"" \
      | tee "$OUTDIR/gap_reloj.txt" || echo "     (no se pudo medir el gap)"

  # locationdTemporaryError NO sale en swaglog: solo como onroadEvent en el route log.
  # El analisis (LogReader/capnp) se ejecuta EN EL COMMA. Probamos el python del venv de
  # openpilot (.venv) y, si no, python3 del sistema. Si ninguno tiene capnp, quedan los
  # rlog/qlog descargados para re-analizar en tu PC con el entorno openpilot activado.
  NEWEST=$(ssh_do "ls -1t /data/media/0/realdata 2>/dev/null | grep -vE '^(boot|crash)$' | head -n 1" 2>/dev/null | tr -d '\r')
  if [ -n "$NEWEST" ]; then
    echo "  Ruta mas reciente: $NEWEST"
    SEGS=$(ssh_do "ls -1dt /data/media/0/realdata/${NEWEST}* 2>/dev/null | head -n 2 | tr '\n' ' '" 2>/dev/null | tr -d '\r')
    echo "  Segmentos: $SEGS"

    echo "  -> VEREDICTO (analyze_route_logs.py en el comma; puede tardar ~30-60s)..."
    ssh_do "cd $REMOTE_OP && { [ -x .venv/bin/python3 ] && PB=.venv/bin/python3 || PB=python3; }; PYTHONPATH=$REMOTE_OP \$PB tools/orbit/analyze_route_logs.py $SEGS 2>&1" \
      | tee "$OUTDIR/veredicto.txt" \
      || echo "    (analyze fallo en el comma; abajo quedan rlog/qlog para analizar en local)"

    echo "  -> onroadEvents (count_events en el comma)..."
    LAST1=$(echo "$SEGS" | awk '{print $1}')
    ssh_do "cd $REMOTE_OP && { [ -x .venv/bin/python3 ] && PB=.venv/bin/python3 || PB=python3; }; PYTHONPATH=$REMOTE_OP \$PB selfdrive/debug/count_events.py ${LAST1}/qlog.zst 2>/dev/null" \
      | grep -iE 'locationdTemporaryError|commIssue|posenetInvalid|alertType|paramsd|Total|cameraFrameRate' \
      | tee "$OUTDIR/onroad_events.txt" || true

    echo "  -> Archivando rlog/qlog en local (por si re-analizas)..."
    for seg in $SEGS; do
      base=$(basename "$seg")
      mkdir -p "$OUTDIR/route/$base"
      rsync -az -e "$RSH" "$HOST:$seg/rlog.zst" "$OUTDIR/route/$base/" 2>/dev/null || true
      rsync -az -e "$RSH" "$HOST:$seg/qlog.zst" "$OUTDIR/route/$base/" 2>/dev/null || true
    done
  else
    err "No se hallaron rutas en /data/media/0/realdata."
  fi

  banner "LISTO. Carpeta de salida: $OUTDIR"
  echo "Mira primero:  $OUTDIR/veredicto.txt  (causa)  y  $OUTDIR/commissue_resumen.txt  (servicio que cae)"
  echo "Comando util extra (ver el JSON exacto con fichero:linea):"
  echo "  PYTHONPATH=. python3 selfdrive/debug/filter_log_message.py --level ERROR $OUTDIR/route/*/"
}

# ----------------------------------------------------------------------------
live_mode() {
  mkdir -p "$OUTDIR"
  check_conn
  banner "Captura EN VIVO durante ${SECS}s — REPRODUCE EL FALLO AHORA (activa OP)"
  echo "Salida -> $OUTDIR/  (Ctrl-C para cortar antes)"

  # a) stream de errores de swaglog (incluye el JSON de commIssue con fichero:linea)
  ( timeout "$SECS" ssh_do "cd $REMOTE_OP && PYTHONPATH=$REMOTE_OP python3 selfdrive/debug/filter_log_message.py --level ERROR 2>&1" \
      | while IFS= read -r l; do printf '%s %s\n' "$(date +%H:%M:%S)" "$l"; done \
      | tee "$OUTDIR/live_errors.txt" ) &
  PID_ERR=$!

  # b) frecuencias reales por servicio (mapea directo a not_freq_ok / not_alive)
  ( timeout "$SECS" ssh_do "cd $REMOTE_OP && PYTHONPATH=$REMOTE_OP python3 selfdrive/debug/check_freq.py 2>&1" \
      | tee "$OUTDIR/live_freq.txt" ) &
  PID_FREQ=$!

  # c) CPU por proceso (confirma starvation de sensord/modeld/locationd/controlsd)
  ( timeout "$SECS" ssh_do "cd $REMOTE_OP && PYTHONPATH=$REMOTE_OP python3 selfdrive/debug/cpu_usage_stat.py 2>&1" \
      | tee "$OUTDIR/live_cpu.txt" ) &
  PID_CPU=$!

  # d) eventos onroad + estado en vivo (locationdTemporaryError aparece aqui)
  ( timeout "$SECS" ssh_do "cd $REMOTE_OP && PYTHONPATH=$REMOTE_OP python3 selfdrive/debug/dump.py onroadEvents selfdriveState 2>&1" \
      | tee "$OUTDIR/live_onroad.txt" ) &
  PID_DUMP=$!

  wait $PID_ERR $PID_FREQ $PID_CPU $PID_DUMP 2>/dev/null || true
  banner "Captura terminada. Revisa:"
  echo "  $OUTDIR/live_errors.txt   (commIssue con fichero:linea + arrays)"
  echo "  $OUTDIR/live_freq.txt     (Hz reales: el servicio por debajo = el que cae)"
  echo "  $OUTDIR/live_cpu.txt      (CPU por proceso)"
  echo "  $OUTDIR/live_onroad.txt   (onroadEvents/selfdriveState: locationdTemporaryError)"
}

case "$MODE" in
  pull) pull_mode ;;
  live) live_mode ;;
  *) err "Modo desconocido: '$MODE'. Usa 'pull' o 'live'."; exit 2 ;;
esac
