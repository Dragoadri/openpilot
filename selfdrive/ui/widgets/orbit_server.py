"""
ORBIT server reachability helpers.

Reads the Orbit MQTT broker address from sicuem/orbit/config_mqtt.json and
checks whether it is reachable with a plain TCP connect (no MQTT handshake).
Used by the home screen (live status) and the server-IP settings ("test") button.
"""
import json
import os
import socket
import threading

from openpilot.common.basedir import BASEDIR

CONFIG_REL = "sicuem/orbit/config_mqtt.json"


def _resolve(rel: str) -> str:
  for path in (os.path.join(BASEDIR, rel), os.path.join("/data/openpilot", rel)):
    if os.path.exists(path):
      return path
  return os.path.join(BASEDIR, rel)


def read_broker() -> tuple[str, int]:
  """Return (ip, port) of the Orbit MQTT broker from config_mqtt.json."""
  try:
    with open(_resolve(CONFIG_REL)) as f:
      data = json.load(f)
    if isinstance(data, dict):
      ip = data.get("broker") or ""
      port = int(data.get("broker_port", 1883) or 1883)
      return (ip if isinstance(ip, str) else ""), port
  except Exception:
    pass
  return "", 1883


def probe_server(ip: str, port: int, timeout: float = 2.0) -> bool:
  """True if a TCP connection to (ip, port) succeeds within `timeout`."""
  if not ip:
    return False
  try:
    with socket.create_connection((ip, int(port)), timeout=timeout):
      return True
  except Exception:
    return False


class ServerMonitor:
  """Background poller that keeps the current broker IP and reachability."""

  def __init__(self, interval: float = 5.0):
    self._interval = interval
    self._connected = False
    self._ip = ""
    self._lock = threading.Lock()
    self._stop = threading.Event()
    self._thread = threading.Thread(target=self._loop, name="orbit_server_monitor", daemon=True)
    self._thread.start()

  def _loop(self) -> None:
    while not self._stop.is_set():
      ip, port = read_broker()
      ok = probe_server(ip, port)
      with self._lock:
        self._ip = ip
        self._connected = ok
      if self._stop.wait(self._interval):
        break

  @property
  def connected(self) -> bool:
    with self._lock:
      return self._connected

  @property
  def ip(self) -> str:
    with self._lock:
      return self._ip

  def stop(self) -> None:
    self._stop.set()
