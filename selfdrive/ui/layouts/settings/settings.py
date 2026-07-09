import pyray as rl
from dataclasses import dataclass
from enum import IntEnum
from collections.abc import Callable
from openpilot.selfdrive.ui.layouts.settings.developer import DeveloperLayout
from openpilot.selfdrive.ui.layouts.settings.device import DeviceLayout
from openpilot.selfdrive.ui.layouts.settings.firehose import FirehoseLayout
from openpilot.selfdrive.ui.layouts.settings.software import SoftwareLayout
from openpilot.selfdrive.ui.layouts.settings.toggles import TogglesLayout
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wifi_manager import WifiManager
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.network import NetworkUI

# Constants
SIDEBAR_WIDTH = 560
CLOSE_ICON_SIZE = 46
PANEL_MARGIN = 50

# Sidebar geometry
SB_PAD = 32              # left/right padding inside the sidebar
LOGO_SIZE = 80           # ORBIT logo texture size
NAV_TOP = 180            # offset from sidebar top where nav tiles begin
NAV_TILE_MAX_H = 150     # cap for a nav tile height
NAV_TILE_GAP = 18        # vertical gap between tiles
CLOSE_BTN_H = 92         # close button height
CLOSE_BTN_MARGIN = 32    # gap from bottom edge

# ORBIT palette (dark "in-car ground station")
ORBIT_VOID = rl.Color(11, 18, 32, 255)       # #0B1220
ORBIT_NAVY = rl.Color(22, 35, 58, 255)        # #16233A
ORBIT_PANEL = rl.Color(27, 44, 72, 255)       # #1B2C48
ORBIT_HAIRLINE = rl.Color(43, 62, 95, 255)    # #2B3E5F
ORBIT_BLUE = rl.Color(125, 180, 255, 255)     # #7DB4FF telemetry/uplink
ORBIT_GREEN = rl.Color(74, 222, 128, 255)     # #4ADE80 commands/downlink
ORBIT_CYAN = rl.Color(34, 211, 238, 255)      # #22D3EE live pulse accent
ORBIT_INK = rl.Color(226, 236, 255, 255)      # #E2ECFF
ORBIT_MUTED = rl.Color(147, 180, 230, 255)    # #93B4E6

# Aliases kept for the (unchanged-behavior) right-hand panel card
SIDEBAR_COLOR = ORBIT_VOID
PANEL_COLOR = ORBIT_NAVY

# Compat constants for the sunnypilot settings layer (SettingsLayoutSP), which
# still references these upstream names via `settings as OP`. The ORBIT rewrite
# of this module dropped them; re-add them mapped to the ORBIT palette so the SP
# sidebar renders in ORBIT colors instead of crashing on missing attributes.
NAV_BTN_HEIGHT = 110
CLOSE_BTN_COLOR = ORBIT_PANEL
CLOSE_BTN_PRESSED = ORBIT_HAIRLINE
TEXT_NORMAL = ORBIT_MUTED
TEXT_SELECTED = ORBIT_INK


class PanelType(IntEnum):
  DEVICE = 0
  NETWORK = 1
  TOGGLES = 2
  SOFTWARE = 3
  FIREHOSE = 4
  DEVELOPER = 5


# Accent color for each section's icon chip
NAV_ACCENT = {
  PanelType.DEVICE: ORBIT_BLUE,
  PanelType.NETWORK: ORBIT_CYAN,
  PanelType.TOGGLES: ORBIT_GREEN,
  PanelType.SOFTWARE: ORBIT_BLUE,
  PanelType.FIREHOSE: ORBIT_GREEN,
  PanelType.DEVELOPER: ORBIT_MUTED,
}


@dataclass
class PanelInfo:
  name: str
  instance: Widget
  button_rect: rl.Rectangle = rl.Rectangle(0, 0, 0, 0)


class SettingsLayout(Widget):
  def __init__(self):
    super().__init__()
    self._current_panel = PanelType.DEVICE

    # Panel configuration
    wifi_manager = WifiManager()
    wifi_manager.set_active(False)

    self._panels = {
      PanelType.DEVICE: PanelInfo(tr_noop("Device"), DeviceLayout()),
      PanelType.NETWORK: PanelInfo(tr_noop("Network"), NetworkUI(wifi_manager)),
      PanelType.TOGGLES: PanelInfo(tr_noop("Toggles"), TogglesLayout()),
      PanelType.SOFTWARE: PanelInfo(tr_noop("Software"), SoftwareLayout()),
      PanelType.FIREHOSE: PanelInfo(tr_noop("Firehose"), FirehoseLayout()),
      PanelType.DEVELOPER: PanelInfo(tr_noop("Developer"), DeveloperLayout()),
    }

    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._close_icon = gui_app.texture("icons/close2.png", CLOSE_ICON_SIZE, CLOSE_ICON_SIZE)

    # ORBIT brand logo (512x512 RGBA) rendered small next to the wordmark
    try:
      self._logo = gui_app.texture("img_orbit_logo.png", LOGO_SIZE, LOGO_SIZE)
    except Exception:
      self._logo = None

    self._close_btn_rect = rl.Rectangle(0, 0, 0, 0)

    # Callbacks
    self._close_callback: Callable | None = None

  def set_callbacks(self, on_close: Callable):
    self._close_callback = on_close

  def _render(self, rect: rl.Rectangle):
    # Calculate layout
    sidebar_rect = rl.Rectangle(rect.x, rect.y, SIDEBAR_WIDTH, rect.height)
    panel_rect = rl.Rectangle(rect.x + SIDEBAR_WIDTH, rect.y, rect.width - SIDEBAR_WIDTH, rect.height)

    # Draw components
    self._draw_sidebar(sidebar_rect)
    self._draw_current_panel(panel_rect)

  def _draw_sidebar(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, SIDEBAR_COLOR)
    mouse_pos = rl.get_mouse_position()
    mouse_down = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)

    # --- ORBIT brand header: logo + wordmark ---
    logo_x = rect.x + SB_PAD
    logo_y = rect.y + 44
    if self._logo is not None:
      rl.draw_texture_pro(
        self._logo,
        rl.Rectangle(0, 0, self._logo.width, self._logo.height),
        rl.Rectangle(logo_x, logo_y, LOGO_SIZE, LOGO_SIZE),
        rl.Vector2(0, 0),
        0,
        rl.WHITE,
      )
    wordmark = "ORBIT"
    wm_size = 60
    wm_h = measure_text_cached(self._font_bold, wordmark, wm_size).y
    wm_pos = rl.Vector2(logo_x + LOGO_SIZE + 22, logo_y + (LOGO_SIZE - wm_h) / 2)
    rl.draw_text_ex(self._font_bold, wordmark, wm_pos, wm_size, 2, ORBIT_INK)

    # Hairline separator under the header
    sep_y = logo_y + LOGO_SIZE + 28
    rl.draw_line_ex(
      rl.Vector2(rect.x + SB_PAD, sep_y), rl.Vector2(rect.x + rect.width - SB_PAD, sep_y), 2, ORBIT_HAIRLINE
    )

    # --- Close button (bottom, clearly a button) ---
    close_top = rect.y + rect.height - CLOSE_BTN_H - CLOSE_BTN_MARGIN
    close_btn_rect = rl.Rectangle(rect.x + SB_PAD, close_top, rect.width - 2 * SB_PAD, CLOSE_BTN_H)
    self._close_btn_rect = close_btn_rect
    self._draw_close_button(close_btn_rect, mouse_pos, mouse_down)

    # --- Navigation tiles (big, full-width, tappable) ---
    nav_top = rect.y + NAV_TOP
    nav_bottom = close_top - 24
    n = len(self._panels)
    avail = nav_bottom - nav_top
    tile_h = min(NAV_TILE_MAX_H, (avail - NAV_TILE_GAP * (n - 1)) / n)
    tile_w = rect.width - 2 * SB_PAD

    y = nav_top
    for panel_type, panel_info in self._panels.items():
      tile_rect = rl.Rectangle(rect.x + SB_PAD, y, tile_w, tile_h)
      panel_info.button_rect = tile_rect  # click detection maps to the drawn rect
      is_selected = panel_type == self._current_panel
      hovered = rl.check_collision_point_rec(mouse_pos, tile_rect)
      accent = NAV_ACCENT[panel_type]

      # Tile background
      if is_selected:
        rl.draw_rectangle_rounded(tile_rect, 0.22, 16, ORBIT_PANEL)
      elif hovered and mouse_down:
        rl.draw_rectangle_rounded(tile_rect, 0.22, 16, ORBIT_NAVY)

      # Cyan left accent bar for the selected tile
      if is_selected:
        bar_h = tile_h * 0.5
        bar_rect = rl.Rectangle(tile_rect.x + 6, tile_rect.y + (tile_h - bar_h) / 2, 8, bar_h)
        rl.draw_rectangle_rounded(bar_rect, 1.0, 8, ORBIT_CYAN)

      # Icon chip on the left
      chip = tile_h * 0.58
      chip_rect = rl.Rectangle(tile_rect.x + 34, tile_rect.y + (tile_h - chip) / 2, chip, chip)
      chip_bg = rl.Color(accent.r, accent.g, accent.b, 46 if not is_selected else 74)
      rl.draw_rectangle_rounded(chip_rect, 0.3, 12, chip_bg)
      glyph_color = accent if is_selected else rl.Color(accent.r, accent.g, accent.b, 210)
      self._draw_nav_glyph(panel_type, chip_rect, glyph_color)

      # Label (left-aligned)
      label = tr(panel_info.name)
      lb_size = 44
      lb_h = measure_text_cached(self._font_bold, label, lb_size).y
      lb_pos = rl.Vector2(chip_rect.x + chip + 26, tile_rect.y + (tile_h - lb_h) / 2)
      text_color = ORBIT_INK if is_selected else ORBIT_MUTED
      rl.draw_text_ex(self._font_bold, label, lb_pos, lb_size, 0, text_color)

      y += tile_h + NAV_TILE_GAP

  def _draw_close_button(self, rect: rl.Rectangle, mouse_pos: rl.Vector2, mouse_down: bool):
    pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, rect)
    bg = ORBIT_PANEL if not pressed else ORBIT_HAIRLINE
    rl.draw_rectangle_rounded(rect, 0.35, 16, bg)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.35, 16, 2, ORBIT_HAIRLINE)

    label = tr("Close")
    lb_size = 42
    lb_w = measure_text_cached(self._font_bold, label, lb_size).x
    lb_h = measure_text_cached(self._font_bold, label, lb_size).y
    gap = 20
    group_w = self._close_icon.width + gap + lb_w
    start_x = rect.x + (rect.width - group_w) / 2

    icon_color = ORBIT_INK if not pressed else ORBIT_MUTED
    icon_dest = rl.Rectangle(
      start_x, rect.y + (rect.height - self._close_icon.height) / 2,
      self._close_icon.width, self._close_icon.height,
    )
    rl.draw_texture_pro(
      self._close_icon,
      rl.Rectangle(0, 0, self._close_icon.width, self._close_icon.height),
      icon_dest, rl.Vector2(0, 0), 0, icon_color,
    )
    lb_pos = rl.Vector2(start_x + self._close_icon.width + gap, rect.y + (rect.height - lb_h) / 2)
    rl.draw_text_ex(self._font_bold, label, lb_pos, lb_size, 0, icon_color)

  def _draw_nav_glyph(self, panel_type: PanelType, chip: rl.Rectangle, color: rl.Color):
    # Draw a simple geometric glyph inside the chip using raylib primitives.
    pad = chip.width * 0.24
    gx, gy = chip.x + pad, chip.y + pad
    gw, gh = chip.width - 2 * pad, chip.height - 2 * pad
    cx, cy = gx + gw / 2, gy + gh / 2
    th = max(3.0, chip.width * 0.075)

    if panel_type == PanelType.DEVICE:
      # Screen: rounded rect outline with a small stand
      screen = rl.Rectangle(gx, gy, gw, gh * 0.72)
      rl.draw_rectangle_rounded_lines_ex(screen, 0.18, 10, th, color)
      rl.draw_line_ex(rl.Vector2(cx - gw * 0.16, gy + gh), rl.Vector2(cx + gw * 0.16, gy + gh), th, color)
      rl.draw_line_ex(rl.Vector2(cx, gy + gh * 0.72), rl.Vector2(cx, gy + gh), th, color)

    elif panel_type == PanelType.NETWORK:
      # Wifi arcs radiating from a dot
      origin = rl.Vector2(cx, gy + gh * 0.92)
      for i, r in enumerate((gw * 0.5, gw * 0.34, gw * 0.18)):
        rl.draw_ring(origin, r - th, r, 235, 305, 24, color)
      rl.draw_circle(int(cx), int(origin.y), th * 0.85, color)

    elif panel_type == PanelType.TOGGLES:
      # Two slider tracks with knobs
      y1, y2 = gy + gh * 0.3, gy + gh * 0.7
      rl.draw_line_ex(rl.Vector2(gx, y1), rl.Vector2(gx + gw, y1), th, color)
      rl.draw_line_ex(rl.Vector2(gx, y2), rl.Vector2(gx + gw, y2), th, color)
      rl.draw_circle(int(gx + gw * 0.68), int(y1), th * 1.4, color)
      rl.draw_circle(int(gx + gw * 0.32), int(y2), th * 1.4, color)

    elif panel_type == PanelType.SOFTWARE:
      # Down-arrow into a tray (download)
      rl.draw_line_ex(rl.Vector2(cx, gy), rl.Vector2(cx, gy + gh * 0.62), th, color)
      rl.draw_line_ex(rl.Vector2(cx, gy + gh * 0.62), rl.Vector2(cx - gw * 0.22, gy + gh * 0.4), th, color)
      rl.draw_line_ex(rl.Vector2(cx, gy + gh * 0.62), rl.Vector2(cx + gw * 0.22, gy + gh * 0.4), th, color)
      rl.draw_line_ex(rl.Vector2(gx, gy + gh), rl.Vector2(gx + gw, gy + gh), th, color)

    elif panel_type == PanelType.FIREHOSE:
      # Up-arrow from a base (upload)
      rl.draw_line_ex(rl.Vector2(cx, gy + gh), rl.Vector2(cx, gy + gh * 0.28), th, color)
      rl.draw_line_ex(rl.Vector2(cx, gy + gh * 0.28), rl.Vector2(cx - gw * 0.22, gy + gh * 0.5), th, color)
      rl.draw_line_ex(rl.Vector2(cx, gy + gh * 0.28), rl.Vector2(cx + gw * 0.22, gy + gh * 0.5), th, color)
      rl.draw_line_ex(rl.Vector2(gx, gy), rl.Vector2(gx + gw, gy), th, color)

    else:  # DEVELOPER: code brackets < >
      rl.draw_line_ex(rl.Vector2(gx + gw * 0.34, gy), rl.Vector2(gx, cy), th, color)
      rl.draw_line_ex(rl.Vector2(gx, cy), rl.Vector2(gx + gw * 0.34, gy + gh), th, color)
      rl.draw_line_ex(rl.Vector2(gx + gw * 0.66, gy), rl.Vector2(gx + gw, cy), th, color)
      rl.draw_line_ex(rl.Vector2(gx + gw, cy), rl.Vector2(gx + gw * 0.66, gy + gh), th, color)

  def _draw_current_panel(self, rect: rl.Rectangle):
    rl.draw_rectangle_rounded(
      rl.Rectangle(rect.x + 10, rect.y + 10, rect.width - 20, rect.height - 20), 0.04, 30, PANEL_COLOR
    )
    content_rect = rl.Rectangle(rect.x + PANEL_MARGIN, rect.y + 25, rect.width - (PANEL_MARGIN * 2), rect.height - 50)
    # rl.draw_rectangle_rounded(content_rect, 0.03, 30, PANEL_COLOR)
    panel = self._panels[self._current_panel]
    if panel.instance:
      panel.instance.render(content_rect)

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    # Check close button
    if rl.check_collision_point_rec(mouse_pos, self._close_btn_rect):
      if self._close_callback:
        self._close_callback()
      return

    # Check navigation buttons
    for panel_type, panel_info in self._panels.items():
      if rl.check_collision_point_rec(mouse_pos, panel_info.button_rect):
        self.set_current_panel(panel_type)
        return

  def set_current_panel(self, panel_type: PanelType):
    if panel_type != self._current_panel:
      self._panels[self._current_panel].instance.hide_event()
      self._current_panel = panel_type
      self._panels[self._current_panel].instance.show_event()

  def show_event(self):
    super().show_event()
    self._panels[self._current_panel].instance.show_event()

  def hide_event(self):
    super().hide_event()
    self._panels[self._current_panel].instance.hide_event()
