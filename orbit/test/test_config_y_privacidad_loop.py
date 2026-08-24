"""El hilo del loop ORBIT: configuracion deseada/reportada (§8) y los dos huecos que le
quedaban al interruptor de privacidad (§9).

    Aborto no declarado ............ _mantener_spool colgaba del final de _ciclo_v2, que
                                     tambien retorna antes cuando motor_v2.tick() lanza.
                                     Un motor que falle siempre dejaba el interruptor sin
                                     efecto sobre la cola, en silencio y para siempre.
    Silencio en la CAPTURA ......... `trip` no tiene fuente que quitar (se alimenta de
                                     carState), asi que se filtra despues del tick.
    Sobre aplicado ................. un cfg/desired ganador aterriza en Params, en
                                     config_jetson.json y en el CameraSender, y solo
                                     despues se publica cfg/reported.
    Reported dice lo que HAY ....... un cambio hecho en la pantalla del comma sube de
                                     version con source comma_ui sin ningun params-buzon.
    Aplicar no es publicar ......... el reported avanza al APLICARSE (tambien sin
                                     cobertura, que es cuando la regla del empate hace
                                     falta); lo que depende del publish es solo la deuda
                                     con el retenido del broker, que se reintenta.
    Un rechazo tampoco es eterno ... los de VALOR mueren con la correccion hecha en local,
                                     los de CLAVE no (no hay cambio local que los arregle).
    Tipos nativos .................. Params.put con el tipo equivocado lanza TypeError y el
                                     ajuste se perderia en silencio.
"""
import json
import types

import pytest

from openpilot.orbit import config_v2 as cfg2
from openpilot.orbit import spool as spool_mod
from openpilot.orbit.mqtt_envio_general import MQTTEnvioGeneral

DONGLE = "0123456789abcdef"
T0 = 1_700_000_000_000

# Tipo NATIVO que exige Params.put para cada clave que toca este camino.
_TIPOS = {
  "OrbitPrivacyMute": bool, "OrbitTelemetryProfile": str, "orbit_speed_increment": float,
  "SteerTorqueMode": int, "JetsonObstacleApplyTarget": str, "JetsonConfigChanged": bool,
  "OrbitConfigDesired": str, "OrbitConfigReported": str,
  "carState_toggle": bool, "carControl_toggle": bool, "controlsState_toggle": bool,
  "liveCalibration_toggle": bool, "gpsLocationExternal_toggle": bool,
  "gpsLocation_toggle": bool, "drivingModelData_toggle": bool, "radarState_toggle": bool,
}


class ParamsFalsos:
  """Params con TIPOS: put() con el tipo equivocado lanza, como el de verdad."""

  def __init__(self, valores=None):
    self.valores = dict(valores or {})

  def get(self, key, block=False, return_default=False):
    return self.valores.get(key)

  def get_bool(self, key, block=False):
    return bool(self.valores.get(key, False))

  def put(self, key, dat, block=False):
    esperado = _TIPOS.get(key)
    if esperado is not None and type(dat) is not esperado:
      raise TypeError(f"{key} exige {esperado.__name__}, no {type(dat).__name__}")
    self.valores[key] = dat

  def put_bool(self, key, val, block=False):
    self.valores[key] = bool(val)

  def remove(self, key):
    self.valores.pop(key, None)


class ParamsQueFallanAlEscribir(ParamsFalsos):
  """Params cuyo put() falla en unas claves. Es el caso real de `no_aplicado`: el valor
  era valido, el contrato lo acepto y aun asi no aterrizo."""

  def __init__(self, fallan=(), valores=None):
    super().__init__(valores)
    self.fallan = set(fallan)

  def put(self, key, dat, block=False):
    if key in self.fallan:
      raise OSError("la eMMC dijo que no")
    super().put(key, dat, block)


class ClienteFalso:
  def __init__(self, rc=0):
    self.publicados = []
    self.rc = rc

  def publish(self, topic, payload, qos=0, retain=False):
    self.publicados.append((topic, payload, qos, retain))
    return types.SimpleNamespace(rc=self.rc)

  def is_connected(self):
    return True


class MotorFalso:
  def __init__(self, mensajes=(), lanza=False):
    self.mensajes = list(mensajes)
    self.lanza = lanza
    self.sellos_invalidados = []
    self.revertidos = []
    self.perfil_pedido = "normal"
    self.diag_expirado = False

  def tick(self, ahora, fuentes):
    if self.lanza:
      raise RuntimeError("una fuente cereal cambio de forma tras un rebase")
    return list(self.mensajes)

  def invalidar_sello(self, canal):
    self.sellos_invalidados.append(canal)
    return True

  def revertir(self, canal):
    self.revertidos.append(canal)
    return True

  def pedir_perfil(self, perfil, ahora):
    self.perfil_pedido = perfil


class CamaraFalsa:
  def __init__(self):
    self.sending_enabled = False
    self.interval_seconds = 2.0
    self.camera_type = "road"
    self.aplicados = []

  def apply_config(self, cfg):
    self.aplicados.append(dict(cfg))
    if "image_sending_enabled" in cfg:
      self.sending_enabled = bool(cfg["image_sending_enabled"])
    if "send_frequency_seconds" in cfg:
      self.interval_seconds = float(cfg["send_frequency_seconds"])
    if "camera_type" in cfg:
      self.camera_type = str(cfg["camera_type"])


def _envio(tmp_path, params=None, motor=None, spool=None, camara=None, mute=False):
  """MQTTEnvioGeneral real sin __init__: ni broker, ni SubMaster, ni /data."""
  e = MQTTEnvioGeneral.__new__(MQTTEnvioGeneral)
  e.params = params if params is not None else ParamsFalsos()
  if mute:
    e.params.valores["OrbitPrivacyMute"] = True
  e.DongleID = DONGLE
  e.dongle_valido = True
  e.conectado = True
  e.mqttc = ClienteFalso()
  e.motor_v2 = motor if motor is not None else MotorFalso()
  e.camera_sender = camara
  e.servicios_v2 = ()
  e.sm = types.SimpleNamespace(alive={}, data={})
  e._privacy_ts = 0.0
  e._privacy_cache = False
  e._privacy_avisado = False
  e._last_perfil_check = 1e9        # el perfil no se relee en estas pruebas
  e._last_rc_log = 0.0
  e.RC_LOG_SECS = 60.0
  e.PERFIL_RELOAD_SECS = 5.0
  e._perfil_avisado = False
  e._spool_obj = spool
  e._spool_roto = spool is None
  e._last_spool = 0.0
  e.SPOOL_SECS = 0.0
  e._cfg_deseado = None
  e._cfg_reportado = None
  e._cfg_reportado_publicado = False
  e._cfg_rechazos = {}
  e._cfg_cargado = False
  e._last_cfg = 0.0
  e.CFG_SECS = 0.0
  ruta = str(tmp_path / "config_jetson.json")
  (tmp_path / "config_jetson.json").write_text(json.dumps({"jetson_ip": "", "jpeg_quality": 10}))
  e._cfg_ruta_jetson = lambda: ruta
  return e


def _spool_real(tmp_path):
  s = spool_mod.Spool(ruta=str(tmp_path / "spool"))
  assert s.activo, s.motivo
  return s


# ------------------------------------------------- el segundo camino de aborto (§9)

def test_el_mantenimiento_del_spool_corre_aunque_el_motor_lance(tmp_path):
  """_mantener_spool colgaba del FINAL de _ciclo_v2, y _ciclo_v2 tambien retorna antes
  cuando motor_v2.tick() lanza. Ese camino no estaba declarado en ninguna parte: un motor
  que falle en cada ciclo dejaba la purga de posicion sin ejecutarse nunca, con el mute
  puesto, en silencio."""
  s = _spool_real(tmp_path)
  for i in range(3):
    assert s.guardar("road", {"d": {"road_name": f"Calle {i}"}}, ts_ms=T0 + i)
  assert s.flush() == 3

  e = _envio(tmp_path, motor=MotorFalso(lanza=True), spool=s, mute=True)
  e._ciclo_v2(1000.0)

  assert s.estado()["filas"] == 0, "la purga no corrio: el interruptor se quedo sin efecto"
  assert s.estado()["contadores"]["descartadas_privacidad"] == 3
  s.cerrar()


def test_sin_identidad_se_purga_pero_no_se_reenvia(tmp_path):
  """Sin DongleId valido no se puede reenviar (seria telemetria atribuida al vehiculo
  fantasma que comparten todos los comma sin registrar), pero el interruptor tiene que
  alcanzar lo que este proceso ya encolo."""
  s = _spool_real(tmp_path)
  assert s.guardar("road", {"d": {"road_name": "Gran Via"}}, ts_ms=T0)
  assert s.guardar("vehicle", {"d": {"v": 50}}, ts_ms=T0)
  s.flush()

  e = _envio(tmp_path, spool=s, mute=True)
  e.dongle_valido = False
  e._ciclo_v2(1000.0)

  assert s.estado()["filas"] == 1, "queda `vehicle`: la purga es de posicion"
  assert e.mqttc.publicados == [], "sin identidad no sale nada por el cable"
  s.cerrar()


def test_sin_identidad_y_sin_spool_abierto_no_se_crea_uno(tmp_path):
  """Crear /data/orbit_spool y una base SQLite para un dispositivo que nunca ha tenido
  identidad no purga nada: solo escribe en la eMMC."""
  e = _envio(tmp_path, mute=True)
  e.dongle_valido = False
  e._spool_obj = None
  e._spool_roto = False
  e._ciclo_v2(1000.0)
  assert e._spool_obj is None


# -------------------------------------------------- el silencio en la captura (§9, d)

def test_el_resumen_de_viaje_no_se_publica_ni_se_encola_con_el_mute(tmp_path):
  """`trip` no se alimenta de una fuente de posicion (viene de carState), asi que quitar
  fuentes en _fuentes_v2 no lo tapa. Y no se difiere: encolarlo dejaria el resumen en disco
  esperando a que se quite el mute, que es justo lo que la purga existe para evitar."""
  s = _spool_real(tmp_path)
  motor = MotorFalso(mensajes=[("trip", {"ev": "end", "dist_km": 43.2}),
                               ("vehicle", {"speed_kph": 50.0})])
  e = _envio(tmp_path, motor=motor, spool=s, mute=True)
  e._ciclo_v2(1000.0)

  canales = [t.rsplit("/", 1)[-1] for t, _, _, _ in e.mqttc.publicados]
  assert canales == ["vehicle"], "el mute no apaga la telemetria entera, solo lo que dice por donde vas"
  assert s.estado()["filas"] == 0 and s.estado()["en_ram"] == 0
  assert motor.revertidos == [], "no se difiere ni se revierte: se descarta"
  s.cerrar()


def test_sin_el_mute_el_resumen_de_viaje_sale(tmp_path):
  s = _spool_real(tmp_path)
  motor = MotorFalso(mensajes=[("trip", {"ev": "end", "dist_km": 43.2})])
  e = _envio(tmp_path, motor=motor, spool=s)
  e._ciclo_v2(1000.0)
  assert [t.rsplit("/", 1)[-1] for t, _, _, _ in e.mqttc.publicados] == ["trip"]
  s.cerrar()


def test_el_drenaje_recibe_el_testigo_y_no_un_bool(tmp_path):
  """Una tanda son hasta 200 publicaciones seguidas: si se pasara el valor, pulsar el
  interruptor dentro de la tanda no la cortaria."""
  visto = {}

  class SpoolEspia:
    activo = True
    def flush(self): return 0
    def purgar_posicion(self): return 0
    def hay_pendientes(self): return True
    def canales_perdidos(self): return {}
    def drenar(self, publicar, dongle=None, privacidad=False, **kw):
      visto["privacidad"] = privacidad
      return spool_mod.ResumenDrenaje()

  e = _envio(tmp_path, spool=SpoolEspia())
  e._mantener_spool(1000.0, True)
  assert callable(visto["privacidad"])
  assert visto["privacidad"].__func__ is MQTTEnvioGeneral._privacidad_silenciada


# --------------------------------------------------------- configuracion (§8)

def _sobre(version=1, **values):
  return json.dumps({"version": version, "ts_ms": T0, "source": "backend", "values": values})


def _reportado(e):
  for topic, payload, qos, retain in e.mqttc.publicados:
    if topic.startswith("orbit/v2/cfg/reported/"):
      return json.loads(payload), qos, retain
  return None, None, None


def test_un_desired_ganador_aterriza_y_se_reporta(tmp_path):
  cam = CamaraFalsa()
  e = _envio(tmp_path, camara=cam)
  cfg2.get_bus().tomar()          # el buzon es un singleton de proceso: se deja limpio
  cfg2.get_bus().recibir(_sobre(version=4, jetson_ip="192.168.1.50", jpeg_quality=80,
                                telemetry_profile="ahorro", camera_enabled=True,
                                speed_increment_kph=3))
  e._mantener_config(1000.0)

  # 1) aterrizo donde tenia que aterrizar, con el tipo NATIVO de cada param
  assert cfg2.leer_config_jetson(e._cfg_ruta_jetson())["jetson_ip"] == "192.168.1.50"
  assert e.params.valores["JetsonConfigChanged"] is True
  assert e.params.valores["OrbitTelemetryProfile"] == "ahorro"
  assert isinstance(e.params.valores["orbit_speed_increment"], float)
  assert cam.sending_enabled is True

  # 2) y solo DESPUES se reporta, retenido y con qos 1
  sobre, qos, retain = _reportado(e)
  assert (qos, retain) == (1, True)
  assert sobre["source"] == cfg2.FUENTE_COMMA_UI, "reported es la palabra del COCHE"
  assert sobre["version"] == 4
  assert sobre["values"]["jetson_ip"] == "192.168.1.50"
  assert sobre["values"]["telemetry_profile"] == "ahorro"
  assert e.params.valores["OrbitConfigReported"]


def test_lo_que_el_contrato_rechaza_viaja_en_el_reported(tmp_path):
  """Si el rechazo fuera mudo, cada fila de la app se quedaria en "aplicando..." para
  siempre sin saber por que."""
  e = _envio(tmp_path)
  cfg2.get_bus().tomar()
  cfg2.get_bus().recibir(_sobre(version=2, jetson_ip="8.8.8.8", steer_mode=2, jpeg_quality=80))
  e._mantener_config(1000.0)

  sobre, _, _ = _reportado(e)
  assert sobre["rechazos"]["jetson_ip"] == cfg2.MOT_RANGO
  assert sobre["rechazos"]["steer_mode"] == cfg2.MOT_SOLO_REPORTE
  assert cfg2.leer_config_jetson(e._cfg_ruta_jetson())["jetson_ip"] == "", "la IP publica no se escribio"
  assert sobre["values"]["jpeg_quality"] == 80, "lo que si valia se aplico igual"


def test_un_desired_que_no_gana_no_se_aplica(tmp_path):
  """El broker re-entrega el retenido en CADA reconexion."""
  e = _envio(tmp_path)
  e._cfg_deseado = cfg2.Sobre(version=9, ts_ms=T0, source="backend", values={})
  e._cfg_cargado = True
  cfg2.get_bus().tomar()
  cfg2.get_bus().recibir(_sobre(version=3, jpeg_quality=95))
  e._mantener_config(1000.0)
  assert cfg2.leer_config_jetson(e._cfg_ruta_jetson())["jpeg_quality"] == 10


def test_un_cambio_local_sube_de_version_con_source_comma_ui(tmp_path):
  """Lo que sustituye a los params-buzon: la pantalla del comma escribe SU param y esto lo
  ve leyendo el destino, sin que nadie tenga que serializar un JSON a mano."""
  e = _envio(tmp_path)
  e._cfg_deseado = cfg2.Sobre(version=7, ts_ms=T0, source="backend", values={})
  e._cfg_cargado = True
  e.params.valores["carState_toggle"] = True

  e._mantener_config(1000.0)
  sobre, _, _ = _reportado(e)
  assert sobre["source"] == cfg2.FUENTE_COMMA_UI
  assert sobre["version"] == 8, "por encima del ultimo desired conocido"
  assert sobre["values"]["carState_toggle"] is True


def test_no_se_republica_un_reported_identico(tmp_path):
  """cfg/reported es RETENIDO: republicarlo cada 5 s seria ruido en el broker y en la app."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  e._mantener_config(1000.0)
  publicados = len(e.mqttc.publicados)
  assert publicados == 1
  e._mantener_config(2000.0)
  assert len(e.mqttc.publicados) == publicados


def test_el_reported_que_no_salio_se_reintenta_hasta_que_sale(tmp_path):
  """El `reported` avanza al APLICARSE (es lo que el coche SABE de si mismo), pero el
  RETENIDO del broker solo tiene lo que salio de verdad. Esa deuda no se puede olvidar: el
  sobre se reintenta -- el MISMO, misma version -- hasta que el publish devuelve rc 0, o el
  backend se queda mirando un retenido de hace tres ajustes."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  e.mqttc.rc = 4                       # MQTT_ERR_NO_CONN
  e._mantener_config(1000.0)
  assert e._cfg_reportado is not None, "el coche no sabe lo que tiene por no haberlo dicho"
  assert e._cfg_reportado_publicado is False
  primero = json.loads(e.mqttc.publicados[-1][1])

  e._mantener_config(2000.0)           # sigue sin salir: se vuelve a intentar
  assert len(e.mqttc.publicados) == 2
  assert json.loads(e.mqttc.publicados[-1][1])["version"] == primero["version"], \
    "el reintento invento una version nueva para el mismo estado"

  e.mqttc.rc = 0
  e._mantener_config(3000.0)
  assert e._cfg_reportado_publicado is True
  assert json.loads(e.mqttc.publicados[-1][1])["version"] == primero["version"]

  e._mantener_config(4000.0)           # ya no hay deuda: no se republica un retenido igual
  assert len(e.mqttc.publicados) == 3


def test_el_estado_solo_de_reporte_sale_en_el_reported(tmp_path):
  """La app tiene que poder pintar el modo de volante y el mute aunque no se puedan
  escribir por aqui."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  e.params.valores.update({"SteerTorqueMode": 3, "JetsonObstacleApplyTarget": "torque",
                           "OrbitPrivacyMute": True})
  e._mantener_config(1000.0)
  sobre, _, _ = _reportado(e)
  assert sobre["values"]["steer_mode"] == 3
  assert sobre["values"]["steer_apply_target"] == "torque"
  assert sobre["values"]["privacy_mute"] is True


def test_la_version_no_retrocede_tras_un_reinicio(tmp_path):
  """Sin esto, un cfg/desired viejo retenido en el broker le ganaria al estado real."""
  e = _envio(tmp_path)
  e.params.valores["OrbitConfigReported"] = cfg2.Sobre(
    version=42, ts_ms=T0, source=cfg2.FUENTE_COMMA_UI, values={}).a_json()
  e._cfg_cargar_persistido()
  assert e._cfg_reportado.version == 42
  e.params.valores["carState_toggle"] = True
  e._mantener_config(1000.0)
  sobre, _, _ = _reportado(e)
  assert sobre["version"] == 43


@pytest.fixture(autouse=True)
def _buzon_limpio():
  """El buzon es un singleton de PROCESO (get_bus): un sobre olvidado contamina el
  siguiente test."""
  cfg2.get_bus().tomar()
  yield
  cfg2.get_bus().tomar()


# ------------------------------------- el empate lo gana el COCHE, tambien en el llamante

def _jetson(e, **campos):
  """Deja config_jetson.json con lo que se le diga (el estado REAL del enlace)."""
  import pathlib as _p
  ruta = _p.Path(e._cfg_ruta_jetson())
  datos = json.loads(ruta.read_text())
  datos.update(campos)
  ruta.write_text(json.dumps(datos))


def test_el_backend_no_gana_el_empate_contra_lo_que_el_coche_reporta(tmp_path):
  """Alguien corrige jpeg_quality en la pantalla del comma (reported v2, comma_ui). El
  backend, que todavia no ha ingerido ese reported, emite `desired` con la MISMA version
  (su _siguiente_version es max(deseada, reportada)+1 sobre lo que EL sabe). Ese empate lo
  gana el coche: es el unico lado que puede tener a alguien delante sin red.

  Comparar solo contra `_cfg_deseado` lo perdia, y ademas en silencio."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  _jetson(e, jpeg_quality=55)
  e._cfg_deseado = cfg2.Sobre(version=1, ts_ms=T0, source="backend", values={"jpeg_quality": 80})
  e._cfg_reportado = cfg2.Sobre(version=2, ts_ms=T0, source=cfg2.FUENTE_COMMA_UI,
                                values={"jpeg_quality": 55})

  cfg2.get_bus().recibir(_sobre(version=2, jpeg_quality=80))
  e._mantener_config(1000.0)

  assert cfg2.leer_config_jetson(e._cfg_ruta_jetson())["jpeg_quality"] == 55, \
    "el empate lo gano el backend y se deshizo el ajuste hecho en la pantalla"
  assert e._cfg_deseado.version == 1, "ni se dio por aceptado"


def test_un_desired_retrasado_no_deshace_un_reported_mas_alto(tmp_path):
  """Mismo agujero por el otro lado: aqui ni siquiera hay empate, el `desired` viene por
  DEBAJO de la version que el coche ya publico, y aun asi se aplicaba."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  _jetson(e, jpeg_quality=63)
  e._cfg_deseado = cfg2.Sobre(version=2, ts_ms=T0, source="backend", values={})
  e._cfg_reportado = cfg2.Sobre(version=6, ts_ms=T0, source=cfg2.FUENTE_COMMA_UI,
                                values={"jpeg_quality": 63})

  cfg2.get_bus().recibir(_sobre(version=3, jpeg_quality=10))
  e._mantener_config(1000.0)

  assert cfg2.leer_config_jetson(e._cfg_ruta_jetson())["jpeg_quality"] == 63


def test_el_backend_sigue_ganando_en_cuanto_sube_de_version(tmp_path):
  """La regla del empate no puede convertirse en "el backend no manda nunca"."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  _jetson(e, jpeg_quality=55)
  e._cfg_deseado = cfg2.Sobre(version=1, ts_ms=T0, source="backend", values={})
  e._cfg_reportado = cfg2.Sobre(version=2, ts_ms=T0, source=cfg2.FUENTE_COMMA_UI,
                                values={"jpeg_quality": 55})

  cfg2.get_bus().recibir(_sobre(version=3, jpeg_quality=80))
  e._mantener_config(1000.0)

  assert cfg2.leer_config_jetson(e._cfg_ruta_jetson())["jpeg_quality"] == 80
  assert e._cfg_deseado.version == 3


def test_tras_un_reinicio_el_desired_retenido_no_deshace_un_cambio_local(tmp_path):
  """La otra mitad de B1: los dos sobres se releen de Params (las claves ya existen en el
  binario) y el retenido que el broker re-entrega al reconectar empata con el `reported`
  del cambio local, que es de ANTES del reinicio. Lo gana el coche."""
  params = ParamsFalsos()
  params.valores["OrbitConfigDesired"] = cfg2.Sobre(
    version=2, ts_ms=T0, source="backend", values={"jpeg_quality": 80}).a_json()
  params.valores["OrbitConfigReported"] = cfg2.Sobre(
    version=3, ts_ms=T0, source=cfg2.FUENTE_COMMA_UI, values={"jpeg_quality": 55}).a_json()

  e = _envio(tmp_path, params=params)
  _jetson(e, jpeg_quality=55)
  e._cfg_cargar_persistido()
  assert e._cfg_deseado.version == 2, "_cfg_cargar_persistido no releyo el desired"
  assert e._cfg_reportado.version == 3, "_cfg_cargar_persistido no releyo el reported"

  cfg2.get_bus().recibir(_sobre(version=3, jpeg_quality=80))
  e._mantener_config(1000.0)

  assert e._cfg_deseado.version == 2, "el retenido gano el empate y deshizo el cambio local"
  assert cfg2.leer_config_jetson(e._cfg_ruta_jetson())["jpeg_quality"] == 55
  sobre, _, _ = _reportado(e)
  assert sobre["version"] == 4, "el reported nuevo sube por encima de los dos"


# ---------------------------------------- un rechazo no se borra solo (D2) y dice QUE (D4)

def test_un_rechazo_de_aplicacion_viaja_con_la_clave_del_contrato(tmp_path):
  """Salia `{"rechazos": {"OrbitTelemetryProfile": "no_aplicado"}}`: el nombre del PARAM.
  La app resuelve cada clave contra el vocabulario del contrato y tira lo que no reconoce,
  y el backend lo cruza contra `desired.values`, que tambien esta en claves de contrato.
  Con el nombre del destino, el rechazo no llega a nadie."""
  params = ParamsQueFallanAlEscribir(fallan={"OrbitTelemetryProfile", "orbit_speed_increment"})
  e = _envio(tmp_path, params=params)          # sin camera_sender: camera_* tampoco aterriza
  e._cfg_cargado = True
  cfg2.get_bus().recibir(_sobre(version=2, telemetry_profile="ahorro", speed_increment_kph=3,
                                camera_enabled=True, camera_interval_s=5))
  e._mantener_config(1000.0)

  sobre, _, _ = _reportado(e)
  assert sobre["rechazos"] == {
    "telemetry_profile": cfg2.MOT_NO_APLICADO,
    "speed_increment_kph": cfg2.MOT_NO_APLICADO,
    "camera_enabled": cfg2.MOT_SIN_CAMARA,
    "camera_interval_s": cfg2.MOT_SIN_CAMARA,
  }
  assert all(k in cfg2.CLAVES for k in sobre["rechazos"]), "hay claves que la app tirara"


def test_un_rechazo_sobrevive_mientras_su_causa_sigue_viva(tmp_path):
  """Se publicaba reported v1 CON rechazos y, en el tick siguiente, reported v2 SIN ellos:
  `rechazos_aplicar` solo se calcula en el tick que aplica. El backend, con version por
  encima de la deseada, adoptaba el documento entero, el ajuste pedido desaparecia del
  deseado y la app pintaba "Al dia" sobre algo que no se aplico nunca."""
  params = ParamsQueFallanAlEscribir(fallan={"OrbitTelemetryProfile"})
  e = _envio(tmp_path, params=params)
  e._cfg_cargado = True
  cfg2.get_bus().recibir(_sobre(version=2, telemetry_profile="ahorro"))
  e._mantener_config(1000.0)
  assert _reportado(e)[0]["rechazos"] == {"telemetry_profile": cfg2.MOT_NO_APLICADO}

  # Tick siguiente sin nada nuevo: no hay nada que decir, no se republica.
  publicados = len(e.mqttc.publicados)
  e._mantener_config(2000.0)
  assert len(e.mqttc.publicados) == publicados, "se republico un reported identico"

  # Y cuando algo mas SI cambia, el rechazo sigue viajando con el sobre nuevo.
  e.params.valores["carState_toggle"] = True
  e._mantener_config(3000.0)
  ultimo = json.loads(e.mqttc.publicados[-1][1])
  assert ultimo["values"]["carState_toggle"] is True
  assert ultimo["rechazos"] == {"telemetry_profile": cfg2.MOT_NO_APLICADO}, \
    "el ajuste rechazado se borro solo y el sistema dijo Al dia"


def test_un_rechazo_muere_cuando_muere_su_causa(tmp_path):
  """"Mientras la causa siga viva" tiene las dos mitades: si el valor pedido acaba puesto,
  el rechazo tiene que desaparecer o la app se queda pintando un error que ya no existe."""
  e = _envio(tmp_path)                          # sin camera_sender
  e._cfg_cargado = True
  cfg2.get_bus().recibir(_sobre(version=2, camera_enabled=True, camera_interval_s=5))
  e._mantener_config(1000.0)
  assert _reportado(e)[0]["rechazos"] == {"camera_enabled": cfg2.MOT_SIN_CAMARA,
                                          "camera_interval_s": cfg2.MOT_SIN_CAMARA}

  cam = CamaraFalsa()
  cam.sending_enabled, cam.interval_seconds = True, 5
  e.camera_sender = cam
  e._mantener_config(2000.0)
  assert "rechazos" not in json.loads(e.mqttc.publicados[-1][1])


def test_un_rechazo_de_contrato_sobrevive_a_un_reinicio(tmp_path):
  """El rechazo del contrato es funcion pura del `desired`, y el `desired` esta en Params:
  perderlo en el reinicio dejaria al backend adoptando un reported limpio."""
  params = ParamsFalsos()
  params.valores["OrbitConfigDesired"] = cfg2.Sobre(
    version=5, ts_ms=T0, source="backend",
    values={"jetson_ip": "8.8.8.8", "steer_mode": 2}).a_json()
  e = _envio(tmp_path, params=params)
  e._mantener_config(1000.0)

  sobre, _, _ = _reportado(e)
  assert sobre["rechazos"]["jetson_ip"] == cfg2.MOT_RANGO
  assert sobre["rechazos"]["steer_mode"] == cfg2.MOT_SOLO_REPORTE


# ------------------- el reported avanza al APLICAR, no al PUBLICAR (§8 con la red caida)

def test_un_cambio_local_sin_cobertura_no_lo_deshace_el_desired_retenido(tmp_path):
  """EL escenario de la regla del empate, y el que se perdia: alguien corrige jpeg_quality
  en la pantalla del comma SIN COBERTURA. El `reported` no puede salir, y si por eso no
  avanzara, `gana_a_todos` se quedaria sin nada con que defender el cambio: al volver la
  red, el `desired` retenido -- que el broker re-entrega en cada reconexion -- empata
  contra el reported viejo y deshace el ajuste.

  "El coche siempre puede corregir en local, sin red" es exactamente esto, asi que el
  reported tiene que avanzar cuando el cambio SE APLICA. Publicar es otra cosa."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  e.conectado = False
  _jetson(e, jpeg_quality=55)
  e._cfg_deseado = cfg2.Sobre(version=1, ts_ms=T0, source="backend", values={"jpeg_quality": 80})

  e._mantener_config(1000.0)
  assert e.mqttc.publicados == [], "sin enlace no sale nada por el cable"
  assert e._cfg_reportado is not None, "el coche se olvido de lo que acababa de aplicar"
  assert e._cfg_reportado.values["jpeg_quality"] == 55
  assert e._cfg_reportado.version == 2, "por encima del ultimo desired conocido"
  assert e.params.valores["OrbitConfigReported"], "no sobrevivira a un reinicio"

  # Vuelve la cobertura y con ella el retenido, que empata con lo que el coche sabe.
  e.conectado = True
  cfg2.get_bus().recibir(_sobre(version=2, jpeg_quality=80))
  e._mantener_config(2000.0)

  assert cfg2.leer_config_jetson(e._cfg_ruta_jetson())["jpeg_quality"] == 55, \
    "el desired retenido gano el empate y deshizo un ajuste hecho delante del coche"
  assert e._cfg_deseado.version == 1, "ni se dio por aceptado"


# --------------------------- un rechazo de contrato tampoco es eterno: se poda (§8, A-2)

def test_un_rechazo_de_valor_muere_con_la_correccion_hecha_en_local(tmp_path):
  """El backend pide una IP publica: rechazada por rango, el enlace se queda como estaba.
  Alguien la corrige a mano en la pantalla. El `reported` salia con el valor CORREGIDO y
  con el rechazo VIVO a la vez, y como el backend no adopta las claves rechazadas, esa
  correccion no llegaba nunca: la clave quedaba vetada para siempre."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  cfg2.get_bus().recibir(_sobre(version=2, jetson_ip="8.8.8.8"))
  e._mantener_config(1000.0)
  sobre, _, _ = _reportado(e)
  assert sobre["rechazos"] == {"jetson_ip": cfg2.MOT_RANGO}
  assert sobre["values"]["jetson_ip"] == "", "la IP publica no se escribio"

  _jetson(e, jetson_ip="192.168.1.5")            # correccion LOCAL, delante del coche
  e._mantener_config(2000.0)
  ultimo = json.loads(e.mqttc.publicados[-1][1])
  assert ultimo["values"]["jetson_ip"] == "192.168.1.5"
  assert "rechazos" not in ultimo, "el reported sale con el valor bueno y el rechazo vivo"

  # Y la poda es DEFINITIVA: si solo se filtrara al vuelo, en el tick siguiente el valor
  # ya coincide con el ultimo reported y el rechazo volveria a la vida.
  e.params.valores["carState_toggle"] = True
  e._mantener_config(3000.0)
  assert "rechazos" not in json.loads(e.mqttc.publicados[-1][1]), "el rechazo resucito"


def test_un_rechazo_de_clave_no_lo_mata_ningun_cambio_local(tmp_path):
  """La otra mitad: `solo_reporte` y `clave_desconocida` no hablan del VALOR sino de la
  CLAVE. Mover el volante con el verbo cambia steer_mode, pero "esto no se escribe por
  aqui" sigue siendo verdad y el backend no puede adoptarla."""
  e = _envio(tmp_path)
  e._cfg_cargado = True
  e.params.valores["SteerTorqueMode"] = 0
  cfg2.get_bus().recibir(_sobre(version=2, steer_mode=2, no_existe=1))
  e._mantener_config(1000.0)
  esperado = {"steer_mode": cfg2.MOT_SOLO_REPORTE, "no_existe": cfg2.MOT_DESCONOCIDA}
  assert _reportado(e)[0]["rechazos"] == esperado

  e.params.valores["SteerTorqueMode"] = 3        # el VERBO torque_mode, que si puede
  e._mantener_config(2000.0)
  ultimo = json.loads(e.mqttc.publicados[-1][1])
  assert ultimo["values"]["steer_mode"] == 3
  assert ultimo["rechazos"] == esperado, "un cambio local mato un rechazo que no era suyo"


def test_la_poda_de_un_rechazo_de_valor_sobrevive_al_reinicio(tmp_path):
  """Los de contrato se recalculan del `desired`, que sigue en Params: sin mirar el
  `reported`, el rechazo ya podado revivia en el arranque siguiente y volvia a vetar la
  clave. El `reported` con version >= la del `desired` es POSTERIOR a el y su veredicto es
  el que vale."""
  params = ParamsFalsos()
  params.valores["OrbitConfigDesired"] = cfg2.Sobre(
    version=5, ts_ms=T0, source="backend", values={"jetson_ip": "8.8.8.8"}).a_json()
  params.valores["OrbitConfigReported"] = cfg2.Sobre(
    version=6, ts_ms=T0, source=cfg2.FUENTE_COMMA_UI,
    values={"jetson_ip": "192.168.1.5"}).a_json()

  e = _envio(tmp_path, params=params)
  _jetson(e, jetson_ip="192.168.1.5")
  e._mantener_config(1000.0)

  assert e._cfg_rechazos == {}, "el rechazo podado resucito en el reinicio"
  assert "rechazos" not in json.loads(e.mqttc.publicados[-1][1])


def test_un_reported_anterior_al_desired_no_poda_nada(tmp_path):
  """El otro lado del mismo filtro: si el proceso murio entre guardar el `desired` y
  guardar el `reported`, ese reported es de ANTES y no vio el sobre. Ahi los rechazos de
  contrato se recalculan enteros, que es lo que evita que un ajuste rechazado se cuele
  como adoptado por haber elegido mal el momento de morir."""
  params = ParamsFalsos()
  params.valores["OrbitConfigDesired"] = cfg2.Sobre(
    version=5, ts_ms=T0, source="backend", values={"jetson_ip": "8.8.8.8"}).a_json()
  params.valores["OrbitConfigReported"] = cfg2.Sobre(
    version=4, ts_ms=T0, source=cfg2.FUENTE_COMMA_UI, values={"jetson_ip": ""}).a_json()

  e = _envio(tmp_path, params=params)
  e._mantener_config(1000.0)
  assert _reportado(e)[0]["rechazos"] == {"jetson_ip": cfg2.MOT_RANGO}
