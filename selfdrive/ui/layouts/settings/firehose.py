import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.scroll_panel import GuiScrollPanel
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.selfdrive.ui.mici.layouts.settings.firehose import FirehoseLayoutBase

TITLE = tr_noop("Firehose Mode")
DESCRIPTION = tr_noop(
  "ORBIT learns to drive by watching humans, like you, drive.\n\n"
  + "Firehose Mode allows you to maximize your training data uploads to improve "
  + "openpilot's driving models. More data means bigger models, which means better Experimental Mode."
)
INSTRUCTIONS = tr_noop(
  "For maximum effectiveness, bring your device inside and connect to a good USB-C adapter and Wi-Fi weekly.\n\n"
  + "Firehose Mode can also work while you're driving if connected to a hotspot or unlimited SIM card.\n\n\n"
  + "Frequently Asked Questions\n\n"
  + "Does it matter how or where I drive? Nope, just drive as you normally would.\n\n"
  + "Do all of my segments get pulled in Firehose Mode? No, we selectively pull a subset of your segments.\n\n"
  + "What's a good USB-C adapter? Any fast phone or laptop charger should be fine.\n\n"
  + "Does it matter which software I run? Yes, only upstream openpilot (and particular forks) are able to be used for training."
)

# ORBIT palette: PANEL cards on the void background, INK title, MUTED body text.
PANEL = rl.Color(27, 44, 72, 255)
HAIRLINE = rl.Color(43, 62, 95, 255)
INK = rl.Color(226, 236, 255, 255)
MUTED = rl.Color(147, 180, 230, 255)
MUTED_DIM = rl.Color(92, 117, 153, 255)
CARD_PAD = 30
CARD_GAP = 24
CARD_ROUNDNESS = 0.12


class FirehoseLayout(FirehoseLayoutBase):
  def __init__(self):
    super().__init__()
    self._scroll_panel = GuiScrollPanel()

  def _render(self, rect: rl.Rectangle):
    # Calculate content dimensions
    content_rect = rl.Rectangle(rect.x, rect.y, rect.width, self._content_height)

    # Handle scrolling and render with clipping
    scroll_offset = self._scroll_panel.update(rect, content_rect)
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    self._content_height = self._render_content(rect, scroll_offset)
    rl.end_scissor_mode()

  def _render_content(self, rect: rl.Rectangle, scroll_offset: float) -> int:
    x = int(rect.x + 40)
    y = int(rect.y + 40 + scroll_offset)
    w = int(rect.width - 80)

    # Title (centered)
    title_text = tr(TITLE)  # live translate
    title_font = gui_app.font(FontWeight.MEDIUM)
    text_width = measure_text_cached(title_font, title_text, 100).x
    title_x = rect.x + (rect.width - text_width) / 2
    rl.draw_text_ex(title_font, title_text, rl.Vector2(title_x, y), 100, 0, INK)
    y += 160

    # Description card
    y = self._draw_card(x, y, w, [(tr(DESCRIPTION), gui_app.font(FontWeight.NORMAL), 45, MUTED)])
    y += CARD_GAP

    # Status card
    status_text, status_color = self._get_status()
    y = self._draw_card(x, y, w, [(status_text, gui_app.font(FontWeight.BOLD), 60, status_color)])
    y += CARD_GAP

    # TODO: add back once reliable
    # Contribution count (if available)
    #if self._segment_count > 0:
    #  contrib_text = trn("{} segment of your driving is in the training dataset so far.",
    #                     "{} segments of your driving is in the training dataset so far.", self._segment_count).format(self._segment_count)
    #  y = self._draw_card(x, y, w, [(contrib_text, gui_app.font(FontWeight.BOLD), 52, INK)])
    #  y += CARD_GAP

    # Instructions card
    y = self._draw_card(x, y, w, [(tr(INSTRUCTIONS), gui_app.font(FontWeight.NORMAL), 40, MUTED_DIM)])

    # bottom margin + remove effect of scroll offset
    return int(round(y - self._scroll_panel.offset + 40))

  def _draw_card(self, x: int, y: int, w: int, blocks: list[tuple]) -> int:
    """Rounded PANEL card with a HAIRLINE border around wrapped text blocks."""
    inner_w = w - CARD_PAD * 2
    wrapped = []
    text_h = 0
    for text, font, font_size, color in blocks:
      lines = wrap_text(font, text, font_size, inner_w)
      wrapped.append((lines, font, font_size, color))
      text_h += int(len(lines) * font_size * FONT_SCALE)

    card = rl.Rectangle(x, y, w, text_h + CARD_PAD * 2)
    rl.draw_rectangle_rounded(card, CARD_ROUNDNESS, 12, PANEL)
    rl.draw_rectangle_rounded_lines_ex(card, CARD_ROUNDNESS, 12, 2, HAIRLINE)

    ty = y + CARD_PAD
    for lines, font, font_size, color in wrapped:
      for line in lines:
        rl.draw_text_ex(font, line, rl.Vector2(x + CARD_PAD, ty), font_size, 0, color)
        ty += font_size * FONT_SCALE
    return int(round(card.y + card.height))
