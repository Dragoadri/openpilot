#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_route_logs.py — VEREDICTO offline de por qué OP se desactiva al enganchar
(commIssue / locationdTemporaryError) a partir de una RUTA YA GRABADA en el comma.

Flujo previsto:
  1) El conductor hace una ruta e intenta enganchar OP (se reproduce el fallo).
  2) Mas tarde sacas los logs del comma (tools/orbit/grab_orbit_logs.sh pull).
  3) Corres ESTE script sobre el/los segmento(s) descargado(s) -> te dice la causa.

Uso (en tu PC, dentro del repo openpilot):
  PYTHONPATH=. python3 tools/orbit/analyze_route_logs.py <ruta_a_segmento_o_rlog/qlog> [...]
  # acepta un directorio de segmento (busca rlog.zst/qlog.zst dentro) o ficheros sueltos.

Que mira y por que:
  - Desfase de reloj sensord<->camara: accel/gyro (sensord) vs cameraOdometry.timestampEof
    (camara=BOOTTIME) usando logMonoTime (BOOTTIME de loggerd) como referencia. Si sensord
    sella en MONOTONIC y el comma suspendio, el skew de accel sera GRANDE (>0.8s) = el bug
    que rechaza toda muestra de IMU en locationd -> inputsOK=False -> locationdTemporaryError.
  - livePose.inputsOK / posenetOK / sensorsOK: aisla si el fallo es de ENTRADAS (reloj) vs
    de movimiento/poses.
  - onroadEvents: cuenta locationdTemporaryError / commIssue / posenetInvalid y cuando aparecen.
  - Frecuencias de modelV2 / cameraOdometry / livePose: si modelV2/cameraOdometry caen <16Hz
    -> commIssueAvgFreq (carga de modeld), causa secundaria.
"""
import os
import sys
import statistics
from collections import Counter, defaultdict

try:
  from openpilot.tools.lib.logreader import LogReader, ReadMode  # noqa: F401
  from openpilot.selfdrive.test.process_replay.migration import migrate_all
except Exception as e:
  print(f"ERROR importando LogReader: {e}\nEjecuta con: PYTHONPATH=. python3 tools/orbit/analyze_route_logs.py <seg>")
  sys.exit(2)


def expand_paths(args):
  paths = []
  for a in args:
    if os.path.isdir(a):
      for name in ("rlog.zst", "rlog", "qlog.zst", "qlog"):
        p = os.path.join(a, name)
        if os.path.exists(p):
          paths.append(p)
    elif os.path.exists(a):
      paths.append(a)
    else:
      print(f"  (aviso) no existe: {a}")
  return paths


def main():
  if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

  paths = expand_paths(sys.argv[1:])
  if not paths:
    print("No hay ficheros de log que analizar.")
    sys.exit(1)

  print(f"Analizando: {paths}\n")

  accel_skew = []   # logMonoTime - accelerometer.timestamp   (s)
  gyro_skew = []    # logMonoTime - gyroscope.timestamp        (s)
  cam_skew = []     # logMonoTime - cameraOdometry.timestampEof(s)
  livepose = Counter()           # 'inputsOK_true'/'inputsOK_false'/...
  events = Counter()             # onroadEvent name -> count
  event_first_t = {}             # onroadEvent name -> primer t (s rel)
  msg_count = Counter()          # which() -> count (para Hz)
  alert_changes = []             # (t, alertType)
  t0 = None
  t1 = None

  for path in paths:
    try:
      lr = LogReader(path)
    except Exception as e:
      print(f"  (no pude abrir {path}: {e})")
      continue
    try:
      it = migrate_all(lr)
    except Exception:
      it = lr
    for msg in it:
      try:
        w = msg.which()
        lmt = msg.logMonoTime / 1e9
        if t0 is None or lmt < t0:
          t0 = lmt
        if t1 is None or lmt > t1:
          t1 = lmt
        msg_count[w] += 1

        if w == 'accelerometer':
          accel_skew.append(lmt - msg.accelerometer.timestamp / 1e9)
        elif w == 'gyroscope':
          gyro_skew.append(lmt - msg.gyroscope.timestamp / 1e9)
        elif w == 'cameraOdometry':
          cam_skew.append(lmt - msg.cameraOdometry.timestampEof / 1e9)
        elif w == 'livePose':
          lp = msg.livePose
          livepose['inputsOK_true' if lp.inputsOK else 'inputsOK_false'] += 1
          livepose['posenetOK_true' if lp.posenetOK else 'posenetOK_false'] += 1
          livepose['sensorsOK_true' if lp.sensorsOK else 'sensorsOK_false'] += 1
        elif w == 'onroadEvents':
          rel = lmt - t0
          for e in msg.onroadEvents:
            n = str(e.name)
            events[n] += 1
            if n not in event_first_t:
              event_first_t[n] = rel
        elif w == 'selfdriveState':
          at = msg.selfdriveState.alertType
          if not alert_changes or alert_changes[-1][1] != at:
            alert_changes.append((lmt - t0, at))
      except Exception:
        continue

  dur = (t1 - t0) if (t0 is not None and t1 is not None) else 0.0

  def med(xs):
    return statistics.median(xs) if xs else float('nan')

  sk_acc = med(accel_skew)
  sk_gyr = med(gyro_skew)
  sk_cam = med(cam_skew)

  print("=" * 70)
  print(f"Duracion analizada: {dur:.1f}s")
  print("-" * 70)
  print("[1] DESFASE DE RELOJ (skew = logMonoTime[BOOTTIME] - timestamp del mensaje)")
  print(f"    accelerometer skew  = {sk_acc:.3f} s   (n={len(accel_skew)})")
  print(f"    gyroscope     skew  = {sk_gyr:.3f} s   (n={len(gyro_skew)})")
  print(f"    cameraOdometry skew = {sk_cam:.3f} s   (n={len(cam_skew)})")
  mismatch = (sk_acc - sk_cam) if (accel_skew and cam_skew) else float('nan')
  print(f"    -> mismatch accel-vs-camara = {mismatch:.3f} s")

  print("-" * 70)
  print("[2] livePose")
  it_t = livepose.get('inputsOK_true', 0); it_f = livepose.get('inputsOK_false', 0)
  pt = livepose.get('posenetOK_true', 0); pf = livepose.get('posenetOK_false', 0)
  st = livepose.get('sensorsOK_true', 0); sf = livepose.get('sensorsOK_false', 0)
  tot = max(it_t + it_f, 1)
  print(f"    inputsOK:  True={it_t}  False={it_f}  ({100*it_f/tot:.0f}% False)")
  print(f"    posenetOK: True={pt}  False={pf}")
  print(f"    sensorsOK: True={st}  False={sf}")

  print("-" * 70)
  print("[3] onroadEvents relevantes (cuenta y primer instante)")
  for n in ('locationdTemporaryError', 'commIssue', 'commIssueAvgFreq', 'posenetInvalid',
            'paramsdTemporaryError', 'cameraMalfunction', 'cameraFrameRate', 'sensorDataInvalid',
            'processNotRunning', 'selfdrivedLagging'):
    if events.get(n):
      print(f"    {n:26s} x{events[n]:<6d} primer@ {event_first_t.get(n, -1):.1f}s")
  if not any(events.get(n) for n in ('locationdTemporaryError', 'commIssue', 'commIssueAvgFreq')):
    print("    (no se registraron commIssue/locationdTemporaryError en este segmento)")

  print("-" * 70)
  print("[4] Frecuencias (deben ser ~20Hz modelV2/cameraOdometry/livePose)")
  for n in ('modelV2', 'cameraOdometry', 'livePose', 'accelerometer', 'gyroscope', 'controlsState', 'carState'):
    hz = msg_count.get(n, 0) / dur if dur > 0 else 0
    flag = "  <-- BAJO" if (n in ('modelV2', 'cameraOdometry') and 0 < hz < 16) else ""
    print(f"    {n:16s} {hz:6.1f} Hz{flag}")

  print("=" * 70)
  print("VEREDICTO:")
  verdict = []
  if accel_skew and abs(sk_acc) > 0.8 and (not cam_skew or abs(sk_cam) < 0.5):
    verdict.append(
      f"  >>> CAUSA #1 CONFIRMADA: sensord sella en MONOTONIC y va {sk_acc:.1f}s descolgado de la\n"
      f"      camara (BOOTTIME). locationd rechaza toda muestra de IMU -> inputsOK=False.\n"
      f"      El fix (sensord -> CLOCK_BOOTTIME) lo resuelve.")
  elif accel_skew and abs(mismatch) > 0.8:
    verdict.append(
      f"  >>> CAUSA #1 PROBABLE: desfase accel-vs-camara = {mismatch:.1f}s (>0.8). Apunta al reloj de sensord.")
  if it_f > it_t and pt >= pf and st >= sf:
    verdict.append(
      "  >>> livePose.inputsOK mayormente False con posenet/sensors OK = fallo de ENTRADAS/RELOJ,\n"
      "      no de movimiento. Coherente con la causa #1.")
  low_model = (msg_count.get('modelV2', 0) / dur if dur > 0 else 0)
  if 0 < low_model < 16:
    verdict.append(
      f"  >>> CAUSA #2: modelV2 a {low_model:.1f}Hz (<16) -> commIssueAvgFreq. modeld no mantiene 20Hz;\n"
      "      revisar carga de los hilos MQTT/camara dentro del proceso manager.")
  if events.get('processNotRunning'):
    verdict.append("  >>> Hay processNotRunning: algun proceso gestionado se cayo/no arranco (ver swaglog).")
  if not verdict:
    verdict.append(
      "  >>> No se confirma la causa #1 (reloj) ni #2 (freq) en este segmento. Mira [3] y el swaglog\n"
      "      (commIssue array not_alive/not_freq_ok) para ver QUE servicio cae, y pasamelo.")
  print("\n".join(verdict))
  print("=" * 70)


if __name__ == "__main__":
  main()
