import pyray as rl
import qrcode
import numpy as np
import time

from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.button import IconButton


class OrbitEnrollDialog(Widget):
  """Dialog for linking this device to ORBIT with a QR code."""

  QR_REFRESH_INTERVAL = 300  # 5 minutes in seconds

  def __init__(self):
    super().__init__()
    self.params = Params()
    self.qr_texture: rl.Texture | None = None
    self.last_qr_generation = float('-inf')
    self._last_code: str | None = None
    self._close_btn = IconButton(gui_app.texture("icons/close.png", 80, 80))
    self._close_btn.set_click_callback(gui_app.pop_widget)

  def _get_pairing_code(self) -> str:
    try:
      return self.params.get("OrbitPairingCode") or ""
    except Exception:
      cloudlog.exception("Failed to read OrbitPairingCode")
      return ""

  def _get_pairing_url(self) -> str:
    try:
      dongle_id = self.params.get("DongleId") or ""
    except Exception:
      cloudlog.exception("Failed to read DongleId")
      dongle_id = ""
    code = self._get_pairing_code()
    return f"orbit://enroll?d={dongle_id}&c={code}"

  def _generate_qr_code(self) -> None:
    try:
      qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
      qr.add_data(self._get_pairing_url())
      qr.make(fit=True)

      pil_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')
      img_array = np.array(pil_img, dtype=np.uint8)

      if self.qr_texture and self.qr_texture.id != 0:
        rl.unload_texture(self.qr_texture)

      rl_image = rl.Image()
      rl_image.data = rl.ffi.cast("void *", img_array.ctypes.data)
      rl_image.width = pil_img.width
      rl_image.height = pil_img.height
      rl_image.mipmaps = 1
      rl_image.format = rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8

      self.qr_texture = rl.load_texture_from_image(rl_image)
    except Exception:
      cloudlog.exception("QR code generation failed")
      self.qr_texture = None

  def _check_qr_refresh(self) -> None:
    current_time = time.monotonic()
    code = self._get_pairing_code()

    # Regenerate when the pairing code changes, in addition to the periodic refresh.
    if code != self._last_code or current_time - self.last_qr_generation >= self.QR_REFRESH_INTERVAL:
      self._generate_qr_code()
      self._last_code = code
      self.last_qr_generation = current_time

  def _update_state(self):
    try:
      if self.params.get_bool("OrbitClaimed"):
        gui_app.pop_widget()
    except Exception:
      cloudlog.exception("Failed to read OrbitClaimed")

  def _render(self, rect: rl.Rectangle) -> int:
    rl.clear_background(rl.Color(11, 18, 32, 255))  # ORBIT: VOID background

    self._check_qr_refresh()

    margin = 70
    content_rect = rl.Rectangle(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)
    y = content_rect.y

    # Close button
    close_size = 80
    pad = 20
    close_rect = rl.Rectangle(content_rect.x - pad, y - pad, close_size + pad * 2, close_size + pad * 2)
    self._close_btn.render(close_rect)

    y += close_size + 40

    # Title
    title = tr("Link this device to ORBIT")
    title_font = gui_app.font(FontWeight.NORMAL)
    left_width = int(content_rect.width * 0.5 - 15)

    title_wrapped = wrap_text(title_font, title, 75, left_width)
    rl.draw_text_ex(title_font, "\n".join(title_wrapped), rl.Vector2(content_rect.x, y), 75, 0.0, rl.Color(226, 236, 255, 255))  # ORBIT: INK title
    y += len(title_wrapped) * 75 + 60

    # Two columns: instructions and QR code
    remaining_height = content_rect.height - (y - content_rect.y)
    right_width = content_rect.width // 2 - 20

    # Instructions
    self._render_instructions(rl.Rectangle(content_rect.x, y, left_width, remaining_height))

    # QR code
    qr_size = min(right_width, content_rect.height) - 40
    qr_x = content_rect.x + left_width + 40 + (right_width - qr_size) // 2
    qr_y = content_rect.y
    self._render_qr_code(rl.Rectangle(qr_x, qr_y, qr_size, qr_size))

    return -1

  def _render_instructions(self, rect: rl.Rectangle) -> None:
    instructions = [
      tr("Open the ORBIT app"),
      tr("Go to Settings/Home -> Link device"),
      tr("Scan the QR (or type the code below)"),
    ]

    font = gui_app.font(FontWeight.BOLD)
    y = rect.y

    for i, text in enumerate(instructions):
      circle_radius = 25
      circle_x = rect.x + circle_radius + 15
      text_x = rect.x + circle_radius * 2 + 40
      text_width = rect.width - (circle_radius * 2 + 40)

      wrapped = wrap_text(font, text, 47, int(text_width))
      text_height = len(wrapped) * 47
      circle_y = y + text_height // 2

      # Circle and number  # ORBIT: BLUE_DEEP circle with INK number
      rl.draw_circle(int(circle_x), int(circle_y), circle_radius, rl.Color(37, 99, 235, 255))
      number = str(i + 1)
      number_size = measure_text_cached(font, number, 30)
      rl.draw_text_ex(font, number, (int(circle_x - number_size.x // 2), int(circle_y - number_size.y // 2)), 30, 0, rl.Color(226, 236, 255, 255))

      # Text  # ORBIT: INK instruction text
      rl.draw_text_ex(font, "\n".join(wrapped), rl.Vector2(text_x, y), 47, 0.0, rl.Color(226, 236, 255, 255))
      y += text_height + 50

  def _render_qr_code(self, rect: rl.Rectangle) -> None:
    if not self.qr_texture:
      rl.draw_rectangle_rounded(rect, 0.1, 20, rl.Color(22, 35, 58, 255))  # ORBIT: NAVY error placeholder, keep red error text
      error_font = gui_app.font(FontWeight.BOLD)
      rl.draw_text_ex(
        error_font, tr("QR Code Error"), rl.Vector2(rect.x + 20, rect.y + rect.height // 2 - 15), 30, 0.0, rl.RED
      )
      return

    # ORBIT: white quiet-zone tile behind QR so it stays scannable (QR texture kept untinted)
    tile_pad = 12
    tile_rect = rl.Rectangle(rect.x - tile_pad, rect.y - tile_pad, rect.width + tile_pad * 2, rect.height + tile_pad * 2)
    rl.draw_rectangle_rounded(tile_rect, 0.05, 20, rl.WHITE)

    source = rl.Rectangle(0, 0, self.qr_texture.width, self.qr_texture.height)
    rl.draw_texture_pro(self.qr_texture, source, rect, rl.Vector2(0, 0), 0, rl.WHITE)

    # Human-readable raw pairing code (manual-entry fallback) beneath the QR
    code = self._get_pairing_code()
    code_font = gui_app.font(FontWeight.BOLD)
    code_text = code if code else tr("waiting for code...")
    code_size = 40
    code_measure = measure_text_cached(code_font, code_text, code_size)
    code_x = rect.x + (rect.width - code_measure.x) // 2
    code_y = rect.y + rect.height + 20
    rl.draw_text_ex(code_font, code_text, rl.Vector2(code_x, code_y), code_size, 0.0, rl.Color(226, 236, 255, 255))  # ORBIT: INK pairing code

  def __del__(self):
    if self.qr_texture and self.qr_texture.id != 0:
      rl.unload_texture(self.qr_texture)


if __name__ == "__main__":
  gui_app.init_window("orbit enroll")
  enroll = OrbitEnrollDialog()
  gui_app.push_widget(enroll)
  try:
    for _ in gui_app.render():
      pass
  finally:
    del enroll
