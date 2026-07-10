"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

OrbitLayout - panel ORBIT de los ajustes (antes UemLayout / "UEM").

Panel principal de la integracion ORBIT: cabecera hero con el estado en vivo
(servidor, enlace MQTT, cuenta vinculada, Jetson) y secciones CONEXION /
TELEMETRIA / CONDUCCION / JETSON / PRUEBAS. Los subpaneles (canales de
telemetria y Jetson) se despachan con el patron IntEnum de steering.py.
"""
import time
from enum import IntEnum

import pyray as rl

from openpilot.selfdrive.ui.layouts.settings import settings as OP
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.widgets.orbit_section import SectionHeaderSP
from openpilot.selfdrive.ui.widgets.orbit_server import ServerMonitor
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, button_item_sp
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import text_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.orbit_sub_layouts.jetson_settings import (
  JetsonSettingsLayout,
  MODE_NAMES,
  TORQUE_STALE_SECONDS,
)
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.orbit_sub_layouts.server_settings import ServerRows
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.orbit_sub_layouts.telemetry_settings import TelemetrySettingsLayout

_REFRESH_SECONDS = 2.0
_HERO_HEIGHT = 260
# El heartbeat MQTT escribe OrbitLastPublish cada ~3 s; sin dato fresco en 30 s
# el enlace se considera caido aunque OrbitConnected quedara en True (el
# proceso pudo morir sin escribir el False de despedida).
_LINK_STALE_SECONDS = 30.0


def _publish_age(params) -> float:
  """Segundos desde el ultimo publish MQTT; inf si no hay dato."""
  try:
    last = params.get("OrbitLastPublish")
    if last:
      return max(0.0, time.time() - float(last))
  except Exception:
    pass
  return float("inf")


class PanelType(IntEnum):
  MAIN = 0
  JETSON = 1
  TELEMETRY = 2


class _OrbitHero(Widget):
  """Tarjeta de cabecera: logo + wordmark + chips de estado en vivo.

  Todo el estado se refresca como mucho cada _REFRESH_SECONDS (nunca por
  frame); el probe del servidor lo hace ServerMonitor en su propio hilo.
  """

  def __init__(self, monitor: ServerMonitor):
    super().__init__()
    self._rect = rl.Rectangle(0, 0, 0, _HERO_HEIGHT)
    self._monitor = monitor
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font = gui_app.font(FontWeight.NORMAL)
    try:
      self._logo = gui_app.texture("img_orbit_logo.png", 128, 128)
    except Exception:
      self._logo = None

    self._last_refresh = 0.0
    self._chips: list[tuple[str, bool]] = []

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _refresh(self):
    now = time.monotonic()
    if now - self._last_refresh < _REFRESH_SECONDS:
      return
    self._last_refresh = now

    params = ui_state.params
    connected = params.get_bool("OrbitConnected") and _publish_age(params) <= _LINK_STALE_SECONDS
    owner = params.get("OrbitOwner")
    owner = owner.strip() if isinstance(owner, str) else ""

    torque_fresh = False
    try:
      ts = params.get("JetsonTorqueTimestamp")
      torque_fresh = bool(ts) and (time.time() - float(ts)) <= TORQUE_STALE_SECONDS
    except Exception:
      torque_fresh = False

    server_ok = self._monitor.broker_ok and self._monitor.backend_ok
    cuenta = owner.split()[0][:14].upper() if owner else tr("SIN VINCULAR")

    self._chips = [
      (tr("SERVIDOR"), server_ok),
      (tr("ENLACE"), connected),
      (cuenta, bool(owner)),
      (tr("JETSON"), torque_fresh),
    ]

  def _render(self, _):
    self._refresh()
    card = rl.Rectangle(self._rect.x, self._rect.y + 8, self._rect.width, self._rect.height - 16)
    rl.draw_rectangle_rounded(card, 0.12, 12, OP.ORBIT_NAVY)
    rl.draw_rectangle_rounded_lines_ex(card, 0.12, 12, 2, OP.ORBIT_HAIRLINE)

    pad = 32
    logo_size = 128
    text_x = card.x + pad
    if self._logo is not None:
      rl.draw_texture_pro(
        self._logo,
        rl.Rectangle(0, 0, self._logo.width, self._logo.height),
        rl.Rectangle(card.x + pad, card.y + (card.height - logo_size) / 2 - 20, logo_size, logo_size),
        rl.Vector2(0, 0), 0, rl.WHITE,
      )
      text_x = card.x + pad + logo_size + 30

    title_y = card.y + 42
    rl.draw_text_ex(self._font_bold, "ORBIT", rl.Vector2(text_x, title_y), 60, 4, OP.ORBIT_INK)
    subtitle_y = title_y + measure_text_cached(self._font_bold, "ORBIT", 60, 4).y + 6
    rl.draw_text_ex(self._font, tr("Estacion de control del vehiculo"),
                    rl.Vector2(text_x, subtitle_y), 32, 0, OP.ORBIT_MUTED)

    # Chips de estado, fila inferior de la tarjeta.
    chip_h = 52
    chip_y = card.y + card.height - chip_h - 24
    x = card.x + pad
    for label, ok in self._chips:
      size = measure_text_cached(self._font_bold, label, 28, 1)
      chip_w = size.x + chip_h + 26
      if x + chip_w > card.x + card.width - pad:
        break
      chip_rect = rl.Rectangle(x, chip_y, chip_w, chip_h)
      rl.draw_rectangle_rounded(chip_rect, 1.0, 12, OP.ORBIT_VOID)
      rl.draw_rectangle_rounded_lines_ex(chip_rect, 1.0, 12, 2, OP.ORBIT_HAIRLINE)
      dot_color = OP.ORBIT_GREEN if ok else rl.Color(OP.ORBIT_MUTED.r, OP.ORBIT_MUTED.g, OP.ORBIT_MUTED.b, 120)
      rl.draw_circle(int(x + 26), int(chip_y + chip_h / 2), 8, dot_color)
      text_color = OP.ORBIT_INK if ok else OP.ORBIT_MUTED
      rl.draw_text_ex(self._font_bold, label,
                      rl.Vector2(x + 44, chip_y + (chip_h - size.y) / 2), 28, 1, text_color)
      x += chip_w + 16


class OrbitLayout(Widget):
  def __init__(self):
    super().__init__()

    self._current_panel = PanelType.MAIN
    self._jetson_layout = JetsonSettingsLayout(lambda: self._set_current_panel(PanelType.MAIN))
    self._telemetry_layout = TelemetrySettingsLayout(lambda: self._set_current_panel(PanelType.MAIN))

    self._monitor = ServerMonitor()
    self._server_rows = ServerRows()

    self._last_refresh = 0.0
    self._telemetry_status = ""
    self._jetson_status = "-"

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  def _initialize_items(self):
    self._hero = _OrbitHero(self._monitor)

    self._telemetry_row = text_item(
      lambda: tr("Estado"),
      lambda: self._telemetry_status,
      description=lambda: tr("La telemetria se publica al broker ORBIT; el heartbeat de presencia va siempre."),
    )
    self._telemetry_button = button_item_sp(
      title=lambda: tr("Canales de telemetria"),
      button_text=lambda: tr("ABRIR"),
      description=lambda: tr("Elige que canales cereal se publican por MQTT."),
      callback=lambda: self._set_current_panel(PanelType.TELEMETRY),
    )

    self._show_blindspot_toggle = toggle_item_sp(
      param="show_blindspot",
      title=lambda: tr("MOSTRAR ANGULO MUERTO"),
      description=lambda: tr("Muestra el estado del angulo muerto en la pantalla de conduccion."),
    )
    self._lane_warn_toggle = toggle_item_sp(
      param="c_carril",
      title=lambda: tr("AVISOS EN CAMBIO DE CARRIL"),
      description=lambda: tr("Anade avisos en pantalla si hay un vehiculo en el angulo muerto durante un cambio de carril."),
    )

    self._jetson_row = text_item(
      lambda: tr("Estado"),
      lambda: self._jetson_status,
      description=lambda: tr("Modo de control del volante y enlace con la Jetson."),
    )
    self._jetson_button = button_item_sp(
      title=lambda: tr("Configurar Jetson"),
      button_text=lambda: tr("ABRIR"),
      description=lambda: tr("Modo de volante, IPs, puertos y calidad de imagen."),
      callback=lambda: self._set_current_panel(PanelType.JETSON),
    )

    self._modo_debug_toggle = toggle_item_sp(
      param="modo_debug",
      title=lambda: tr("MODO DEBUG"),
      description=lambda: tr("Muestra los mensajes MQTT recibidos en la pantalla de conduccion."),
    )
    self._silenciar_alertas_toggle = toggle_item_sp(
      param="silenciar_alertas_comm",
      title=lambda: tr("SILENCIAR ALERTAS DE COMUNICACION"),
      description=lambda: tr("Oculta commIssue y errores temporales de locationd/paramsd. Solo para pruebas: " +
                             "si aparecen constantemente hay un problema real (ver tools/orbit)."),
    )

    return [
      self._hero,
      SectionHeaderSP(tr("CONEXION")),
      *self._server_rows.items,
      SectionHeaderSP(tr("TELEMETRIA")),
      self._telemetry_row,
      self._telemetry_button,
      SectionHeaderSP(tr("CONDUCCION")),
      self._show_blindspot_toggle,
      self._lane_warn_toggle,
      SectionHeaderSP(tr("JETSON")),
      self._jetson_row,
      self._jetson_button,
      SectionHeaderSP(tr("PRUEBAS")),
      self._modo_debug_toggle,
      self._silenciar_alertas_toggle,
    ]

  # ------------------------------------------------------------ estado vivo
  def _refresh_status(self):
    now = time.monotonic()
    if now - self._last_refresh < _REFRESH_SECONDS:
      return
    self._last_refresh = now
    params = ui_state.params

    age = _publish_age(params)
    if params.get_bool("OrbitConnected") and age <= _LINK_STALE_SECONDS:
      self._telemetry_status = tr("Conectado") + " - " + tr("ultimo dato hace") + f" {int(age)}s"
    else:
      self._telemetry_status = tr("Sin conexion con el broker")

    try:
      mode = int(params.get("SteerTorqueMode") or 0)
    except (TypeError, ValueError):
      mode = 0
    jetson_txt = MODE_NAMES.get(mode, "-")
    try:
      ts = params.get("JetsonTorqueTimestamp")
      if ts and (time.time() - float(ts)) <= TORQUE_STALE_SECONDS:
        jetson_txt += " - " + tr("torque OK")
    except Exception:
      pass
    self._jetson_status = jetson_txt

  # -------------------------------------------------------------- lifecycle
  def _set_current_panel(self, panel: PanelType):
    self._current_panel = panel

  def _render(self, rect):
    if self._current_panel == PanelType.JETSON:
      self._jetson_layout.render(rect)
    elif self._current_panel == PanelType.TELEMETRY:
      self._telemetry_layout.render(rect)
    else:
      self._refresh_status()
      self._server_rows.poll()
      self._scroller.render(rect)

  def show_event(self):
    self._set_current_panel(PanelType.MAIN)
    self._last_refresh = 0.0
    self._scroller.show_event()
