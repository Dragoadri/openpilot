#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo para enviar imágenes de las cámaras del Comma al servidor Orbit mediante MQTT.
Usa el thumbnail JPEG nativo generado por camerad (cereal 'thumbnail') para evitar
operaciones pesadas de CPU (VisionIPC, numpy, PIL) que causaban "Camera Frame Rate Low".

Soporta control remoto desde la app ORBIT via MQTT:
- Activar/desactivar envio de imagenes
- Cambiar frecuencia de envio (1s, 2s, 5s, 10s, 30s, 60s)
- Persistencia de configuracion en /data/orbit_camera_config.json
"""
import time
import threading
import base64
import json
import os

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

DEBUG_FILE = "/tmp/mqtt_debug_messages.txt"
CAMERA_CONFIG_FILE = "/data/orbit_camera_config.json"
JETSON_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_jetson.json")
VALID_FREQUENCIES = [1, 2, 5, 10, 30, 60]


class CameraSender:
  """Envía imágenes de las cámaras al servidor mediante MQTT usando el thumbnail nativo de camerad."""

  def __init__(self, mqtt_client, dongle_id, camera_type="road", interval_seconds=2.0):
    """
    Inicializa el envío de imágenes de cámara.

    Args:
      mqtt_client: Cliente MQTT compartido (paho.mqtt.client.Client)
      dongle_id: ID del dispositivo
      camera_type: Tipo de cámara ("road", "driver", "wide")
      interval_seconds: Intervalo entre envíos (segundos)
    """
    self.mqtt_client = mqtt_client
    self.dongle_id = dongle_id
    self.camera_type = self._normalize_camera_type(camera_type) or "road"
    self.interval_seconds = interval_seconds

    self.stop_event = threading.Event()
    self.sending_enabled = False  # Control remoto: desactivado por defecto
    self.last_sent = 0
    self.frame_count = 0
    self.error_count = 0
    self.consecutive_errors = 0
    self.max_backoff = 60.0

    self.params = Params()
    self.debug_enabled = False
    self._last_debug_check = 0

    # Mapeo de camera_type a canal cereal para thumbnails.
    # 'road' usa 'jetsonThumbnail' (~5 Hz, canal dedicado, NO logueado):
    # asi NO saturamos el 'thumbnail' original de comma (0.2 Hz, logueado en qlog),
    # que si se publica a 5 Hz rompe la subida de rutas a la plataforma comma.
    # 'wide' NO esta en el mapa a proposito (ver _normalize_camera_type).
    # 'driver' queda mapeado como documentacion del canal, pero HOY ES INALCANZABLE:
    # _normalize_camera_type rechaza 'driver' y es el unico camino por el que
    # self.camera_type toma valor (__init__, _load_config y apply_config lo llaman
    # los tres). Ver el comentario de privacidad en _normalize_camera_type.
    self._thumbnail_channels = {
      'road': 'jetsonThumbnail',
      'driver': 'driverThumbnail',
    }

    # Canal al que esta suscrito el loop ahora mismo. Se usa para detectar cambios
    # en caliente de camera_type y recrear el SubMaster (ver run()).
    self._active_channel = None

    # ZMQ client para envío a Jetson (se inicializa si está habilitado en config)
    self.zmq_client = None
    self._init_jetson_zmq()

    # Cargar configuracion persistida (si existe)
    self._load_config()

  def _init_jetson_zmq(self):
    """Inicializa el cliente ZMQ para envío de imágenes a la Jetson si está habilitado."""
    try:
      if not os.path.exists(JETSON_CONFIG_FILE):
        cloudlog.info("CameraSender: config_jetson.json no encontrado, Jetson ZMQ deshabilitado")
        return

      with open(JETSON_CONFIG_FILE, 'r') as f:
        config = json.load(f)

      if not config.get("jetson_enabled", False):
        cloudlog.info("CameraSender: Jetson ZMQ deshabilitado en config")
        return

      jetson_ip = config.get("jetson_ip", "192.168.1.50")
      img_port = int(config.get("jetson_img_port", 5555))
      torque_port = int(config.get("jetson_torque_port", 5556))
      jpeg_quality = int(config.get("jpeg_quality", 80))

      from openpilot.orbit.zmq_client import ZMQClient
      self.zmq_client = ZMQClient(
        jetson_ip=jetson_ip,
        img_port=img_port,
        torque_port=torque_port,
        jpeg_quality=jpeg_quality,
      )
      self.zmq_client.start()
      cloudlog.info(f"CameraSender: Jetson ZMQ iniciado -> {jetson_ip}:{img_port}")
    except Exception as e:
      cloudlog.error(f"CameraSender: error iniciando Jetson ZMQ: {e}")
      self.zmq_client = None

  def _normalize_camera_type(self, camera_type):
    """Devuelve el camera_type efectivo, o None si no es valido.

    'wide' se normaliza a 'road': loggerd solo publica el thumbnail rapido desde la
    road cam (main_road_encoder_info.fast_thumbnail_name), la wide no publica ningun
    thumbnail. Aceptar 'wide' tal cual hacia que publicasemos imagenes de la ROAD en
    el topic .../camera/wide, es decir la etiqueta mentia sobre la camara real.

    PRIVACIDAD: 'driver' se RECHAZA (mismo trato que 'wide'), no se acepta.
    Al conmutar el canal cereal en caliente, el chip 'Conductor' de la app se
    convirtio en un interruptor REMOTO que enciende el habitaculo EN VIVO, lo
    persiste en /data/orbit_camera_config.json y lo sube al backend, sin
    consentimiento de quien va dentro y SIN NINGUN INDICADOR en la pantalla del
    comma. Antes de eso, el mismo chip solo cambiaba la etiqueta hasta el
    siguiente reinicio. Se reabre cuando exista confirmacion FISICA en la pantalla
    del comma (diseno §15: la monitorizacion del conductor solo se usa como gate,
    publicarla es un tratamiento con base juridica propia).
    """
    ct = str(camera_type)
    if ct == "wide":
      cloudlog.warning("CameraSender: 'wide' no tiene thumbnail propio, se usa 'road'")
      return "road"
    if ct == "driver":
      cloudlog.warning("CameraSender: 'driver' rechazado: la cabina no se enciende en remoto sin confirmacion fisica en el comma")
      return None
    if ct == "road":
      return ct
    return None

  _PRIVACY_TTL_S = 1.0

  def _privacidad_silenciada(self) -> bool:
    """Interruptor maestro LOCAL de privacidad (OrbitPrivacyMute).

    Se relee con cache de 1 s: tiene que hacer efecto EN CALIENTE (si hubiera que
    reiniciar, el interruptor no serviria de nada en el momento en que hace falta), pero
    sin abrir el param en cada frame.
    """
    ahora = time.monotonic()
    if ahora - getattr(self, "_privacy_ts", 0.0) >= self._PRIVACY_TTL_S:
      self._privacy_ts = ahora
      try:
        self._privacy_cache = bool(self.params.get_bool("OrbitPrivacyMute"))
      except Exception:
        # Clave no registrada o disco: NO se silencia por error, pero se avisa una vez.
        if not getattr(self, "_privacy_avisado", False):
          self._privacy_avisado = True
          cloudlog.exception("CameraSender: no se pudo leer OrbitPrivacyMute")
        self._privacy_cache = False
    return getattr(self, "_privacy_cache", False)

  def _load_config(self):
    """Carga configuracion de camara desde archivo persistido."""
    try:
      if os.path.exists(CAMERA_CONFIG_FILE):
        with open(CAMERA_CONFIG_FILE, 'r') as f:
          config = json.load(f)
        if "image_sending_enabled" in config:
          self.sending_enabled = bool(config["image_sending_enabled"])
        if "send_frequency_seconds" in config:
          freq = int(config["send_frequency_seconds"])
          if freq in VALID_FREQUENCIES:
            self.interval_seconds = float(freq)
        if "camera_type" in config:
          ct = self._normalize_camera_type(config["camera_type"])
          if ct is not None:
            self.camera_type = ct
        cloudlog.info(f"CameraSender: config loaded - enabled={self.sending_enabled}, freq={self.interval_seconds}s, type={self.camera_type}")
    except Exception as e:
      cloudlog.warning(f"CameraSender: could not load config, using defaults: {e}")

  def _save_config(self):
    """Persiste configuracion de camara a disco para sobrevivir reinicios."""
    try:
      config = {
        "image_sending_enabled": self.sending_enabled,
        "send_frequency_seconds": int(self.interval_seconds),
        "camera_type": self.camera_type,
      }
      with open(CAMERA_CONFIG_FILE, 'w') as f:
        json.dump(config, f)
    except Exception as e:
      cloudlog.warning(f"CameraSender: could not save config: {e}")

  def set_enabled(self, enabled):
    """Activa o desactiva el envio de imagenes (control remoto desde app)."""
    self.sending_enabled = bool(enabled)
    self._save_config()
    cloudlog.info(f"CameraSender: sending {'enabled' if self.sending_enabled else 'disabled'}")

  def set_frequency(self, seconds):
    """Cambia la frecuencia de envio de imagenes (control remoto desde app)."""
    seconds = int(seconds)
    if seconds in VALID_FREQUENCIES:
      self.interval_seconds = float(seconds)
      self._save_config()
      cloudlog.info(f"CameraSender: frequency changed to {seconds}s")
    else:
      cloudlog.warning(f"CameraSender: invalid frequency {seconds}s, valid: {VALID_FREQUENCIES}")

  def apply_config(self, config_data):
    """Aplica configuracion recibida por MQTT desde la app.

    Args:
      config_data: dict con campos opcionales:
        - image_sending_enabled: bool
        - send_frequency_seconds: int (1, 2, 5, 10, 30, 60)
        - save_images: bool (informativo, no afecta al comma)
    """
    changed = False
    if "image_sending_enabled" in config_data:
      # El interruptor LOCAL de privacidad gana siempre: es la unica garantia real que
      # tiene quien va dentro del coche, y una orden remota no puede anularla. Antes esta
      # linea encendia el envio en caliente y dejaba el interruptor de la pantalla
      # prometiendo un silencio que no existia.
      if bool(config_data["image_sending_enabled"]) and self._privacidad_silenciada():
        cloudlog.warning("CameraSender: peticion remota de encender la camara IGNORADA: privacidad local activa")
      else:
        self.sending_enabled = bool(config_data["image_sending_enabled"])
      changed = True
    if "send_frequency_seconds" in config_data:
      # int() de un valor raro ("5s", None) lanzaba y abortaba el resto de apply_config:
      # el enabled ya aplicado se quedaba sin _save_config y volvia atras al reiniciar.
      try:
        freq = int(config_data["send_frequency_seconds"])
      except (TypeError, ValueError):
        freq = None
      if freq in VALID_FREQUENCIES:
        self.interval_seconds = float(freq)
        changed = True
      else:
        cloudlog.warning(f"CameraSender: frecuencia invalida {config_data['send_frequency_seconds']!r}, ignorada")
    if "camera_type" in config_data:
      ct = self._normalize_camera_type(config_data["camera_type"])
      if ct is not None:
        self.camera_type = ct
        changed = True
      else:
        cloudlog.warning(f"CameraSender: camera_type invalido {config_data['camera_type']!r}, ignorado")
    if changed:
      self._save_config()
      cloudlog.info(f"CameraSender: config updated - enabled={self.sending_enabled}, freq={self.interval_seconds}s, type={self.camera_type}")

  def _log_debug(self, message, camera_type=None):
    """Escribe/actualiza un mensaje de cámara en el fichero de debug si modo_debug está activo.
    En lugar de añadir una nueva línea cada vez, actualiza la entrada existente de cámara."""
    try:
      camera_type = camera_type or self.camera_type
      now = time.time()
      if now - self._last_debug_check > 2.0:
        self.debug_enabled = self.params.get_bool("modo_debug")
        self._last_debug_check = now
      if not self.debug_enabled:
        return
      ts = time.strftime("%H:%M:%S", time.localtime())
      topic = f"telemetry_mqtt/{self.dongle_id}/camera/{camera_type}"
      new_entry = f"[{ts}] {topic}\n{message}"

      # Leer contenido existente y reemplazar la entrada de cámara si ya existe
      entries = []
      camera_marker = f"/camera/{camera_type}"
      found = False
      if os.path.exists(DEBUG_FILE):
        try:
          with open(DEBUG_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
          if content.strip():
            entries = [e.strip() for e in content.split("\n\n") if e.strip()]
            for i, entry in enumerate(entries):
              if camera_marker in entry:
                entries[i] = new_entry
                found = True
                break
        except Exception:
          entries = []

      if not found:
        entries.append(new_entry)

      try:
        with open(DEBUG_FILE, 'w', encoding='utf-8') as f:
          f.write("\n\n".join(entries))
      except Exception:
        pass
    except Exception:
      pass

  def send_image(self, jpeg_data, frame_id, timestamp, camera_type=None):
    """Envía imagen por MQTT usando el cliente compartido.

    camera_type es el tipo de la camara de la que salio ESTA imagen; el loop lo pasa
    explicito. Leer self.camera_type aqui era fuga de privacidad: apply_config lo
    cambia desde el hilo de paho, asi que un frame de cabina ya leido podia acabar
    publicado en .../camera/road (y al reves).
    """
    try:
      camera_type = camera_type or self.camera_type
      jpeg_base64 = base64.b64encode(jpeg_data).decode('utf-8')

      payload = {
        "dongle_id": self.dongle_id,
        "camera_type": camera_type,
        "frame_id": frame_id,
        "timestamp": timestamp,
        "image": jpeg_base64,
        "size_bytes": len(jpeg_data),
      }

      topic = f"telemetry_mqtt/{self.dongle_id}/camera/{camera_type}"

      result = self.mqtt_client.publish(topic, json.dumps(payload), qos=0)
      if result.rc != 0:
        cloudlog.warning(f"CameraSender: MQTT publish failed rc={result.rc}")
        self.error_count += 1
        self.consecutive_errors += 1
        return False

      self.frame_count += 1
      self.consecutive_errors = 0
      self._log_debug(f"Imagen enviada frame={frame_id} size={len(jpeg_data)}B", camera_type)
      cloudlog.debug(f"CameraSender: sent frame {frame_id} ({len(jpeg_data)} bytes)")
      return True
    except Exception as e:
      cloudlog.error(f"CameraSender: send_image error: {e}")
      self.error_count += 1
      self.consecutive_errors += 1
      return False

  def run(self):
    """Loop principal: lee thumbnail nativo de camerad y envía por MQTT."""
    sm = None

    while not self.stop_event.is_set():
      # camera_type puede cambiar en caliente: apply_config corre en el hilo de paho.
      # Lo copiamos a una local y recreamos el SubMaster cuando cambia el canal, igual
      # que ya se hace con JetsonConfigChanged. Antes el canal se resolvia UNA sola vez
      # al arrancar el hilo, asi que pedir 'driver' desde la app seguia leyendo la road
      # cam y publicandola como cabina, y al reves: imagenes del habitaculo etiquetadas
      # como carretera (fuga de privacidad). Solo cambiaba la etiqueta, no la camara.
      camera_type = self.camera_type
      channel = self._thumbnail_channels.get(camera_type)
      if channel is None:
        # No deberia pasar (apply_config/_load_config normalizan), pero si llega un tipo
        # desconocido caemos a road y etiquetamos como road: la etiqueta no debe mentir.
        camera_type = 'road'
        channel = self._thumbnail_channels['road']

      # `or sm is None` NO es redundante: si messaging.SubMaster() lanza, sm se queda
      # en None y _active_channel conserva el canal ANTERIOR (solo se actualiza tras
      # el exito). Al volver a ese canal anterior la condicion era falsa, se saltaba
      # la creacion y el sm.update() de abajo -- que esta FUERA del try -- moria con
      # AttributeError: 'NoneType'. Y ese AttributeError se lleva por delante el hilo
      # entero, es decir camara + mandos + telemetria, no solo la camara.
      if channel != self._active_channel or sm is None:
        try:
          sm = None  # soltar los sockets del canal anterior antes de abrir el nuevo
          sm = messaging.SubMaster([channel])
          self._active_channel = channel
          cloudlog.info(f"CameraSender: suscrito a '{channel}' (camera_type={camera_type})")
        except Exception as e:
          # Sin la espera, un fallo repetido al suscribir dejaria el hilo girando al 100%
          cloudlog.error(f"CameraSender: no se pudo suscribir a '{channel}': {e}")
          self.stop_event.wait(1.0)
          continue

      sm.update(timeout=1000)

      # IMPORTANTE: comprobamos JetsonConfigChanged ANTES del `continue` de abajo.
      # Antes estaba dentro del bloque de procesado de thumbnail, asi que si el
      # canal no traia frames (sim sin camara, offroad, cargas puntuales...) el
      # flag nunca se leia y habia que hacer sudo reboot para que la nueva IP
      # de la Jetson tuviese efecto. Ahora el reload se hace pase lo que pase.
      try:
        if self.params.get_bool("JetsonConfigChanged"):
          self.params.put_bool("JetsonConfigChanged", False)
          self.reload_jetson_config()
      except Exception as e:
        cloudlog.warning(f"CameraSender: error comprobando JetsonConfigChanged: {e}")

      if not sm.updated[channel]:
        continue

      try:
        thumb = sm[channel]
        jpeg_data = thumb.thumbnail
        frame_id = thumb.frameId

        if not jpeg_data:
          cloudlog.warning("CameraSender: received empty thumbnail")
          continue

        # Respetar sending_enabled ANTES de cualquier envio. El send_image por ZMQ
        # estaba por encima de este guard: desactivar la camara desde la app no cortaba
        # el streaming de video hacia la IP de la Jetson (fuga de privacidad).
        if not self.sending_enabled or self._privacidad_silenciada():
          continue

        # A la Jetson solo van frames de la road cam (cada frame, independiente del
        # intervalo MQTT). Ahora que el canal si cambia con camera_type, sin este filtro
        # seleccionar 'driver' empezaria a mandar el habitaculo a esa IP externa, que
        # nunca ha recibido imagenes de cabina.
        if self.zmq_client is not None and channel == 'jetsonThumbnail':
          self.zmq_client.send_image(bytes(jpeg_data))

        current_time = time.time()

        # Backoff exponencial si hay errores consecutivos
        if self.consecutive_errors > 0:
          backoff = min(self.max_backoff, 2.0 ** min(self.consecutive_errors, 6))
          effective_interval = self.interval_seconds + backoff
        else:
          effective_interval = self.interval_seconds

        # Verificar intervalo
        if current_time - self.last_sent < effective_interval:
          continue

        timestamp_ms = int(current_time * 1000)
        self.send_image(jpeg_data, frame_id, timestamp_ms, camera_type)
        self.last_sent = current_time

      except Exception as e:
        cloudlog.error(f"CameraSender: error processing thumbnail: {e}")
        self.error_count += 1
        self.consecutive_errors += 1

  def start(self):
    """Inicia el thread de captura."""
    if not self.stop_event.is_set():
      self.thread = threading.Thread(target=self.run, daemon=True, name=f"CameraSender-{self.camera_type}")
      self.thread.start()
      return True
    return False

  def reload_jetson_config(self):
    """Recarga la configuracion de Jetson y reinicia el ZMQ client si es necesario."""
    try:
      # Parar ZMQ anterior si existe
      if self.zmq_client is not None:
        try:
          self.zmq_client.stop()
        except Exception:
          pass
        self.zmq_client = None

      # Reinicializar con nueva config
      self._init_jetson_zmq()
      cloudlog.info("CameraSender: Jetson ZMQ config recargada")
    except Exception as e:
      cloudlog.error(f"CameraSender: error recargando Jetson ZMQ: {e}")

  def stop(self):
    """Detiene el capturador."""
    self.stop_event.set()
    if self.zmq_client is not None:
      self.zmq_client.stop()
    if hasattr(self, 'thread'):
      self.thread.join(timeout=5)
