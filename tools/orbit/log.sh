#!/usr/bin/env bash
# ============================================================================
# log.sh — SIMPLE. Tras la ruta, saca TODO el log relevante a UN solo .txt
#          para pasarmelo. Un comando, un fichero. Ya esta.
#
# USO A) desde tu PC (despues de que el conductor haya hecho la ruta):
#   tools/orbit/log.sh                      # comma por USB/tethering (192.168.43.1)
#   tools/orbit/log.sh comma@192.168.1.50   # otra IP
#   KEY=~/.ssh/tu_clave tools/orbit/log.sh  # con clave SSH concreta
#
# USO B) si YA estas conectado por ssh DENTRO del comma:
#   tools/orbit/log.sh local
#
# Resultado: crea  orbit_log_<fecha>.txt  en la carpeta actual. Me lo pasas.
# ============================================================================
HOST="${1:-${HOST:-comma@192.168.43.1}}"
OUT="orbit_log_$(date +%Y%m%d_%H%M%S).txt"

SSH=(ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
[ -n "${KEY:-}" ] && SSH+=(-i "$KEY")

# --- payload: lo que se ejecuta EN el comma (local o por ssh) ---
PAYLOAD_FILE="$(mktemp 2>/dev/null || echo /tmp/orbit_payload.$$)"
cat > "$PAYLOAD_FILE" <<'REMOTE'
echo "==================== SICUEM LOG ===================="
date 2>/dev/null
echo "branch: $(cd /data/openpilot 2>/dev/null && git rev-parse --short HEAD 2>/dev/null)"
echo
echo "===== 1) DESFASE DE RELOJ (BOOTTIME-MONOTONIC) — causa #1 si > 0.8 ====="
python3 -c "import time; print('gap = %.3f s' % ((time.clock_gettime_ns(time.CLOCK_BOOTTIME)-time.monotonic_ns())/1e9))" 2>&1
echo
echo "===== 2) commIssue / process_not_running / locationd (swaglog) ====="
echo "    (la linea de commIssue lleva not_alive/not_freq_ok/invalid = el servicio que cae)"
grep -ahE 'commIssue|process_not_running|locationd|cameraMalfunction|cameraFrameRate|selfdrivedLagging' $(ls -t /data/log/swaglog.* 2>/dev/null | head -12) 2>/dev/null | tail -60
echo
echo "===== 3) Por que rechaza locationd + errores/excepciones + [Bemposta] (swaglog) ====="
echo "    (estas lineas dicen la razon EXACTA del rechazo de locationd: reloj vs otra cosa)"
grep -ahE 'off from log time|rewind threshold|kalman reset|Sensor reading ignored|Observation timestamp|Non-finite|posenet|"error"|Exception|Traceback|\[Bemposta\]|no registrado|failed timing' $(ls -t /data/log/swaglog.* 2>/dev/null | head -12) 2>/dev/null | tail -50
echo
echo "===== 4) onroadEvents de la ULTIMA ruta (locationdTemporaryError/commIssue) ====="
NEWEST=$(ls -1t /data/media/0/realdata 2>/dev/null | grep -vE '^(boot|crash)$' | head -1)
SEG=$(ls -1dt /data/media/0/realdata/${NEWEST}* 2>/dev/null | head -1)
echo "    ruta: $NEWEST   segmento: $SEG"
if [ -n "$SEG" ] && cd /data/openpilot 2>/dev/null; then
  PB=python3; [ -x .venv/bin/python3 ] && PB=.venv/bin/python3
  PYTHONPATH=/data/openpilot $PB selfdrive/debug/count_events.py "$SEG/qlog.zst" 2>/dev/null \
    | grep -iE 'locationdTemporaryError|commIssue|posenetInvalid|paramsd|cameraFrameRate|Total' \
    || echo "    (count_events no disponible aqui; con las secciones 1-3 me basta)"
  echo
  echo "===== 5) procesos que deberian correr y NO corren ====="
  PYTHONPATH=/data/openpilot $PB -c "import cereal.messaging as m; sm=m.SubMaster(['managerState']); [sm.update(1000) for _ in range(6)]; nr=[p.name for p in sm['managerState'].processes if p.shouldBeRunning and not p.running]; print('    NOT_RUNNING:', nr if nr else 'ninguno (todos vivos)')" 2>/dev/null \
    || echo "    (n/d)"
else
  echo "    (no hay ruta o no esta /data/openpilot; con secciones 1-3 me basta)"
fi
echo "==================== FIN ===================="
REMOTE

if [ "$HOST" = "local" ]; then
  echo "Recogiendo log EN ESTE dispositivo (modo local)..."
  bash "$PAYLOAD_FILE" > "$OUT" 2>&1
  RC=$?
else
  echo "Conectando a $HOST y recogiendo el log (unos segundos)..."
  "${SSH[@]}" "$HOST" 'bash -s' < "$PAYLOAD_FILE" > "$OUT" 2>&1
  RC=$?
fi
rm -f "$PAYLOAD_FILE"

if ! grep -q "SICUEM LOG" "$OUT" 2>/dev/null; then
  echo "ERROR: no se pudo conectar/recoger (rc=$RC). Revisa HOST/KEY (o usa 'local' dentro del comma)."
  echo "Salida parcial guardada en: $OUT"
else
  echo "Listo -> $OUT"
  echo "Pasame ese fichero .txt y te digo la causa exacta."
fi
