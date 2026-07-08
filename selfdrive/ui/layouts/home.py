import time
import pyray as rl
from collections.abc import Callable
from enum import IntEnum
from openpilot.common.params import Params
from openpilot.selfdrive.ui.widgets.offroad_alerts import UpdateAlert, OffroadAlert
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr, trn
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets import Widget

HEADER_HEIGHT = 80
HEAD_BUTTON_FONT_SIZE = 40
CONTENT_MARGIN = 40
SPACING = 25
RIGHT_COLUMN_WIDTH = 750
REFRESH_INTERVAL = 10.0

# ORBIT palette (from the logo)
VOID = rl.Color(11, 18, 32, 255)        # #0B1220 background
NAVY = rl.Color(22, 35, 58, 255)        # #16233A
PANEL = rl.Color(27, 44, 72, 255)       # #1B2C48
HAIRLINE = rl.Color(43, 62, 95, 255)    # #2B3E5F
TELEMETRY = rl.Color(125, 180, 255, 255)  # #7DB4FF uplink blue
COMMANDS = rl.Color(74, 222, 128, 255)   # #4ADE80 downlink green
PULSE = rl.Color(34, 211, 238, 255)      # #22D3EE live cyan accent
INK = rl.Color(226, 236, 255, 255)       # #E2ECFF near-white
MUTED = rl.Color(147, 180, 230, 255)     # #93B4E6

LOGO_SIZE = 380
WORDMARK_SIZE = 150
WORDMARK_SPACING = 26
TAGLINE_SIZE = 34
PILL_HEIGHT = 66
PILL_FONT_SIZE = 34
READOUT_FONT_SIZE = 32
SETTINGS_BTN_W = 300
SETTINGS_BTN_H = 88


class HomeLayoutState(IntEnum):
  HOME = 0
  UPDATE = 1
  ALERTS = 2


class HomeLayout(Widget):
  def __init__(self):
    super().__init__()
    self.params = Params()

    self.update_alert = UpdateAlert()
    self.offroad_alert = OffroadAlert()

    self._layout_widgets = {HomeLayoutState.UPDATE: self.update_alert, HomeLayoutState.ALERTS: self.offroad_alert}

    self.current_state = HomeLayoutState.HOME
    self.last_refresh = 0
    self.settings_callback: Callable[[], None] | None = None

    self.update_available = False
    self.alert_count = 0
    self._version_text = ""
    self._prev_update_available = False
    self._prev_alerts_present = False

    self.header_rect = rl.Rectangle(0, 0, 0, 0)
    self.content_rect = rl.Rectangle(0, 0, 0, 0)
    self.settings_btn_rect = rl.Rectangle(0, 0, SETTINGS_BTN_W, SETTINGS_BTN_H)

    self.update_notif_rect = rl.Rectangle(0, 0, 200, HEADER_HEIGHT - 10)
    self.alert_notif_rect = rl.Rectangle(0, 0, 220, HEADER_HEIGHT - 10)

    try:
      self._logo = gui_app.texture("img_orbit_logo.png", LOGO_SIZE, LOGO_SIZE)
    except Exception:
      self._logo = None

    self._setup_callbacks()

  def show_event(self):
    super().show_event()
    self.last_refresh = time.monotonic()
    self._refresh()

  def _setup_callbacks(self):
    self.update_alert.set_dismiss_callback(lambda: self._set_state(HomeLayoutState.HOME))
    self.offroad_alert.set_dismiss_callback(lambda: self._set_state(HomeLayoutState.HOME))

  def set_settings_callback(self, callback: Callable):
    self.settings_callback = callback

  def _open_settings(self):
    if self.settings_callback:
      self.settings_callback()

  def _set_state(self, state: HomeLayoutState):
    # propagate show/hide events
    if state != self.current_state:
      if state in self._layout_widgets:
        self._layout_widgets[state].show_event()
      if self.current_state in self._layout_widgets:
        self._layout_widgets[self.current_state].hide_event()

    self.current_state = state

  def _render(self, rect: rl.Rectangle):
    current_time = time.monotonic()
    if current_time - self.last_refresh >= REFRESH_INTERVAL:
      self._refresh()
      self.last_refresh = current_time

    rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), int(rect.height), VOID)

    self._render_header()

    # Render content based on current state
    if self.current_state == HomeLayoutState.HOME:
      self._render_home_content()
    elif self.current_state == HomeLayoutState.UPDATE:
      self._render_update_view()
    elif self.current_state == HomeLayoutState.ALERTS:
      self._render_alerts_view()

  def _update_state(self):
    self.header_rect = rl.Rectangle(
      self._rect.x + CONTENT_MARGIN, self._rect.y + CONTENT_MARGIN, self._rect.width - 2 * CONTENT_MARGIN, HEADER_HEIGHT
    )

    content_y = self._rect.y + CONTENT_MARGIN + HEADER_HEIGHT + SPACING
    content_height = self._rect.height - CONTENT_MARGIN - HEADER_HEIGHT - SPACING - CONTENT_MARGIN

    self.content_rect = rl.Rectangle(
      self._rect.x + CONTENT_MARGIN, content_y, self._rect.width - 2 * CONTENT_MARGIN, content_height
    )

    # Settings button anchored bottom-center of the content area
    self.settings_btn_rect.x = self.content_rect.x + (self.content_rect.width - SETTINGS_BTN_W) / 2
    self.settings_btn_rect.y = self.content_rect.y + self.content_rect.height - SETTINGS_BTN_H

    self.update_notif_rect.x = self.header_rect.x
    self.update_notif_rect.y = self.header_rect.y + (self.header_rect.height - 60) // 2

    notif_x = self.header_rect.x + (220 if self.update_available else 0)
    self.alert_notif_rect.x = notif_x
    self.alert_notif_rect.y = self.header_rect.y + (self.header_rect.height - 60) // 2

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)

    if self.update_available and rl.check_collision_point_rec(mouse_pos, self.update_notif_rect):
      self._set_state(HomeLayoutState.UPDATE)
    elif self.alert_count > 0 and rl.check_collision_point_rec(mouse_pos, self.alert_notif_rect):
      self._set_state(HomeLayoutState.ALERTS)
    elif self.current_state == HomeLayoutState.HOME and rl.check_collision_point_rec(mouse_pos, self.settings_btn_rect):
      self._open_settings()

  def _render_header(self):
    font = gui_app.font(FontWeight.MEDIUM)

    version_text_width = self.header_rect.width

    # Update notification button
    if self.update_available:
      version_text_width -= self.update_notif_rect.width

      # Highlight if currently viewing updates
      highlight_color = rl.Color(75, 95, 255, 255) if self.current_state == HomeLayoutState.UPDATE else rl.Color(54, 77, 239, 255)
      rl.draw_rectangle_rounded(self.update_notif_rect, 0.3, 10, highlight_color)

      text = tr("UPDATE")
      text_size = measure_text_cached(font, text, HEAD_BUTTON_FONT_SIZE)
      text_x = self.update_notif_rect.x + (self.update_notif_rect.width - text_size.x) // 2
      text_y = self.update_notif_rect.y + (self.update_notif_rect.height - text_size.y) // 2
      rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), HEAD_BUTTON_FONT_SIZE, 0, rl.WHITE)

    # Alert notification button
    if self.alert_count > 0:
      version_text_width -= self.alert_notif_rect.width

      # Highlight if currently viewing alerts
      highlight_color = rl.Color(255, 70, 70, 255) if self.current_state == HomeLayoutState.ALERTS else rl.Color(226, 44, 44, 255)
      rl.draw_rectangle_rounded(self.alert_notif_rect, 0.3, 10, highlight_color)

      alert_text = trn("{} ALERT", "{} ALERTS", self.alert_count).format(self.alert_count)
      text_size = measure_text_cached(font, alert_text, HEAD_BUTTON_FONT_SIZE)
      text_x = self.alert_notif_rect.x + (self.alert_notif_rect.width - text_size.x) // 2
      text_y = self.alert_notif_rect.y + (self.alert_notif_rect.height - text_size.y) // 2
      rl.draw_text_ex(font, alert_text, rl.Vector2(int(text_x), int(text_y)), HEAD_BUTTON_FONT_SIZE, 0, rl.WHITE)

    # Version text (right aligned)
    if self.update_available or self.alert_count > 0:
      version_text_width -= SPACING * 1.5

    version_rect = rl.Rectangle(self.header_rect.x + self.header_rect.width - version_text_width, self.header_rect.y,
                                version_text_width, self.header_rect.height)
    gui_label(version_rect, self._version_text, 48, MUTED, alignment=rl.GuiTextAlignment.TEXT_ALIGN_RIGHT)

  def _render_update_view(self):
    self.update_alert.render(self.content_rect)

  def _render_alerts_view(self):
    self.offroad_alert.render(self.content_rect)

  # ---------------------------------------------------------------------------
  # ORBIT home
  # ---------------------------------------------------------------------------
  def _render_home_content(self):
    cx = self.content_rect.x + self.content_rect.width / 2

    bold = gui_app.font(FontWeight.BOLD)
    normal = gui_app.font(FontWeight.NORMAL)

    tagline = "Open Remote Bidirectional IoV Telemetry"

    # Measure the stacked hero block so it can be vertically centered.
    wordmark_size = measure_text_cached(bold, "ORBIT", WORDMARK_SIZE, WORDMARK_SPACING)
    tagline_size = measure_text_cached(normal, tagline, TAGLINE_SIZE)

    gap_logo = 30
    gap_wordmark = 22
    gap_pill = 46
    gap_readout = 34

    block_h = (LOGO_SIZE + gap_logo + wordmark_size.y + gap_wordmark + tagline_size.y +
               gap_pill + PILL_HEIGHT + gap_readout + READOUT_FONT_SIZE)

    # Reserve room for the settings button at the bottom so the hero stays centered above it.
    avail_h = self.content_rect.height - SETTINGS_BTN_H - SPACING
    y = self.content_rect.y + max((avail_h - block_h) / 2, 0)

    # Logo
    if self._logo is not None:
      logo_rect = rl.Rectangle(cx - LOGO_SIZE / 2, y, LOGO_SIZE, LOGO_SIZE)
      source = rl.Rectangle(0, 0, self._logo.width, self._logo.height)
      rl.draw_texture_pro(self._logo, source, logo_rect, rl.Vector2(0, 0), 0, rl.WHITE)
    y += LOGO_SIZE + gap_logo

    # Wordmark
    rl.draw_text_ex(bold, "ORBIT", rl.Vector2(int(cx - wordmark_size.x / 2), int(y)),
                    WORDMARK_SIZE, WORDMARK_SPACING, INK)
    # cyan accent underline (the signature live accent)
    underline_w = wordmark_size.x
    underline_y = y + wordmark_size.y + 10
    rl.draw_rectangle(int(cx - underline_w / 2), int(underline_y), int(underline_w), 4, PULSE)
    y += wordmark_size.y + gap_wordmark

    # Tagline
    rl.draw_text_ex(normal, tagline, rl.Vector2(int(cx - tagline_size.x / 2), int(y)), TAGLINE_SIZE, 0, MUTED)
    y += tagline_size.y + gap_pill

    # Link-status pill (real state)
    self._render_link_pill(cx, y)
    y += PILL_HEIGHT + gap_readout

    # Readout row (real data only)
    self._render_readout(cx, y)

    # Settings entry point (always visible)
    self._render_settings_button()

  def _get_claimed(self) -> bool:
    try:
      return bool(self.params.get_bool("OrbitClaimed"))
    except Exception:
      return False

  def _render_link_pill(self, cx: float, y: float):
    font = gui_app.font(FontWeight.MEDIUM)
    claimed = self._get_claimed()

    if claimed:
      text = "Linked to ORBIT"
      accent = COMMANDS
    else:
      text = "Not linked — open Settings to scan the QR"
      accent = PULSE

    text_size = measure_text_cached(font, text, PILL_FONT_SIZE)
    dot_r = 8
    inner_pad = 34
    dot_gap = 18
    pill_w = inner_pad * 2 + dot_r * 2 + dot_gap + text_size.x
    pill_rect = rl.Rectangle(cx - pill_w / 2, y, pill_w, PILL_HEIGHT)

    rl.draw_rectangle_rounded(pill_rect, 1.0, 20, PANEL)
    rl.draw_rectangle_rounded_lines_ex(pill_rect, 1.0, 20, 2, accent)

    # status dot
    dot_x = pill_rect.x + inner_pad + dot_r
    dot_y = pill_rect.y + PILL_HEIGHT / 2
    rl.draw_circle(int(dot_x), int(dot_y), dot_r, accent)

    text_x = dot_x + dot_r + dot_gap
    text_y = pill_rect.y + (PILL_HEIGHT - text_size.y) / 2
    rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), PILL_FONT_SIZE, 0, INK)

  def _short_id(self, value: str, keep: int = 12) -> str:
    if len(value) > keep:
      return value[:keep] + "…"
    return value

  def _render_readout(self, cx: float, y: float):
    label_font = gui_app.font(FontWeight.NORMAL)
    value_font = gui_app.font(FontWeight.MEDIUM)

    # Device (real DongleId)
    try:
      dongle = self.params.get("DongleId") or ""
    except Exception:
      dongle = ""
    device_val = self._short_id(dongle) if dongle else "—"

    # Optional connection indicator (param may be unregistered -> neutral)
    try:
      connected = bool(self.params.get_bool("OrbitConnected"))
      link_val = "Online" if connected else "Offline"
      link_color = COMMANDS if connected else MUTED
    except Exception:
      link_val = "—"
      link_color = MUTED

    items = [
      ("DEVICE", device_val, TELEMETRY),
      ("LINK", link_val, link_color),
    ]

    # Layout: evenly spaced cells centered on cx.
    cell_w = 360
    total_w = cell_w * len(items)
    start_x = cx - total_w / 2

    for i, (label, value, value_color) in enumerate(items):
      cell_cx = start_x + cell_w * i + cell_w / 2

      label_size = measure_text_cached(label_font, label, 26)
      rl.draw_text_ex(label_font, label, rl.Vector2(int(cell_cx - label_size.x / 2), int(y)), 26, 2, MUTED)

      value_size = measure_text_cached(value_font, value, READOUT_FONT_SIZE)
      rl.draw_text_ex(value_font, value, rl.Vector2(int(cell_cx - value_size.x / 2), int(y + 34)),
                      READOUT_FONT_SIZE, 0, value_color)

  def _render_settings_button(self):
    font = gui_app.font(FontWeight.MEDIUM)
    rect = self.settings_btn_rect

    rl.draw_rectangle_rounded(rect, 0.3, 20, PANEL)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.3, 20, 2, HAIRLINE)

    text = "Settings"
    text_size = measure_text_cached(font, text, 40)
    text_x = rect.x + (rect.width - text_size.x) / 2
    text_y = rect.y + (rect.height - text_size.y) / 2
    rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), 40, 0, INK)

  def _refresh(self):
    self._version_text = self._get_version_text()
    update_available = self.update_alert.refresh()
    alert_count = self.offroad_alert.refresh()
    alerts_present = alert_count > 0

    # Show panels on transition from no alert/update to any alerts/update
    if not update_available and not alerts_present:
      self._set_state(HomeLayoutState.HOME)
    elif update_available and ((not self._prev_update_available) or (not alerts_present and self.current_state == HomeLayoutState.ALERTS)):
      self._set_state(HomeLayoutState.UPDATE)
    elif alerts_present and ((not self._prev_alerts_present) or (not update_available and self.current_state == HomeLayoutState.UPDATE)):
      self._set_state(HomeLayoutState.ALERTS)

    self.update_available = update_available
    self.alert_count = alert_count
    self._prev_update_available = update_available
    self._prev_alerts_present = alerts_present

  def _get_version_text(self) -> str:
    brand = "sunnypilot"
    description = self.params.get("UpdaterCurrentDescription")
    return f"{brand} {description}" if description else brand
