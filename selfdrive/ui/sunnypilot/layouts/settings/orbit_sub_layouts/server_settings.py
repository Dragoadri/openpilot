"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Filas de CONEXION con el servidor ORBIT (broker MQTT).

`ServerRows` construye las filas compartidas (editar broker + probar conexion)
que usan dos superficies: la seccion CONEXION del panel ORBIT de ajustes
(orbit_panel.py) y el modal a pantalla completa que abre la tarjeta SERVIDOR
de la home (`ServerSettingsLayout`). Edita la key "broker" de
orbit/config_mqtt.json preservando el resto de keys; mqtt_envio_general
recarga el broker en caliente al detectar el cambio.
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
from openpilot.selfdrive.ui.widgets.orbit_server import probe_server, probe_backend, read_backend_port
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
from openpilot.system.ui.sunnypilot.widgets.list_view import button_item_sp
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


class ServerRows:
  """Filas broker-EDITAR y PROBAR, con estado del test compartido.

  El contenedor debe llamar a `poll()` desde su _render (hilo UI): el probe
  corre en un worker y el dialogo de resultado solo puede abrirse aqui.
  """

  def __init__(self):
    self._orbit_path = _resolve_path("orbit/config_mqtt.json")
    self._test_status = ""
    self._pending_test: str | None = None

    self._broker_row = button_item_sp(
      title=lambda: tr("Servidor ORBIT (broker MQTT)"),
      button_text=lambda: tr("EDITAR"),
      description=lambda: tr("Direccion actual:") + f" {self._broker_label()}",
      callback=self._edit_broker,
    )
    self._test_row = button_item_sp(
      title=lambda: tr("Probar conexion con ORBIT"),
      button_text=lambda: tr("PROBAR"),
      description=lambda: self._test_status or tr("Comprueba el broker MQTT y la API del backend."),
      callback=self._test_connection,
      button_style=ButtonStyle.ACTION,
    )

  @property
  def items(self) -> list:
    return [self._broker_row, self._test_row]

  def poll(self):
    if self._pending_test is not None:
      msg, self._pending_test, self._test_status = self._pending_test, None, ""
      gui_app.push_widget(alert_dialog(msg))

  # ---------------------------------------------------------------- broker
  def _read_broker_ip(self) -> str:
    broker = _load_json(self._orbit_path).get("broker")
    return broker if isinstance(broker, str) else ""

  def _read_broker_port(self) -> int:
    try:
      return int(_load_json(self._orbit_path).get("broker_port", 1883) or 1883)
    except (TypeError, ValueError):
      return 1883

  def _broker_label(self) -> str:
    ip = self._read_broker_ip()
    return f"{ip}:{self._read_broker_port()}" if ip else "-"

  def _edit_broker(self):
    current = self._read_broker_ip()

    def on_input(result: DialogResult, text: str):
      if result != DialogResult.CONFIRM:
        return
      text = text.strip()
      if not text:
        return
      root = _load_json(self._orbit_path)  # preserva broker_port y el resto de keys
      root["broker"] = text
      _save_json(self._orbit_path, root)

    InputDialogSP(tr("IP del servidor ORBIT"), current_text=current, min_text_size=1, callback=on_input).show()

  # ---------------------------------------------------------------- probe
  def _test_connection(self):
    ip = self._read_broker_ip()
    port = self._read_broker_port()
    if not ip:
      gui_app.push_widget(alert_dialog(tr("No hay IP configurada")))
      return
    self._test_status = tr("Probando...")

    def _run():
      broker_ok = probe_server(ip, port, timeout=3.0)
      backend_ok = probe_backend(ip, read_backend_port(), timeout=3.0)
      broker_msg = tr("Broker OK") if broker_ok else tr("Broker sin respuesta")
      backend_msg = tr("API OK") if backend_ok else tr("API sin respuesta")
      self._pending_test = f"{ip}:{port}\n{broker_msg} - {backend_msg}"

    threading.Thread(target=_run, name="orbit_probe", daemon=True).start()


class ServerSettingsLayout(Widget):
  """Pantalla completa (Back + filas): la envuelve el modal SERVIDOR de la home."""

  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)

    self._rows = ServerRows()
    self._scroller = Scroller(self._rows.items, line_separator=False, spacing=0)

  def _render(self, rect):
    self._rows.poll()
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
