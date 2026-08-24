#!/usr/bin/env python3
import json
import math
import time
import secrets
import threading
import paho.mqtt.client as mqtt
import cereal.messaging as messaging
from cereal.services import SERVICE_LIST
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
import os
from .mqtt_comandos import MQTTComandos
from .camera_sender import CameraSender
from .command_state import get_command_plane


# Namespaces MQTT de presencia. v1 (telemetry_mqtt/...) es LEGACY: es el que
# consume la app de hoy y muere al cerrar la migracion. v2 (orbit/v2/...) es el
# contrato congelado del diseno de mando remoto v2 (seccion 3.1: retenido, qos 0).
# Durante la migracion se publica en AMBOS (seccion 13, publicacion dual v1+v2).
TOPIC_PRESENCE_V1 = "telemetry_mqtt/{}/presence"
TOPIC_PRESENCE_V2 = "orbit/v2/presence/{}"

# Retenidos rancios que quedaron en el broker de la epoca de los topics */global
# (mandos a TODA la flota, ya retirados del firmware). Ver _purge_retenidos_legacy.
TOPICS_GLOBAL_LEGACY = (
  "steer_torque_mode/global",
  "jetson_config/global",
  "jetson_obstacle_status/global",
)


def _epoch_ms() -> int:
  """Instante de PARED en epoch milisegundos enteros (seccion 3.2 del diseno v2).

  Existe para no repetir el noqa: time.time esta prohibido en este arbol porque casi
  siempre lo que se quiere es un plazo, y un plazo con reloj de pared salta cuando entra
  el NTP. Aqui si se quiere pared: son sellos que fecha la app o el backend. Los plazos
  internos de este fichero usan time.monotonic().
  """
  return time.time_ns() // 1_000_000


def _sanea_no_finitos(obj):
  """Sustituye recursivamente los float no finitos (NaN/inf) por None.

  json.dumps() emite por defecto los literales NaN/Infinity, que NO son JSON
  valido (RFC 8259): el parser del backend revienta y se pierde el mensaje
  ENTERO, de forma intermitente y sin ningun rastro porque el publish sale con
  rc=0. Que en este arbol hay no finitos esta confirmado por las defensas que
  ya existen aguas arriba (controlsd.py filtra la curvatura con math.isfinite,
  calibrationd.py comprueba np.isnan).
  """
  if isinstance(obj, float):
    return obj if math.isfinite(obj) else None
  if isinstance(obj, dict):
    return {k: _sanea_no_finitos(v) for k, v in obj.items()}
  if isinstance(obj, (list, tuple)):
    return [_sanea_no_finitos(v) for v in obj]
  return obj


class MQTTEnvioGeneral:
  def __init__(self):
    self.velocidadActualizacion = 1
    self.base_path = os.path.dirname(os.path.abspath(__file__))
    self.jsonConfig = os.path.join(self.base_path, "config_mqtt.json")
    self.jsonCanales = os.path.join(self.base_path, "canales.json")
    self.espera = 0.5
    self.pause_event = threading.Event()
    self.pause_event.set()
    self.stop_event = threading.Event()
    self.params = Params()
    # Identidad del dispositivo. Params.get() ya devuelve str.
    # SIN DongleId real NO hay identidad: el literal "DongleID" no es un id, es
    # un namespace COMPARTIDO por todos los comma sin registrar. Publicar ahi
    # GPS, velocidad y JPEG de camara junta a TODOS los dispositivos sin
    # registrar en un unico vehiculo fantasma llamado "DongleID" (el backend v2
    # toma topic_parts[1] como identidad autoritativa). Mientras el dongle no
    # sea valido este proceso NO publica telemetria, ni heartbeat, ni camara,
    # ni snapshots de configuracion: la UNICA salida permitida es el anuncio de
    # enrolamiento, que es justo el mecanismo por el que el dispositivo consigue
    # identidad. La ENTRADA de mandos ya estaba cerrada en mqtt_comandos.py.
    self.DongleID = "DongleID"
    self.dongle_valido = False
    # Arranque diferido del CameraSender al hilo del loop (ver _start_camera_sender).
    self._camera_pendiente = False
    # Log rate-limitado del estado "sin identidad": el loop corre a 1 Hz y sin
    # limite llenaria el log (y la flash) mientras el dispositivo no se registre.
    self._last_sin_dongle_log = 0.0
    self.SIN_DONGLE_LOG_SECS = 60.0
    self._refresh_dongle()
    self.conectado = False
    self.params.put_bool("OrbitConnected", False)
    self._last_heartbeat = 0.0
    self.HEARTBEAT_SECS = 3.0
    # Log de publish fallido con rate limit: el bucle de canales corre a 1 Hz
    # sobre N canales, asi que sin limite un broker caido llena el log (y la
    # flash) con la misma linea cientos de veces por minuto.
    self._last_rc_log = 0.0
    self.RC_LOG_SECS = 30.0
    # Hilo UNICO de conexion + su senal de relevo (ver _relanzar_hilo_conexion).
    self._conn_thread = None
    self._conn_stop = threading.Event()
    self._conn_pendiente = False
    # Deteccion de 'conectado pero mudo' para healthy(): instante (monotonic)
    # del primer sintoma, para exigir que persista antes de pedir un reinicio.
    self._mudo_desde = None
    self.MUDO_GRACE_SECS = 15.0
    self._last_toggles_check = time.monotonic()   # plazo interno: monotono, no epoch
    self.TOGGLES_RELOAD_SECS = 5.0
    # Estado del anuncio de enrolamiento ORBIT (QR). Ver _maybe_announce_enroll.
    self._last_enroll = 0.0
    self._enroll_issued_at = 0.0
    self._pairing_code = None
    self.ENROLL_ANNOUNCE_SECS = 30.0
    self.ENROLL_TTL_S = 600
    # Diagnostico remoto (healthcheck): SubMaster propio de este hilo, perezoso.
    self._diag_sm = None
    self.load_config()
    self.cargar_canales()
    self.init_submaster()
    self.init_mqtt()
    self.init_comandos()
    self.init_camera_sender()
    self._link_camera_to_comandos()

  def load_config(self):
    with open(self.jsonConfig) as f:
      config = json.load(f)
      self.broker_address = config.get("broker", "localhost")
      self.broker_port = int(config.get("broker_port", 1883))
      # Credenciales MQTT opcionales (broker con auth). Vacio/ausente = anonimo.
      self.mqtt_username = (config.get("username") or "").strip() or None
      self.mqtt_password = config.get("password") or None
    try:
      self._cfg_mtime = os.path.getmtime(self.jsonConfig)
    except OSError:
      self._cfg_mtime = None

  def _maybe_reload_broker(self):
    """Relee config_mqtt.json en caliente. Si el usuario cambia la IP del broker
    desde la UI del comma (Ajustes -> Servidor Orbit), reconecta SIN reiniciar
    openpilot. Antes la IP se leia una sola vez al arrancar y el cambio no surtia
    efecto hasta un reinicio -> causa tipica de 'cambie la IP y sigue sin salir'."""
    # Reintento del relevo si el hilo de conexion anterior aun no habia muerto
    # cuando se pidio el cambio (ver _relanzar_hilo_conexion).
    if self._conn_pendiente:
      self._relanzar_hilo_conexion()
    try:
      mtime = os.path.getmtime(self.jsonConfig)
    except OSError:
      return
    if mtime == self._cfg_mtime:
      return
    self._cfg_mtime = mtime
    try:
      with open(self.jsonConfig) as f:
        cfg = json.load(f)
      new_broker = cfg.get("broker", self.broker_address)
      new_port = int(cfg.get("broker_port", self.broker_port))
      new_username = (cfg.get("username") or "").strip() or None
      new_password = cfg.get("password") or None
    except Exception:
      return
    if (new_broker == self.broker_address and new_port == self.broker_port
        and new_username == self.mqtt_username and new_password == self.mqtt_password):
      return
    antes = f"{self.broker_address}:{self.broker_port}"
    cloudlog.warning(f"[Bemposta] broker/credenciales cambiados {antes} -> {new_broker}:{new_port}, reconectando (sin reiniciar openpilot)")
    self.broker_address, self.broker_port = new_broker, new_port
    self.mqtt_username, self.mqtt_password = new_username, new_password
    try:
      self.mqttc.loop_stop()
    except Exception:
      pass
    try:
      self.mqttc.disconnect()
    except Exception:
      pass
    self.conectado = False
    # Reaplicar credenciales antes de reconectar (username=None -> anonimo).
    self.mqttc.username_pw_set(self.mqtt_username, self.mqtt_password)
    self._relanzar_hilo_conexion()
    try:
      if getattr(self, "comandos_mqtt", None):
        self.comandos_mqtt.reload_broker(new_broker)
    except Exception:
      pass

  def cargar_canales(self):
    with open(self.jsonCanales) as f:
      data = json.load(f)
    enabled = [item for item in data["canales"] if item.get("enable") == 1]
    # Solo suscribir a canales que sean servicios cereal reales en este build
    # ('navInstruction' ya no existe en el sunnypilot nuevo). Evita el KeyError
    # del SubMaster y el acceso posterior self.sm[canal].
    self.enabled_items = [item for item in enabled if item["canal"] in SERVICE_LIST]
    dropped = [item["canal"] for item in enabled if item["canal"] not in SERVICE_LIST]
    if dropped:
      print(f"[Bemposta] canales sin servicio cereal, ignorados: {dropped}")
    # Respetar los toggles de UI del panel de canales ORBIT (param f"{canal}_toggle"). Su
    # consumidor original (SicMqttHilo2) fue retirado y los toggles quedaron
    # huerfanos; aqui volvemos a honrarlos SIN cambiar el comportamiento por
    # defecto: un canal solo se excluye si su toggle esta EXPLICITAMENTE a False.
    # Si el param esta sin configurar (None) o a True, se mantiene habilitado
    # (default = habilitado -> comportamiento actual intacto). El heartbeat de
    # carState no pasa por aqui, asi que la PRESENCIA del dispositivo sobrevive
    # aunque se desactive el canal carState.
    def _canal_habilitado(nombre):
      key = f"{nombre}_toggle"
      try:
        raw = self.params.get(key)
        if raw is None:
          return True  # sin configurar -> habilitado por defecto
        return bool(self.params.get_bool(key))  # solo excluye si el usuario lo puso a False
      except Exception:
        return True  # clave no registrada / error -> habilitado
    self.enabled_items = [item for item in self.enabled_items if _canal_habilitado(item["canal"])]
    self.lista_suscripciones = [item["canal"] for item in self.enabled_items]
    self.keys_importantes_por_canal = {
      item["canal"]: item.get("keys_importantes", [])
      for item in self.enabled_items
    }

  def _maybe_reload_canales(self):
    """Re-evalua en caliente los toggles de canal del panel ORBIT
    (param f"{canal}_toggle"). cargar_canales() solo corria en __init__, asi que
    activar/desactivar un canal desde la UI no surtia efecto hasta reiniciar
    openpilot. Lecturas de Params baratas cada TOGGLES_RELOAD_SECS; si cambia la
    lista de canales se reconstruye el SubMaster (mismo hilo que lo consume)."""
    now = time.monotonic()
    if (now - self._last_toggles_check) < self.TOGGLES_RELOAD_SECS:
      return
    self._last_toggles_check = now
    try:
      antes = self.lista_suscripciones
      self.cargar_canales()
      if self.lista_suscripciones != antes:
        cloudlog.warning(f"[Bemposta] toggles de canal cambiados {antes} -> {self.lista_suscripciones}, recreando SubMaster")
        self.init_submaster()
    except Exception:
      cloudlog.exception("[Bemposta] _maybe_reload_canales fallo")

  def init_submaster(self):
    # SubMaster([]) lanza ValueError y tumbaria TODO el subsistema ORBIT del
    # manager (telemetria + comandos + camara; los eventos sobreviven porque
    # viven en selfdrived). Si el usuario desactiva todos los canales desde el
    # panel, mantenemos un SubMaster minimo con carState: no se publica como
    # canal (enabled_items sigue vacio) pero alimenta el heartbeat de presencia.
    self.sm = messaging.SubMaster(self.lista_suscripciones or ["carState"])

  def init_mqtt(self):
    self.mqttc = mqtt.Client()
    if self.mqtt_username:
      self.mqttc.username_pw_set(self.mqtt_username, self.mqtt_password)
    self.mqttc.max_queued_messages_set(0)  # No encolar mensajes en RAM si no hay conexión
    self.mqttc.on_connect = self.on_connect
    self.mqttc.on_disconnect = self.on_disconnect
    self.mqttc.reconnect_delay_set(min_delay=1, max_delay=30)
    self._set_will()
    self._relanzar_hilo_conexion()

  def _set_will(self):
    """(Re)arma el Last Will de presencia.

    Last Will: si el coche se apaga o se queda sin cobertura, el broker publica
    este retenido POR NOSOTROS. Antes no habia ni una llamada a will_set en todo
    orbit/ y la app deducia 'conectado' de que llegara telemetria en <10 s, lo
    que no distingue 'apagado' de 'sin cobertura'. Sin timestamp a proposito: el
    broker lo publica en un instante futuro desconocido, poner la hora de ahora
    seria mentir.

    El will se queda en el topic v1 porque es el que consume la app de hoy:
    moverlo a v2 dejaria a la app ya instalada sin aviso de muerte y un coche
    apagado se veria "conectado" para siempre. MQTT admite UN SOLO will por
    conexion, asi que orbit/v2/presence/<dongle> NO puede tener el suyo desde
    este cliente; su 'online' retenido se publica en on_connect y el propio
    payload v2 dice en "lwt_topic" donde vive el aviso de muerte autoritativo
    mientras dure la migracion dual (seccion 13 del diseno v2).

    Sin dongle valido NO se arma: el will tambien es un retenido y en el
    namespace comun "DongleID" seria un 'offline' compartido por toda la flota
    sin registrar.

    OJO: paho aplica el will en el SIGUIENTE CONNECT, no sobre la conexion viva.
    """
    # getattr: _refresh_dongle puede llamarnos desde __init__, antes de que
    # init_mqtt haya creado el cliente (entonces lo arma el propio init_mqtt).
    if not self.dongle_valido or getattr(self, "mqttc", None) is None:
      return
    try:
      self.mqttc.will_set(TOPIC_PRESENCE_V1.format(self.DongleID),
                          json.dumps({"online": False, "dongle_id": self.DongleID,
                                      "reason": "lwt", "schema_version": 1}),
                          qos=0, retain=True)
    except Exception as e:
      cloudlog.warning(f"[Bemposta] will_set fallo: {e}")

  def _refresh_dongle(self) -> bool:
    """Relee DongleId de Params y actualiza DongleID/dongle_valido.

    Se reevalua en cada on_connect (y en el loop mientras siga invalido) porque
    el dongle lo asigna el REGISTRO, despues del primer arranque: leerlo solo en
    __init__ dejaba al dispositivo silenciado hasta reiniciar openpilot aunque
    ya tuviera identidad.

    Devuelve True si acaba de pasar a valido.
    """
    try:
      d = self.params.get("DongleId")
    except Exception:
      return False
    d = d.strip() if isinstance(d, str) else ""
    valido = bool(d) and d != "DongleID"
    nuevo = d if valido else "DongleID"
    if valido == self.dongle_valido and nuevo == self.DongleID:
      return False

    self.DongleID = nuevo
    self.dongle_valido = valido

    if not valido:
      # DongleId borrado en caliente (des-registro). Callar tambien la camara:
      # sus JPEG llevan el dongle en el topic y acabarian en el namespace comun.
      cloudlog.error("[Bemposta] DongleId dejo de ser valido: telemetria y camara silenciadas")
      cam = getattr(self, "camera_sender", None)
      if cam is not None:
        try:
          cam.stop()
        except Exception:
          pass
        self.camera_sender = None
      return False

    cloudlog.warning(f"[Bemposta] DongleId valido ({nuevo}): habilitada la publicacion de telemetria y camara")
    self._set_will()
    cam = getattr(self, "camera_sender", None)
    if cam is not None:
      # El topic de camara lleva el dongle; si ya estaba corriendo hay que
      # moverlo al nuevo (atributo publico que fija su constructor).
      try:
        cam.dongle_id = self.DongleID
      except Exception:
        pass
    else:
      # Arranque diferido al hilo del loop: construir el CameraSender lee
      # ficheros de disco y levanta ZMQ, y _refresh_dongle tambien se llama
      # desde on_connect, que es el hilo de RED (un handler lento ahi tira el
      # PINGRESP y con el la conexion).
      self._camera_pendiente = True
    return True

  def init_comandos(self):
    """Inicializa el sistema de comandos MQTT.
    Protegido: si el cliente de ordenes falla al construirse, la telemetria
    (y por tanto la PRESENCIA del dispositivo en la app) NO debe caerse con el.
    Antes esto no estaba en try/except y una excepcion aqui abortaba todo el
    __init__ -> manager lo tragaba -> ni telemetria ni ordenes ni dispositivo."""
    try:
      # Plano de mando (GateMonitor + estado + publicador de orbitCommandState a 10 Hz).
      # Lo supervisa el manager como un hilo ORBIT mas; aqui solo se garantiza que este
      # en marcha para el caso de arrancar este modulo suelto (sin manager). start() es
      # idempotente y el objeto es el MISMO singleton que ve el manager, asi que esto no
      # duplica hilos ni deja al router apuntando a un GateMonitor huerfano.
      plane = get_command_plane()
      plane.start()
      self.comandos_mqtt = MQTTComandos(plane=plane)
      self.comandos_mqtt.start()
    except Exception:
      cloudlog.exception("[Bemposta] init_comandos fallo; la telemetria sigue sin ordenes")
      self.comandos_mqtt = None

  def init_camera_sender(self):
    """Inicializa el sistema de envío de imágenes de cámaras.
    La configuracion (enabled, frecuencia) se carga automaticamente
    desde /data/orbit_camera_config.json si existe."""
    self.camera_sender = None
    self._start_camera_sender()

  def _start_camera_sender(self):
    """Arranca el CameraSender, SOLO con dongle valido.

    Sus JPEG van a telemetry_mqtt/<dongle>/camera/...: sin identidad acabarian
    en el namespace comun "DongleID" (ver __init__), y ademas el envio puede
    venir ya activado de /data/orbit_camera_config.json, asi que un dispositivo
    sin registrar emitiria imagenes de la carretera nada mas arrancar.

    Se llama desde __init__ y desde el hilo del loop cuando el dongle pasa a
    valido en caliente; NUNCA desde el callback de paho (construirlo lee
    ficheros de disco y levanta ZMQ, y un handler lento en el hilo de red tira
    el PINGRESP y con el la conexion).
    """
    self._camera_pendiente = False
    if getattr(self, "camera_sender", None) is not None:
      return
    if not self.dongle_valido:
      cloudlog.warning("[Bemposta] sin DongleId valido: CameraSender NO arranca (los JPEG irian al namespace comun)")
      return
    try:
      self.camera_sender = CameraSender(
        mqtt_client=self.mqttc,
        dongle_id=self.DongleID,
        camera_type="road",
        interval_seconds=2.0,  # Default, se sobreescribe si hay config persistida
      )
      self.camera_sender.start()
    except Exception:
      cloudlog.exception("[Bemposta] arranque del CameraSender fallo; la telemetria sigue sin camara")
      self.camera_sender = None

  def _link_camera_to_comandos(self):
    """Conecta el CameraSender con MQTTComandos para permitir control remoto desde la app."""
    if getattr(self, 'camera_sender', None) is not None and getattr(self, 'comandos_mqtt', None) is not None:
      self.comandos_mqtt.set_camera_sender(self.camera_sender)

  def _relanzar_hilo_conexion(self):
    """Arranca el UNICO hilo de conexion, relevando antes al anterior.

    Antes: si el broker no respondia, el hilo inicial se quedaba en su bucle de
    reintento (sleep de 5 s) y al corregir la IP desde Ajustes se lanzaba un
    SEGUNDO hilo sin avisar al primero. Cuando el nuevo conectaba y el viejo
    despertaba, el connect() del viejo sobre el MISMO objeto cliente hacia
    _sock_close() y _out_packet.clear(): cerraba el socket recien abierto y el
    dispositivo se quedaba mudo hasta reiniciar.
    """
    viejo = self._conn_thread
    if viejo is not None and viejo.is_alive():
      self._conn_stop.set()
      # 6 s = la espera de 5 s entre reintentos (ya interrumpible) mas el
      # margen del connect() en curso, que paho corta a los 5 s.
      viejo.join(timeout=6.0)
      if viejo.is_alive():
        # No relanzar con el viejo todavia vivo: seria exactamente el doble
        # connect() que este metodo existe para evitar. Se reintenta en la
        # siguiente iteracion del loop.
        cloudlog.warning("[Bemposta] hilo de conexion anterior aun vivo; relevo aplazado")
        self._conn_pendiente = True
        return
    self._conn_pendiente = False
    self._conn_stop = threading.Event()
    self._conn_thread = threading.Thread(target=self.setup_mqtt, args=(self._conn_stop,),
                                         daemon=True, name="OrbitMQTTConnect")
    self._conn_thread.start()

  def setup_mqtt(self, stop=None):
    """Bucle de conexion inicial. Corre en el hilo unico de conexion; `stop` es
    su senal de relevo (la pone _relanzar_hilo_conexion antes de sustituirlo)."""
    if stop is None:
      stop = self._conn_stop
    while not self.stop_event.is_set() and not stop.is_set():
      try:
        cloudlog.warning(f"[Bemposta] MQTTEnvioGeneral conectando a broker {self.broker_address}:{self.broker_port}")
        self.mqttc.connect(self.broker_address, self.broker_port, 60)
        if not self.conectado:
          self.mqttc.loop_start()
          # Esperar un momento para que se establezca la conexión
          time.sleep(0.5)
        break
      except Exception as e:
        # Diagnostico clave: si el broker cambio de IP (IP domestica dinamica),
        # este es el log que lo delata. Antes estaba silenciado y no se veia nada.
        cloudlog.warning(f"[Bemposta] MQTTEnvioGeneral NO pudo conectar a {self.broker_address}:{self.broker_port}: {e}. Reintento en 5s")
        # Espera interrumpible: con time.sleep(5) el relevo tardaba hasta 5 s en
        # notarse y era cuando se solapaban los dos hilos de conexion.
        if stop.wait(5.0):
          break

  def on_connect(self, client, userdata, flags, rc):
    # Cuerpo COMPLETO en try/except: el paho 2.1.0 vendorizado corre las
    # callbacks con suppress_exceptions=False, asi que cualquier excepcion aqui
    # sale hasta _thread_main, cuyo finally pone _thread=None y mata el hilo de
    # red EN SILENCIO. Como para entonces ya habiamos puesto conectado=True, el
    # loop seguia publicando contra un socket que nadie escribe y el dispositivo
    # quedaba mudo mostrando 'conectado' para siempre.
    try:
      if rc == 0:
        self.conectado = True
        self.params.put_bool("OrbitConnected", True)
        cloudlog.warning(f"[Bemposta] MQTTEnvioGeneral CONECTADO al broker {self.broker_address}:{self.broker_port} (rc={rc})")
        # Reevaluar la identidad en CADA conexion: el dongle lo asigna el
        # registro despues del primer arranque (una sola lectura de Params, no
        # bloquea el hilo de red).
        self._refresh_dongle()
        # Limpieza unica de los retenidos rancios de */global. Va aqui porque
        # solo se puede borrar un retenido con el socket abierto.
        self._purge_retenidos_legacy()
        if not self.dongle_valido:
          cloudlog.error("[Bemposta] SIN DongleId valido: no publico presencia ni telemetria (namespace comun), solo enrolamiento")
          return
        # Gemelo 'online' del Last Will (ver _set_will): retenido, para que la
        # app distinga 'apagado' de 'sin datos' sin esperar a la telemetria.
        self._publish_presence_online()
        # "Cold start" sync: publicar nuestro estado actual como mensaje
        # RETAINED para que cualquier app que se conecte despues lo reciba
        # inmediatamente (sin necesidad de que el usuario mueva nada).
        #
        # Lo hacemos con un pequeno delay para dar tiempo a que el otro
        # cliente MQTT (mqtt_comandos, que tiene las suscripciones) procese
        # los retained que el broker le pueda estar entregando del lado app
        # (caso: el usuario cambio algo en la app mientras el Comma estaba
        # offline). Asi publicamos DESPUES de haber aplicado esos cambios
        # y nuestro retained refleja el estado real.
        threading.Timer(1.5, self._publish_state_snapshot_retained).start()
      else:
        self.conectado = False
        self.params.put_bool("OrbitConnected", False)
        cloudlog.warning(f"[Bemposta] MQTTEnvioGeneral rechazado por broker (rc={rc})")
    except Exception:
      cloudlog.exception("[Bemposta] on_connect fallo (el hilo de red habria muerto en silencio)")

  def _publish_presence_online(self):
    """Publica el 'online' retenido de presencia en AMBOS namespaces.

    Migracion dual v1+v2 (seccion 13 del diseno v2): v1 es el que consume la app
    de hoy, v2 (orbit/v2/presence/<dongle>, retenido) es el namespace congelado
    del contrato nuevo (seccion 3.1). Ambos llevan schema_version para que el
    consumidor sepa que esta leyendo.

    El aviso de muerte (Last Will) solo puede vivir en UNO de los dos porque
    MQTT admite un will por conexion, y se queda en v1 para no romper la app ya
    instalada; por eso el payload v2 publica "lwt_topic" apuntando a el.
    """
    if not self.dongle_valido:
      return
    # epoch ms ENTERO: el contrato v2 (seccion 3.2) prohibe ISO-8601 en el cable
    # y exige que el instante sea siempre epoch en milisegundos.
    ts_ms = _epoch_ms()   # epoch de PARED: lo fecha la app
    v1_topic = TOPIC_PRESENCE_V1.format(self.DongleID)
    try:
      self.mqttc.publish(v1_topic,
                         json.dumps({"online": True, "dongle_id": self.DongleID,
                                     "timestamp": ts_ms, "schema_version": 1}),
                         qos=0, retain=True)
    except Exception as e:
      cloudlog.warning(f"[Bemposta] presence v1 (online) fallo: {e}")
    try:
      self.mqttc.publish(TOPIC_PRESENCE_V2.format(self.DongleID),
                         json.dumps({"v": 2, "schema_version": 2, "online": True,
                                     "ts_ms": ts_ms, "lwt_topic": v1_topic}),
                         qos=0, retain=True)
    except Exception as e:
      cloudlog.warning(f"[Bemposta] presence v2 (online) fallo: {e}")

  def _purge_retenidos_legacy(self):
    """Borra del broker los retenidos rancios de los topics */global.

    El firmware ya no publica NI escucha */global (se retiraron por ser mandos a
    TODA la flota: un topic sin dongle en la ruta lo obedecen todos los coches).
    Pero el broker conserva el ULTIMO valor retenido de cada uno y se lo entrega
    a cualquiera que se suscriba: un steer_torque_mode de hace meses sigue ahi y
    se lee como estado actual. El gesto MQTT para borrar un retenido es publicar
    payload VACIO con retain=True.

    qos=1: es una operacion de una sola vez y queremos que paho la reintente si
    la conexion se corta, no que se pierda como un qos=0 cualquiera.

    Gateado por OrbitGlobalRetainPurged, que guarda el broker DONDE ya se hizo:
    asi no se repite en cada reconexion (el motivo del gate) pero si se rehace
    al cambiar de broker, porque el broker nuevo tiene sus propios retenidos.
    """
    destino = f"{self.broker_address}:{self.broker_port}"
    try:
      if self.params.get("OrbitGlobalRetainPurged") == destino:
        return
    except Exception:
      pass
    ok = True
    for topic in TOPICS_GLOBAL_LEGACY:
      try:
        info = self.mqttc.publish(topic, None, qos=1, retain=True)  # payload vacio + retain = borrar
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
          ok = False
      except Exception as e:
        ok = False
        cloudlog.warning(f"[Bemposta] purga del retenido {topic} fallo: {e}")
    if not ok:
      return
    try:
      # STRING: put() exige el tipo nativo del param (un put(int) aqui seria
      # TypeError). No bloquea: putNonBlocking por defecto.
      self.params.put("OrbitGlobalRetainPurged", destino)
    except Exception as e:
      cloudlog.warning(f"[Bemposta] no pude marcar la purga de */global: {e}")
    cloudlog.warning(f"[Bemposta] retenidos legacy */global purgados en {destino}")

  def _publish_state_snapshot_retained(self):
    """Publica el estado actual de SteerTorqueMode y config_jetson con retain=True.

    Se llama una vez al conectar MQTT. El broker guarda estos mensajes y los
    entrega instantaneamente a cualquier subscriber futuro (p.ej. la app al
    lanzarse). source='comma_ui' para que el anti-eco de mqtt_comandos.py
    ignore el retained cuando le llegue a el mismo por su suscripcion.
    """
    if not self.conectado:
      return
    # Sin identidad estos retenidos irian a telemetry_config/DongleID/..., un
    # namespace compartido por todos los comma sin registrar (ver __init__).
    if not self.dongle_valido:
      return
    try:
      # --- SteerTorqueMode ---
      mode_raw = self.params.get("SteerTorqueMode")
      try:
        mode = int(mode_raw) if mode_raw else 0
      except (ValueError, TypeError):
        mode = 0
      steer_payload = {
        "dongle_id": self.DongleID,
        "steer_torque_mode": mode,
        "source": "comma_ui",
        "timestamp": _epoch_ms(),   # epoch de PARED: lo fecha la app, no es un plazo
      }
      steer_str = json.dumps(steer_payload)
      # SOLO la variante por dongle: un topic sin el dongle en la ruta
      # ("steer_torque_mode/global") es un mando a TODA la flota y la ACL del
      # broker no puede distinguir destinatarios dentro de el.
      self.mqttc.publish(f"telemetry_config/{self.DongleID}/steer_torque_mode", steer_str, qos=0, retain=True)
      print(f"[COLD-START SYNC] Retained SteerTorqueMode={mode} publicado")

      # --- config_jetson.json (IPs, puertos, calidad, enabled) ---
      config_path = os.path.join(self.base_path, "config_jetson.json")
      if os.path.exists(config_path):
        try:
          with open(config_path) as f:
            cfg = json.load(f)
        except Exception:
          cfg = {}
        # Propagar el _version EXACTO del disco. Asi, si este retained vuelve
        # a nosotros via handle_jetson_config, el anti-eco por _version lo
        # descartara porque sera igual al ya guardado en disco (no mayor).
        # Si no hay _version en el archivo (migracion), no lo inventamos
        # aqui para no pisarnos a nosotros mismos en el futuro.
        jetson_payload = {
          "dongle_id": self.DongleID,
          "jetson_enabled": cfg.get("jetson_enabled", False),
          "jetson_ip": cfg.get("jetson_ip", ""),
          "comma_ip": cfg.get("comma_ip", ""),
          "jetson_img_port": cfg.get("jetson_img_port", 5555),
          "jetson_torque_port": cfg.get("jetson_torque_port", 5556),
          "jpeg_quality": cfg.get("jpeg_quality", 80),
          "source": "comma_ui",
          "timestamp": _epoch_ms(),   # epoch de PARED: lo fecha la app, no es un plazo
        }
        if "_version" in cfg:
          jetson_payload["_version"] = str(cfg["_version"])
        jet_str = json.dumps(jetson_payload)
        # SOLO por dongle (ver arriba): "jetson_config/global" reconfiguraba la
        # Jetson de todos los vehiculos a la vez.
        self.mqttc.publish(f"telemetry_config/{self.DongleID}/jetson_config", jet_str, qos=0, retain=True)
        print(f"[COLD-START SYNC] Retained jetson_config publicado: {jetson_payload}")
    except Exception as e:
      print(f"[COLD-START SYNC] ERROR publicando snapshot: {e}")

  def on_disconnect(self, client, userdata, rc):
    # Mismo blindaje que on_connect: con suppress_exceptions=False una excepcion
    # aqui sale a _thread_main y mata el hilo de red, dejando la reconexion
    # automatica de paho sin nadie que la ejecute (mudo hasta reiniciar).
    try:
      self.conectado = False
      self.params.put_bool("OrbitConnected", False)
      cloudlog.warning(f"[Bemposta] MQTTEnvioGeneral DESCONECTADO del broker {self.broker_address} (rc={rc})")
    except Exception:
      cloudlog.exception("[Bemposta] on_disconnect fallo (el hilo de red habria muerto en silencio)")

  def start(self):
    # Guardar el handle: el supervisor de manager (manager_thread) vigila este
    # hilo y reinicia la instancia si muere, asi que necesita is_alive()/join().
    self.thread = threading.Thread(target=self.loop, daemon=True, name="MQTTEnvioGeneral")
    self.thread.start()

  def is_alive(self) -> bool:
    """True si el hilo principal (loop de telemetria) sigue vivo."""
    t = getattr(self, "thread", None)
    return t is not None and t.is_alive()

  def join(self, timeout=None):
    t = getattr(self, "thread", None)
    if t is not None:
      t.join(timeout)

  @staticmethod
  def _enlace_mudo(cli, cree_conectado) -> bool:
    """True si un cliente paho cree estar conectado pero ya no puede publicar.

    Dos sintomas: su hilo de red desaparecio (_thread=None, que es lo que deja
    el finally de _thread_main cuando una callback lanza) o el propio cliente
    se declara desconectado. El primero es el importante: is_connected() mira
    _state, que se queda en CONNECTED cuando el hilo muere, asi que por si solo
    NO detecta el caso 'mudo'.
    """
    if cli is None or not cree_conectado:
      return False
    try:
      if getattr(cli, "_thread", None) is None:
        return True
      return not cli.is_connected()
    except Exception:
      return False

  def healthy(self) -> bool:
    """True si los subsistemas internos que deben estar vivos lo estan.

    El supervisor de manager reinicia la instancia entera si esto devuelve
    False (p.ej. el hilo de camera_sender murio por una excepcion y la app
    se quedaba sin camara hasta reiniciar el dispositivo).
    """
    cam = getattr(self, "camera_sender", None)
    if cam is not None:
      cam_t = getattr(cam, "thread", None)
      if cam_t is not None and not cam_t.is_alive():
        return False

    # Enlace MQTT mudo (telemetria o comandos): hasta ahora el supervisor no
    # tenia forma de ver una conexion muerta y el dispositivo se quedaba sin
    # publicar ni obedecer hasta reiniciarlo a mano.
    # OJO: 'no conectado' a secas NO es enfermedad. Sin cobertura o con el
    # broker apagado es lo normal, y devolver False ahi reiniciaria la
    # instancia cada 30 s (matando camara y comandos) sin arreglar nada. Por
    # eso se exige que NOSOTROS creamos estar conectados, y que el sintoma
    # persista MUDO_GRACE_SECS para no cazar la ventana normal de reconexion.
    mudo = self._enlace_mudo(getattr(self, "mqttc", None), self.conectado)
    cmd = getattr(self, "comandos_mqtt", None)
    if cmd is not None:
      mudo = mudo or self._enlace_mudo(getattr(cmd, "mqttc", None), getattr(cmd, "conectado", False))
    if not mudo:
      self._mudo_desde = None
      return True
    now = time.monotonic()
    if self._mudo_desde is None:
      self._mudo_desde = now
    elif (now - self._mudo_desde) >= self.MUDO_GRACE_SECS:
      cloudlog.warning("[Bemposta] enlace MQTT mudo (se cree conectado pero no publica); pido reinicio")
      return False
    return True

  def stop(self):
    """Detiene el sistema MQTT completo."""
    self.stop_event.set()
    # Despertar YA al hilo de conexion (espera interrumpible de 5 s): el
    # supervisor de manager hace stop()+join(2 s) antes de recrear la
    # instancia, y un hilo viejo aun dentro de connect() pisaria el socket
    # del cliente nuevo.
    self._conn_stop.set()
    # comandos_mqtt puede ser None si init_comandos fallo: el atributo existe
    # (hasattr no basta) y None.stop() abortaria el resto del apagado.
    if getattr(self, 'comandos_mqtt', None) is not None:
      self.comandos_mqtt.stop()
    if hasattr(self, 'camera_sender') and self.camera_sender is not None:
      self.camera_sender.stop()
    self.mqttc.disconnect()
    # print("🛑 Sistema MQTT detenido")  # Comentado para reducir uso de memoria

  def _maybe_publish_healthcheck(self):
    """Si la UI/app dejo una peticion (Param OrbitHealthcheckRequest), construye
    el informe de salud y lo publica una vez. Corre en el hilo de loop()."""
    try:
      req = self.params.get("OrbitHealthcheckRequest")
    except Exception:
      return
    if not req:
      return
    # Consumir la peticion de forma idempotente (aunque falle el publish).
    try:
      self.params.remove("OrbitHealthcheckRequest")
    except Exception:
      pass
    try:
      payload = self._build_healthcheck()
      self.mqttc.publish(f"telemetry_mqtt/{self.DongleID}/healthcheck",
                         json.dumps(payload), qos=0, retain=False)
    except Exception as e:
      cloudlog.warning(f"[ORBIT] healthcheck publish fallo: {e}")

  def _build_healthcheck(self):
    """Reune metricas de salud del dispositivo. El SubMaster de diagnostico se
    crea y consume en ESTE hilo (msgq no es thread-safe) y se calienta unos
    ciclos para captar datos frescos de servicios de baja frecuencia."""
    if self._diag_sm is None:
      self._diag_sm = messaging.SubMaster(['deviceState', 'pandaStates', 'managerState'])
    for _ in range(6):
      self._diag_sm.update(100)

    report = {
      "dongle_id": self.DongleID,
      "ts": _epoch_ms() // 1000,   # epoch de PARED: sella el informe para el backend
      "fw": self.params.get("Version") or "",
      "branch": self.params.get("GitBranch") or "",
      "commit": (self.params.get("GitCommit") or "")[:7],
    }

    try:
      if self._diag_sm.updated["deviceState"] or self._diag_sm.recv_frame["deviceState"] > 0:
        ds = self._diag_sm["deviceState"]
        cpu = list(ds.cpuTempC)
        gpu = list(ds.gpuTempC)
        report["device"] = {
          "cpu_temp_c": round(max(cpu), 1) if cpu else None,
          "gpu_temp_c": round(max(gpu), 1) if gpu else None,
          "max_temp_c": round(float(ds.maxTempC), 1),
          "thermal_status": str(ds.thermalStatus),
          "mem_used_pct": int(ds.memoryUsagePercent),
          "free_space_pct": round(float(ds.freeSpacePercent), 1),
          "network_type": str(ds.networkType),
          "network_strength": str(ds.networkStrength),
        }
    except Exception:
      pass

    try:
      pandas = list(self._diag_sm["pandaStates"])
      if pandas:
        ps = pandas[0]
        report["panda"] = {
          "voltage_mv": int(ps.voltage),
          "ignition": bool(ps.ignitionLine or ps.ignitionCan),
          "fault_status": str(ps.faultStatus),
          "faults": [str(f) for f in ps.faults],
          "safety_model": str(ps.safetyModel),
        }
    except Exception:
      pass

    try:
      procs = list(self._diag_sm["managerState"].processes)
      not_running = [p.name for p in procs if p.shouldBeRunning and not p.running]
      report["manager"] = {
        "process_count": len(procs),
        "not_running": not_running,
      }
    except Exception:
      pass

    # Frescura de enlaces ORBIT (ya en Params).
    try:
      last_pub = self.params.get("OrbitLastPublish")
      # OrbitLastPublish se escribe con epoch, asi que la edad se calcula con epoch.
      report["orbit_last_publish_age_s"] = (int(_epoch_ms() / 1000.0 - float(last_pub))
                                            if last_pub else None)
    except Exception:
      report["orbit_last_publish_age_s"] = None
    try:
      jt_ts = self.params.get("JetsonTorqueTimestamp")
      # JetsonTorqueTimestamp lo escribe zmq_client con epoch: misma base de tiempo.
      report["jetson_torque_age_s"] = (round(_epoch_ms() / 1000.0 - float(jt_ts), 1)
                                       if jt_ts else None)
    except Exception:
      report["jetson_torque_age_s"] = None

    return report

  def _log_publish_rc(self, que, topic, rc):
    """Loguea un publish fallido (rc != 0) como mucho cada RC_LOG_SECS.

    Sin rate limit esto seria una linea por canal y por ciclo (1 Hz): con el
    broker caido llenaria el log y la flash del dispositivo."""
    now = time.monotonic()
    if (now - self._last_rc_log) < self.RC_LOG_SECS:
      return
    self._last_rc_log = now
    cloudlog.warning(f"[Bemposta] publish de {que} en {topic} NO salio (rc={rc})")

  @staticmethod
  def _campos_no_serializables(datos):
    """Nombres de los campos que impiden serializar el mensaje, para el log.

    json.dumps solo dice 'Out of range float values are not JSON compliant',
    nunca QUE campo: sin esto no habia forma de saber que dato corrompe la
    telemetria de un canal."""
    malos = []
    if isinstance(datos, dict):
      for k, v in datos.items():
        try:
          json.dumps(v, allow_nan=False)
        except (ValueError, TypeError):
          malos.append(k)
    return malos or ["<desconocido>"]

  def loop(self):
    # Guard de nivel superior: el loop corre en un hilo daemon sin reinicio, asi
    # que cualquier excepcion no capturada dentro de una iteracion mataba la
    # telemetria EN SILENCIO para el resto de la sesion (los comandos seguian
    # vivos en su propio hilo -> sintoma confuso). Logueamos y reintentamos.
    while not self.stop_event.is_set():
      self.pause_event.wait()
      try:
        self._loop_once()
      except Exception:
        cloudlog.exception("[Bemposta] iteracion del loop de telemetria fallo; reintento")
        time.sleep(self.velocidadActualizacion)

  def _loop_once(self):
      self.sm.update()

      # Recoger en caliente un cambio de IP del broker hecho desde la UI.
      self._maybe_reload_broker()

      # Recoger en caliente los toggles de canal cambiados desde la UI (panel ORBIT).
      self._maybe_reload_canales()

      # Reevaluar la identidad mientras no la tengamos: el DongleId lo asigna el
      # registro DESPUES del primer arranque, y sin esto el dispositivo se
      # quedaba silenciado hasta reiniciar openpilot. Una lectura de Params por
      # iteracion (1 Hz) y SOLO mientras siga invalido.
      if not self.dongle_valido:
        self._refresh_dongle()

      # Arranque diferido del CameraSender cuando el dongle pasa a valido en
      # caliente: se hace aqui, en el hilo del loop, y nunca en el de red.
      if self._camera_pendiente:
        self._start_camera_sender()
        self._link_camera_to_comandos()

      # Enrolamiento ORBIT (QR): generar/rotar el codigo SIEMPRE (aunque no haya
      # broker) para que la UI pueda pintar el QR sin conexion; el publish va
      # gateado por conexion dentro del propio metodo. Best-effort.
      self._maybe_announce_enroll()

      # Verificar conexión antes de intentar enviar (evita encolar mensajes)
      # Usar verificación más simple: si está conectado según el callback
      is_connected = self.conectado
      # También verificar el estado real del cliente si está disponible
      if hasattr(self.mqttc, 'is_connected'):
        is_connected = is_connected and self.mqttc.is_connected()

      if not is_connected:
        # Sin conexión: no procesar ni encolar mensajes para evitar saturación de RAM
        # Log ocasional para debug (cada 50 iteraciones = ~50 segundos)
        if hasattr(self, '_no_connection_log_counter'):
          self._no_connection_log_counter += 1
        else:
          self._no_connection_log_counter = 0

        # Log eliminado para reducir uso de memoria

        time.sleep(self.velocidadActualizacion)
        return

      # Resetear contador si hay conexión
      if hasattr(self, '_no_connection_log_counter'):
        self._no_connection_log_counter = 0

      # SIN IDENTIDAD NO SE PUBLICA NADA (ver __init__): ni telemetria, ni
      # heartbeat de presencia, ni sicuem_torque, ni snapshots de config, ni
      # camara. Todo eso lleva el dongle en el topic y sin el iria al namespace
      # comun "DongleID", donde el backend v2 (que toma topic_parts[1] como
      # identidad) mezclaria a todos los dispositivos sin registrar en un unico
      # vehiculo fantasma. La UNICA excepcion es el anuncio de enrolamiento, que
      # ya se hizo arriba: es como el dispositivo consigue identidad.
      if not self.dongle_valido:
        ahora_mono = time.monotonic()
        if (ahora_mono - self._last_sin_dongle_log) >= self.SIN_DONGLE_LOG_SECS:
          self._last_sin_dongle_log = ahora_mono
          cloudlog.error("[Bemposta] sin DongleId valido: telemetria y camara silenciadas, solo anuncio de enrolamiento")
        time.sleep(self.velocidadActualizacion)
        return

      # Responder a una peticion de diagnostico remoto (healthcheck), si la hay.
      self._maybe_publish_healthcheck()

      # Descriptor de capacidades v2 (orbit/v2/caps/<dongle>, retenido). Se reintenta a
      # 1 Hz porque marca y plataforma salen de carParams, que offroad todavia no existe:
      # el descriptor publicado al conectar sale con los dos campos vacios y hay que
      # rehacerlo en cuanto el coche se identifica. Solo republica si CAMBIA.
      if getattr(self, "comandos_mqtt", None) is not None:
        try:
          self.comandos_mqtt.maybe_publish_caps()
        except Exception:
          cloudlog.exception("[Bemposta] maybe_publish_caps fallo")

      # Publicar Jetson config si fue cambiada desde la UI del Comma
      try:
        jetson_payload = self.params.get("JetsonConfigMqttPayload")
        if jetson_payload and len(jetson_payload) > 2:
          payload_str = jetson_payload
          print(f"[JETSON SYNC] Detectado JetsonConfigMqttPayload: {payload_str[:200]}")
          try:
            # retain=True: el broker guarda la ultima version de cada topic y
            # la entrega automaticamente a futuros subscribers. Asi la app al
            # lanzarse tiene el estado actual sin tener que preguntarle a nadie.
            # SOLO por dongle: "jetson_config/global" reconfiguraba la Jetson
            # de TODA la flota y la ACL del broker no puede distinguir
            # destinatarios dentro de un topic sin dongle en la ruta.
            result = self.mqttc.publish(f"telemetry_config/{self.DongleID}/jetson_config", payload_str, qos=0, retain=True)
            print(f"[JETSON SYNC] Publicado (retained) a telemetry_config/{self.DongleID}/jetson_config rc={result.rc}")
          except Exception as e:
            print(f"[JETSON SYNC] ERROR publicando MQTT: {e}")
          self.params.remove("JetsonConfigMqttPayload")
          print("[JETSON SYNC] Param JetsonConfigMqttPayload eliminado")
      except Exception as e:
        print(f"[JETSON SYNC] ERROR leyendo param: {e}")

      # Publicar SteerTorqueMode si fue cambiado desde la UI del Comma
      try:
        steer_mode_payload = self.params.get("SteerTorqueModeMqttPayload")
        if steer_mode_payload and len(steer_mode_payload) > 2:
          payload_str = steer_mode_payload
          print(f"[STEER MODE SYNC] Detectado payload: {payload_str[:200]}")
          try:
            # retain=True: ver comentario arriba en JetsonConfig.
            # SOLO por dongle (ver JetsonConfig): el topic global cambiaba el
            # modo de torque del volante de TODOS los vehiculos a la vez.
            result = self.mqttc.publish(f"telemetry_config/{self.DongleID}/steer_torque_mode", payload_str, qos=0, retain=True)
            print(f"[STEER MODE SYNC] Publicado (retained) a telemetry_config/{self.DongleID}/steer_torque_mode rc={result.rc}")
          except Exception as e:
            print(f"[STEER MODE SYNC] ERROR publicando MQTT: {e}")
          self.params.remove("SteerTorqueModeMqttPayload")
      except Exception as e:
        print(f"[STEER MODE SYNC] ERROR leyendo param: {e}")

      # Publicar JetsonObstacleApplyTarget si fue cambiado desde la UI del Comma
      try:
        apply_target_payload = self.params.get("JetsonObstacleApplyTargetMqttPayload")
        if apply_target_payload and len(apply_target_payload) > 2:
          payload_str = apply_target_payload
          print(f"[APPLY TARGET SYNC] Detectado payload: {payload_str[:200]}")
          try:
            # retain=True: que la app reciba el estado al reconectarse.
            result1 = self.mqttc.publish(f"telemetry_config/{self.DongleID}/jetson_apply_target", payload_str, qos=0, retain=True)
            print(f"[APPLY TARGET SYNC] Publicado (retained) a telemetry_config/{self.DongleID}/jetson_apply_target rc={result1.rc}")
          except Exception as e:
            print(f"[APPLY TARGET SYNC] ERROR publicando MQTT: {e}")
          self.params.remove("JetsonObstacleApplyTargetMqttPayload")
      except Exception as e:
        print(f"[APPLY TARGET SYNC] ERROR leyendo param: {e}")

      # Publicar JetsonObstacleStatus (modo 3 COMMA+JETSON) si cambió en controlsd
      try:
        obstacle_payload = self.params.get("JetsonObstacleStatusMqttPayload")
        if obstacle_payload and len(obstacle_payload) > 2:
          payload_str = obstacle_payload
          # controlsd no conoce el dongle: inyectarlo aqui para que el backend
          # sepa de que vehiculo es el estado (antes registraba "GLOBAL" como
          # dispositivo y la app derivaba deviceId="global"). Best-effort.
          try:
            _obs = json.loads(payload_str)
            if isinstance(_obs, dict) and "dongle_id" not in _obs:
              _obs["dongle_id"] = self.DongleID
              payload_str = json.dumps(_obs)
          except Exception:
            pass
          print(f"[OBSTACLE STATUS SYNC] Detectado payload: {payload_str[:200]}")
          try:
            # retain=False aquí: el status del esquive es transitorio, no
            # queremos que un suscriptor que se conecte tarde reciba un
            # "DODGING_RIGHT" de hace 10 minutos como si estuviera vivo.
            # SOLO por dongle (ver JetsonConfig): el topic global mezclaba el
            # estado de esquive de toda la flota en un unico canal sin dueno.
            result = self.mqttc.publish(f"telemetry_config/{self.DongleID}/jetson_obstacle_status", payload_str, qos=0, retain=False)
            print(f"[OBSTACLE STATUS SYNC] Publicado a telemetry_config/{self.DongleID}/jetson_obstacle_status rc={result.rc}")
          except Exception as e:
            print(f"[OBSTACLE STATUS SYNC] ERROR publicando MQTT: {e}")

          # Puente sicuem_torque: la app + backend consumen "sicuem_torque/<dongle>"
          # pero el firmware nunca lo publicaba. Lo emitimos aqui, a la misma cadencia
          # que el status de obstaculo (cuando controlsd publica un cambio). 'torque'
          # sale de la mejor fuente numerica disponible (param JetsonTorque, escrito por
          # zmq_client desde la Jetson); 'active'/'obstacle_detected' se derivan del status
          # de esquive (DODGING_*/BSM_* => detectado; "" => idle). Best-effort: cualquier
          # fallo se ignora y NUNCA rompe el loop.
          try:
            status = ""
            try:
              status = (json.loads(payload_str) or {}).get("status", "") or ""
            except Exception:
              status = ""
            obstacle_detected = bool(status)
            try:
              torque = float(self.params.get("JetsonTorque") or 0.0)
            except Exception:
              torque = 0.0
            active = obstacle_detected or (torque != 0.0)
            torque_payload = {
              "torque": torque,
              "active": active,
              "obstacle_detected": obstacle_detected,
              "dongle_id": self.DongleID,
            }
            self.mqttc.publish(f"sicuem_torque/{self.DongleID}", json.dumps(torque_payload), qos=0)
          except Exception as e:
            print(f"[SICUEM TORQUE SYNC] ERROR publicando MQTT: {e}")

          self.params.remove("JetsonObstacleStatusMqttPayload")
      except Exception as e:
        print(f"[OBSTACLE STATUS SYNC] ERROR leyendo param: {e}")

      for canal in self.enabled_items:
        nombre = canal["canal"]
        topic = canal["topic"].format(self.DongleID)

        if nombre in self.sm.data and self.sm.updated[nombre]:
          datos = self.sm[nombre].to_dict()
          datos_filtrados = self.enviar_datos_importantes(nombre, datos)
          if datos_filtrados:
            # Verificar conexión nuevamente antes de cada publicación
            if self.conectado:
              # Verificar también el estado real si está disponible
              if hasattr(self.mqttc, 'is_connected') and not self.mqttc.is_connected():
                continue
              try:
                # Saneado + allow_nan=False: json.dumps emite por defecto el
                # literal NaN, que NO es JSON valido (RFC 8259), asi que un
                # solo desiredCurvature NaN corrompia el mensaje ENTERO de
                # forma intermitente y sin rastro (el publish salia con rc=0).
                cuerpo = json.dumps(_sanea_no_finitos(datos_filtrados), allow_nan=False)
              except (ValueError, TypeError):
                malos = self._campos_no_serializables(datos_filtrados)
                cloudlog.warning(f"[Bemposta] canal {nombre}: campos no serializables {malos}; mensaje descartado")
                continue
              try:
                info = self.mqttc.publish(topic, cuerpo, qos=0)
                # rc != 0 (tipico: MQTT_ERR_NO_CONN) significa que el mensaje no
                # salio. Antes se ignoraba y la telemetria parecia estar fluyendo.
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                  self._log_publish_rc(f"canal {nombre}", topic, info.rc)
              except Exception as e:
                # NO tocar self.conectado aqui: un fallo de serializacion
                # (json.dumps de un to_dict() con bytes/NaN, etc.) o un error
                # puntual de un canal NO significa que el socket MQTT este caido.
                # Si lo poniamos a False, como on_disconnect nunca disparaba, la
                # telemetria quedaba CONGELADA para siempre. Dejar que las callbacks
                # (on_disconnect) gestionen el estado real de la conexion.
                cloudlog.warning(f"[Bemposta] fallo publicando canal {nombre} en {topic}: {e}")
            # Si no hay conexión, simplemente no enviar (no encolar)

      # Heartbeat de PRESENCIA. La app marca "conectado" solo si le llega
      # telemetria en <10 s. Onroad carState ya fluye; pero PARADO/OFFROAD ningun
      # canal se actualiza (sm.updated=False) y no se publica nada -> el dispositivo
      # aparece desconectado aunque el MQTT este perfectamente conectado. Republicamos
      # el ultimo carState conocido a ritmo bajo para que salga "conectado" tambien en
      # banco (como hacia el sender antiguo, que publicaba cada ciclo sin condicion).
      now = time.monotonic()
      if self.conectado and (now - self._last_heartbeat) >= self.HEARTBEAT_SECS:
        self._last_heartbeat = now
        if not (hasattr(self.mqttc, 'is_connected') and not self.mqttc.is_connected()):
          try:
            if "carState" in self.sm.data:
              hb = self.sm["carState"].to_dict()
            else:
              hb = {}
            hb["dongle_id"] = self.DongleID
            topic_hb = f"telemetry_mqtt/{self.DongleID}/carState"
            # Mismo saneado que en el bucle de canales: un solo float NaN de
            # carState invalidaba el JSON y la app perdia la PRESENCIA entera.
            info = self.mqttc.publish(topic_hb, json.dumps(_sanea_no_finitos(hb), allow_nan=False), qos=0)
            # Marca de vida para la UI: epoch (s) del ultimo ciclo de publicacion.
            # Ligada a la cadencia del heartbeat (3 s) para no anadir mas
            # frecuencia de escritura en Params. Va DENTRO del try y solo si el
            # publish salio de verdad (rc==0): antes estaba fuera, asi que
            # orbit_panel.py y home.py pintaban el enlace vivo aunque todos los
            # publishes reventaran.
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
              # OJO: epoch de PARED, NO `now` (que es monotonic y solo sirve para el
              # intervalo del heartbeat). Este valor CRUZA PROCESOS: lo leen
              # orbit_panel.py:50 y home.py:664 restando contra time.time(). Escribir
              # monotonic aqui hacia que la UI calculase ~57 anos de antiguedad y
              # dejaba el chip de enlace permanentemente en rojo.
              self.params.put("OrbitLastPublish", str(_epoch_ms() // 1000))
            else:
              self._log_publish_rc("heartbeat", topic_hb, info.rc)
          except Exception as e:
            cloudlog.warning(f"[Bemposta] heartbeat fallo: {e}")

          # sicuem_torque a cadencia baja (unida al heartbeat). El backend/app
          # consumen sicuem_torque/<dongle> de forma CONTINUA, pero antes solo se
          # publicaba dentro del bloque JetsonObstacleStatusMqttPayload (transitorio,
          # solo al cambiar el status) -> la app veia el torque congelado. Aqui lo
          # republicamos a ritmo bajo SIEMPRE que haya un modo de torque Jetson/
          # obstaculo activo (SteerTorqueMode 1=JETSON, 3=COMMA+JETSON), leyendo el
          # ultimo torque del param JetsonTorque (escrito por zmq_client). No se
          # incluye 'confidence' porque no existe ninguna fuente para el en este
          # build (se omite; el backend ya lo trata como opcional). Best-effort:
          # cualquier fallo se ignora y NUNCA rompe el loop de telemetria.
          try:
            try:
              mode_raw = self.params.get("SteerTorqueMode")
              mode = int(mode_raw) if mode_raw else 0
            except (ValueError, TypeError):
              mode = 0
            if mode in (1, 3):
              try:
                torque = float(self.params.get("JetsonTorque") or 0.0)
              except Exception:
                torque = 0.0
              torque_payload = {
                "torque": torque,
                "active": True,
                "obstacle_detected": torque != 0.0,
                "dongle_id": self.DongleID,
              }
              self.mqttc.publish(f"sicuem_torque/{self.DongleID}", json.dumps(torque_payload), qos=0)
          except Exception as e:
            cloudlog.warning(f"[Bemposta] sicuem_torque (heartbeat) fallo: {e}")

      time.sleep(self.velocidadActualizacion)

  def _maybe_announce_enroll(self):
    """Anuncia el codigo de enrolamiento ORBIT (QR) por MQTT mientras el
    dispositivo no este reclamado, y rota el codigo cuando expira su TTL.

    - Sale si OrbitClaimed (ya emparejado): el QR no debe reaparecer.
    - Exige dongle valido (lo reevalua _refresh_dongle desde el loop): con el
      literal de fallback "DongleID" no anuncia, porque emparejaria contra un id
      inexistente que ademas comparten todos los comma sin registrar.
    - Rota el codigo (CSPRNG, 8 chars mayusculas, sin O/0/1/I) al inicio y al
      expirar ENROLL_TTL_S; deja OrbitPairingCode / OrbitEnrollExpiry en Params
      para que la UI pinte el QR y una cuenta atras opcional.
    - Publica a telemetry_mqtt/<dongle>/enroll (qos=0, retain=False) cada
      ENROLL_ANNOUNCE_SECS.

    Best-effort: cualquier fallo se loguea y NUNCA rompe el loop de telemetria.
    """
    try:
      if self.params.get_bool("OrbitClaimed"):
        return
      if not self.dongle_valido:
        return
      # Epoch de PARED a proposito: el TTL del codigo se publica en OrbitEnrollExpiry y
      # en issued_at, y tanto la UI del comma como el backend los comparan con SU reloj de
      # pared. Un plazo monotono aqui seria incomparable fuera de este proceso.
      now = _epoch_ms() / 1000.0
      d = self.DongleID
      # Regeneracion manual (trigger OrbitEnrollRegen, lo pone la UI o el
      # unclaim): consumirlo y forzar rotacion + anuncio inmediatos.
      if self.params.get_bool("OrbitEnrollRegen"):
        self.params.remove("OrbitEnrollRegen")
        self._pairing_code = None
      # Rotacion del codigo: primera vez o TTL expirado. Se genera SIEMPRE (aunque
      # no haya broker) para que la UI pueda pintar el QR/codigo sin conexion.
      if self._pairing_code is None or (now - self._enroll_issued_at) >= self.ENROLL_TTL_S:
        # Re-chequear OrbitClaimed justo antes de escribir: cierra la carrera con
        # handle_enroll_ack (otro hilo) que borra OrbitPairingCode al reclamar.
        if self.params.get_bool("OrbitClaimed"):
          return
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        self._enroll_issued_at = now
        self._pairing_code = code
        # Anunciar el codigo nuevo YA: si se respetara la ventana de 30 s, el
        # backend seguiria validando contra el codigo viejo (bad_code) hasta
        # el proximo anuncio.
        self._last_enroll = 0.0
        self.params.put("OrbitPairingCode", code)
        self.params.put("OrbitEnrollExpiry", str(int((self._enroll_issued_at + self.ENROLL_TTL_S) * 1000)))
      # Anuncio periodico por MQTT: SOLO con conexion. Sin broker el codigo ya
      # esta disponible para la UI y se reintentara en la siguiente iteracion.
      if self.conectado and (now - self._last_enroll) >= self.ENROLL_ANNOUNCE_SECS:
        try:
          fw = self.params.get("Version") or ""
        except Exception:
          fw = ""
        payload = {
          "dongle_id": d,
          "pairing_code": self._pairing_code,
          "issued_at": int(self._enroll_issued_at * 1000),
          "ttl_s": self.ENROLL_TTL_S,
          "fw": fw,
          "hw": "comma3x",
        }
        self.mqttc.publish(f"telemetry_mqtt/{d}/enroll", json.dumps(payload), qos=0, retain=False)
        self._last_enroll = now
    except Exception as e:
      cloudlog.warning(f"[Bemposta] _maybe_announce_enroll fallo: {e}")

  def enviar_datos_importantes(self, canal, datos):
    claves = self.keys_importantes_por_canal.get(canal, [])

    # Si no hay claves definidas, usar datos directamente sin copiar
    if not claves:
      datos["dongle_id"] = self.DongleID
      return datos
    else:
      resultado = {k: datos[k] for k in claves if k in datos}
      resultado["dongle_id"] = self.DongleID
      return resultado

if __name__ == "__main__":
  sender = MQTTEnvioGeneral()
  sender.start()

  while not sender.conectado:
    time.sleep(0.5)

  while True:
    time.sleep(10)
