"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Onroad overtake (adelantamiento) status badge for SIC-UEM / Orbit.

Port of AnnotatedCameraWidgetSP::drawOvertakeIndicator
(selfdrive/ui/sunnypilot/qt/onroad/annotated_camera.cc:715-849). Shown only when
the "sic_adelantar" param is on; reads "overtakeStatus" plus the configured
overtake_* params, and the lead distance from radarState. Top-center badge whose
color encodes the overtake state machine.

Emoji are dropped (the UI font does not render them); text is otherwise identical.
Param reads are throttled (~0.5s).
"""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

PARAM_READ_INTERVAL_FRAMES = 30  # ~0.5s at 60fps
FONT_SIZE = 50

_BLACK = rl.Color(0, 0, 0, 255)
_WHITE = rl.Color(255, 255, 255, 255)

# state -> (fill, border, text_color)
STATE_STYLES = {
  "ESPERANDO": (rl.Color(255, 200, 0, 220), rl.Color(255, 255, 0, 255), _BLACK),
  "CAMBIANDO_IZQ": (rl.Color(0, 150, 255, 220), rl.Color(0, 200, 255, 255), _WHITE),
  "ADELANTANDO": (rl.Color(0, 200, 0, 220), rl.Color(0, 255, 0, 255), _WHITE),
  "ESPERANDO_RETORNO": (rl.Color(255, 150, 0, 220), rl.Color(255, 180, 0, 255), _BLACK),
  "VOLVIENDO": (rl.Color(0, 150, 255, 220), rl.Color(0, 200, 255, 255), _WHITE),
  "FINALIZADO": (rl.Color(200, 200, 200, 220), rl.Color(255, 255, 255, 255), _BLACK),
  "BLOQUEADO": (rl.Color(200, 0, 0, 220), rl.Color(255, 0, 0, 255), _WHITE),
  "BSM_IZQ_OCUPADO": (rl.Color(200, 0, 0, 220), rl.Color(255, 50, 50, 255), _WHITE),
  "BSM_DER_OCUPADO": (rl.Color(200, 0, 0, 220), rl.Color(255, 50, 50, 255), _WHITE),
}
_DEFAULT_STYLE = STATE_STYLES["ESPERANDO"]


class OvertakeRenderer:
  def __init__(self):
    self.font = gui_app.font(FontWeight.BOLD)
    self._frame = 0
    self._enabled = False
    self._status = "ESPERANDO"
    self._lead_d_rel = 0.0
    self._dist_activacion = 50.0
    self._tiempo_carril_izq = 15.0
    self._incremento_vel = 15.0

  @staticmethod
  def _read_float(name: str, default: float) -> float:
    raw = ui_state.params.get(name)
    try:
      return float(raw) if raw else default
    except (ValueError, TypeError):
      return default

  def update(self):
    self._frame += 1
    if self._frame % PARAM_READ_INTERVAL_FRAMES != 0:
      return
    self._enabled = ui_state.params.get_bool("sic_adelantar")
    if not self._enabled:
      return
    status = ui_state.params.get("overtakeStatus")
    self._status = status if status else "ESPERANDO"
    self._dist_activacion = self._read_float("overtake_distancia_activacion", 50.0)
    self._tiempo_carril_izq = self._read_float("overtake_tiempo_carril_izq", 15.0)
    self._incremento_vel = self._read_float("overtake_incremento_velocidad", 15.0)
    try:
      self._lead_d_rel = float(ui_state.sm['radarState'].leadOne.dRel)
    except (KeyError, AttributeError, ValueError):
      self._lead_d_rel = 0.0

  def render(self, rect: rl.Rectangle):
    if not self._enabled:
      return

    config_info = f"[{self._dist_activacion:.0f}m {self._tiempo_carril_izq:.0f}s +{self._incremento_vel:.0f}km/h]"
    label = f"Dis: {self._lead_d_rel:.1f} | ADELANTAMIENTO: {self._status} {config_info}"
    fill, border, text_color = STATE_STYLES.get(self._status, _DEFAULT_STYLE)

    text_size = measure_text_cached(self.font, label, FONT_SIZE)
    pad_x, pad_y = 20, 10
    box_w = text_size.x + pad_x * 2
    box_h = text_size.y + pad_y * 2
    box_x = rect.x + rect.width / 2 - box_w / 2
    box_y = rect.y + 20

    box_rect = rl.Rectangle(box_x, box_y, box_w, box_h)
    rl.draw_rectangle_rounded(box_rect, 0.3, 10, fill)
    rl.draw_rectangle_rounded_lines_ex(box_rect, 0.3, 10, 3, border)

    text_pos = rl.Vector2(box_x + (box_w - text_size.x) / 2, box_y + (box_h - text_size.y) / 2)
    rl.draw_text_ex(self.font, label, text_pos, FONT_SIZE, 0, text_color)
