"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

ServerIpSettings sub-panel (SIC-UEM / Orbit).

Port of the old Qt ServerIpSettings (selfdrive/ui/sunnypilot/qt/offroad/settings/
sunnypilot/server_ip_settings.cc).

Edits two server IPs, preserving all other keys in each JSON file:
  - Orbit MQTT broker: key "broker" in orbit/config_mqtt.json
  - SICUEM server:         config.IpServer.value in sicuem/config.json

Paths resolve under BASEDIR/sicuem/... with a /data/openpilot fallback.
"""
import json
import os
import tempfile
import threading
from collections.abc import Callable

import pyray as rl

from openpilot.common.basedir import BASEDIR
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
from openpilot.selfdrive.ui.widgets.orbit_server import probe_server
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
from openpilot.system.ui.sunnypilot.widgets.list_view import button_item_sp, LineSeparatorSP
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.button import ButtonStyle
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller


def _resolve_path(rel: str) -> str:
  candidates = [
    os.path.join(BASEDIR, rel),
    os.path.join("/data/openpilot", rel),
  ]
  for path in candidates:
    if os.path.exists(path):
      return path
  return candidates[0]


def _load_json(path: str) -> dict:
  try:
    with open(path) as f:
      data = json.load(f)
    if isinstance(data, dict):
      return data
  except (OSError, ValueError):
    pass
  return {}


def _save_json(path: str, root: dict) -> bool:
  directory = os.path.dirname(path)
  try:
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
      with os.fdopen(fd, "w") as f:
        json.dump(root, f, indent=4)
      os.replace(tmp_path, path)
    except Exception:
      if os.path.exists(tmp_path):
        os.remove(tmp_path)
      raise
  except OSError:
    return False
  return True


class ServerIpSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)

    self._orbit_path = _resolve_path("orbit/config_mqtt.json")
    self._sicuem_path = _resolve_path("sicuem/config.json")
    self._test_status = ""
    self._pending_test: str | None = None

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  def _initialize_items(self):
    self._orbit_button = button_item_sp(
      title=lambda: tr("Servidor Orbit (broker MQTT)"),
      button_text=lambda: tr("EDITAR"),
      description=lambda: tr("IP actual:") + f" {self._read_orbit_ip() or '-'}",
      callback=self._edit_orbit,
    )
    self._sicuem_button = button_item_sp(
      title=lambda: tr("Servidor SICUEM (Universidad Europea)"),
      button_text=lambda: tr("EDITAR"),
      description=lambda: tr("IP actual:") + f" {self._read_sicuem_ip() or '-'}",
      callback=self._edit_sicuem,
    )
    self._test_button = button_item_sp(
      title=lambda: tr("Probar conexion al broker Orbit"),
      button_text=lambda: tr("PROBAR"),
      description=lambda: self._test_status or tr("Comprueba si el servidor responde en la IP y puerto actuales."),
      callback=self._test_connection,
      button_style=ButtonStyle.ACTION,
    )

    return [
      self._orbit_button,
      LineSeparatorSP(40),
      self._sicuem_button,
      LineSeparatorSP(40),
      self._test_button,
    ]

  def _test_connection(self):
    ip = self._read_orbit_ip()
    root = _load_json(self._orbit_path)
    try:
      port = int(root.get("broker_port", 1883) or 1883)
    except (TypeError, ValueError):
      port = 1883
    if not ip:
      gui_app.push_widget(alert_dialog(tr("No hay IP configurada")))
      return
    self._test_status = tr("Probando...")

    def _run():
      ok = probe_server(ip, port, timeout=3.0)
      # Hand the result to the UI thread (see _render) — never push a dialog from a worker thread.
      self._pending_test = (tr("Conectado a") if ok else tr("Sin conexion con")) + f" {ip}:{port}"

    threading.Thread(target=_run, name="orbit_probe", daemon=True).start()

  # ---------------------------------------------------------------- reads
  def _read_orbit_ip(self) -> str:
    root = _load_json(self._orbit_path)
    broker = root.get("broker")
    return broker if isinstance(broker, str) else ""

  def _read_sicuem_ip(self) -> str:
    root = _load_json(self._sicuem_path)
    config = root.get("config")
    if isinstance(config, dict):
      ip_server = config.get("IpServer")
      if isinstance(ip_server, dict):
        value = ip_server.get("value")
        if isinstance(value, str):
          return value
    return ""

  # ---------------------------------------------------------------- edits
  def _edit_orbit(self):
    current = self._read_orbit_ip()

    def on_input(result: DialogResult, text: str):
      if result != DialogResult.CONFIRM:
        return
      text = text.strip()
      if not text:
        return
      root = _load_json(self._orbit_path)  # preserve broker_port and any other keys
      root["broker"] = text
      _save_json(self._orbit_path, root)

    InputDialogSP(tr("IP Servidor Orbit"), current_text=current, min_text_size=1, callback=on_input).show()

  def _edit_sicuem(self):
    current = self._read_sicuem_ip()

    def on_input(result: DialogResult, text: str):
      if result != DialogResult.CONFIRM:
        return
      text = text.strip()
      if not text:
        return
      root = _load_json(self._sicuem_path)  # preserve speed/send/etc.
      config = root.get("config")
      if not isinstance(config, dict):
        config = {}
      ip_server = config.get("IpServer")
      if not isinstance(ip_server, dict):
        ip_server = {}
      ip_server["value"] = text
      config["IpServer"] = ip_server
      root["config"] = config
      _save_json(self._sicuem_path, root)

    InputDialogSP(tr("IP Servidor SICUEM"), current_text=current, min_text_size=1, callback=on_input).show()

  # ------------------------------------------------------------- lifecycle
  def _render(self, rect):
    # Show a probe result produced by the worker thread (UI-thread-safe here).
    if self._pending_test is not None:
      msg, self._pending_test, self._test_status = self._pending_test, None, ""
      gui_app.push_widget(alert_dialog(msg))
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    content_rect = rl.Rectangle(
      rect.x,
      rect.y + self._back_button.rect.height + 40,
      rect.width,
      rect.height - self._back_button.rect.height - 40,
    )
    self._scroller.render(content_rect)

  def show_event(self):
    self._scroller.show_event()
