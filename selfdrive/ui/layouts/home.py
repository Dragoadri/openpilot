import time
import pyray as rl
from enum import IntEnum
from openpilot.common.params import Params
from openpilot.selfdrive.ui.widgets.offroad_alerts import UpdateAlert, OffroadAlert
from openpilot.selfdrive.ui.widgets.orbit_server import ServerMonitor
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
COMMANDS = rl.Color(74, 222, 128, 255)   # #4ADE80 downlink green
PULSE = rl.Color(34, 211, 238, 255)      # #22D3EE live cyan accent
INK = rl.Color(226, 236, 255, 255)       # #E2ECFF near-white
MUTED = rl.Color(147, 180, 230, 255)     # #93B4E6
MUTED_DIM = rl.Color(92, 117, 153, 255)  # #5C7599 tertiary text
AMBER = rl.Color(245, 200, 66, 255)      # warning / no-connection

LOGO_SIZE = 380
WORDMARK_SIZE = 150
WORDMARK_SPACING = 26
TAGLINE_SIZE = 34
PILL_HEIGHT = 66
PILL_FONT_SIZE = 34

# "powered by drago" credit badge (bottom-right corner)
DRAGO_LOGO_H = 72
DRAGO_ASPECT = 469 / 640   # source logo-drago.png is portrait
POWERED_SIZE = 28

# Bottom signal cards (Screen 01: telemetry up / commands down / device)
CARD_H = 170
CARD_GAP = 26
CARD_BOTTOM_RESERVE = 116   # space below the cards for the drago badge

# Telemetry pulse (ECG-style polyline on the SERVIDOR card), one beat per period
# as (fraction of period, offset in amplitudes; negative = up).
WAVE_BEAT = ((0.00, 0.0), (0.30, 0.0), (0.36, -0.30), (0.42, 0.0), (0.48, 0.20),
             (0.54, -1.00), (0.60, 0.35), (0.66, 0.0), (1.00, 0.0))
WAVE_PERIOD = 125.0   # px
WAVE_AMP = 20.0       # px
WAVE_SPEED = 70.0     # px/s


class HomeLayoutState(IntEnum):
  HOME = 0
  UPDATE = 1
  ALERTS = 2


class _ServerSettingsModal(Widget):
  """Full-screen modal wrapping the Orbit/SICUEM server-IP settings panel so it
  can be opened straight from the home (tap the SERVIDOR card)."""

  def __init__(self):
    super().__init__()
    from openpilot.selfdrive.ui.sunnypilot.layouts.settings.uem_sub_layouts.server_ip_settings import (
      ServerIpSettingsLayout,
    )
    self._panel = ServerIpSettingsLayout(back_btn_callback=gui_app.pop_widget)

  def show_event(self):
    super().show_event()
    self._panel.show_event()

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), int(rect.height), VOID)
    m = 60
    self._panel.render(rl.Rectangle(rect.x + m, rect.y + m, rect.width - 2 * m, rect.height - 2 * m))


class HomeLayout(Widget):
  def __init__(self):
    super().__init__()
    self.params = Params()

    self.update_alert = UpdateAlert()
    self.offroad_alert = OffroadAlert()

    self._layout_widgets = {HomeLayoutState.UPDATE: self.update_alert, HomeLayoutState.ALERTS: self.offroad_alert}

    self.current_state = HomeLayoutState.HOME
    self.last_refresh = 0

    self.update_available = False
    self.alert_count = 0
    self._version_text = ""
    self._prev_update_available = False
    self._prev_alerts_present = False

    self.header_rect = rl.Rectangle(0, 0, 0, 0)
    self.content_rect = rl.Rectangle(0, 0, 0, 0)

    self.update_notif_rect = rl.Rectangle(0, 0, 200, HEADER_HEIGHT - 10)
    self.alert_notif_rect = rl.Rectangle(0, 0, 220, HEADER_HEIGHT - 10)

    try:
      self._logo = gui_app.texture("img_orbit_logo.png", LOGO_SIZE, LOGO_SIZE)
    except Exception:
      self._logo = None

    try:
      self._drago = gui_app.texture("img_drago_logo.png", int(DRAGO_LOGO_H * DRAGO_ASPECT) + 6,
                                    DRAGO_LOGO_H, keep_aspect_ratio=True)
    except Exception:
      self._drago = None

    # Live reachability of the Orbit server (background TCP+HTTP probe) + tappable hitboxes.
    self._server = ServerMonitor()
    self._card_rects: dict[str, rl.Rectangle] = {}
    self._pill_rect = rl.Rectangle(0, 0, 0, 0)

    self._setup_callbacks()

  def show_event(self):
    super().show_event()
    self.last_refresh = time.monotonic()
    self._refresh()

  def _setup_callbacks(self):
    self.update_alert.set_dismiss_callback(lambda: self._set_state(HomeLayoutState.HOME))
    self.offroad_alert.set_dismiss_callback(lambda: self._set_state(HomeLayoutState.HOME))

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

    self.update_notif_rect.x = self.header_rect.x
    self.update_notif_rect.y = self.header_rect.y + (self.header_rect.height - 60) // 2

    notif_x = self.header_rect.x + (220 if self.update_available else 0)
    self.alert_notif_rect.x = notif_x
    self.alert_notif_rect.y = self.header_rect.y + (self.header_rect.height - 60) // 2

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)

    if self.update_available and rl.check_collision_point_rec(mouse_pos, self.update_notif_rect):
      self._set_state(HomeLayoutState.UPDATE)
      return
    if self.alert_count > 0 and rl.check_collision_point_rec(mouse_pos, self.alert_notif_rect):
      self._set_state(HomeLayoutState.ALERTS)
      return

    # Tappable status cards + link pill (home view only)
    if self.current_state == HomeLayoutState.HOME:
      empty = rl.Rectangle(0, 0, 0, 0)
      if rl.check_collision_point_rec(mouse_pos, self._card_rects.get("server", empty)):
        self._open_server_settings()
      elif not self._get_claimed() and (rl.check_collision_point_rec(mouse_pos, self._card_rects.get("link", empty)) or
                                        rl.check_collision_point_rec(mouse_pos, self._pill_rect)):
        self._open_enroll()

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

    # Bottom band: three functional status cards, room below for the drago badge.
    cards_bottom = self.content_rect.y + self.content_rect.height - CARD_BOTTOM_RESERVE
    cards_rect = rl.Rectangle(self.content_rect.x, cards_bottom - CARD_H, self.content_rect.width, CARD_H)

    # Hero (logo + wordmark + tagline + link pill), vertically centered above the cards.
    wordmark_size = measure_text_cached(bold, "ORBIT", WORDMARK_SIZE, WORDMARK_SPACING)
    tagline_size = measure_text_cached(normal, tagline, TAGLINE_SIZE)
    gap_logo, gap_wordmark, gap_pill = 24, 26, 30

    def _hero_h(ls):
      return ls + gap_logo + wordmark_size.y + gap_wordmark + tagline_size.y + gap_pill + PILL_HEIGHT

    logo_size = LOGO_SIZE
    hero_area_h = (cards_rect.y - SPACING) - self.content_rect.y
    if _hero_h(logo_size) > hero_area_h - 2 * SPACING:
      logo_size = max(logo_size - (_hero_h(logo_size) - (hero_area_h - 2 * SPACING)), 160)
    y = self.content_rect.y + max((hero_area_h - _hero_h(logo_size)) / 2, SPACING)

    # Logo
    if self._logo is not None:
      logo_rect = rl.Rectangle(cx - logo_size / 2, y, logo_size, logo_size)
      rl.draw_texture_pro(self._logo, rl.Rectangle(0, 0, self._logo.width, self._logo.height),
                          logo_rect, rl.Vector2(0, 0), 0, rl.WHITE)
    y += logo_size + gap_logo

    # Wordmark + cyan accent underline (the signature live accent)
    rl.draw_text_ex(bold, "ORBIT", rl.Vector2(int(cx - wordmark_size.x / 2), int(y)),
                    WORDMARK_SIZE, WORDMARK_SPACING, INK)
    rl.draw_rectangle(int(cx - wordmark_size.x / 2), int(y + wordmark_size.y + 10),
                      int(wordmark_size.x), 4, PULSE)
    y += wordmark_size.y + gap_wordmark

    # Tagline
    rl.draw_text_ex(normal, tagline, rl.Vector2(int(cx - tagline_size.x / 2), int(y)), TAGLINE_SIZE, 0, MUTED)
    y += tagline_size.y + gap_pill

    # Link status pill (tap to enroll while unclaimed)
    self._render_link_pill(cx, y)

    # Functional status cards + credit badge
    self._render_status_cards(cards_rect)
    self._render_powered_by()

  def _render_status_cards(self, rect: rl.Rectangle):
    # Real, actionable status. SERVIDOR -> tap opens server-IP settings (with a
    # test button); ENLACE -> tap shows the QR to claim the device; DEVICE -> info.
    claimed = self._get_claimed()
    broker_ok = self._server.broker_ok
    backend_ok = self._server.backend_ok
    try:
      dongle = self.params.get("DongleId") or ""
    except Exception:
      dongle = ""
    dev_val = self._short_id(dongle) if dongle and dongle != "UnregisteredDevice" else "sin registrar"

    if broker_ok and backend_ok:
      server_val, server_color = "BROKER ✓ - API ✓", COMMANDS
    elif broker_ok:
      server_val, server_color = "BROKER ✓ - sin API", AMBER
    elif backend_ok:
      server_val, server_color = "sin BROKER - API ✓", AMBER
    else:
      server_val, server_color = "Sin conexión", AMBER
    server_sub = self._last_publish_text() if (broker_ok or backend_ok) else "toca para configurar la IP"

    cards = [
      ("server", "SERVIDOR", server_val, server_color, server_sub, True),
      ("link", "ENLACE ORBIT",
       "Enlazado" if claimed else "Sin enlazar", COMMANDS if claimed else PULSE,
       "dispositivo activo" if claimed else "toca para ver el QR", not claimed),
      ("device", "DISPOSITIVO", dev_val, INK,
       "comma 3X" if dev_val != "sin registrar" else "aún sin dongle", False),
    ]

    hdr_font = gui_app.font(FontWeight.MEDIUM)
    val_font = gui_app.font(FontWeight.BOLD)
    sub_font = gui_app.font(FontWeight.NORMAL)
    pad = 30
    n = len(cards)
    cw = (rect.width - CARD_GAP * (n - 1)) / n
    self._card_rects = {}

    for i, (key, title, value, color, sub, tappable) in enumerate(cards):
      card = rl.Rectangle(rect.x + i * (cw + CARD_GAP), rect.y, cw, rect.height)
      self._card_rects[key] = card
      rl.draw_rectangle_rounded(card, 0.12, 12, NAVY)
      rl.draw_rectangle_rounded_lines_ex(card, 0.12, 12, 2, color if tappable else HAIRLINE)

      rl.draw_text_ex(hdr_font, title, rl.Vector2(int(card.x + pad), int(card.y + 26)), 26, 3, MUTED)
      if tappable:
        self._draw_chevron(card.x + card.width - pad - 16, card.y + card.height / 2, 20, color)

      rl.draw_text_ex(val_font, value, rl.Vector2(int(card.x + pad), int(card.y + 74)), 40, 0, color)
      rl.draw_text_ex(sub_font, sub, rl.Vector2(int(card.x + pad), int(card.y + card.height - 46)),
                      24, 0, MUTED_DIM)
      if key == "server":
        self._render_telemetry_wave(card)

  def _render_telemetry_wave(self, card: rl.Rectangle):
    # Live-uplink pulse along the top-right of the SERVIDOR card: an animated
    # ECG-style polyline while OrbitConnected, a flat muted line otherwise.
    pad = 30
    x1 = card.x + card.width - pad
    x0 = x1 - 250
    base_y = card.y + 44
    if x1 - x0 < 80:
      return

    try:
      live = bool(self.params.get_bool("OrbitConnected"))
    except Exception:
      live = False
    if not live:
      rl.draw_line_ex(rl.Vector2(x0, base_y), rl.Vector2(x1, base_y), 3, MUTED_DIM)
      return

    phase = (time.monotonic() * WAVE_SPEED) % WAVE_PERIOD
    step = 5.0
    prev = None
    x = x0
    while x <= x1:
      u = ((x - x0 + phase) % WAVE_PERIOD) / WAVE_PERIOD
      pt = rl.Vector2(x, base_y + WAVE_AMP * self._wave_offset(u))
      if prev is not None:
        rl.draw_line_ex(prev, pt, 3, PULSE)
      prev = pt
      x += step

  def _wave_offset(self, u: float) -> float:
    for (u0, v0), (u1, v1) in zip(WAVE_BEAT, WAVE_BEAT[1:], strict=False):
      if u <= u1:
        t = (u - u0) / (u1 - u0) if u1 > u0 else 0.0
        return v0 + (v1 - v0) * t
    return WAVE_BEAT[-1][1]

  def _last_publish_text(self) -> str:
    try:
      last = float(self.params.get("OrbitLastPublish") or 0)
    except Exception:
      last = 0.0
    if last <= 0:
      return "sin datos"
    age = max(0, int(time.time() - last))  # noqa: TID251 (OrbitLastPublish is epoch seconds)
    return f"último dato hace {age}s"

  def _draw_chevron(self, x: float, y: float, size: float, color: rl.Color):
    # A ">" affordance meaning "tap to open".
    half = size / 2
    rl.draw_line_ex(rl.Vector2(x, y - half), rl.Vector2(x + half, y), 4, color)
    rl.draw_line_ex(rl.Vector2(x + half, y), rl.Vector2(x, y + half), 4, color)

  def _open_enroll(self):
    from openpilot.selfdrive.ui.widgets.orbit_enroll_dialog import OrbitEnrollDialog
    gui_app.push_widget(OrbitEnrollDialog())

  def _open_server_settings(self):
    gui_app.push_widget(_ServerSettingsModal())

  def _get_claimed(self) -> bool:
    try:
      return bool(self.params.get_bool("OrbitClaimed"))
    except Exception:
      return False

  def _get_owner(self) -> str:
    try:
      return self.params.get("OrbitOwner") or ""
    except Exception:
      return ""

  def _render_link_pill(self, cx: float, y: float):
    font = gui_app.font(FontWeight.MEDIUM)
    claimed = self._get_claimed()

    if claimed:
      owner = self._get_owner()
      text = f"VINCULADO - {owner}" if owner else "VINCULADO A ORBIT"
      accent = COMMANDS
    else:
      text = "SIN VINCULAR"
      accent = MUTED

    text_size = measure_text_cached(font, text, PILL_FONT_SIZE)
    dot_r = 8
    inner_pad = 34
    dot_gap = 18
    pill_w = inner_pad * 2 + dot_r * 2 + dot_gap + text_size.x
    pill_rect = rl.Rectangle(cx - pill_w / 2, y, pill_w, PILL_HEIGHT)
    self._pill_rect = pill_rect

    rl.draw_rectangle_rounded(pill_rect, 1.0, 20, PANEL)
    rl.draw_rectangle_rounded_lines_ex(pill_rect, 1.0, 20, 2, accent if claimed else HAIRLINE)

    # status dot
    dot_x = pill_rect.x + inner_pad + dot_r
    dot_y = pill_rect.y + PILL_HEIGHT / 2
    rl.draw_circle(int(dot_x), int(dot_y), dot_r, accent)

    text_x = dot_x + dot_r + dot_gap
    text_y = pill_rect.y + (PILL_HEIGHT - text_size.y) / 2
    rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), PILL_FONT_SIZE, 0, accent)

  def _short_id(self, value: str, keep: int = 12) -> str:
    if len(value) > keep:
      return value[:keep] + "..."
    return value

  def _render_powered_by(self):
    # Bottom-right corner credit: "powered by drago" + the green dragon mark.
    if self._drago is None:
      return

    tex = self._drago
    # Pin to the true bottom-right corner of the screen (self._rect), not the
    # content inset, so it sits lower and further right.
    margin = 16
    x_right = self._rect.x + self._rect.width - margin
    y_bottom = self._rect.y + self._rect.height - margin

    dragon_x = x_right - tex.width
    dragon_y = y_bottom - tex.height
    rl.draw_texture_ex(tex, rl.Vector2(int(dragon_x), int(dragon_y)), 0.0, 1.0, rl.WHITE)

    # "powered by " (muted) + "DRAGO" (green, matching the dragon), right-aligned
    # to the left of the mark and vertically centered on it.
    font = gui_app.font(FontWeight.MEDIUM)
    part1, part2 = "powered by ", "DRAGO"
    s1 = measure_text_cached(font, part1, POWERED_SIZE)
    s2 = measure_text_cached(font, part2, POWERED_SIZE)
    text_x = dragon_x - 16 - (s1.x + s2.x)
    text_y = dragon_y + (tex.height - max(s1.y, s2.y)) / 2
    rl.draw_text_ex(font, part1, rl.Vector2(int(text_x), int(text_y)), POWERED_SIZE, 0, MUTED)
    rl.draw_text_ex(font, part2, rl.Vector2(int(text_x + s1.x), int(text_y)), POWERED_SIZE, 0, COMMANDS)

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
    try:
      version = (self.params.get("Version") or "").split("-")[0]
    except Exception:
      version = ""
    return f"ORBIT {version}".strip()
