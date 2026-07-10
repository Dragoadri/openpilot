import io
import json
import os
import time
import numpy as np

from msgq.visionipc import VisionIpcServer, VisionStreamType
from cereal import messaging

from openpilot.common.basedir import BASEDIR
from openpilot.tools.sim.lib.common import W, H

THUMBNAIL_W = W // 4
THUMBNAIL_H = H // 4
THUMBNAIL_EVERY_N_FRAMES = 5
JETSON_CONFIG_FILE = os.path.join(BASEDIR, "orbit/config_jetson.json")


def rgb_to_nv12(rgb):
  """Convert RGB image to NV12 (YUV420) format using BT.601 coefficients."""
  h, w = rgb.shape[:2]
  r = rgb[:, :, 0].astype(np.int32)
  g = rgb[:, :, 1].astype(np.int32)
  b = rgb[:, :, 2].astype(np.int32)

  # Y plane - BT.601 coefficients (matches original OpenCL kernel)
  y = (((b * 13 + g * 65 + r * 33) + 64) >> 7) + 16
  y = np.clip(y, 0, 255).astype(np.uint8)

  # Subsample RGB for UV (2x2 box filter)
  r_sub = (r[0::2, 0::2] + r[0::2, 1::2] + r[1::2, 0::2] + r[1::2, 1::2] + 2) >> 2
  g_sub = (g[0::2, 0::2] + g[0::2, 1::2] + g[1::2, 0::2] + g[1::2, 1::2] + 2) >> 2
  b_sub = (b[0::2, 0::2] + b[0::2, 1::2] + b[1::2, 0::2] + b[1::2, 1::2] + 2) >> 2

  # U and V planes
  u = np.clip((b_sub * 56 - g_sub * 37 - r_sub * 19 + 0x8080) >> 8, 0, 255).astype(np.uint8)
  v = np.clip((r_sub * 56 - g_sub * 47 - b_sub * 9 + 0x8080) >> 8, 0, 255).astype(np.uint8)

  # Interleave UV for NV12 format
  uv = np.empty((h // 2, w), dtype=np.uint8)
  uv[:, 0::2] = u
  uv[:, 1::2] = v

  return np.concatenate([y.ravel(), uv.ravel()]).tobytes()


class Camerad:
  """Simulates the camerad daemon"""
  def __init__(self, dual_camera):
    self.pm = messaging.PubMaster(['roadCameraState', 'wideRoadCameraState', 'thumbnail'])
    self.zmq_client = None
    self._init_jetson_zmq()

    self.frame_road_id = 0
    self.frame_wide_id = 0
    self._tick_eof = None
    self.vipc_server = VisionIpcServer("camerad")

    self.vipc_server.create_buffers(VisionStreamType.VISION_STREAM_ROAD, 5, W, H)
    if dual_camera:
      self.vipc_server.create_buffers(VisionStreamType.VISION_STREAM_WIDE_ROAD, 5, W, H)

    self.vipc_server.start_listener()

  def _init_jetson_zmq(self):
    """Inicializa ZMQClient para enviar imágenes a la Jetson si está habilitado en config.
    Todo va envuelto en try/except: si falta config, PIL, orbit o la Jetson, el sim
    sigue funcionando normalmente sin enviar nada."""
    try:
      if not os.path.exists(JETSON_CONFIG_FILE):
        print("Camerad: config_jetson.json no encontrado, Jetson ZMQ deshabilitado")
        return

      with open(JETSON_CONFIG_FILE) as f:
        config = json.load(f)

      if not config.get("jetson_enabled", False):
        print("Camerad: Jetson ZMQ deshabilitado en config")
        return

      from openpilot.orbit.zmq_client import ZMQClient
      self.zmq_client = ZMQClient(
        jetson_ip=config.get("jetson_ip", "127.0.0.1"),
        img_port=int(config.get("jetson_img_port", 5555)),
        torque_port=int(config.get("jetson_torque_port", 5556)),
        jpeg_quality=int(config.get("jpeg_quality", 80)),
      )
      self.zmq_client.start()
      print(f"Camerad: Jetson ZMQ activo -> {config.get('jetson_ip')}:{config.get('jetson_img_port')}")
    except Exception as e:
      print(f"Camerad: error iniciando Jetson ZMQ: {e}")
      self.zmq_client = None

  def cam_send_yuv_road(self, yuv, rgb=None):
    # Timestamp del frame en el MISMO reloj que logMonoTime / los sensores simulados
    # (time.monotonic). Antes se usaba frame_id*0.05e9 (reloj falso que arranca en 0):
    # locationd compara cameraOdometry.timestampEof (heredado de este eof) contra el
    # tiempo del filtro (avanzado por accelerometer/gyroscope, que usan logMonoTime) y
    # descartaba TODAS las observaciones por "older than the max rewind threshold" ->
    # livePose.inputsOK=False -> locationdTemporaryError (noEntry) -> OP nunca engancha.
    self._tick_eof = int(time.monotonic() * 1e9)
    self._send_yuv(yuv, self.frame_road_id, 'roadCameraState', VisionStreamType.VISION_STREAM_ROAD, self._tick_eof)
    # En el coche real, orbit/camera_sender.py se suscribe al canal cereal
    # 'jetsonThumbnail' (~5 Hz) y reenvia ese mismo JPEG por ZMQ a la Jetson. Para que
    # el sim se comporte igual, generamos el thumbnail solo cada N frames y reusamos
    # esos bytes tanto para el mensaje cereal como para el envio ZMQ a la Jetson.
    if rgb is not None and self.frame_road_id % THUMBNAIL_EVERY_N_FRAMES == 0:
      self._publish_thumbnail(rgb, self.frame_road_id, self._tick_eof)
    self.frame_road_id += 1

  def cam_send_yuv_wide_road(self, yuv):
    # Reusa el eof del frame road del mismo tick (send_camera_images envia road y luego
    # wide): modeld empareja main/extra por timestamp_sof y exige |delta| < 10 ms.
    eof = self._tick_eof if self._tick_eof is not None else int(time.monotonic() * 1e9)
    self._send_yuv(yuv, self.frame_wide_id, 'wideRoadCameraState', VisionStreamType.VISION_STREAM_WIDE_ROAD, eof)
    self.frame_wide_id += 1

  def rgb_to_yuv(self, rgb):
    """Convert RGB to NV12 YUV format."""
    assert rgb.shape == (H, W, 3), f"{rgb.shape}"
    assert rgb.dtype == np.uint8
    return rgb_to_nv12(rgb)

  def _publish_thumbnail(self, rgb, frame_id, eof):
    """Genera un JPEG thumbnail del frame RGB, lo publica en el canal cereal 'thumbnail'
    y, si la Jetson esta habilitada, envia los MISMOS bytes por ZMQ (igual que hace
    orbit/camera_sender.py en el coche real con 'jetsonThumbnail')."""
    try:
      from PIL import Image
      img = Image.fromarray(rgb)
      img = img.resize((THUMBNAIL_W, THUMBNAIL_H))
      buf = io.BytesIO()
      img.save(buf, format='JPEG', quality=50)
      jpeg_data = buf.getvalue()
    except Exception as e:
      print(f"Camerad: error generando thumbnail: {e}")
      return

    dat = messaging.new_message('thumbnail', valid=True)
    dat.thumbnail.frameId = frame_id
    dat.thumbnail.timestampEof = eof
    dat.thumbnail.thumbnail = jpeg_data
    self.pm.send('thumbnail', dat)

    if self.zmq_client is not None:
      try:
        self.zmq_client.send_image(jpeg_data)
      except Exception as e:
        print(f"Camerad: error enviando frame a Jetson: {e}")

  def _send_yuv(self, yuv, frame_id, pub_type, yuv_type, eof):
    self.vipc_server.send(yuv_type, yuv, frame_id, eof, eof)

    dat = messaging.new_message(pub_type, valid=True)
    msg = {
      "frameId": frame_id,
      "transform": [1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0]
    }
    setattr(dat, pub_type, msg)
    self.pm.send(pub_type, dat)
