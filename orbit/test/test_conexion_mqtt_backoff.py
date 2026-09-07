"""El bucle de conexion inicial de los DOS clientes MQTT (telemetria y mandos).

config_mqtt.json se distribuye con "broker": "" y paho.connect("") lanza al instante
("Invalid host."), asi que los dos hilos de conexion giraban en su reintento plano de 5 s
para siempre: 4 avisos cada 5 s en el rlog de TODOS los dispositivos sin configurar
("MQTTEnvioGeneral conectando a broker :1883" / "NO pudo conectar a :1883: Invalid host..
Reintento en 5s", y lo mismo para MQTTComandos). Lo que fijan estos tests, para los dos
ficheros con la MISMA semantica:

    Sin broker ........... UN aviso la primera vez, luego esperas de 30 s interrumpibles
                           sin connect() y sin mas lineas mientras siga vacio.
    Broker caido ......... 5 -> 10 -> 20 -> 60 -> 60 s (tope), y cada aviso dice la espera
                           real ("Reintento en Ns").
    Relevo limpio ........ el contador y el aviso son LOCALES al hilo: cada relevo
                           (_relanzar_hilo_conexion / reload_broker tras escribir un
                           broker desde Ajustes) arranca otra vez en 5 s.
    Sigue vivo ........... el hilo NO sale mientras espera. Si saliera sin conectar nadie
                           volveria a intentarlo (la reconexion automatica de paho solo
                           existe tras un primer connect() bueno) y el supervisor del
                           manager no lo ve: is_alive() mira el hilo del loop y healthy()
                           no mira _conn_thread.
    Mandos sin lock ...... en MQTTComandos la rama 'sin broker' va ANTES de coger
                           _conn_lock: la espera larga nunca se hace con el lock cogido.
"""
import threading
import time

import pytest

from openpilot.orbit import mqtt_comandos as mc
from openpilot.orbit import mqtt_envio_general as meg
from openpilot.orbit.mqtt_comandos import MQTTComandos
from openpilot.orbit.mqtt_envio_general import MQTTEnvioGeneral

BROKER = "192.0.2.10"


class _StopGuionado:
  """Event de relevo falso: wait(t) apunta t y devuelve True (= relevo) en la llamada k.

  `al_esperar(obj)` se ejecuta dentro de cada wait, ANTES de contestar: sirve para mirar
  el estado del objeto justo mientras el hilo esperaria (lock libre, etc.) y para simular
  que la UI escribe el broker mientras el hilo dormia.
  """

  def __init__(self, k, al_esperar=None):
    self.k = k
    self.esperas = []
    self._al_esperar = al_esperar
    self._set = False

  def is_set(self):
    return self._set

  def set(self):
    self._set = True

  def wait(self, timeout=None):
    self.esperas.append(timeout)
    if self._al_esperar is not None:
      self._al_esperar()
    if len(self.esperas) >= self.k:
      self._set = True
    return self._set


class _ClienteGuionado:
  """Cliente paho falso: connect() falla hasta el intento `exito_en` (1-based; None = nunca)."""

  def __init__(self, exito_en=None):
    self.exito_en = exito_en
    self.connects = []
    self.loop_starts = 0

  def connect(self, host, port, keepalive):
    self.connects.append((host, port, keepalive))
    if self.exito_en is None or len(self.connects) < self.exito_en:
      raise ValueError("Invalid host.")
    return 0

  def loop_start(self):
    self.loop_starts += 1


class _LogFalso:
  def __init__(self):
    self.warnings = []
    self.otros = []

  def warning(self, msg, *a, **k):
    self.warnings.append(str(msg))

  def error(self, msg, *a, **k):
    self.otros.append(str(msg))

  def exception(self, msg, *a, **k):
    self.otros.append(str(msg))

  info = debug = error

  def reintentos(self):
    return [w for w in self.warnings if "Reintento en" in w]

  def sin_broker(self):
    return [w for w in self.warnings if "broker no configurado" in w]


def _envio(broker, cliente):
  """MQTTEnvioGeneral sin __init__ (no levanta paho, SubMaster ni CameraSender)."""
  e = MQTTEnvioGeneral.__new__(MQTTEnvioGeneral)
  e.stop_event = threading.Event()
  e._conn_stop = threading.Event()
  e.broker_address = broker
  e.broker_port = 1883
  e.mqttc = cliente
  e.conectado = False
  return e


def _comandos(broker, cliente):
  """MQTTComandos sin __init__ (ni broker, ni disco, ni Params reales)."""
  c = MQTTComandos.__new__(MQTTComandos)
  c.stop_event = threading.Event()
  c._conn_stop = threading.Event()
  c._conn_lock = threading.Lock()
  c.broker_address = broker
  c.broker_port = 1883
  c.mqttc = cliente
  c.conectado = False
  return c


# Los dos bucles se prueban con el MISMO guion: (fabrica, modulo cuyo cloudlog se sustituye).
GEMELOS = pytest.mark.parametrize("fabrica, modulo", [(_envio, meg), (_comandos, mc)], ids=["telemetria", "mandos"])


@pytest.fixture
def log(monkeypatch):
  """Sustituye cloudlog en los dos modulos y evita el sleep(0.5) del camino bueno de la telemetria."""
  falso = _LogFalso()
  monkeypatch.setattr(meg, "cloudlog", falso)
  monkeypatch.setattr(mc, "cloudlog", falso)
  monkeypatch.setattr(time, "sleep", lambda s: None)
  return falso


# ------------------------------------------------------------------------------ sin broker

@GEMELOS
@pytest.mark.parametrize("vacio", ["", "   ", None], ids=["vacio", "blanco", "nulo"])
def test_sin_broker_un_aviso_una_espera_de_30s_y_ningun_connect(fabrica, modulo, vacio, log):
  cliente = _ClienteGuionado()
  obj = fabrica(vacio, cliente)
  stop = _StopGuionado(k=1)

  obj.setup_mqtt(stop)

  assert stop.esperas == [30.0]
  assert cliente.connects == [], "con el broker vacio NO se llama a connect()"
  assert cliente.loop_starts == 0
  assert len(log.warnings) == 1
  assert len(log.sin_broker()) == 1
  assert log.reintentos() == []
  assert obj.conectado is False


@GEMELOS
def test_sin_broker_no_repite_el_aviso_mientras_siga_vacio(fabrica, modulo, log):
  """Varias vueltas de espera con el broker vacio: una sola linea en el log, no una por vuelta."""
  cliente = _ClienteGuionado()
  obj = fabrica("", cliente)
  stop = _StopGuionado(k=4)

  obj.setup_mqtt(stop)

  assert stop.esperas == [30.0, 30.0, 30.0, 30.0]
  assert cliente.connects == []
  assert len(log.warnings) == 1
  assert len(log.sin_broker()) == 1


@GEMELOS
def test_sin_broker_relee_la_direccion_en_cada_vuelta_y_conecta_cuando_aparece(fabrica, modulo, log):
  """Si el broker aparece mientras el hilo dormia (relevo aplazado, escritura externa del
  JSON), la vuelta siguiente lo ve y conecta: la direccion se lee en cada iteracion, no
  una vez al entrar."""
  cliente = _ClienteGuionado(exito_en=1)
  obj = fabrica("", cliente)

  def escribe_broker():
    obj.broker_address = BROKER

  stop = _StopGuionado(k=99, al_esperar=escribe_broker)

  obj.setup_mqtt(stop)

  assert stop.esperas == [30.0]
  assert cliente.connects == [(BROKER, 1883, 60)]
  assert cliente.loop_starts == 1
  assert len(log.sin_broker()) == 1
  assert log.reintentos() == []


def test_mandos_sin_broker_espera_con_el_lock_libre(log):
  """La rama 'sin broker' se evalua ANTES de coger _conn_lock: un relevo (reload_broker)
  que llegue durante la espera larga no puede quedarse bloqueado detras del hilo dormido."""
  cliente = _ClienteGuionado()
  obj = _comandos("", cliente)
  lock_en_espera = []

  stop = _StopGuionado(k=3, al_esperar=lambda: lock_en_espera.append(obj._conn_lock.locked()))

  obj.setup_mqtt(stop)

  assert stop.esperas == [30.0, 30.0, 30.0]
  assert lock_en_espera == [False, False, False]
  assert cliente.connects == []


# ---------------------------------------------------------------------------- broker caido

@GEMELOS
def test_broker_caido_escala_5_10_20_60_y_se_queda_en_60(fabrica, modulo, log):
  cliente = _ClienteGuionado()
  obj = fabrica(BROKER, cliente)
  stop = _StopGuionado(k=5)

  obj.setup_mqtt(stop)

  assert stop.esperas == [5, 10, 20, 60, 60]
  assert len(cliente.connects) == 5
  assert all(c == (BROKER, 1883, 60) for c in cliente.connects)
  assert cliente.loop_starts == 0
  assert obj.conectado is False
  # Cada intento avisa con SU espera, no con el '5s' fijo de antes.
  reintentos = log.reintentos()
  assert len(reintentos) == 5
  assert [r.rsplit("Reintento en ", 1)[1] for r in reintentos] == ["5s", "10s", "20s", "60s", "60s"]
  assert all(f"{BROKER}:1883" in r and "Invalid host." in r for r in reintentos)
  assert log.sin_broker() == [], "con broker configurado no se avisa de 'sin broker'"


def test_mandos_broker_caido_suelta_el_lock_antes_de_esperar(log):
  cliente = _ClienteGuionado()
  obj = _comandos(BROKER, cliente)
  lock_en_espera = []

  stop = _StopGuionado(k=2, al_esperar=lambda: lock_en_espera.append(obj._conn_lock.locked()))

  obj.setup_mqtt(stop)

  assert stop.esperas == [5, 10]
  assert lock_en_espera == [False, False]


# -------------------------------------------------------------------------- camino bueno

@GEMELOS
def test_conecta_al_tercer_intento_y_el_bucle_termina(fabrica, modulo, log):
  cliente = _ClienteGuionado(exito_en=3)
  obj = fabrica(BROKER, cliente)
  stop = _StopGuionado(k=99)  # el relevo nunca llega: el bucle tiene que salir por el connect() bueno

  obj.setup_mqtt(stop)

  assert stop.esperas == [5, 10]
  assert len(cliente.connects) == 3
  assert cliente.loop_starts == 1, "loop_start() una sola vez, tras el connect() bueno"
  assert [r.rsplit("Reintento en ", 1)[1] for r in log.reintentos()] == ["5s", "10s"]


def test_telemetria_conectada_deja_el_estado_a_on_connect(log):
  """En la telemetria `conectado` lo pone on_connect (callback de paho), no el bucle."""
  cliente = _ClienteGuionado(exito_en=1)
  obj = _envio(BROKER, cliente)

  obj.setup_mqtt(_StopGuionado(k=99))

  assert cliente.loop_starts == 1
  assert obj.conectado is False


def test_mandos_conectado_marca_conectado_como_antes(log):
  """En los mandos el bucle si marca conectado=True nada mas arrancar el hilo de red."""
  cliente = _ClienteGuionado(exito_en=1)
  obj = _comandos(BROKER, cliente)

  obj.setup_mqtt(_StopGuionado(k=99))

  assert cliente.loop_starts == 1
  assert obj.conectado is True


@GEMELOS
def test_ya_conectado_no_vuelve_a_arrancar_el_hilo_de_red(fabrica, modulo, log):
  """Como antes: si `conectado` ya era True, el connect() bueno no repite loop_start()."""
  cliente = _ClienteGuionado(exito_en=1)
  obj = fabrica(BROKER, cliente)
  obj.conectado = True

  obj.setup_mqtt(_StopGuionado(k=99))

  assert len(cliente.connects) == 1
  assert cliente.loop_starts == 0


# --------------------------------------------------------------------------------- relevo

@GEMELOS
def test_cada_relevo_arranca_otra_vez_en_5s(fabrica, modulo, log):
  """El estado del reintento es LOCAL al hilo: un segundo setup_mqtt sobre el MISMO objeto
  (lo que hace _relanzar_hilo_conexion / reload_broker al escribir un broker desde
  Ajustes) empieza en 5 s, no donde se quedo el anterior."""
  cliente = _ClienteGuionado()
  obj = fabrica(BROKER, cliente)

  primero = _StopGuionado(k=4)
  obj.setup_mqtt(primero)
  assert primero.esperas == [5, 10, 20, 60]

  segundo = _StopGuionado(k=2)
  obj.setup_mqtt(segundo)
  assert segundo.esperas == [5, 10]

  # Y el aviso de 'sin broker' tambien se reinicia con el relevo: si el broker vuelve a
  # quedarse vacio en un hilo nuevo, ese hilo avisa una vez.
  obj.broker_address = ""
  tercero = _StopGuionado(k=2)
  obj.setup_mqtt(tercero)
  assert tercero.esperas == [30.0, 30.0]
  assert len(log.sin_broker()) == 1


@GEMELOS
def test_el_relevo_interrumpe_la_espera_larga_de_verdad(fabrica, modulo, log):
  """Con un threading.Event REAL: el hilo de conexion parado en la espera de 30 s sale en
  cuanto se pone la senal de relevo (es lo que hace que el join(6 s) del relevo llegue)."""
  cliente = _ClienteGuionado()
  obj = fabrica("", cliente)
  stop = threading.Event()

  hilo = threading.Thread(target=obj.setup_mqtt, args=(stop,), daemon=True)
  hilo.start()
  t0 = time.monotonic()
  # Le damos margen para entrar en la espera y comprobamos que sigue VIVO esperando.
  hilo.join(timeout=0.2)
  assert hilo.is_alive(), "el hilo no debe salir mientras no haya broker: nadie mas reintentaria"
  stop.set()
  hilo.join(timeout=2.0)

  assert not hilo.is_alive()
  assert time.monotonic() - t0 < 2.0
  assert cliente.connects == []
  assert len(log.sin_broker()) == 1


@GEMELOS
def test_stop_event_general_tambien_saca_al_hilo(fabrica, modulo, log):
  """stop() del subsistema pone stop_event y _conn_stop: aqui basta stop_event ya puesto
  para que el bucle no de ni una vuelta."""
  cliente = _ClienteGuionado()
  obj = fabrica(BROKER, cliente)
  obj.stop_event.set()
  stop = _StopGuionado(k=99)

  obj.setup_mqtt(stop)

  assert stop.esperas == []
  assert cliente.connects == []
  assert log.warnings == []


# ------------------------------------------------------------------------ politica comun

def test_la_escalera_de_reintento_es_5_10_20_60_y_es_la_misma_para_los_dos():
  """Los dos ficheros usan la MISMA politica (la telemetria la importa de los mandos)."""
  assert mc.CONN_RETRY_SECS == (5.0, 10.0, 20.0, 60.0)
  assert mc.CONN_SIN_BROKER_SECS == 30.0
  assert meg.espera_reintento is mc.espera_reintento
  assert meg.CONN_SIN_BROKER_SECS is mc.CONN_SIN_BROKER_SECS
  assert [mc.espera_reintento(i) for i in range(7)] == [5.0, 10.0, 20.0, 60.0, 60.0, 60.0, 60.0]
