#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente ZeroMQ para comunicación Comma <-> Jetson.

- Publica imágenes hacia la Jetson (PUB, fire-and-forget, nunca bloquea).
- Recibe torque desde la Jetson en un hilo daemon y lo guarda en Params.

Basado en el código proporcionado por el equipo de la Jetson.
"""
import json
import math
import struct
import threading
import time

import zmq

from openpilot.common.params import Params, UnknownKeyName
from openpilot.common.swaglog import cloudlog


# [Orbit/FIX clamp] Log del recorte de torque, limitado a ~1/s: si la Jetson manda una
# escala equivocada lo hace en TODOS los mensajes (hasta 30 Hz), y un cloudlog por mensaje
# publica por ZMQ a logmessaged y suma I/O en el mismo camino que ya throttleamos abajo.
_TORQUE_CLAMP_LOG_DT = 1.0
_last_torque_clamp_log = 0.0


def _clamp_torque(v: float) -> float:
  """Recorta el torque al contrato de cereal/car.capnp (actuators.torque en [-1,1]).

  El filtro de formato de _parse_torque acepta hasta |v| < 100 SOLO para poder
  descartar denormals al adivinar endianness/precision; ese valor no puede salir
  tal cual del parser. Sintoma que evita: la Jetson manda grados (37.5) o un torque
  sin normalizar y ese 37.5 llegaba entero al carcontroller como si fuera |1| x37.
  """
  global _last_torque_clamp_log
  if -1.0 <= v <= 1.0:
    return v
  clamped = 1.0 if v > 1.0 else -1.0
  # monotonic: esto es un intervalo, no una marca de tiempo que cruce procesos.
  now = time.monotonic()
  if now - _last_torque_clamp_log >= _TORQUE_CLAMP_LOG_DT:
    cloudlog.error(f"ZMQClient: torque fuera del contrato [-1,1] recortado: {v} -> {clamped}")
    _last_torque_clamp_log = now
  return clamped


def _parse_torque(data: bytes):
  """Convierte el payload de la Jetson en un float, sea cual sea su formato.

  Si elegimos un formato fijo y la Jetson manda otro (big-endian, double,
  texto…), el resultado tipico es un valor denormal (~1e-44) que en la UI
  sale como "0.00" — el sintoma de "imprime 0 aunque mande 0.5".

  Probamos las representaciones razonables y nos quedamos con la primera
  que caiga en el rango fisicamente posible para nuestro torque normalizado
  [-1, 1] (con holgura). Los denormals quedan filtrados por |v| < 1e-30.
  Devuelve None si nada cuadra.

  El valor elegido sale SIEMPRE recortado a [-1,1] (_clamp_torque): la holgura
  del filtro es para adivinar el formato, no un rango valido de salida.
  """
  candidates: list[float] = []
  n = len(data)
  if n == 4:
    candidates.append(struct.unpack("<f", data)[0])
    candidates.append(struct.unpack(">f", data)[0])
  elif n == 8:
    candidates.append(struct.unpack("<d", data)[0])
    candidates.append(struct.unpack(">d", data)[0])
  else:
    try:
      v = float(data.decode().strip())
    except Exception:
      return None
    if not math.isfinite(v):
      return None
    return _clamp_torque(v)

  for v in candidates:
    if not math.isfinite(v):
      continue
    if v == 0.0 or 1e-30 < abs(v) < 100.0:
      return _clamp_torque(v)
  return None


class ZMQClient:
  """Comunicación ZeroMQ entre Comma (pcA) y Jetson (pcB)."""

  def __init__(self, jetson_ip, img_port=5555, torque_port=5556, jpeg_quality=80):
    """
    Args:
      jetson_ip:    IP de la Jetson en la red local. Ej: "192.168.1.50"
      img_port:     Puerto para enviar imágenes (default 5555).
      torque_port:  Puerto para recibir torque (default 5556).
      jpeg_quality: Calidad JPEG 0-100 (default 80).
    """
    self._jpeg_quality = jpeg_quality
    self._params = Params()
    self._running = False

    self._context = zmq.Context()

    # PUB: envío de imágenes — fire-and-forget, nunca bloquea
    self._img_socket = self._context.socket(zmq.PUB)
    self._img_socket.setsockopt(zmq.SNDHWM, 1)  # descarta si Jetson va lento
    # LINGER=0: al hacer close() no esperamos a drenar colas pendientes.
    # Critico para reload_jetson_config (cambio de IP en caliente): sin esto
    # context.term() podia bloquear y dejar el puerto 5555 en un estado raro.
    self._img_socket.setsockopt(zmq.LINGER, 0)
    self._img_socket.bind(f"tcp://*:{img_port}")

    # PULL: recepción de torque desde Jetson
    self._torque_socket = self._context.socket(zmq.PULL)
    self._torque_socket.setsockopt(zmq.LINGER, 0)
    # Timeout en recv para que el hilo listener no quede bloqueado para
    # siempre si la Jetson no envia nada; asi stop()+join() pueden cerrar
    # en tiempo finito incluso si la Jetson esta muerta.
    self._torque_socket.setsockopt(zmq.RCVTIMEO, 500)  # ms
    self._torque_socket.connect(f"tcp://{jetson_ip}:{torque_port}")

    self._listener_thread = threading.Thread(
      target=self._torque_listener,
      daemon=True,
      name="jetson-torque-listener",
    )

    # [Orbit/FIX commIssue] Escritor de Params DESACOPLADO y COALESCENTE.
    # ANTES: cada mensaje ZMQ de la Jetson hacia 2x Params.put() (valor + timestamp)
    # directamente en el hilo listener. En este openpilot put() = mkstemp + fsync(fichero)
    # + flock EXCLUSIVO del .lock GLOBAL de /data/params (eMMC) + rename + fsync(directorio),
    # SIN coalescing (params.cc:132-169,237-243). A 30 Hz (obstaculo modo 3) eso son ~60
    # fsync/s bajo un lock que comparten TODOS los procesos -> satura el journal ext4 y
    # serializa el acceso a params de controlsd/card/locationd, que pierden su ventana de
    # "alive" (100 ms) -> selfdrived dispara commIssue / locationdTemporaryError (se alternan).
    # El comentario original ("put_nonblocking: el writer es un hilo aparte con cola FIFO")
    # describia un diseno que NUNCA se implemento. Aqui SI: el listener solo actualiza
    # variables en memoria y este hilo vuelca a disco SOLO el ultimo valor pendiente a un
    # ritmo acotado, de modo que una rafaga de N mensajes = como mucho 1 escritura por periodo.
    self._pending_lock = threading.Lock()
    self._pending_torque = None        # float | None  (ultimo torque recibido sin escribir)
    self._pending_obstacle = None      # str(JSON) | None  (ultimo pulso recibido sin escribir)
    self._writer_stop = threading.Event()
    self._writer_thread = threading.Thread(
      target=self._param_writer,
      daemon=True,
      name="jetson-param-writer",
    )
    self._last_torque_log = 0.0        # throttle del cloudlog.info por mensaje
    self._last_obstacle_log = 0.0

    cloudlog.info(f"ZMQClient: configurado para Jetson en {jetson_ip} (img:{img_port}, torque:{torque_port})")

  def start(self):
    """Arranca los hilos de escucha de torque y de escritura coalescente."""
    self._running = True
    self._writer_stop.clear()
    self._listener_thread.start()
    self._writer_thread.start()
    cloudlog.info("ZMQClient: hilos de escucha de torque y escritor de params iniciados")

  def send_image(self, jpeg_data):
    """
    Envía datos JPEG ya codificados a la Jetson.
    No bloquea nunca: si la Jetson no está lista, el frame se descarta.

    Args:
      jpeg_data: bytes con la imagen JPEG ya codificada
    """
    try:
      self._img_socket.send(jpeg_data, zmq.NOBLOCK)
    except zmq.Again:
      pass  # Socket lleno, frame descartado (comportamiento esperado)
    except zmq.ZMQError as e:
      cloudlog.warning(f"ZMQClient: error enviando imagen: {e}")

  def stop(self):
    """Cierra los sockets y el contexto ZMQ limpiamente.

    Critico para cambiar IP en caliente: esta funcion se llama desde
    reload_jetson_config cada vez que el usuario modifica la config. Tiene
    que dejar el puerto 5555 LIBRE para que el siguiente bind funcione.
    """
    self._running = False
    self._writer_stop.set()
    # Esperar a que el hilo listener salga del recv (timeout RCVTIMEO=500ms)
    # y termine limpio antes de cerrar sockets/contexto. Sin join podiamos
    # tener el hilo vivo usando _torque_socket mientras otro thread lo cierra.
    if self._listener_thread.is_alive():
      self._listener_thread.join(timeout=1.5)
    if self._writer_thread.is_alive():
      self._writer_thread.join(timeout=1.0)
    try:
      self._img_socket.close(linger=0)
    except Exception:
      pass
    try:
      self._torque_socket.close(linger=0)
    except Exception:
      pass
    try:
      self._context.term()
    except Exception:
      pass
    cloudlog.info("ZMQClient: detenido")

  def _handle_obstacle_json(self, data: bytes) -> None:
    """Parsea un mensaje JSON del modo 3 (COMMA+JETSON) y lo publica en Params.

    Modelo "estado continuo" (v3): el formato esperado es
      {"obstacle": bool, "intensity": float [-1,+1]}
    El Comma se queda con el último mensaje recibido: obstacle=true →
    esquive activo con esa intensity hasta que llegue otro mensaje,
    obstacle=false → idle. Ya no existe `duration_ms`.
    SÍ hay watchdog (controlsd, JETSON_TORQUE_TIMEOUT_S): por eso cada
    mensaje refresca JetsonObstacleTimestamp — si la Jetson se calla, el
    esquive caduca y vuelve a neutro. Las otras cancelaciones son volante /
    freno (CANCELED_DRIVER) y latActive=false.

    Si el JSON está mal formado o le faltan campos clave, se loguea y se
    descarta. NO se escribe en JetsonObstaclePulse para que el lado de
    controlsd no detecte un mensaje nuevo erróneo.
    """
    try:
      payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
      cloudlog.error(f"ZMQClient: JSON obstáculo no decodificable: {e} bytes={data[:50]!r}")
      return

    if not isinstance(payload, dict):
      cloudlog.error(f"ZMQClient: JSON obstáculo no es objeto: {payload!r}")
      return

    intensity = payload.get("intensity")
    if not isinstance(intensity, (int, float)) or not math.isfinite(intensity):
      cloudlog.error(f"ZMQClient: JSON obstáculo intensity no válido (esperado float finito): {payload!r}")
      return

    now = time.time()
    # Log throttled a ~1/s: antes era 1 por mensaje (hasta 30/s) y cada cloudlog.info
    # publica por ZMQ a logmessaged -> mas presion de I/O en el mismo camino.
    if now - self._last_obstacle_log >= 1.0:
      cloudlog.info(f"ZMQClient: pulso obstáculo {payload}")
      self._last_obstacle_log = now
    # NO se escribe en Params aqui: solo dejamos el ultimo payload pendiente. El hilo
    # _param_writer lo vuelca a disco a ritmo acotado (coalescing). Estado continuo:
    # si llegan varios pulsos antes del proximo volcado, solo cuenta el ultimo.
    with self._pending_lock:
      self._pending_obstacle = json.dumps(payload)

  def _torque_listener(self):
    """Hilo daemon: espera torques/obstáculos de la Jetson y los guarda en Params.

    Drain pattern (estado-continuo):
      Cada `recv()` bloqueante despierta el hilo; acto seguido drenamos la
      cola ZMQ en modo no-bloqueante y nos quedamos SOLO con el ÚLTIMO
      mensaje de cada tipo (torque vs obstáculo). Ambos canales son
      estado-continuo (controlsd lee el último valor del param), así que
      procesar mensajes intermedios solo gasta CPU/I-O.

      Sin esto: si la Jetson manda `obstacle:true` a 30 Hz y luego un
      `obstacle:false`, el `false` quedaba al final de la cola y tardaba
      varios segundos en aplicarse (= "tarda en volver al modelo Comma").

    Guarda tambien un timestamp (wall-clock) por cada torque recibido. Eso
    permite a controlsd detectar que la Jetson se ha caido (watchdog): si el
    timestamp tiene mas de N ms de antiguedad, controlsd fuerza torque=0
    para que el volante no se quede atascado con un valor viejo.
    """
    while self._running:
      try:
        data = self._torque_socket.recv()
      except zmq.Again:
        # RCVTIMEO cumplido sin datos. Volvemos a comprobar _running y
        # seguimos esperando. Es el mecanismo que permite a stop() romper
        # el bucle en tiempo finito.
        continue
      except zmq.ZMQError as e:
        if e.errno == zmq.ETERM:
          break
        cloudlog.warning(f"ZMQClient: error recibiendo torque: {e}")
        continue
      except Exception as e:
        cloudlog.error(f"ZMQClient: error inesperado: {e}")
        continue

      # Drenar la cola: solo el ÚLTIMO mensaje de cada tipo nos importa.
      # Distinguimos por longitud (heredado del protocolo): len==4 → torque
      # clásico (float empaquetado, modo 1); len>4 → JSON modo 3.
      latest_torque: bytes | None = None
      latest_obstacle: bytes | None = None
      if len(data) > 4:
        latest_obstacle = data
      else:
        latest_torque = data
      # Bound defensivo para evitar bucle largo si llegan mensajes
      # continuamente más rápido de lo que drenamos (no debería pasar, pero
      # nunca dejes una recv-loop sin techo).
      drained_extra = 0
      while drained_extra < 1024:
        try:
          d = self._torque_socket.recv(zmq.NOBLOCK)
        except zmq.Again:
          break
        except zmq.ZMQError as e:
          if e.errno == zmq.ETERM:
            return
          cloudlog.warning(f"ZMQClient: error drenando cola: {e}")
          break
        drained_extra += 1
        if len(d) > 4:
          latest_obstacle = d
        else:
          latest_torque = d
      if drained_extra > 0:
        cloudlog.info(f"ZMQClient: drenados {drained_extra} mensajes (backlog), procesando solo el último de cada tipo")

      # Procesar obstáculo (si lo hay): el handler ya hace put_nonblocking.
      if latest_obstacle is not None:
        self._handle_obstacle_json(latest_obstacle)

      # Procesar torque clásico (si lo hay).
      if latest_torque is not None:
        torque = _parse_torque(latest_torque)
        if torque is None:
          # Payload irreconocible -> ignorar este mensaje (no escribimos
          # nada en params, asi el watchdog de controlsd lo marcara stale
          # y el volante quedara en 0 hasta que llegue un valor valido).
          cloudlog.error(f"ZMQClient: payload de torque irreconocible bytes={latest_torque.hex()} len={len(latest_torque)}")
          continue
        # Log throttled a ~1/s (antes 1 por mensaje): a ritmo de la Jetson cada
        # cloudlog.info publica por ZMQ a logmessaged y suma I/O.
        now = time.time()
        if now - self._last_torque_log >= 1.0:
          cloudlog.info(f"ZMQClient: torque recibido bytes={latest_torque.hex()} len={len(latest_torque)} -> {torque}")
          self._last_torque_log = now
        # NO se escribe en Params aqui: solo dejamos el ultimo torque pendiente.
        # El hilo _param_writer lo vuelca (con su timestamp) a ritmo acotado.
        with self._pending_lock:
          self._pending_torque = torque

  def _param_writer(self):
    """Vuelca a Params el ULTIMO torque/obstaculo recibido, a ritmo ACOTADO (coalescing).

    Este es el "hilo escritor con cola" que el codigo prometia pero no tenia: una rafaga
    de N mensajes ZMQ se colapsa en como mucho 1 escritura por periodo, eliminando la
    tormenta de fsync+flock global que disparaba commIssue / locationdTemporaryError al
    activar OP.

    Semantica de CONSUMO: cogemos y LIMPIAMOS el pendiente bajo lock SOLO cuando toca
    escribir (rate-limit cumplido); si esta limitado, el pendiente se queda para el
    proximo tick -> NUNCA perdemos el ULTIMO mensaje (p.ej. el "obstacle:false" final).
    El fsync se hace FUERA del lock, asi el listener jamas se bloquea en disco. Se preserva
    el orden original (timestamp antes que valor) y la frescura del timestamp por mensaje
    (controlsd usa JetsonObstacleTimestamp para la re-ingesta del pulso; un futuro watchdog
    de torque podra usar JetsonTorqueTimestamp).

    Vive en el proceso manager (SCHED_OTHER), asi que su fsync nunca corre a prioridad
    de tiempo real; el unico objetivo es BAJAR el numero de escrituras/segundo.
    """
    TORQUE_MIN_DT = 0.04       # <=25 Hz (latencia baja para direccion; la Jetson real va ~5 Hz)
    OBSTACLE_MIN_DT = 0.10     # <=10 Hz (estado continuo, tolera coalescing)
    last_torque_t = 0.0
    last_obstacle_t = 0.0
    while not self._writer_stop.is_set():
      now = time.time()
      # Fase 1: coger+limpiar bajo lock SOLO lo que vamos a escribir ya (respetando rate-limit).
      pend_torque = None
      pend_obstacle = None
      with self._pending_lock:
        if self._pending_torque is not None and (now - last_torque_t) >= TORQUE_MIN_DT:
          pend_torque = self._pending_torque
          self._pending_torque = None
        if self._pending_obstacle is not None and (now - last_obstacle_t) >= OBSTACLE_MIN_DT:
          pend_obstacle = self._pending_obstacle
          self._pending_obstacle = None

      # Fase 2: escribir FUERA del lock (el fsync nunca bloquea al listener).
      if pend_torque is not None:
        try:
          self._params.put("JetsonTorqueTimestamp", f"{now:.6f}")  # ts primero (liveness), valor despues
        except UnknownKeyName:
          pass
        try:
          self._params.put("JetsonTorque", str(pend_torque))
          last_torque_t = now
        except UnknownKeyName:
          if not getattr(self, "_warned_torque_param", False):
            cloudlog.error("JetsonTorque no registrado en params_keys.h.")
            self._warned_torque_param = True

      if pend_obstacle is not None:
        try:
          self._params.put("JetsonObstaclePulse", pend_obstacle)
          self._params.put("JetsonObstacleTimestamp", f"{now:.6f}")
          last_obstacle_t = now
        except UnknownKeyName:
          if not getattr(self, "_warned_obstacle_param", False):
            cloudlog.error("JetsonObstaclePulse/Timestamp no registrado en params_keys.h.")
            self._warned_obstacle_param = True

      # Tick corto: los *_MIN_DT gobiernan el ritmo real de escritura; esto solo acota
      # la latencia maxima (<=20 ms) entre recibir un valor y volcarlo.
      self._writer_stop.wait(0.02)
