import pyray as rl

from cereal import log
from openpilot.common.params import Params, UnknownKeyName
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.selfdrive.ui.ui_state import ui_state

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants

# ORBIT palette (local copy to avoid a circular import with settings.settings).
VOID = rl.Color(11, 18, 32, 255)
NAVY = rl.Color(22, 35, 58, 255)
PANEL = rl.Color(27, 44, 72, 255)
HAIRLINE = rl.Color(43, 62, 95, 255)
GREEN = rl.Color(74, 222, 128, 255)
CYAN = rl.Color(34, 211, 238, 255)
INK = rl.Color(226, 236, 255, 255)
MUTED = rl.Color(147, 180, 230, 255)
MUTED_DIM = rl.Color(92, 117, 153, 255)


def _a(c: rl.Color, alpha: int) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, alpha)


# Description constants
DESCRIPTIONS = {
  "OpenpilotEnabledToggle": tr_noop(
    "Use the sunnypilot system for adaptive cruise control and lane keep driver assistance. " +
    "Your attention is required at all times to use this feature."
  ),
  "DisengageOnAccelerator": tr_noop("When enabled, pressing the accelerator pedal will disengage sunnypilot."),
  "LongitudinalPersonality": tr_noop(
    "Standard is recommended. In aggressive mode, sunnypilot will follow lead cars closer and be more aggressive with the gas and brake."
  ),
  "IsLdwEnabled": tr_noop(
    "Receive alerts to steer back into the lane when your vehicle drifts over a detected lane line " +
    "without a turn signal activated while driving over 31 mph (50 km/h)."
  ),
  "AlwaysOnDM": tr_noop("Enable driver monitoring even when sunnypilot is not engaged."),
  'RecordFront': tr_noop("Upload data from the driver facing camera and help improve the driver monitoring algorithm."),
  "IsMetric": tr_noop("Display speed in km/h instead of mph."),
  "RecordAudio": tr_noop("Record and store microphone audio while driving. The audio will be included in the dashcam video in comma connect."),
}


class TogglesLayout(Widget):
  """Car-friendly toggles: big square check tiles laid out two per row, green
  when active, dim when off; a personality selector sits below the grid."""

  def __init__(self):
    super().__init__()
    self._params = Params()

    # param -> (title, description, icon, needs_restart)
    self._toggle_defs = {
      "OpenpilotEnabledToggle": (lambda: tr("Enable sunnypilot"), DESCRIPTIONS["OpenpilotEnabledToggle"], "chffr_wheel.png", True),
      "ExperimentalMode": (lambda: tr("Experimental Mode"), "", "experimental_white.png", False),
      "DisengageOnAccelerator": (lambda: tr("Disengage on Accelerator Pedal"), DESCRIPTIONS["DisengageOnAccelerator"], "disengage_on_accelerator.png", False),
      "IsLdwEnabled": (lambda: tr("Enable Lane Departure Warnings"), DESCRIPTIONS["IsLdwEnabled"], "warning.png", False),
      "AlwaysOnDM": (lambda: tr("Always-On Driver Monitoring"), DESCRIPTIONS["AlwaysOnDM"], "monitoring.png", False),
      "RecordFront": (lambda: tr("Record and Upload Driver Camera"), DESCRIPTIONS["RecordFront"], "monitoring.png", True),
      "RecordAudio": (lambda: tr("Record and Upload Microphone Audio"), DESCRIPTIONS["RecordAudio"], "microphone.png", True),
      "IsMetric": (lambda: tr("Use Metric System"), DESCRIPTIONS["IsMetric"], "metric.png", False),
    }
    self._order = list(self._toggle_defs.keys())

    self._tile_rects: dict[str, tuple[rl.Rectangle, bool]] = {}
    self._perso_rects: list[rl.Rectangle] = []

  # --------------------------------------------------------------- availability
  def _tile_enabled(self, param: str) -> bool:
    try:
      if self._params.get_bool(param + "Lock"):
        return False
    except UnknownKeyName:
      pass
    if param == "ExperimentalMode" and ui_state.CP is not None and not ui_state.has_longitudinal_control:
      return False
    if self._toggle_defs[param][3] and ui_state.engaged:  # restart-required, blocked while engaged
      return False
    return True

  # --------------------------------------------------------------------- render
  def _render(self, rect: rl.Rectangle):
    cols = 2
    gap = 18
    n = len(self._order)
    rows = (n + cols - 1) // cols
    perso_h = 150

    tile_w = (rect.width - gap) / cols
    avail = rect.height - perso_h - gap
    tile_h = max((avail - gap * (rows - 1)) / rows, 96)

    self._tile_rects = {}
    for i, param in enumerate(self._order):
      col, row = i % cols, i // cols
      tile = rl.Rectangle(rect.x + col * (tile_w + gap), rect.y + row * (tile_h + gap), tile_w, tile_h)
      enabled = self._tile_enabled(param)
      on = self._params.get_bool(param)
      self._tile_rects[param] = (tile, enabled)
      self._draw_toggle_tile(tile, self._toggle_defs[param][0](), on, enabled)

    py = rect.y + rows * (tile_h + gap)
    self._draw_personality(rl.Rectangle(rect.x, py, rect.width, perso_h),
                           int(self._params.get("LongitudinalPersonality", return_default=True)))

  def _draw_toggle_tile(self, rect: rl.Rectangle, title: str, on: bool, enabled: bool):
    if not enabled:
      fill, border, bw, box_fill, box_line, txt = NAVY, HAIRLINE, 2, None, MUTED_DIM, MUTED_DIM
    elif on:
      fill, border, bw, box_fill, box_line, txt = _a(GREEN, 26), GREEN, 3, GREEN, GREEN, INK
    else:
      fill, border, bw, box_fill, box_line, txt = NAVY, HAIRLINE, 2, None, MUTED, MUTED

    rl.draw_rectangle_rounded(rect, 0.14, 12, fill)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.14, 12, bw, border)

    # Square check indicator
    bs = rect.height * 0.40
    bx = rect.x + 28
    by = rect.y + (rect.height - bs) / 2
    box = rl.Rectangle(bx, by, bs, bs)
    if box_fill is not None:
      rl.draw_rectangle_rounded(box, 0.28, 8, box_fill)
      rl.draw_line_ex(rl.Vector2(bx + bs * 0.24, by + bs * 0.52), rl.Vector2(bx + bs * 0.42, by + bs * 0.72), 5, VOID)
      rl.draw_line_ex(rl.Vector2(bx + bs * 0.42, by + bs * 0.72), rl.Vector2(bx + bs * 0.76, by + bs * 0.30), 5, VOID)
    else:
      rl.draw_rectangle_rounded_lines_ex(box, 0.28, 8, 3, box_line)

    # Title (wrapped) to the right of the box
    font = gui_app.font(FontWeight.MEDIUM)
    tx = bx + bs + 24
    tsize = 34
    lines = wrap_text(font, title, tsize, int(rect.x + rect.width - tx - 20))
    total_h = len(lines) * tsize
    ty = rect.y + (rect.height - total_h) / 2
    rl.draw_text_ex(font, "\n".join(lines), rl.Vector2(int(tx), int(ty)), tsize, 0, txt)

  def _draw_personality(self, rect: rl.Rectangle, selected: int):
    font = gui_app.font(FontWeight.MEDIUM)
    rl.draw_text_ex(font, tr("Driving Personality"), rl.Vector2(int(rect.x + 28), int(rect.y + 16)), 28, 2, MUTED)

    labels = [tr("Aggressive"), tr("Standard"), tr("Relaxed")]
    seg_y = rect.y + 60
    seg_h = rect.height - 72
    gap = 16
    seg_w = (rect.width - 56 - gap * 2) / 3

    self._perso_rects = []
    for i, lab in enumerate(labels):
      seg = rl.Rectangle(rect.x + 28 + i * (seg_w + gap), seg_y, seg_w, seg_h)
      self._perso_rects.append(seg)
      on = (i == selected)
      rl.draw_rectangle_rounded(seg, 0.3, 10, _a(GREEN, 32) if on else NAVY)
      rl.draw_rectangle_rounded_lines_ex(seg, 0.3, 10, 3 if on else 2, GREEN if on else HAIRLINE)
      ts = measure_text_cached(font, lab, 32)
      rl.draw_text_ex(font, lab, rl.Vector2(int(seg.x + (seg_w - ts.x) / 2), int(seg_y + (seg_h - ts.y) / 2)),
                      32, 0, INK if on else MUTED)

  # ---------------------------------------------------------------- interaction
  def _handle_mouse_release(self, mouse_pos) -> None:
    for param, (tile, enabled) in self._tile_rects.items():
      if enabled and rl.check_collision_point_rec(mouse_pos, tile):
        self._flip(param)
        return
    for i, seg in enumerate(self._perso_rects):
      if rl.check_collision_point_rec(mouse_pos, seg):
        self._set_longitudinal_personality(i)
        return

  def _flip(self, param: str):
    self._toggle_callback(not self._params.get_bool(param), param)

  def _toggle_callback(self, state: bool, param: str):
    if param == "ExperimentalMode":
      self._handle_experimental_mode_toggle(state)
      return
    self._params.put_bool(param, state, block=True)
    if self._toggle_defs[param][3]:  # needs restart
      self._params.put_bool("OnroadCycleRequested", True, block=True)

  def _handle_experimental_mode_toggle(self, state: bool):
    confirmed = self._params.get_bool("ExperimentalModeConfirmed")
    if state and not confirmed:
      def confirm_callback(result: DialogResult):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("ExperimentalMode", True, block=True)
          self._params.put_bool("ExperimentalModeConfirmed", True, block=True)

      content = ("<h1>" + tr("Experimental Mode") + "</h1><br><p>" +
                 tr("Let the driving model control the gas and brakes. This is an alpha-quality feature; mistakes should be expected.") +
                 "</p>")
      gui_app.push_widget(ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback))
    else:
      self._params.put_bool("ExperimentalMode", state, block=True)

  def _set_longitudinal_personality(self, button_index: int):
    self._params.put("LongitudinalPersonality", button_index, block=True)

  def show_event(self):
    super().show_event()
    ui_state.update_params()
