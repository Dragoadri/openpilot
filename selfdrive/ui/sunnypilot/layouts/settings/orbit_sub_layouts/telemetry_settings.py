"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Subpanel de canales de telemetria ORBIT.

Toggles por canal que gobiernan que canales cereal publica el emisor MQTT
(orbit/mqtt_envio_general.py, via _canal_habilitado("<canal>_toggle")). La
lista refleja orbit/canales.json; el heartbeat de presencia (carState cada 3 s
en parado) se publica siempre, independientemente de estos toggles.
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

# Escrito por orbit/camera_sender.py (_save_config); aqui solo lectura.
CAMERA_CONFIG_FILE = "/data/orbit_camera_config.json"

# (param, titulo, descripcion) — alineado con orbit/canales.json.
TELEMETRY_TOGGLES = [
  ("carState_toggle", "carState", "Publica el estado del vehiculo (velocidad, pedales, volante) por MQTT."),
  ("carControl_toggle", "carControl", "Publica las ordenes de control enviadas al coche por MQTT."),
  ("gpsLocationExternal_toggle", "gpsLocationExternal", "Publica la localizacion GPS externa por MQTT."),
  ("gpsLocation_toggle", "gpsLocation", "Publica la localizacion GPS del dispositivo por MQTT."),
  ("radarState_toggle", "radarState", "Publica los objetivos del radar por MQTT."),
  ("drivingModelData_toggle", "drivingModelData", "Publica la salida del modelo de conduccion por MQTT."),
  ("controlsState_toggle", "controlsState", "Publica el estado interno del control por MQTT."),
  ("liveCalibration_toggle", "liveCalibration", "Publica la calibracion en vivo por MQTT."),
]


class TelemetrySettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)

    self._camera_cfg: dict = {}
    self._camera_cfg_read_ts = 0.0

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

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
