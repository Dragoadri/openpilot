"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Aviso predictivo de frenada (ORBIT) — SOLO INFORMATIVO.

Muestra un chip "FRENADA PROBABLE" arriba-centro cuando el modelo de conduccion
anticipa una frenada fuerte (modelV2.meta.hardBrakePredicted). Es un HUD de aviso:
NO actua sobre los frenos (el frenado remoto brutebreak es otra cosa, siempre
manual). El flanco de subida se engancha en pantalla ~2.5 s para que el aviso
sea legible aunque la prediccion sea momentanea.
"""
import time

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

UPDATE_INTERVAL_FRAMES = 6   # ~10 Hz: la prediccion cambia rapido, no la perdemos
LATCH_SECONDS = 2.5
FONT_SIZE = 52

_FILL = rl.Color(0xF5, 0xC8, 0x42, 235)      # ambar de aviso
_BORDER = rl.Color(0xFF, 0xE4, 0x9A, 255)
_TEXT = rl.Color(0x14, 0x1A, 0x0A, 255)      # texto oscuro sobre ambar
LABEL = "FRENADA PROBABLE"


class HardBrakeOverlay:
  def __init__(self):
    self.font = gui_app.font(FontWeight.BOLD)
    self._frame = 0
    self._deadline = 0.0
    self._prev = False

  def update(self):
    self._frame += 1
    if self._frame % UPDATE_INTERVAL_FRAMES != 0:
      return
    try:
      if ui_state.sm.recv_frame["modelV2"] < ui_state.started_frame:
        return
      predicted = bool(ui_state.sm['modelV2'].meta.hardBrakePredicted)
    except (KeyError, AttributeError):
      return
    # Flanco de subida -> engancha el chip.
    if predicted and not self._prev:
      self._deadline = time.monotonic() + LATCH_SECONDS
    self._prev = predicted

  def render(self, rect: rl.Rectangle):
    if time.monotonic() >= self._deadline:
      return

    text_size = measure_text_cached(self.font, LABEL, FONT_SIZE)
    pad_x, pad_y = 34, 14
    box_w = pad_x * 2 + text_size.x
    box_h = text_size.y + pad_y * 2
    box_x = rect.x + rect.width / 2 - box_w / 2
    box_y = rect.y + 118   # bajo la banda de pildoras superior
    box = rl.Rectangle(box_x, box_y, box_w, box_h)

    rl.draw_rectangle_rounded(box, 0.5, 10, _FILL)
    rl.draw_rectangle_rounded_lines_ex(box, 0.5, 10, 3, _BORDER)
    text_pos = rl.Vector2(box_x + pad_x, box_y + (box_h - text_size.y) / 2)
    rl.draw_text_ex(self.font, LABEL, text_pos, FONT_SIZE, 0, _TEXT)
