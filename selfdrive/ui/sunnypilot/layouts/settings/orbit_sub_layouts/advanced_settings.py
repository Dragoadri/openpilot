"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Subpanel AJUSTES AVANZADOS del panel ORBIT (antes `jetson_settings.py`).

Recoge lo que la seccion 9 del diseno manda a la app y que todavia no tiene equivalente
alli, para sacarlo del scroll del panel principal sin perder la capacidad:

  * PANTALLA: los dos avisos de HUD (angulo muerto y cambio de carril). Los overlays que
    consumen esos params se quedan onroad; lo que baja un nivel es su interruptor.
  * JETSON: enlace, estado en vivo y red (IPs, puertos, calidad JPEG) guardada en
    orbit/config_jetson.json (escritura atomica, sube _version y levanta
    JetsonConfigChanged, que camera_sender comprueba en cada vuelta de su bucle).

EL SELECTOR DE MODO DE VOLANTE YA NO ESTA AQUI. Se movio a
`orbit_sub_layouts/steer_mode.py` y se pinta en el panel ORBIT principal, porque la
seccion 9 lo deja en el comma como control de primera linea y enterrarlo tras dos
navegaciones era lo contrario.
"""
import json
import os
import tempfile
import time
from collections.abc import Callable

import pyray as rl

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import UnknownKeyName
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
from openpilot.selfdrive.ui.widgets.orbit_section import SectionHeaderSP
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.orbit_sub_layouts.steer_mode import (
  MODE_NAMES,
  TORQUE_STALE_SECONDS,
)
from openpilot.system.ui.sunnypilot.widgets.list_view import (
  button_item_sp,
  toggle_item_sp,
)
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.list_view import text_item
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller

# Reexportados para quien todavia los importe desde aqui; la definicion vive en
# steer_mode.py, que es donde esta el selector.
__all__ = ["AdvancedSettingsLayout", "MODE_NAMES", "TORQUE_STALE_SECONDS", "CONFIG_DEFAULTS"]

PARAM_READ_INTERVAL_FRAMES = 30  # ~0.5s at 60fps

# Default config values, mirror the old Qt defaults.
CONFIG_DEFAULTS = {
  "jetson_enabled": False,
  "jetson_ip": "192.168.1.50",
  "comma_ip": "127.0.0.1",
  "jetson_img_port": 5555,
  "jetson_torque_port": 5556,
  "jpeg_quality": 80,
}


def _resolve_config_path() -> str:
  """Resolve config_jetson.json, preferring BASEDIR with a /data/openpilot fallback."""
  candidates = [
    os.path.join(BASEDIR, "orbit", "config_jetson.json"),
    "/data/openpilot/orbit/config_jetson.json",
  ]
  for path in candidates:
    if os.path.exists(path):
      return path
  # Default to the BASEDIR location even if it does not exist yet (will be created).
  return candidates[0]


class AdvancedSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)

    self._config_path = _resolve_config_path()
    self._config: dict = {}
    self._load_config()
    self._config_mtime = self._current_mtime()

    # Throttle / live state
    self._frame = 0
    self._live_torque = ""
    self._live_torque_ts = ""
    self._live_obstacle = ""

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  # ---------------------------------------------------------------- items
  def _initialize_items(self):
    self._jetson_enabled_toggle = toggle_item_sp(
      title=lambda: tr("Activar envio a la Jetson"),
      description=lambda: tr("Habilita el envio de imagenes a la Jetson y la recepcion de su torque."),
      initial_state=bool(self._config.get("jetson_enabled", False)),
      callback=self._on_jetson_enabled,
    )

    self._ip_button = button_item_sp(
      title=lambda: tr("IP de la Jetson"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("jetson_ip", tr("IP de la Jetson"), is_int=False),
    )
    self._comma_ip_button = button_item_sp(
      title=lambda: tr("IP del Comma (este dispositivo)"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("comma_ip", tr("IP del Comma (este dispositivo)"), is_int=False),
    )
    self._img_port_button = button_item_sp(
      title=lambda: tr("Puerto de imagenes"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("jetson_img_port", tr("Puerto de imagenes"), is_int=True),
    )
    self._torque_port_button = button_item_sp(
      title=lambda: tr("Puerto de torque"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("jetson_torque_port", tr("Puerto de torque"), is_int=True),
    )
    self._quality_button = button_item_sp(
      title=lambda: tr("Calidad de imagen (10-100)"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("jpeg_quality", tr("Calidad de imagen (10-100)"), is_int=True,
                                               clamp=(10, 100), step=10),
    )

    # ESTADO: read-only live rows (param reads throttled in _update_state)
    self._status_torque = text_item(lambda: tr("Torque actual"), self._torque_text)
    self._status_obstacle = text_item(lambda: tr("Obstaculo detectado"), self._obstacle_yesno_text)

    self._show_blindspot_toggle = toggle_item_sp(
      param="show_blindspot",
      title=lambda: tr("MOSTRAR ANGULO MUERTO"),
      description=lambda: tr("Muestra el estado del angulo muerto en la pantalla de conduccion."),
    )
    self._lane_warn_toggle = toggle_item_sp(
      param="c_carril",
      title=lambda: tr("AVISOS EN CAMBIO DE CARRIL"),
      description=lambda: tr("Anade avisos en pantalla si hay un vehiculo en el angulo muerto " +
                             "durante un cambio de carril."),
    )

    items = [
      SectionHeaderSP(tr("PANTALLA")),
      self._show_blindspot_toggle,
      self._lane_warn_toggle,
      SectionHeaderSP(tr("JETSON")),
      self._jetson_enabled_toggle,
      SectionHeaderSP(tr("ESTADO")),
      self._status_torque,
      self._status_obstacle,
      SectionHeaderSP(tr("RED")),
      self._ip_button,
      self._comma_ip_button,
      self._img_port_button,
      self._torque_port_button,
      self._quality_button,
    ]
    return items

  # -------------------------------------------------------------- live state
  def _read_live_param(self, key: str) -> str:
    # New params written by orbit/zmq_client.py; tolerate older manifests.
    try:
      raw = ui_state.params.get(key)
    except UnknownKeyName:
      return ""
    return raw if raw else ""

  def _refresh_live_status(self):
    self._live_torque = self._read_live_param("JetsonTorque")
    self._live_torque_ts = self._read_live_param("JetsonTorqueTimestamp")
    self._live_obstacle = self._read_live_param("JetsonObstaclePulse")

  def _torque_text(self) -> str:
    if not self._live_torque:
      return "-"
    try:
      # Sello de PARED porque asi lo escribe zmq_client (cruza barrera de proceso).
      # time_ns y no time(): `time.time` esta prohibido por ruff en este arbol.
      if not self._live_torque_ts or (time.time_ns() / 1e9) - float(self._live_torque_ts) > TORQUE_STALE_SECONDS:
        return "-"
      return f"{float(self._live_torque):+.2f}"
    except (TypeError, ValueError):
      return "-"

  def _obstacle_yesno_text(self) -> str:
    # JetsonObstaclePulse holds the last {"obstacle": bool, "intensity": float} JSON
    if self._live_obstacle:
      try:
        payload = json.loads(self._live_obstacle)
        if isinstance(payload, dict) and payload.get("obstacle"):
          return tr("SI")
      except ValueError:
        pass
    return tr("NO")

  def _dongle_id(self) -> str | None:
    dongle = ui_state.params.get("DongleId")
    return dongle if dongle else None

  # --------------------------------------------------------- jetson enabled
  def _on_jetson_enabled(self, enabled: bool):
    self._config["jetson_enabled"] = bool(enabled)
    self._save_config()

  def _sync_jetson_enabled(self):
    toggle = getattr(self, "_jetson_enabled_toggle", None)
    if toggle is not None:
      toggle.action_item.toggle.set_state(bool(self._config.get("jetson_enabled", False)))

  # ------------------------------------------------------------- config IO
  def _current_mtime(self) -> float:
    try:
      return os.path.getmtime(self._config_path)
    except OSError:
      return 0.0

  def _load_config(self):
    self._config = dict(CONFIG_DEFAULTS)
    try:
      with open(self._config_path) as f:
        data = json.load(f)
      if isinstance(data, dict):
        self._config.update(data)
    except (OSError, ValueError):
      pass

  def _save_config(self):
    """Atomic write (tempfile + os.replace), bump _version, set JetsonConfigChanged, push MQTT payload."""
    version_ms = time.time_ns() // 1_000_000
    self._config["_version"] = str(version_ms)

    directory = os.path.dirname(self._config_path)
    try:
      os.makedirs(directory, exist_ok=True)
      fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
      try:
        with os.fdopen(fd, "w") as f:
          json.dump(self._config, f, indent=4, sort_keys=True)
        os.replace(tmp_path, self._config_path)
      except Exception:
        if os.path.exists(tmp_path):
          os.remove(tmp_path)
        raise
    except OSError:
      return

    # Record our own write so the live-reload check does not treat it as external.
    self._config_mtime = self._current_mtime()
    ui_state.params.put_bool("JetsonConfigChanged", True)
    self._write_config_payload(version_ms)

  def _write_config_payload(self, version_ms: int):
    dongle = self._dongle_id()
    if not dongle:
      return
    payload = {
      "dongle_id": dongle,
      "jetson_enabled": bool(self._config.get("jetson_enabled", False)),
      "jetson_ip": str(self._config.get("jetson_ip", "")),
      "comma_ip": str(self._config.get("comma_ip", "")),
      "jetson_img_port": int(self._config.get("jetson_img_port", 5555)),
      "jetson_torque_port": int(self._config.get("jetson_torque_port", 5556)),
      "jpeg_quality": int(self._config.get("jpeg_quality", 80)),
      "source": "comma_ui",
      "timestamp": str(time.time_ns() // 1_000_000),
      "_version": str(version_ms),
    }
    ui_state.params.put("JetsonConfigMqttPayload", json.dumps(payload))

  def _edit_config_field(self, key: str, title: str, is_int: bool, clamp: tuple[int, int] | None = None,
                         step: int | None = None):
    current = str(self._config.get(key, CONFIG_DEFAULTS.get(key, "")))

    def on_input(result: DialogResult, text: str):
      if result != DialogResult.CONFIRM:
        return
      text = text.strip()
      if not text:
        return
      if is_int:
        try:
          value = int(text)
        except ValueError:
          return
        if step:
          value = int(round(value / step) * step)
        if clamp:
          value = max(clamp[0], min(clamp[1], value))
        self._config[key] = value
      else:
        self._config[key] = text
      self._save_config()

    dialog = InputDialogSP(title, current_text=current, min_text_size=1, callback=on_input)
    dialog.show()

  # ------------------------------------------------------------- lifecycle
  def _update_state(self):
    super()._update_state()
    self._frame += 1
    if self._frame % PARAM_READ_INTERVAL_FRAMES == 0:
      self._refresh_live_status()
      # Live-reload config_jetson.json if an external writer (e.g. MQTT bridge, or el
      # interruptor de privacidad) changed it while the panel is open. Saving merges
      # keys, so this is safe even mid-edit; our own writes update _config_mtime to
      # avoid self-triggering.
      mtime = self._current_mtime()
      if mtime and mtime != self._config_mtime:
        self._config_mtime = mtime
        self._load_config()
        self._sync_jetson_enabled()

  def _render(self, rect):
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
    self._load_config()
    self._config_mtime = self._current_mtime()
    self._sync_jetson_enabled()
    self._refresh_live_status()
    self._scroller.show_event()
