"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

TelUemSettings sub-panel (SIC-UEM / Orbit).

Port of the old Qt TelUemSettings (selfdrive/ui/sunnypilot/qt/offroad/settings/
sunnypilot/teluem_settings.cc). Per-channel telemetry toggles that gate which
cereal channels the SIC-UEM MQTT sender (orbit/mqtt_envio_general.py)
publishes.

Faithful port: the original bool toggles in the original order. The original was a
pure ParamControlSP binding with no extra logic (updateToggles() was empty), so
this is a layout-only port. All params already exist in common/params_keys.h as
{PERSISTENT, BOOL}.

Note: the migrated backend also reads controlsState_toggle / liveCalibration_toggle,
but the original TelUem panel never exposed them, so they are
intentionally left out here to stay faithful to the original UI. intervalos_toggle
is also written programmatically by the backend; it is kept as a toggle to match
the original, but the backend may override it.
"""
import json
import time
from collections.abc import Callable

import pyray as rl

from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import text_item
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller

# Written by orbit/camera_sender.py (_save_config); read-only here.
CAMERA_CONFIG_FILE = "/data/orbit_camera_config.json"

# (param, title, description) in the original order (teluem_settings.cc:49-101)
TELEMETRY_TOGGLES = [
  ("intervalos_toggle", "INTERVALOS", "Controla el envio de telemetria por intervalos de tiempo."),
  ("lider_toggle", "LIDER", "Publica el estado del modo lider por MQTT."),
  ("carState_toggle", "CarState UEM", "Publica el canal carState por MQTT."),
  ("carControl_toggle", "carControl UEM", "Publica el canal carControl por MQTT."),
  ("gpsLocationExternal_toggle", "GPSLocation UEM", "Publica la localizacion GPS externa por MQTT."),
  ("radarState_toggle", "radarState UEM", "Publica el canal radarState por MQTT."),
  ("drivingModelData_toggle", "drivingModelData UEM", "Publica los datos del modelo de conduccion por MQTT."),
  ("mapbox_toggle", "RESPUESTA MAPBOX", "Publica la respuesta de Mapbox por MQTT."),
]


class TelUemSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)

    self._camera_cfg: dict = {}
    self._camera_cfg_read_ts = 0.0

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    items = []
    for param, title, desc in TELEMETRY_TOGGLES:
      items.append(toggle_item_sp(
        param=param,
        title=lambda t=title: tr(t),
        description=lambda d=desc: tr(d),
      ))
    items.append(text_item(
      lambda: tr("Envio de camara a ORBIT"),
      self._camera_status_text,
      description=lambda: tr("Estado actual del envio de imagenes a la app ORBIT (se controla remotamente desde la app)."),
    ))
    return items

  def _camera_status_text(self) -> str:
    now = time.monotonic()
    if now - self._camera_cfg_read_ts > 1.0:
      self._camera_cfg_read_ts = now
      try:
        with open(CAMERA_CONFIG_FILE) as f:
          data = json.load(f)
        self._camera_cfg = data if isinstance(data, dict) else {}
      except (OSError, ValueError):
        self._camera_cfg = {}

    cfg = self._camera_cfg
    if not cfg.get("image_sending_enabled", False):
      return tr("INACTIVO")
    try:
      freq = int(cfg.get("send_frequency_seconds", 2))
    except (TypeError, ValueError):
      freq = 2
    cam = str(cfg.get("camera_type") or "road")
    return tr("ACTIVO") + f" - {cam}, " + tr("cada") + f" {freq}s"

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
    self._scroller.show_event()
