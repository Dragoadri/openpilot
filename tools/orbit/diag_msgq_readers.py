#!/usr/bin/env python3
"""
diag_msgq_readers.py — Diagnostico en vivo del limite de suscriptores msgq.

CONTEXTO (commIssue ~1 Hz al activar OP, rama sicuem-mig):
msgq limita cada canal a NUM_READERS=15 suscriptores. Cuando un 16º intenta
registrarse, msgq_init_subscriber() EXPULSA A TODOS (read_valids=false,
read_uids=0) y cada proceso se re-registra en su siguiente lectura perdiendo
su cola pendiente (msgq/msgq.cc, bloque "evicting all subscribers").
Con >=16 suscriptores VIVOS el ciclo es perpetuo: el ultimo en re-registrarse
(el hilo MQTT de telemetria, periodo ~1.0008 s) vuelve a desbordar el limite
cada segundo -> todos los daemons (radard, paramsd, plannerd, dmonitoringd,
torqued, lagd, calibrationd, locationd) fallan un ciclo sus checks de carState
-> publican valid=False -> selfdrived: commIssue / locationdTemporaryError.

USO (en el comma, con openpilot corriendo y coche encendido):
    cd /data/openpilot && python3 tools/orbit/diag_msgq_readers.py            # carState, 20 s
    python3 tools/orbit/diag_msgq_readers.py --service carState --dur 30
    python3 tools/orbit/diag_msgq_readers.py --service liveCalibration

Salida: registro de expulsiones (evict-all), quien se registra tras cada una
(el primero = el proceso que desbordo el limite), y tabla final de slots con
nombre de proceso/hilo. Si ves "EVICT-ALL" repetido cada ~1 s: confirmado.
"""
import argparse
import mmap
import os
import struct
import time

NUM_READERS = 15  # debe coincidir con msgq/msgq.h del build instalado
OFF_NUM_READERS = 0
OFF_WRITE_POINTER = 8
OFF_WRITE_UID = 16
OFF_READ_POINTERS = 24
OFF_READ_VALIDS = OFF_READ_POINTERS + 8 * NUM_READERS   # 144
OFF_READ_UIDS = OFF_READ_VALIDS + 8 * NUM_READERS       # 264
HEADER_SIZE = OFF_READ_UIDS + 8 * NUM_READERS           # 384


def resolve_uid(uid: int) -> str:
  """uid msgq = (rand32 << 32) | tid. Resuelve tid -> nombre de hilo y proceso."""
  if uid == 0:
    return "-"
  tid = uid & 0xFFFFFFFF
  try:
    with open(f"/proc/{tid}/comm") as f:
      thread_name = f.read().strip()
    tgid = tid
    try:
      with open(f"/proc/{tid}/status") as f:
        for line in f:
          if line.startswith("Tgid:"):
            tgid = int(line.split()[1])
            break
    except OSError:
      pass
    proc_name = thread_name
    if tgid != tid:
      try:
        with open(f"/proc/{tgid}/comm") as f:
          proc_name = f.read().strip()
      except OSError:
        pass
      return f"tid={tid} '{thread_name}' (proceso {tgid} '{proc_name}')"
    return f"pid={tid} '{thread_name}'"
  except OSError:
    return f"tid={tid} (MUERTO: slot filtrado de un proceso terminado)"


def snapshot(mm) -> tuple[int, list[int], list[int]]:
  mm.seek(0)
  buf = mm.read(HEADER_SIZE)
  n = struct.unpack_from("<Q", buf, OFF_NUM_READERS)[0]
  valids = list(struct.unpack_from(f"<{NUM_READERS}Q", buf, OFF_READ_VALIDS))
  uids = list(struct.unpack_from(f"<{NUM_READERS}Q", buf, OFF_READ_UIDS))
  return n, valids, uids


def main():
  ap = argparse.ArgumentParser(description="Monitor de suscriptores msgq (limite NUM_READERS)")
  ap.add_argument("--service", default="carState", help="canal cereal a vigilar (default: carState)")
  ap.add_argument("--dur", type=float, default=20.0, help="segundos de captura (default: 20)")
  args = ap.parse_args()

  path = f"/dev/shm/{args.service}"
  if not os.path.exists(path):
    print(f"ERROR: no existe {path}. ¿openpilot arrancado? ¿nombre de canal correcto?")
    return 1

  with open(path, "r+b") as f:
    mm = mmap.mmap(f.fileno(), HEADER_SIZE, mmap.MAP_SHARED, mmap.PROT_READ)

    t0 = time.monotonic()
    prev_n, _, prev_uids = snapshot(mm)
    print(f"== {args.service}: num_readers inicial = {prev_n} ==")
    for i, u in enumerate(prev_uids):
      if u:
        print(f"   slot {i:2d}: {resolve_uid(u)}")
    print(f"== vigilando {args.dur:.0f}s... ==")

    evictions = []      # (t, primer_registrado_tras_evict)
    registros = []      # (t, slot, uid) nuevos uids vistos
    known = set(u for u in prev_uids if u)
    evict_pending = False

    while time.monotonic() - t0 < args.dur:
      n, valids, uids = snapshot(mm)
      t = time.monotonic() - t0

      if n < prev_n:
        # num_readers solo baja en el evict-all (se pone a 0 y el evictor hace CAS a 1)
        print(f"[{t:8.3f}s] EVICT-ALL: num_readers {prev_n} -> {n}")
        evictions.append([t, None])
        evict_pending = True

      for i in range(NUM_READERS):
        u = uids[i]
        if u and u != prev_uids[i]:
          nombre = resolve_uid(u)
          nuevo = " (NUEVO)" if u not in known else ""
          known.add(u)
          registros.append((t, i, u))
          if evict_pending and evictions and evictions[-1][1] is None:
            evictions[-1][1] = nombre
            print(f"[{t:8.3f}s]   primer registro tras evict (=EVICTOR probable): slot {i} {nombre}{nuevo}")
            evict_pending = False
          # registros posteriores: solo mostrar los realmente nuevos para no inundar
          elif u not in known or nuevo:
            print(f"[{t:8.3f}s]   registro: slot {i} {nombre}{nuevo}")

      prev_n, prev_uids = n, uids
      time.sleep(0.0005)

    print("\n===== RESUMEN =====")
    print(f"expulsiones (evict-all): {len(evictions)} en {args.dur:.0f}s")
    if len(evictions) >= 2:
      ts = [e[0] for e in evictions]
      per = [b - a for a, b in zip(ts, ts[1:])]
      print(f"periodo medio entre expulsiones: {sum(per)/len(per):.3f}s "
            f"(si es ~1.000-1.001s: ciclo perpetuo confirmado, hay >=16 suscriptores vivos)")
    evictores = [e[1] for e in evictions if e[1]]
    if evictores:
      print("evictores detectados (proceso que desbordo el limite):")
      for ev in dict.fromkeys(evictores):
        print(f"   {ev}  (x{evictores.count(ev)})")
    n, valids, uids = snapshot(mm)
    vivos = sum(1 for u in uids[:n] if u)
    print(f"\nestado final: num_readers={n}, slots con uid={vivos}")
    for i in range(NUM_READERS):
      if uids[i]:
        print(f"   slot {i:2d} valid={bool(valids[i])}: {resolve_uid(uids[i])}")
    if len(evictions) == 0 and n >= NUM_READERS:
      print("\nAVISO: sin expulsiones en la ventana pero los 15 slots estan LLENOS:")
      print("cualquier suscriptor transitorio (athenad, herramientas) provocara una expulsion.")
    return 0


if __name__ == "__main__":
  raise SystemExit(main())
