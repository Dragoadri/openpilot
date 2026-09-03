#!/usr/bin/env python3
"""Baliza de arranque: emite el estado del dispositivo por la red mientras arranca.

Para cuando la pantalla se queda en el logo y no hay SSH: launch_chffrplus.sh
lanza esto en segundo plano al principio del arranque y, durante BEACON_DURATION_S,
cada BEACON_INTERVAL_S envía una instantánea de texto con:

  * hostname, serie, IPs, uptime, memoria, AGNOS (/VERSION), commit y rama;
  * qué procesos del arranque están vivos (build.py, scons, spinner, manager, ui…);
  * las últimas líneas del registro persistente (/data/orbit_boot.log);
  * el contenido de la ventana tmux del arranque (lo que se vería con `tmux a`);
  * el final de dmesg si es legible.

Canales, todos "best effort" y sin bloquear el arranque:

  * UDP broadcast (255.255.255.255 y el broadcast de cada interfaz) al puerto
    BEACON_PORT, troceado en datagramas < 1200 bytes;
  * UDP unicast a cada IP de orbit/beacon_targets.txt y /data/orbit_beacon_targets.txt;
  * MQTT (paho, vendorizado en el repo) al broker de orbit/beacon_mqtt.txt
    (`host:puerto`), topic orbit/boot/<hostname>, si el fichero existe.

En el PC se escucha con tools/orbit/boot_beacon_listen.py. Solo stdlib (+ paho
opcional). Nunca lanza hacia arriba.
"""
import os
import re
import socket
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
BASEDIR = os.path.dirname(_HERE)

BEACON_PORT = 47474
BEACON_INTERVAL_S = 4.0
BEACON_DURATION_S = 30 * 60
CHUNK_BYTES = 1200
BOOT_LOG = "/data/orbit_boot.log"
TARGETS_FILES = (os.path.join(_HERE, "beacon_targets.txt"), "/data/orbit_beacon_targets.txt")
MQTT_FILE = os.path.join(_HERE, "beacon_mqtt.txt")
WATCHED = ("launch_chffrplus", "install_repair", "agnos_update", "updater", "build.py", "scons",
           "spinner.py", "text.py", "manager.py", "ui.py", "failsafe_screen", "pandad", "hardwared")


def sh(cmd: str, timeout: float = 5.0) -> str:
  try:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")
  except Exception as e:
    return f"({type(e).__name__})"


def read(path: str, default: str = "") -> str:
  try:
    with open(path, encoding="utf-8", errors="replace") as f:
      return f.read().strip()
  except Exception:
    return default


def tail_lines(text: str, n: int) -> list[str]:
  lines = [ln.rstrip() for ln in text.splitlines()]
  return lines[-n:]


def local_ips() -> list[tuple[str, str]]:
  """[(ip, broadcast)] de las interfaces con IPv4 global."""
  out = []
  for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)(?: brd (\d+\.\d+\.\d+\.\d+))?", sh("ip -4 -o addr show scope global")):
    out.append((m.group(1), m.group(3) or ""))
  return out


def watched_procs() -> str:
  ps = sh("ps -eo args")
  return " ".join(f"{name}:{'SI' if name in ps else 'no'}" for name in WATCHED)


def snapshot(seq: int, t0: float) -> str:
  ips = local_ips()
  serial = read('/sys/firmware/devicetree/base/serial-number', '?').strip(chr(0))
  commit = sh(f'git -C {BASEDIR} rev-parse --short HEAD').strip() or '?'
  branch = sh(f'git -C {BASEDIR} rev-parse --abbrev-ref HEAD').strip() or '?'
  head = [
    f"ORBIT-BEACON seq={seq} t=+{int(time.monotonic() - t0)}s host={socket.gethostname()} serial={serial}",
    f"ips={','.join(ip for ip, _ in ips) or '?'} | AGNOS={read('/VERSION', '?')} | commit={commit} branch={branch}",
    f"uptime={read('/proc/uptime', '?').split(' ')[0]}s | {sh('free -m | sed -n 2p').strip()} | df_data={sh('df -h /data | sed -n 2p').strip()}",
    f"procs: {watched_procs()}",
  ]
  body = ["-- " + BOOT_LOG + " (últimas 15)"] + tail_lines(read(BOOT_LOG), 15)
  body += ["-- tmux (últimas 25)"] + tail_lines(sh("tmux capture-pane -p -S -200 2>/dev/null || tmux capture-pane -p -t comma -S -200 2>/dev/null"), 25)
  body += ["-- dmesg (últimas 6)"] + tail_lines(sh("dmesg 2>/dev/null | tail -n 6"), 6)
  return "\n".join(head + body) + "\n"


def chunks(seq: int, text: str) -> list[bytes]:
  data = text.encode("utf-8", "replace")
  n = max(1, (len(data) + CHUNK_BYTES - 1) // CHUNK_BYTES)
  return [f"ORBIT-BEACON-PART seq={seq} part={i + 1}/{n}\n".encode() + data[i * CHUNK_BYTES:(i + 1) * CHUNK_BYTES]
          for i in range(n)]


def targets() -> list[str]:
  out: list[str] = []
  for path in TARGETS_FILES:
    for ln in read(path).splitlines():
      ln = ln.split("#", 1)[0].strip()
      if ln:
        out.append(ln)
  return out


def send_udp(parts: list[bytes]) -> None:
  dests = {("255.255.255.255", BEACON_PORT)}
  for _ip, brd in local_ips():
    if brd:
      dests.add((brd, BEACON_PORT))
  for t in targets():
    dests.add((t, BEACON_PORT))
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1.0)
    for dest in dests:
      for p in parts:
        try:
          sock.sendto(p, dest)
        except Exception:
          break
  finally:
    sock.close()


class Mqtt:
  """Publicación opcional por MQTT (paho vendorizado). Cualquier fallo se ignora."""

  def __init__(self):
    self.client = None
    self.next_try = 0.0
    self.topic = f"orbit/boot/{socket.gethostname()}"
    spec = read(MQTT_FILE)
    self.host, _, port = spec.partition(":")
    self.port = int(port) if port.isdigit() else 1883

  def publish(self, text: str) -> None:
    if not self.host:
      return
    now = time.monotonic()
    if self.client is None and now >= self.next_try:
      self.next_try = now + 30.0
      try:
        sys.path.insert(0, BASEDIR)
        import paho.mqtt.client as mqtt  # vendorizado en <repo>/paho
        c = mqtt.Client()
        c.connect(self.host, self.port, keepalive=30)
        c.loop_start()
        self.client = c
      except Exception:
        self.client = None
    if self.client is not None:
      try:
        self.client.publish(self.topic, text, qos=0)
      except Exception:
        self.client = None


def main() -> int:
  t0 = time.monotonic()
  mq = Mqtt()
  seq = 0
  while time.monotonic() - t0 < BEACON_DURATION_S:
    seq += 1
    try:
      text = snapshot(seq, t0)
      send_udp(chunks(seq, text))
      mq.publish(text)
    except Exception:
      pass
    time.sleep(BEACON_INTERVAL_S)
  return 0


if __name__ == "__main__":
  try:
    sys.exit(main())
  except BaseException:  # noqa: B036 -- la baliza jamás puede afectar al arranque
    sys.exit(0)
