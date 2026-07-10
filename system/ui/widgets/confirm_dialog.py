import pyray as rl
from collections.abc import Callable
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import ButtonStyle, Button
from openpilot.system.ui.widgets.label import Label
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets.html_render import HtmlRenderer, ElementType
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller

OUTER_MARGIN = 200
RICH_OUTER_MARGIN = 100
BUTTON_HEIGHT = 160
MARGIN = 50
TEXT_PADDING = 10
FONT_SIZE = 70        # message font; auto-shrunk down to MIN_FONT_SIZE when the wrapped text does not fit
MIN_FONT_SIZE = 40
BACKGROUND_COLOR = rl.Color(22, 35, 58, 255)  # ORBIT NAVY dialog surface


class ConfirmDialog(Widget):
  def __init__(self, text: str, confirm_text: str, cancel_text: str | None = None, rich: bool = False, callback: Callable[[DialogResult], None] | None = None):
    super().__init__()
    if cancel_text is None:
      cancel_text = tr("Cancel")
    self._text = text
    self._label = Label(text, FONT_SIZE, FontWeight.BOLD, text_color=rl.Color(226, 236, 255, 255))  # ORBIT INK message text
    self._html_renderer = HtmlRenderer(text=text, text_size={ElementType.P: 50}, center_text=True)
    self._cancel_button = Button(cancel_text, self._cancel_button_callback)
    self._confirm_button = Button(confirm_text, self._confirm_button_callback, button_style=ButtonStyle.PRIMARY)
    self._rich = rich
    self._callback = callback
    self._cancel_text = cancel_text
    self._scroller = Scroller([self._html_renderer], line_separator=False, spacing=0)
    self._fitted_key: tuple | None = None

  def set_text(self, text):
    self._text = text
    self._fitted_key = None
    if not self._rich:
      self._label.set_text(text)
    else:
      self._html_renderer.parse_html_content(text)

  def _cancel_button_callback(self):
    gui_app.pop_widget()
    if self._callback:
      self._callback(DialogResult.CANCEL)

  def _confirm_button_callback(self):
    gui_app.pop_widget()
    if self._callback:
      self._callback(DialogResult.CONFIRM)

  def _fit_font_size(self, text_rect: rl.Rectangle):
    """Encoge la fuente del mensaje hasta que el texto envuelto quepa en el area
    fija de texto (los dialogos largos del selector Jetson desbordaban el modal)."""
    key = (self._text, int(text_rect.width), int(text_rect.height))
    if self._fitted_key == key:
      return
    self._fitted_key = key
    font = gui_app.font(FontWeight.BOLD)
    size = FONT_SIZE
    while size > MIN_FONT_SIZE:
      lines = wrap_text(font, self._text, size, int(text_rect.width))
      if len(lines) * size * FONT_SCALE <= text_rect.height:  # line height = font_size * FONT_SCALE (regla del repo)
        break
      size -= 2
    self._label.set_font_size(size)

  def _render(self, rect: rl.Rectangle):
    dialog_x = OUTER_MARGIN if not self._rich else RICH_OUTER_MARGIN
    dialog_y = OUTER_MARGIN if not self._rich else RICH_OUTER_MARGIN
    dialog_width = gui_app.width - 2 * dialog_x
    dialog_height = gui_app.height - 2 * dialog_y
    dialog_rect = rl.Rectangle(dialog_x, dialog_y, dialog_width, dialog_height)

    bottom = dialog_rect.y + dialog_rect.height
    button_width = (dialog_rect.width - 3 * MARGIN) // 2
    cancel_button_x = dialog_rect.x + MARGIN
    confirm_button_x = dialog_rect.x + dialog_rect.width - button_width - MARGIN
    button_y = bottom - BUTTON_HEIGHT - MARGIN
    cancel_button = rl.Rectangle(cancel_button_x, button_y, button_width, BUTTON_HEIGHT)
    confirm_button = rl.Rectangle(confirm_button_x, button_y, button_width, BUTTON_HEIGHT)

    rl.draw_rectangle_rec(dialog_rect, BACKGROUND_COLOR)

    text_rect = rl.Rectangle(dialog_rect.x + MARGIN, dialog_rect.y + TEXT_PADDING,
                             dialog_rect.width - 2 * MARGIN, dialog_rect.height - BUTTON_HEIGHT - MARGIN - TEXT_PADDING * 2)
    if not self._rich:
      self._fit_font_size(text_rect)
      rl.begin_scissor_mode(int(text_rect.x), int(text_rect.y), int(text_rect.width), int(text_rect.height))
      self._label.render(text_rect)
      rl.end_scissor_mode()
    else:
      html_rect = rl.Rectangle(text_rect.x, text_rect.y, text_rect.width,
                               self._html_renderer.get_total_height(int(text_rect.width)))
      self._html_renderer.set_rect(html_rect)
      self._scroller.render(text_rect)

    if rl.is_key_pressed(rl.KeyboardKey.KEY_ENTER):
      self._confirm_button_callback()
    elif rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
      self._cancel_button_callback()

    if self._cancel_text:
      self._confirm_button.render(confirm_button)
      self._cancel_button.render(cancel_button)
    else:
      full_button_width = dialog_rect.width - 2 * MARGIN
      full_confirm_button = rl.Rectangle(dialog_rect.x + MARGIN, button_y, full_button_width, BUTTON_HEIGHT)
      self._confirm_button.render(full_confirm_button)


def alert_dialog(message: str, button_text: str | None = None):
  if button_text is None:
    button_text = tr("OK")
  return ConfirmDialog(message, button_text, cancel_text="")
