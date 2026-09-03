#!/usr/bin/env python3
"""Escucha la baliza de arranque del comma (orbit/boot_beacon.py) y la imprime.

  python3 tools/orbit/boot_beacon_listen.py [--port 47474] [--out fichero]

Reensambla los datagramas de cada instantánea (seq/part) y la imprime entera con
la hora y la IP de origen. Con --out, además la va guardando en un fichero.
"""
import argparse
import re
import socket
import sys
import time

HEADER = re.compile(rb"^ORBIT-BEACON-PART seq=(\d+) part=(\d+)/(\d+)\n")


def parse_part(datagram: bytes) -> tuple[int, int, int, bytes] | None:
  m = HEADER.match(datagram)
  if not m:
    return None
  return int(m.group(1)), int(m.group(2)), int(m.group(3)), datagram[m.end():]


class Reassembler:
  def __init__(self):
    self.pending: dict[tuple[str, int], dict[int, bytes]] = {}

  def feed(self, src: str, datagram: bytes) -> str | None:
    parsed = parse_part(datagram)
    if parsed is None:
      return datagram.decode("utf-8", "replace")
    seq, part, total, payload = parsed
    key = (src, seq)
    parts = self.pending.setdefault(key, {})
    parts[part] = payload
    if len(parts) < total:
      return None
    del self.pending[key]
    # olvidar instantáneas viejas incompletas del mismo origen
    for k in [k for k in self.pending if k[0] == src and k[1] < seq]:
      del self.pending[k]
    return b"".join(parts[i] for i in sorted(parts)).decode("utf-8", "replace")


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--port", type=int, default=47474)
  ap.add_argument("--out", default=None)
  args = ap.parse_args()

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  sock.bind(("0.0.0.0", args.port))
  out = open(args.out, "a", encoding="utf-8") if args.out else None
  print(f"escuchando UDP {args.port}… (Ctrl-C para salir)", flush=True)
  rs = Reassembler()
  try:
    while True:
      data, (src, _port) = sock.recvfrom(65535)
      text = rs.feed(src, data)
      if text is None:
        continue
      stamp = time.strftime("%H:%M:%S")
      block = f"\n===== {stamp} desde {src} =====\n{text}"
      print(block, flush=True)
      if out:
        out.write(block)
        out.flush()
  except KeyboardInterrupt:
    pass
  finally:
    if out:
      out.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
