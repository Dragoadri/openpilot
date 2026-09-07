#!/usr/bin/env python3
"""
diag_msgq_readers.py — Diagnostico del limite de suscriptores msgq (NUM_READERS).

CAUSA RAIZ (commIssue ~1 Hz al activar OP; primera vez 2026-07 en sicuem-mig, recaida 2026-09):
msgq limita cada canal a NUM_READERS suscriptores: 15 en el msgq original de commaai/sunnypilot, 31
en nuestro fork Dragoadri/msgq (submodulo msgq_repo desde 2026-09). Cuando el (N+1)-esimo intenta registrarse,
msgq_init_subscriber() EXPULSA A TODOS (num_readers=0, read_valids=false, read_uids=0; bloque
"evicting all subscribers" de msgq/msgq.cc) y cada proceso se re-registra en su siguiente
lectura perdiendo su cola pendiente. Con >=N+1 suscriptores VIVOS el ciclo es perpetuo: el
ultimo en re-registrarse (el hilo MQTT de telemetria, periodo ~1.0008 s) vuelve a desbordar el
limite cada segundo -> todos los daemons (radard, paramsd, plannerd, dmonitoringd, torqued, lagd,
calibrationd, locationd) fallan un ciclo sus checks de carState -> publican valid=False ->
selfdrived: commIssue / locationdTemporaryError.
Los slots NO se liberan al morir un proceso: un tid muerto sigue ocupando su slot (y contando
para el limite) hasta la siguiente expulsion.

RECAIDA 2026-09: el GateMonitor de ORBIT (orbit/command_gates.py, SubMaster a 10 Hz en el hilo
ORBIT del manager para el plano de mando remoto v2) paso a ser el 16º lector de carState ->
misma tormenta con N=15. De ahi el modo --census: contar suscriptores por canal ANTES de anadir
un SubMaster nuevo sobre un canal caliente (y despues, para comprobar que no desborda).

LAYOUT de la cabecera (msgq/msgq.h; todo uint64 little-endian, sin padding):
    num_readers @0 | write_pointer @8 | write_uid @16 | read_pointers[N] @24 |
    read_valids[N] @24+8N | read_uids[N] @24+16N          -> cabecera = 24+24N bytes
N NO se hardcodea: se deduce del tamano del fichero (= queue_size + cabecera) probando los
queue_size conocidos (cereal/services.py: SMALL/MEDIUM/BIG del canal; 1 MiB = DEFAULT_SEGMENT_SIZE
de msgq.h para sockets crudos y streams visionipc). Asi vale igual para N=15 y para N=31.

FICHEROS (msgq.cc, msgq_new_queue): /dev/shm/msgq_<canal>, o /dev/shm/msgq_<OPENPILOT_PREFIX>/<canal>
si el env var esta definido (dentro del prefijo los ficheros NO llevan "msgq_").
msgq_visionipc_<cam>_<tipo> son colas msgq reales (1 MiB); msgq_visionbuf_* son buffers de imagen
crudos, NO colas (el censo los omite).

USO (en el comma, con openpilot corriendo y coche encendido):
    cd /data/openpilot && python3 tools/orbit/diag_msgq_readers.py --census     # censo de TODAS las colas
    python3 tools/orbit/diag_msgq_readers.py                                     # vigila carState, 20 s
    python3 tools/orbit/diag_msgq_readers.py --service carState --dur 30
    python3 tools/orbit/diag_msgq_readers.py --service liveCalibration
    OPENPILOT_PREFIX=xyz python3 tools/orbit/diag_msgq_readers.py --census       # colas de un prefijo

--census: por cola, num_readers, N deducido, slots vivos/muertos (tid resuelto via /proc) y la marca
"!!" si esta al limite (LLENO) o a <=2 slots de el (EVICT-RISK); ordenado por num_readers.
--service: registro de expulsiones (EVICT-ALL), quien se registra tras cada una (el primero = el
proceso que desbordo el limite) y tabla final de slots con nombre de proceso/hilo. Si ves
"EVICT-ALL" repetido cada ~1 s: confirmado.

Ambos modos son de SOLO LECTURA (read() / mmap PROT_READ): NUNCA crean sockets msgq ni SubMasters,
que gastarian un slot y re-truncarian la cola (un sub_sock de diagnostico seria parte del problema).
"""
import argparse
import mmap
import os
import struct
import sys
import time
from dataclasses import dataclass
from functools import cache

SHM_BASE = "/dev/shm"
MIB = 1024 * 1024
# Orden de prueba cuando el canal no esta en SERVICE_LIST (o cereal no se puede importar):
# DEFAULT_SEGMENT_SIZE de msgq.h (sockets crudos, visionipc) y luego SMALL/MEDIUM/BIG de cereal.
SIZE_CANDIDATES = (1 * MIB, 250 * 1024, 2 * MIB, 10 * MIB)
MAX_READERS = 255  # cota de sanidad al deducir N


@dataclass(frozen=True)
class Layout:
  """Offsets de la cabecera msgq para un NUM_READERS concreto (msgq/msgq.h)."""
  n: int            # NUM_READERS del build que creo la cola
  queue_size: int   # tamano del segmento de datos (ultimo socket que conecto)

  OFF_NUM_READERS = 0
  OFF_WRITE_POINTER = 8
  OFF_WRITE_UID = 16
  OFF_READ_POINTERS = 24

  @property
  def off_read_valids(self) -> int:
    return self.OFF_READ_POINTERS + 8 * self.n

  @property
  def off_read_uids(self) -> int:
    return self.OFF_READ_POINTERS + 16 * self.n

  @property
  def header_size(self) -> int:
    return self.OFF_READ_POINTERS + 24 * self.n


@cache
def _service_list():
  """Importa cereal.services perezosamente; None si no esta disponible (el censo sigue funcionando)."""
  try:
    from cereal.services import SERVICE_LIST
  except ImportError:
    # lanzado como script en el device (sys.path[0] = tools/orbit, sin PYTHONPATH): probar la raiz del repo
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    try:
      from cereal.services import SERVICE_LIST
    except Exception:
      return None
  return SERVICE_LIST


def known_queue_size(name: str) -> int | None:
  services = _service_list()
  if services is None or name not in services:
    return None
  return int(services[name].queue_size)


def derive_layout(path: str, name: str) -> Layout | None:
  """Deduce N del tamano del fichero: size = queue_size + 24 + 24N. None si ningun queue_size conocido cuadra."""
  size = os.path.getsize(path)
  candidates = []
  qs = known_queue_size(name)
  if qs is not None:
    candidates.append(qs)
  candidates += [c for c in SIZE_CANDIDATES if c not in candidates]
  for q in candidates:
    rest = size - q - Layout.OFF_READ_POINTERS
    if rest > 0 and rest % 24 == 0 and 1 <= rest // 24 <= MAX_READERS:
      return Layout(n=rest // 24, queue_size=q)
  return None


def _prefix() -> str | None:
  # como getenv() en C: definido aunque este vacio cuenta como prefijo
  return os.environ.get("OPENPILOT_PREFIX")


def shm_dir() -> str:
  """Directorio de las colas: /dev/shm, o /dev/shm/msgq_<OPENPILOT_PREFIX> (msgq.cc, msgq_new_queue)."""
  prefix = _prefix()
  return f"{SHM_BASE}/msgq_{prefix}" if prefix is not None else SHM_BASE


def queue_path(service: str) -> str:
  """Con prefijo los ficheros van dentro del directorio SIN 'msgq_'; sin prefijo, /dev/shm/msgq_<canal>."""
  return f"{shm_dir()}/{service}" if _prefix() is not None else f"{SHM_BASE}/msgq_{service}"


def list_queues() -> list[tuple[str, str]]:
  """(canal, ruta) de todas las colas msgq (ficheros regulares); omite los buffers visionbuf_*."""
  d = shm_dir()
  try:
    entries = sorted(os.listdir(d))
  except OSError:
    return []
  prefixed = _prefix() is not None
  out = []
  for e in entries:
    if prefixed:
      name = e
    elif e.startswith("msgq_"):
      name = e[len("msgq_"):]
    else:
      continue
    if name.startswith("visionbuf_"):
      continue
    p = os.path.join(d, e)
    if os.path.isfile(p):
      out.append((name, p))
  return out


def uid_tid(uid: int) -> int:
  """uid msgq = (rand32 << 32) | tid (msgq.cc, msgq_init_subscriber)."""
  return uid & 0xFFFFFFFF


def tid_alive(tid: int) -> bool:
  return os.path.exists(f"/proc/{tid}")


def resolve_uid(uid: int) -> str:
  """Resuelve el tid del uid -> nombre de hilo y proceso (via /proc)."""
  if uid == 0:
    return "-"
  tid = uid_tid(uid)
  if not tid_alive(tid):
    return f"tid={tid} (MUERTO: slot filtrado de un proceso terminado)"
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


def parse_header(buf: bytes, lay: Layout) -> tuple[int, list[int], list[int]]:
  n = struct.unpack_from("<Q", buf, lay.OFF_NUM_READERS)[0]
  valids = list(struct.unpack_from(f"<{lay.n}Q", buf, lay.off_read_valids))
  uids = list(struct.unpack_from(f"<{lay.n}Q", buf, lay.off_read_uids))
  return n, valids, uids


def read_header(path: str, lay: Layout) -> tuple[int, list[int], list[int]]:
  """Lectura pura de la cabecera (open+read, sin mmap ni escritura): para el censo."""
  with open(path, "rb") as f:
    return parse_header(f.read(lay.header_size), lay)


def snapshot(mm, lay: Layout) -> tuple[int, list[int], list[int]]:
  mm.seek(0)
  return parse_header(mm.read(lay.header_size), lay)


# ----------------------------------------------------------------------------
def census() -> int:
  """Censo de solo lectura de todas las colas: num_readers, N deducido, slots vivos/muertos."""
  d = shm_dir()
  queues = list_queues()
  print(f"== censo msgq en {d}/: {len(queues)} colas (solo lectura: no registra suscriptores) ==")
  if not queues:
    print("   (ninguna cola; ¿openpilot arrancado? ¿OPENPILOT_PREFIX correcto?)")
    return 1

  rows = []    # (num_readers, N, vivos, muertos, canal, marca)
  raros = []   # (canal, tamano) cuyo tamano no cuadra con ningun queue_size conocido
  for name, path in queues:
    lay = derive_layout(path, name)
    if lay is None:
      raros.append((name, os.path.getsize(path)))
      continue
    try:
      n_readers, _valids, uids = read_header(path, lay)
    except (OSError, struct.error):
      raros.append((name, -1))
      continue
    ocupados = [u for u in uids if u]
    vivos = sum(1 for u in ocupados if tid_alive(uid_tid(u)))
    muertos = len(ocupados) - vivos
    if n_readers >= lay.n:
      marca = "!! LLENO"
    elif n_readers >= lay.n - 2:
      marca = "!! EVICT-RISK"
    else:
      marca = ""
    rows.append((n_readers, lay.n, vivos, muertos, name, marca))

  rows.sort(key=lambda r: (-r[0], r[4]))
  print(f"   {'canal':<32} {'readers':>7} {'N':>4} {'vivos':>5} {'muertos':>7}  marca")
  for n_readers, n, vivos, muertos, name, marca in rows:
    print(f"   {name:<32} {n_readers:>7} {n:>4} {vivos:>5} {muertos:>7}  {marca}".rstrip())
  for name, size in raros:
    print(f"   {name:<32} {'?':>7} {'?':>4} {'?':>5} {'?':>7}  (tamano {size} B: ningun queue_size conocido cuadra; omitido)")
  print("   readers = num_readers de la cabecera; N = NUM_READERS deducido del tamano del fichero; muertos = tid ya inexistente")
  print("   !! = al limite (LLENO) o a <=2 slots de el (EVICT-RISK): un suscriptor transitorio (athenad, herramientas) expulsa a todos")

  if not rows:
    print("\nningun fichero con layout msgq reconocible")
    return 1
  top = rows[0]
  en_riesgo = [r[4] for r in rows if r[5]]
  muertos_tot = sum(r[3] for r in rows)
  linea = f"\nmax num_readers = {top[0]}/{top[1]} ({top[4]}); colas con !!: {len(en_riesgo)}"
  if en_riesgo:
    linea += " -> " + ", ".join(en_riesgo)
  if muertos_tot:
    linea += f"; slots muertos en total: {muertos_tot} (siguen contando hasta la siguiente expulsion)"
  print(linea)
  return 0


# ----------------------------------------------------------------------------
def monitor(service: str, dur: float) -> int:
  """Vigila en vivo un canal: expulsiones (EVICT-ALL), registros y tabla final de slots."""
  path = queue_path(service)
  if not os.path.exists(path):
    print(f"ERROR: no existe {path}. ¿openpilot arrancado? ¿nombre de canal correcto? ¿OPENPILOT_PREFIX?")
    return 1
  lay = derive_layout(path, service)
  if lay is None:
    print(f"ERROR: {path} ocupa {os.path.getsize(path)} B y no cuadra con ningun queue_size conocido (¿no es una cola msgq?)")
    return 1

  # "rb" + PROT_READ: solo lectura, nunca se toca la cola
  with open(path, "rb") as f, mmap.mmap(f.fileno(), lay.header_size, mmap.MAP_SHARED, mmap.PROT_READ) as mm:
    t0 = time.monotonic()
    prev_n, _, prev_uids = snapshot(mm, lay)
    print(f"== {service} ({path}): queue_size={lay.queue_size} B, NUM_READERS={lay.n}, num_readers inicial = {prev_n} ==")
    for i, u in enumerate(prev_uids):
      if u:
        print(f"   slot {i:2d}: {resolve_uid(u)}")
    print(f"== vigilando {dur:.0f}s... ==")

    evictions = []      # (t, primer_registrado_tras_evict)
    registros = []      # (t, slot, uid) nuevos uids vistos
    known = {u for u in prev_uids if u}
    evict_pending = False

    while time.monotonic() - t0 < dur:
      n, valids, uids = snapshot(mm, lay)
      t = time.monotonic() - t0

      if n < prev_n:
        # num_readers solo baja en el evict-all (se pone a 0 y el evictor hace CAS a 1)
        print(f"[{t:8.3f}s] EVICT-ALL: num_readers {prev_n} -> {n}")
        evictions.append([t, None])
        evict_pending = True

      for i in range(lay.n):
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
    print(f"expulsiones (evict-all): {len(evictions)} en {dur:.0f}s")
    if len(evictions) >= 2:
      ts = [e[0] for e in evictions]
      per = [b - a for a, b in zip(ts, ts[1:], strict=False)]
      media = sum(per) / len(per)
      print(f"periodo medio entre expulsiones: {media:.3f}s (si es ~1.000-1.001s: ciclo perpetuo confirmado, hay >={lay.n + 1} suscriptores vivos)")
    evictores = [e[1] for e in evictions if e[1]]
    if evictores:
      print("evictores detectados (proceso que desbordo el limite):")
      for ev in dict.fromkeys(evictores):
        print(f"   {ev}  (x{evictores.count(ev)})")
    n, valids, uids = snapshot(mm, lay)
    vivos = sum(1 for u in uids[:n] if u)
    print(f"\nestado final: num_readers={n}/{lay.n}, slots con uid={vivos}")
    for i in range(lay.n):
      if uids[i]:
        print(f"   slot {i:2d} valid={bool(valids[i])}: {resolve_uid(uids[i])}")
    if len(evictions) == 0 and n >= lay.n:
      print(f"\nAVISO: sin expulsiones en la ventana pero los {lay.n} slots estan LLENOS:")
      print("cualquier suscriptor transitorio (athenad, herramientas) provocara una expulsion.")
    return 0


def main():
  ap = argparse.ArgumentParser(description="Monitor / censo de suscriptores msgq (limite NUM_READERS). Solo lectura.")
  ap.add_argument("--service", default="carState", help="canal cereal a vigilar (default: carState)")
  ap.add_argument("--dur", type=float, default=20.0, help="segundos de captura (default: 20)")
  ap.add_argument("--census", action="store_true",
                  help="censo de TODAS las colas (num_readers, N deducido, slots vivos/muertos) y salir; ignora --service/--dur")
  args = ap.parse_args()

  if args.census:
    return census()
  return monitor(args.service, args.dur)


if __name__ == "__main__":
  raise SystemExit(main())
