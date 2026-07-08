"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

MQTT debug panel onroad overlay (SIC-UEM / Orbit).

Port of the old Qt DebugPanel (selfdrive/ui/sunnypilot/qt/onroad/debug_panel.cc).
When the "modo_debug" param is on, tails /tmp/mqtt_debug_messages.txt (written by
mqtt_comandos.py) and draws a right-side panel of colorized lines: timestamp
(green), topic last segment (cyan), payload value (green/red/yellow per value).

Render-only: the framework's onroad layout does not forward mouse events to HUD
overlays for arbitrary buttons (only ExperimentalButton participates in
user_interacting()), so the collapse/clear buttons from the Qt version are NOT
wired. See module-level note + report. Param/file reads are throttled (~0.5s).
"""
import os

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

DEBUG_FILE = "/tmp/mqtt_debug_messages.txt"
READ_CAP_BYTES = 50 * 1024  # cap how much of the file we read
MAX_MESSAGES = 30           # last N messages
READ_INTERVAL_FRAMES = 30   # ~0.5s at 60fps

FONT_SIZE = 30
LINE_SPACING = 6
MSG_SPACING = 20
PANEL_PADDING = 25
HEADER_HEIGHT = 70

PANEL_BG = rl.Color(0, 0, 0, 220)
COLOR_TIME = rl.Color(0, 255, 0, 255)
COLOR_TOPIC = rl.Color(0, 191, 255, 255)
COLOR_TRUE = rl.Color(0, 255, 0, 255)
COLOR_FALSE = rl.Color(255, 0, 0, 255)
COLOR_NUM = rl.Color(255, 215, 0, 255)
COLOR_DEFAULT = rl.Color(255, 255, 255, 255)
COLOR_PLACEHOLDER = rl.Color(136, 136, 136, 255)
COLOR_TITLE = rl.Color(255, 255, 255, 255)


def _parse_message(message: str) -> tuple[str, str, str, rl.Color]:
  """Returns (time, topic_last_segment, value_text, value_color)."""
  hora = ""
  topic = ""
  value = ""
  value_color = COLOR_DEFAULT

  lines = message.split("\n")
  if lines:
    first = lines[0].strip()
    if first.startswith("["):
      end = first.find("]")
      if end > 0:
        hora = first[: end + 1]
        first = first[end + 1:].strip()
    if "/" in first:
      topic = first.rsplit("/", 1)[-1].strip()
      sp = topic.find(" ")
      if sp > 0:
        topic = topic[:sp]
    else:
      topic = first

  if len(lines) >= 2:
    payload = lines[1].strip()
    value = payload
    if payload.startswith("{") and ":" in payload:
      # extract value after first ':'
      after = payload.split(":", 1)[1]
      value = after.replace('"', "").replace("}", "").replace("{", "").strip()
    if value == "true":
      value_color = COLOR_TRUE
    elif value == "false":
      value_color = COLOR_FALSE
    elif value in ("1", "-1"):
      value_color = COLOR_NUM

  return hora, topic, value, value_color


class DebugPanelRenderer:
  def __init__(self):
    self.font = gui_app.font(FontWeight.MEDIUM)
    self.font_bold = gui_app.font(FontWeight.BOLD)
    self._frame = 0
    self._enabled = False
    self._messages: list[str] = []

  def update(self):
    self._frame += 1
    if self._frame % READ_INTERVAL_FRAMES != 0:
      return
    self._enabled = ui_state.params.get_bool("modo_debug")
    if not self._enabled:
      self._messages = []
      return
    self._messages = self._load_messages()

  def _load_messages(self) -> list[str]:
    try:
      size = os.path.getsize(DEBUG_FILE)
    except OSError:
      return []
    try:
      with open(DEBUG_FILE, "rb") as f:
        if size > READ_CAP_BYTES:
          f.seek(size - READ_CAP_BYTES)
        content = f.read().decode("utf-8", errors="ignore")
    except OSError:
      return []

    if not content.strip():
      return []
    parts = [m.strip() for m in content.split("\n\n") if m.strip()]
    return parts[-MAX_MESSAGES:]

  def render(self, rect: rl.Rectangle):
    if not self._enabled:
      return

    panel_width = rect.width / 2
    panel_x = rect.x + rect.width - panel_width
    panel_rect = rl.Rectangle(panel_x, rect.y, panel_width, rect.height)
    rl.draw_rectangle_rec(panel_rect, PANEL_BG)

    # Header / title
    title = "MQTT DEBUG"
    title_size = measure_text_cached(self.font_bold, title, 48)
    rl.draw_text_ex(self.font_bold, title, rl.Vector2(panel_x + PANEL_PADDING, rect.y + 15), 48, 0, COLOR_TITLE)

    content_x = panel_x + PANEL_PADDING
    content_w = panel_width - PANEL_PADDING * 2
    y = rect.y + 15 + title_size.y + 25

    if not self._messages:
      rl.draw_text_ex(self.font, "Esperando mensajes MQTT...",
                      rl.Vector2(content_x, y), FONT_SIZE, 0, COLOR_PLACEHOLDER)
      return

    line_h = FONT_SIZE + LINE_SPACING
    max_y = rect.y + rect.height - PANEL_PADDING

    for message in self._messages:
      hora, topic, value, value_color = _parse_message(message)
      if y + line_h * 3 > max_y:
        break
      if hora:
        rl.draw_text_ex(self.font_bold, hora, rl.Vector2(content_x, y), FONT_SIZE, 0, COLOR_TIME)
        y += line_h
      if topic:
        rl.draw_text_ex(self.font_bold, topic, rl.Vector2(content_x, y), FONT_SIZE, 0, COLOR_TOPIC)
        y += line_h
      if value:
        text = value
        if measure_text_cached(self.font, text, FONT_SIZE).x > content_w:
          while text and measure_text_cached(self.font, text + "...", FONT_SIZE).x > content_w:
            text = text[:-1]
          text = text + "..."
        rl.draw_text_ex(self.font, text, rl.Vector2(content_x, y), FONT_SIZE, 0, value_color)
        y += line_h
      y += MSG_SPACING
