"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from dataclasses import dataclass
from enum import IntEnum
import math
import time

import pyray as rl
from openpilot.selfdrive.ui.layouts.settings import settings as OP
from openpilot.selfdrive.ui.layouts.settings.firehose import FirehoseLayout
from openpilot.selfdrive.ui.layouts.settings.toggles import TogglesLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.cruise import CruiseLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.developer import DeveloperLayoutSP
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.device import DeviceLayoutSP
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.display import DisplayLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.models import ModelsLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.network import NetworkUISP
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.osm import OSMLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.software import SoftwareLayoutSP
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.steering import SteeringLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.sunnylink import SunnylinkLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.trips import TripsLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.uem import UemLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle import VehicleLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.visuals import VisualsLayout
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.system.ui.lib.multilang import tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wifi_manager import WifiManager
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.selfdrive.ui.widgets import orbit_fx as fx

# from openpilot.selfdrive.ui.sunnypilot.layouts.settings.navigation import NavigationLayout

OP.PANEL_COLOR = rl.Color(13, 20, 34, 255)   # ORBIT dark ground (was near-black)
ICON_SIZE = 64
NAV_TILE_INSET = 15          # vertical inset per allocated row → top/bottom margin between tiles
NAV_TILE_H_INSET = 12        # horizontal inset → side margin so tiles float inside the rail
MARKER_ANIM_S = 0.22     # cyan marker slide between tiles
PANEL_ANIM_S = 0.22      # panel slide+fade on tab change
PANEL_SLIDE_PX = 36.0

OP.PanelType = IntEnum(
  "PanelType",
  [es.name for es in OP.PanelType] + [
    "SUNNYLINK",
    "MODELS",
    "STEERING",
    "CRUISE",
    "VISUALS",
    "DISPLAY",
    "OSM",
    "NAVIGATION",
    "TRIPS",
    "VEHICLE",
    "UEM",
  ],
  start=0,
)


@dataclass
class PanelInfo(OP.PanelInfo):
  icon: str = ""


class NavButton(Widget):
  def __init__(self, parent, p_type, p_info):
    super().__init__()
    self.parent = parent
    self.panel_type = p_type
    self.panel_info = p_info

  def _render(self, rect):
    # Mockup "menu tile" (artifact 5212ff09, screen 02): full-width target, icon
    # chip on the left, ORBIT panel background + hairline border + cyan marker bar
    # and cyan icon/label when selected; muted chip + muted label when not.
    is_selected = self.panel_type == self.parent._current_panel
    mouse_down = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)
    hovered = rl.check_collision_point_rec(rl.get_mouse_position(), rect)

    # Inset the visible tile on all four sides so consecutive tiles read as
    # clearly separated cards that float inside the rail (margin top/bottom/sides).
    # The click target stays the full allocated row for an easy tap.
    tile = rl.Rectangle(rect.x + NAV_TILE_H_INSET, rect.y + NAV_TILE_INSET,
                        rect.width - 2 * NAV_TILE_H_INSET, rect.height - 2 * NAV_TILE_INSET)
    self.panel_info.button_rect = rect  # click detection maps to the allocated rect

    if is_selected:
      rl.draw_rectangle_rounded(tile, 0.24, 12, OP.ORBIT_PANEL)
      rl.draw_rectangle_rounded_lines_ex(tile, 0.24, 12, 2, OP.ORBIT_HAIRLINE)
      # (cyan marker bar + halo now drawn by the sidebar so it can slide between tiles)
    elif hovered and mouse_down:
      pressed = rl.Rectangle(tile.x + 2, tile.y + 2, tile.width - 4, tile.height - 4)
      rl.draw_rectangle_rounded(pressed, 0.24, 12, OP.ORBIT_NAVY)

    # Icon chip: cyan-tinted when selected (rgba .16), muted-tinted otherwise (.10)
    chip = tile.height * 0.62
    chip_rect = rl.Rectangle(tile.x + 26, tile.y + (tile.height - chip) / 2, chip, chip)
    if is_selected:
      chip_a = int(41 + 14 * math.sin(time.monotonic() * 2.4))
      chip_bg = rl.Color(OP.ORBIT_CYAN.r, OP.ORBIT_CYAN.g, OP.ORBIT_CYAN.b, chip_a)
    else:
      chip_bg = rl.Color(OP.ORBIT_MUTED.r, OP.ORBIT_MUTED.g, OP.ORBIT_MUTED.b, 26)
    rl.draw_rectangle_rounded(chip_rect, 0.28, 10, chip_bg)

    if self.panel_info.icon:
      icon_texture = gui_app.texture(self.panel_info.icon, ICON_SIZE, ICON_SIZE, keep_aspect_ratio=True)
      tint = OP.ORBIT_CYAN if is_selected else OP.ORBIT_MUTED
      rl.draw_texture_ex(
        icon_texture,
        rl.Vector2(chip_rect.x + (chip - icon_texture.width) / 2, chip_rect.y + (chip - icon_texture.height) / 2),
        0.0, 1.0, tint,
      )

    # Label
    label = self.panel_info.name
    lb_h = measure_text_cached(self.parent._font_bold, label, 48).y
    text_color = OP.ORBIT_INK if is_selected else OP.ORBIT_MUTED
    rl.draw_text_ex(self.parent._font_bold, label,
                    rl.Vector2(chip_rect.x + chip + 28, rect.y + (rect.height - lb_h) / 2), 48, 0, text_color)


class SettingsLayoutSP(OP.SettingsLayout):
  def __init__(self):
    OP.SettingsLayout.__init__(self)
    self._nav_items: list[Widget] = []
    # Marker-slide + panel-transition animation state
    self._marker_prev = self._current_panel
    self._marker_t0 = 0.0
    self._panel_switch_t0 = 0.0

    # Create sidebar scroller
    self._sidebar_scroller = Scroller([], spacing=0, line_separator=False, pad_end=False)

    # Panel configuration
    wifi_manager = WifiManager()
    wifi_manager.set_active(False)

    self._panels = {
      OP.PanelType.UEM: PanelInfo(tr_noop("UEM"), UemLayout(), icon="icons/link.png"),
      OP.PanelType.DEVICE: PanelInfo(tr_noop("Device"), DeviceLayoutSP(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_home.png"),
      OP.PanelType.NETWORK: PanelInfo(tr_noop("Network"), NetworkUISP(wifi_manager), icon="icons/network.png"),
      OP.PanelType.SUNNYLINK: PanelInfo(tr_noop("sunnylink"), SunnylinkLayout(), icon="icons/wifi_strength_full.png"),
      OP.PanelType.TOGGLES: PanelInfo(tr_noop("Toggles"), TogglesLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_toggle.png"),
      OP.PanelType.SOFTWARE: PanelInfo(tr_noop("Software"), SoftwareLayoutSP(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_software.png"),
      OP.PanelType.MODELS: PanelInfo(tr_noop("Models"), ModelsLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_models.png"),
      OP.PanelType.STEERING: PanelInfo(tr_noop("Steering"), SteeringLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_lateral.png"),
      OP.PanelType.CRUISE: PanelInfo(tr_noop("Cruise"), CruiseLayout(), icon="icons/speed_limit.png"),
      OP.PanelType.VISUALS: PanelInfo(tr_noop("Visuals"), VisualsLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_visuals.png"),
      OP.PanelType.DISPLAY: PanelInfo(tr_noop("Display"), DisplayLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_display.png"),
      OP.PanelType.OSM: PanelInfo(tr_noop("OSM"), OSMLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_map.png"),
      # OP.PanelType.NAVIGATION: PanelInfo(tr_noop("Navigation"), NavigationLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_map.png"),
      OP.PanelType.TRIPS: PanelInfo(tr_noop("Trips"), TripsLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_trips.png"),
      OP.PanelType.VEHICLE: PanelInfo(tr_noop("Vehicle"), VehicleLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_vehicle.png"),
      OP.PanelType.FIREHOSE: PanelInfo(tr_noop("Firehose"), FirehoseLayout(), icon="../../sunnypilot/selfdrive/assets/offroad/icon_firehose.png"),
      OP.PanelType.DEVELOPER: PanelInfo(tr_noop("Developer"), DeveloperLayoutSP(), icon="icons/shell.png"),
    }

  def _draw_sidebar(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, OP.SIDEBAR_COLOR)
    # Subtle vertical light so the rail reads as lit from above
    rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y), int(rect.width), int(rect.height * 0.45),
                                 rl.Color(27, 44, 72, 70), rl.Color(27, 44, 72, 0))
    mouse_pos = rl.get_mouse_position()
    mouse_down = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)

    # --- ORBIT brand header (logo + wordmark) ---
    logo_x = rect.x + OP.SB_PAD
    logo_y = rect.y + 40
    if self._logo is not None:
      rl.draw_texture_pro(
        self._logo,
        rl.Rectangle(0, 0, self._logo.width, self._logo.height),
        rl.Rectangle(logo_x, logo_y, OP.LOGO_SIZE, OP.LOGO_SIZE),
        rl.Vector2(0, 0), 0, rl.WHITE,
      )
    wm_h = measure_text_cached(self._font_bold, "ORBIT", 64).y
    rl.draw_text_ex(self._font_bold, "ORBIT",
                    rl.Vector2(logo_x + OP.LOGO_SIZE + 22, logo_y + (OP.LOGO_SIZE - wm_h) / 2),
                    64, 4, OP.ORBIT_INK)
    # No hairline under the brand: the mockup separates brand from nav by spacing only.
    sep_y = logo_y + OP.LOGO_SIZE + 20

    # --- Close button (bottom, full-width ORBIT style; reused from the base) ---
    close_top = rect.y + rect.height - OP.CLOSE_BTN_H - OP.CLOSE_BTN_MARGIN
    close_btn_rect = rl.Rectangle(rect.x + OP.SB_PAD, close_top, rect.width - 2 * OP.SB_PAD, OP.CLOSE_BTN_H)
    self._close_btn_rect = close_btn_rect
    self._draw_close_button(close_btn_rect, mouse_pos, mouse_down)

    # --- Navigation tiles (scrollable; the SP build has ~16 panels) ---
    if not self._nav_items:
      for panel_type, panel_info in self._panels.items():
        nav_button = NavButton(self, panel_type, panel_info)
        nav_button.rect.width = rect.width - 2 * OP.SB_PAD
        nav_button.rect.height = OP.NAV_BTN_HEIGHT
        self._nav_items.append(nav_button)
        self._sidebar_scroller.add_widget(nav_button)

    nav_top = sep_y + 22
    nav_rect = rl.Rectangle(rect.x + OP.SB_PAD, nav_top, rect.width - 2 * OP.SB_PAD, close_top - 22 - nav_top)
    if self._nav_items:
      self._sidebar_scroller.render(nav_rect)
      self._draw_nav_marker(nav_rect)

  def _draw_nav_marker(self, nav_rect: rl.Rectangle):
    """Cyan selection marker + halo, drawn over the rail so it can slide with
    easing between the previous and the current tile. button_rects are updated
    every frame by the scroller, so the marker follows scrolling too."""
    cur = self._panels[self._current_panel].button_rect
    if cur.width <= 0:
      return
    prev = self._panels[self._marker_prev].button_rect
    t = fx.clamp01((time.monotonic() - self._marker_t0) / MARKER_ANIM_S)
    if prev.width <= 0 or t >= 1.0:
      row = cur
    else:
      e = fx.ease_out_cubic(t)
      row = rl.Rectangle(prev.x + (cur.x - prev.x) * e, prev.y + (cur.y - prev.y) * e,
                         prev.width + (cur.width - prev.width) * e,
                         prev.height + (cur.height - prev.height) * e)
    tile_y = row.y + NAV_TILE_INSET
    tile_h = row.height - 2 * NAV_TILE_INSET
    bar = rl.Rectangle(row.x + NAV_TILE_H_INSET + 3, tile_y + tile_h * 0.18, 11, tile_h * 0.64)
    halo = rl.Rectangle(bar.x - 3, bar.y - 3, bar.width + 6, bar.height + 6)
    rl.begin_scissor_mode(int(nav_rect.x), int(nav_rect.y), int(nav_rect.width), int(nav_rect.height))
    rl.draw_rectangle_rounded(halo, 1.0, 8, rl.Color(OP.ORBIT_CYAN.r, OP.ORBIT_CYAN.g, OP.ORBIT_CYAN.b, 55))
    rl.draw_rectangle_rounded(bar, 1.0, 8, OP.ORBIT_CYAN)
    rl.end_scissor_mode()

  def set_current_panel(self, panel_type):
    if panel_type != self._current_panel:
      self._marker_prev = self._current_panel
      now = time.monotonic()
      self._marker_t0 = now
      self._panel_switch_t0 = now
    super().set_current_panel(panel_type)

  def _draw_current_panel(self, rect: rl.Rectangle):
    bg = rl.Rectangle(rect.x + 10, rect.y + 10, rect.width - 20, rect.height - 20)
    rl.draw_rectangle_rounded(bg, 0.04, 30, OP.PANEL_COLOR)
    content_rect = rl.Rectangle(rect.x + OP.PANEL_MARGIN, rect.y + 25,
                                rect.width - (OP.PANEL_MARGIN * 2), rect.height - 50)
    panel = self._panels[self._current_panel]
    if not panel.instance:
      return
    t = fx.clamp01((time.monotonic() - self._panel_switch_t0) / PANEL_ANIM_S)
    if t >= 1.0:
      panel.instance.render(content_rect)
      return
    e = fx.ease_out_cubic(t)
    rl.begin_scissor_mode(int(bg.x), int(bg.y), int(bg.width), int(bg.height))
    panel.instance.render(rl.Rectangle(content_rect.x + (1.0 - e) * PANEL_SLIDE_PX, content_rect.y,
                                       content_rect.width, content_rect.height))
    # Fade-from-dark overlay while the panel slides in
    rl.draw_rectangle_rounded(bg, 0.04, 30,
                              rl.Color(OP.PANEL_COLOR.r, OP.PANEL_COLOR.g, OP.PANEL_COLOR.b,
                                       int(150 * (1.0 - e))))
    rl.end_scissor_mode()

  def _handle_mouse_release(self, mouse_pos: MousePos) -> bool:
    # Check close button
    if rl.check_collision_point_rec(mouse_pos, self._close_btn_rect):
      if self._close_callback:
        self._close_callback()
      return True

    # Check navigation buttons
    for panel_type, panel_info in self._panels.items():
      if rl.check_collision_point_rec(mouse_pos, panel_info.button_rect) and self._sidebar_scroller.scroll_panel.is_touch_valid():
        self.set_current_panel(panel_type)
        return True

    return False

  def show_event(self):
    super().show_event()
    self._panels[self._current_panel].instance.show_event()
    self._sidebar_scroller.show_event()
