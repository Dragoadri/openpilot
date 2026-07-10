"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Coach de distancia de seguimiento (ORBIT) — SOLO INFORMATIVO.

Calcula el tiempo de separacion (THW = dRel / vEgo) con el vehiculo delantero a
partir de radarState.leadOne y carState.vEgo, y lo muestra como una pildora
graduada por color (verde/ambar/rojo) abajo-centro, junto con el tiempo hasta
colision (TTC = dRel / vRel de aproximacion) cuando el lead se acerca. No toca
el control: es un HUD de conciencia de distancia. Lecturas de sm limitadas a
~2 Hz para evitar parpadeo.
"""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

UPDATE_INTERVAL_FRAMES = 30  # ~0.5 s a 60 fps
FONT_SIZE = 46
MIN_SPEED_MS = 2.5           # por debajo, THW no es significativo (parado/atasco)

# ORBIT palette
_NAVY = rl.Color(0x16, 0x23, 0x3A, 220)
_HAIRLINE = rl.Color(0x2B, 0x3E, 0x5F, 255)
_INK = rl.Color(0xE2, 0xEC, 0xFF, 255)
_GREEN = rl.Color(0x4A, 0xDE, 0x80, 255)
_AMBER = rl.Color(0xF5, 0xC8, 0x42, 255)
_RED = rl.Color(0xF2, 0x55, 0x55, 255)

# Umbrales THW (segundos): >= SAFE verde, >= WARN ambar, por debajo rojo.
THW_SAFE = 2.0
THW_WARN = 1.2


class FollowCoachRenderer:
  def __init__(self):
    self.font = gui_app.font(FontWeight.BOLD)
    self._frame = 0
    self._thw: float | None = None
    self._ttc: float | None = None

  def update(self):
    self._frame += 1
    if self._frame % UPDATE_INTERVAL_FRAMES != 0:
      return
    self._thw = None
    self._ttc = None
    try:
      # Solo con datos frescos de este viaje (patron de los overlays onroad).
      if ui_state.sm.recv_frame["radarState"] < ui_state.started_frame:
        return
      if not (ui_state.sm.alive["radarState"] and ui_state.sm.valid["radarState"]):
        return
      lead = ui_state.sm['radarState'].leadOne
      if not lead.status:
        return
      v_ego = float(ui_state.sm['carState'].vEgo)
      if v_ego < MIN_SPEED_MS:
        return
      d_rel = float(lead.dRel)
      self._thw = d_rel / v_ego
      # TTC solo si nos acercamos (vRel negativo = el lead se aleja mas lento
      # o nos acercamos). vRel = vLead - vEgo; closing = -vRel.
      closing = -float(lead.vRel)
      if closing > 0.3:
        self._ttc = d_rel / closing
    except (KeyError, AttributeError, ZeroDivisionError, ValueError):
      self._thw = None
      self._ttc = None

  def render(self, rect: rl.Rectangle):
    if self._thw is None:
      return

    if self._thw >= THW_SAFE:
      color = _GREEN
    elif self._thw >= THW_WARN:
      color = _AMBER
    else:
      color = _RED

    label = f"SEPARACION {self._thw:.1f}s"
    if self._ttc is not None and self._ttc < 6.0:
      label += f"  -  TTC {self._ttc:.1f}s"

    text_size = measure_text_cached(self.font, label, FONT_SIZE)
    pad_x, pad_y = 28, 12
    dot_r, dot_gap = 9, 16
    box_w = pad_x + dot_r * 2 + dot_gap + text_size.x + pad_x
    box_h = text_size.y + pad_y * 2
    box_x = rect.x + rect.width / 2 - box_w / 2
    # Abajo-centro, por encima de la barra de torque y las alertas.
    box_y = rect.y + rect.height - box_h - 260
    box = rl.Rectangle(box_x, box_y, box_w, box_h)

    rl.draw_rectangle_rounded(box, 0.5, 10, _NAVY)
    rl.draw_rectangle_rounded_lines_ex(box, 0.5, 10, 3, _HAIRLINE)
    rl.draw_circle(int(box_x + pad_x + dot_r), int(box_y + box_h / 2), dot_r, color)
    text_pos = rl.Vector2(box_x + pad_x + dot_r * 2 + dot_gap, box_y + (box_h - text_size.y) / 2)
    rl.draw_text_ex(self.font, label, text_pos, FONT_SIZE, 0, _INK)
