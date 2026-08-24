"""Tests del endurecimiento del mando remoto (fase de contencion F0).

Fijan tres cosas que ya se rompieron una vez:

  1. `steer_torque_mode` RETENIDO. El param SteerTorqueMode es PERSISTENT y la app
     publica ese topic con retain:true, asi que el broker re-entregaba el retenido
     en CADA reconexion. Con modo 2 controlsd pone actuators.torque = -1.0 en cada
     ciclo mientras latActive, y con modo 1 la direccion pasa a la Jetson: un
     retenido antiguo volvia a dar par maximo sin que nadie mandara nada.
     Solo se admite retenido el modo 0 (bajar autoridad). Ademas, el modo 2 exige
     armado fisico del banco (OrbitBenchArmed).

  3. CameraSender.run(): si messaging.SubMaster() lanza, `sm` se queda en None con
     `_active_channel` apuntando al canal anterior; al volver a ese canal se
     saltaba la creacion y el sm.update() de fuera del try mataba el hilo entero
     (camara + mandos + telemetria) con AttributeError.

  7. Listas blancas de payload. Antes, cualquier basura que llegara a /left,
     /right, /speed_up o /speed_down terminaba ACTIVANDO la maniobra.

Los numeros son los de la revision adversarial de la fase anterior.
"""
import pytest

from openpilot.orbit import camera_sender
from openpilot.orbit.camera_sender import CameraSender
from openpilot.orbit.command_spec import COMMANDS, Mode
from openpilot.orbit.mqtt_comandos import MQTTComandos


class _ParamsFalsos:
  """Doble de Params: guarda en un dict y respeta que get_bool lance
  UnknownKeyName para una clave que no esta en common/params_keys.h."""

  def __init__(self, valores=None, desconocidos=()):
    self.valores = dict(valores or {})
    self.desconocidos = set(desconocidos)

  def _check(self, key):
    if key in self.desconocidos:
      raise KeyError(key)  # equivalente a params_pyx.UnknownKeyName

  def get(self, key, *args, **kwargs):
    self._check(key)
    return self.valores.get(key)

  def get_bool(self, key, *args, **kwargs):
    self._check(key)
    return bool(self.valores.get(key, False))

  def put(self, key, value, *args, **kwargs):
    self._check(key)
    self.valores[key] = value

  def put_bool(self, key, value, *args, **kwargs):
    self._check(key)
    self.valores[key] = bool(value)

  def remove(self, key):
    self.valores.pop(key, None)


def _comandos(params):
  """MQTTComandos sin __init__ (no toca broker, disco ni Params reales)."""
  c = MQTTComandos.__new__(MQTTComandos)
  c.params = params
  c.DongleID = "dongletest"
  c.dongle_valido = True
  c.camera_sender = None
  return c


# ---------------------------------------------------------------- punto 1 y 2

class TestSteerTorqueModeRetenido:
  """El topic v1 de modo de torque ya NO escribe SteerTorqueMode: lo traduce a un verbo.

  Estos tests miran la TRADUCCION (que verbo y que argumentos sale de cada payload). Que
  ese verbo acabe -- o no -- escribiendo el param, y con que gates, esta en
  test_mando_v1_por_router.py, que ejecuta el camino entero.
  """

  def test_steer_torque_mode_fuera_de_la_lista_blanca_de_retain(self):
    """El topic que cambia la fuente de direccion NO puede aceptar retenidos a
    secas: eso es lo que re-entregaba el modo 2 en cada reconexion."""
    assert "/steer_torque_mode" not in MQTTComandos.RETAIN_PERMITIDO
    assert "/steer_torque_mode" in MQTTComandos.RETAIN_SOLO_SI_BAJA_AUTORIDAD

  def test_retenido_modo_1_descartado(self):
    c = _comandos(_ParamsFalsos({"SteerTorqueMode": 0}))
    assert c._v1_steer_torque_mode('{"steer_torque_mode": 1, "source": "app"}', retenido=True) is None

  def test_retenido_modo_2_descartado_aunque_el_banco_este_armado(self):
    """El filtro de retain va ANTES que nada: un retenido no es una orden nueva, da igual
    que el banco este armado."""
    c = _comandos(_ParamsFalsos({"SteerTorqueMode": 0, "OrbitBenchArmed": True}))
    assert c._v1_steer_torque_mode('{"steer_torque_mode": 2, "source": "app"}', retenido=True) is None

  def test_retenido_modo_3_descartado(self):
    c = _comandos(_ParamsFalsos({"SteerTorqueMode": 0}))
    assert c._v1_steer_torque_mode(
      '{"steer_torque_mode": 3, "apply_target": "curvature", "source": "app"}', retenido=True) is None

  def test_retenido_modo_0_es_disarm_all(self):
    """Volver al modelo de comma BAJA autoridad y por eso nunca se descarta: se traduce al
    unico verbo que no se puede bloquear."""
    c = _comandos(_ParamsFalsos({"SteerTorqueMode": 1}))
    assert c._v1_steer_torque_mode('{"steer_torque_mode": 0, "source": "app"}', retenido=True) == ("disarm_all", {})

  def test_no_retenido_modo_1_se_traduce_a_torque_mode(self):
    """Una orden en vivo de la app sigue llegando; lo que decide si se aplica es el router
    (modo banco + armado fisico), no este puente."""
    c = _comandos(_ParamsFalsos({"SteerTorqueMode": 0}))
    assert c._v1_steer_torque_mode('{"steer_torque_mode": 1, "source": "app"}', retenido=False) == \
      ("torque_mode", {"mode": 1})

  def test_modo_3_exige_apply_target(self):
    c = _comandos(_ParamsFalsos())
    assert c._v1_steer_torque_mode('{"steer_torque_mode": 3, "source": "app"}') is None
    assert c._v1_steer_torque_mode('{"steer_torque_mode": 3, "apply_target": "torque", "source": "app"}') == \
      ("torque_mode", {"mode": 3, "apply_target": "torque"})


class TestModo2ExigeArmadoDeBanco:
  """El armado de banco ya no se comprueba aqui a mano: lo exige el router porque
  command_spec declara `torque_mode` de modo BANCO (y requiere_armado_banco se deriva del
  modo minimo, asi que no puede divergir).

  El gate ad-hoc de la fase de contencion cubria SOLO el modo 2. Ahora cubre 1, 2 y 3:
  los tres mueven el volante. La comprobacion real, con Params y router, esta en
  test_mando_v1_por_router.py::test_steer_torque_mode_v1_exige_armado_fisico_de_banco.
  """

  def test_torque_mode_es_un_verbo_de_banco_con_armado_fisico(self):
    spec = COMMANDS["torque_mode"]
    assert spec.mode_min == Mode.BENCH
    assert spec.requiere_armado_banco

  @pytest.mark.parametrize("modo", [1, 2, 3])
  def test_los_tres_modos_que_mueven_el_volante_van_por_el_verbo_de_banco(self, modo):
    c = _comandos(_ParamsFalsos())
    payload = f'{{"steer_torque_mode": {modo}, "apply_target": "curvature", "source": "app"}}'
    verbo, _ = c._v1_steer_torque_mode(payload)
    assert verbo == "torque_mode"

  def test_el_modo_0_no_pasa_por_el_verbo_de_banco(self):
    """Si apagar exigiera banco, un TEST MAX armado por error no se podria apagar."""
    c = _comandos(_ParamsFalsos({"SteerTorqueMode": 2}, desconocidos={"OrbitBenchArmed"}))
    assert c._v1_steer_torque_mode('{"steer_torque_mode": 0, "source": "app"}') == ("disarm_all", {})


# ------------------------------------------------------------------- punto 3

class _StopFalso:
  """Doble de threading.Event que no duerme: el backoff de 1 s del loop no
  aporta nada al test."""

  def __init__(self):
    self._set = False

  def is_set(self):
    return self._set

  def set(self):
    self._set = True

  def wait(self, timeout=None):
    return self._set


class _SubMasterFalso:
  def __init__(self, canales):
    self.canales = list(canales)
    self.updated = dict.fromkeys(self.canales, False)
    self.updates = 0

  def update(self, timeout=0):
    self.updates += 1


class _SenderGuionado(CameraSender):
  """CameraSender construido SIN __init__ para poder ejecutar run() en un test.

  camera_type se sirve de un guion para simular el cambio de canal en caliente
  (hoy inalcanzable porque _normalize_camera_type rechaza 'driver' por privacidad,
  pero el fallo de run() es de la maquina de estados del canal y tiene que quedar
  cerrado igualmente).
  """

  def __init__(self, guion):
    self._guion = list(guion)
    self.stop_event = _StopFalso()
    self._active_channel = None
    self._thumbnail_channels = {'road': 'jetsonThumbnail', 'driver': 'driverThumbnail'}
    self.params = _ParamsFalsos()
    self.zmq_client = None
    self.sending_enabled = False
    self.interval_seconds = 1.0
    self.last_sent = 0
    self.frame_count = 0
    self.error_count = 0
    self.consecutive_errors = 0
    self.max_backoff = 60.0
    self.dongle_id = "dongletest"
    self.debug_enabled = False
    self._last_debug_check = 0

  @property
  def camera_type(self):
    if not self._guion:
      self.stop_event.set()
      return 'road'
    return self._guion.pop(0)


class TestCameraSenderCanalRoto:

  def test_volver_al_canal_anterior_tras_un_submaster_fallido(self, monkeypatch):
    """road -> driver (SubMaster lanza) -> road.

    Sin `or sm is None`, la tercera vuelta se saltaba la creacion porque
    _active_channel seguia siendo 'jetsonThumbnail', y el sm.update() de fuera
    del try reventaba con AttributeError matando el hilo.
    """
    creados = []

    def _factory(canales):
      creados.append(canales[0])
      if canales[0] == 'driverThumbnail':
        raise RuntimeError("no hay driverThumbnail en este build")
      return _SubMasterFalso(canales)

    s = _SenderGuionado(['road', 'driver', 'road'])
    monkeypatch.setattr(camera_sender.messaging, 'SubMaster', _factory)
    s.run()  # no debe lanzar

    assert creados == ['jetsonThumbnail', 'driverThumbnail', 'jetsonThumbnail']
    assert s._active_channel == 'jetsonThumbnail'


# ------------------------------------------------------------------- punto 4

class TestPrivacidadCamaraCabina:

  def test_driver_no_es_un_tipo_valido(self):
    """El chip 'Conductor' de la app no puede encender el habitaculo en vivo sin
    confirmacion fisica en la pantalla del comma."""
    assert CameraSender._normalize_camera_type(None, 'driver') is None

  def test_wide_sigue_cayendo_a_road(self):
    assert CameraSender._normalize_camera_type(None, 'wide') == 'road'

  def test_road_sigue_valido(self):
    assert CameraSender._normalize_camera_type(None, 'road') == 'road'

  def test_apply_config_ignora_driver_y_no_toca_camera_type(self):
    s = CameraSender.__new__(CameraSender)
    s.camera_type = 'road'
    s.sending_enabled = True
    s.interval_seconds = 2.0
    s._save_config = lambda: None
    s.apply_config({"camera_type": "driver"})
    assert s.camera_type == 'road'


# ------------------------------------------------------------------- punto 7

def _decidir_izq(payload):
  return MQTTComandos.decidir_lane_change(payload, "ForceLaneChangeLeft")


class TestListaBlancaLaneChange:

  def test_json_de_la_app_activa(self):
    assert _decidir_izq('{"ForceLaneChangeLeft": true}') == MQTTComandos.LC_ACTIVAR

  def test_json_de_la_app_cancela(self):
    assert _decidir_izq('{"ForceLaneChangeLeft": false}') == MQTTComandos.LC_CANCELAR

  @pytest.mark.parametrize("payload", ['false', ' FALSE ', 'False'])
  def test_string_plano_false_cancela(self, payload):
    """Bajar autoridad nunca se descarta (diseno seccion 2)."""
    assert _decidir_izq(payload) == MQTTComandos.LC_CANCELAR

  def test_string_plano_true_es_toggle(self):
    assert _decidir_izq('true') == MQTTComandos.LC_TOGGLE

  @pytest.mark.parametrize("payload", ['0', '1', '[]', '["ForceLaneChangeLeft"]', '"x"', 'null'])
  def test_json_valido_que_no_es_dict_se_descarta(self, payload):
    """0, [] y "x" son JSON validos: antes dejaban explicit=None, caian al
    fallback, no eran "false" y terminaban en el else que ACTIVA el giro."""
    assert _decidir_izq(payload) is None

  @pytest.mark.parametrize("payload", ['{"foo": 1}', '{"ForceLaneChangeRight": true}'])
  def test_dict_sin_la_clave_se_descarta(self, payload):
    assert _decidir_izq(payload) is None

  @pytest.mark.parametrize("valor", ['"false"', '"0"', '0', '1', 'null', '"true"'])
  def test_dict_con_valor_no_booleano_se_descarta(self, valor):
    """bool("false") es True: por eso el valor tiene que ser bool de verdad."""
    assert _decidir_izq('{"ForceLaneChangeLeft": ' + valor + '}') is None

  @pytest.mark.parametrize("payload", ['lorem ipsum', '{', '<html>', 'tleft'])
  def test_basura_se_descarta(self, payload):
    assert _decidir_izq(payload) is None


class TestTraduccionLaneChange:
  """El dispatch v1 ya no escribe ForceLaneChange*: traduce el payload a un verbo v2.

  Aqui se fija la TRADUCCION. Que el verbo se aplique de verdad -- y solo con los gates en
  verde, en modo maniobra y con el reloj en hora -- esta en test_mando_v1_por_router.py.
  """

  def test_payload_basura_no_produce_ningun_verbo(self):
    c = _comandos(_ParamsFalsos())
    assert c._v1_lane_change('{"foo": 1}', "ForceLaneChangeLeft", "ForceLaneChangeRight", "left") is None

  def test_json_true_es_lane_change(self):
    c = _comandos(_ParamsFalsos({"ForceLaneChangeRight": True}))
    assert c._v1_lane_change('{"ForceLaneChangeLeft": true}', "ForceLaneChangeLeft",
                             "ForceLaneChangeRight", "left") == ("lane_change", {"direction": "left"})

  def test_la_cancelacion_por_string_plano_es_disarm_all(self):
    """Bajar autoridad tiene UN verbo, y es el unico que ningun gate puede bloquear."""
    c = _comandos(_ParamsFalsos({"ForceLaneChangeLeft": True}))
    assert c._v1_lane_change('false', "ForceLaneChangeLeft", "ForceLaneChangeRight", "left") == \
      ("disarm_all", {})

  def test_la_cancelacion_por_json_es_disarm_all(self):
    c = _comandos(_ParamsFalsos({"ForceLaneChangeRight": True}))
    assert c._v1_lane_change('{"ForceLaneChangeRight": false}', "ForceLaneChangeRight",
                             "ForceLaneChangeLeft", "right") == ("disarm_all", {})

  def test_toggle_cancela_si_el_opuesto_estaba_armado(self):
    c = _comandos(_ParamsFalsos({"ForceLaneChangeRight": True}))
    assert c._v1_lane_change('true', "ForceLaneChangeLeft", "ForceLaneChangeRight", "left") == \
      ("disarm_all", {})

  def test_toggle_activa_si_no_habia_nada_armado(self):
    c = _comandos(_ParamsFalsos())
    assert c._v1_lane_change('true', "ForceLaneChangeRight", "ForceLaneChangeLeft", "right") == \
      ("lane_change", {"direction": "right"})


def _up(payload):
  return MQTTComandos.acepta_paso_velocidad(payload, "speed_up", MQTTComandos.SPEED_UP_PLANOS)


def _down(payload):
  return MQTTComandos.acepta_paso_velocidad(payload, "speed_down", MQTTComandos.SPEED_DOWN_PLANOS)


class TestListaBlancaPasoDeVelocidad:

  @pytest.mark.parametrize("payload", ['1', '+1', 'true', ' TRUE '])
  def test_formatos_planos_subir(self, payload):
    assert _up(payload) is True

  @pytest.mark.parametrize("payload", ['1', '-1', 'true'])
  def test_formatos_planos_bajar(self, payload):
    assert _down(payload) is True

  def test_json_de_la_app(self):
    assert _up('{"speed_up": true, "timestamp": 1}') is True
    assert _down('{"speed_down": true, "timestamp": 1}') is True

  def test_json_con_la_clave_a_false_se_descarta(self):
    assert _up('{"speed_up": false}') is False
    assert _down('{"speed_down": false}') is False

  def test_verbo_ajeno_se_descarta(self):
    assert _up('{"speed_down": true}') is False
    assert _down('{"speed_up": true}') is False

  @pytest.mark.parametrize("payload", ['0', '-1', 'false', '[]', '"1"', 'lorem', '{', '{"foo": 1}'])
  def test_basura_se_descarta(self, payload):
    """Antes 'aceptamos cualquier payload como valido': el AttributeError de
    data.get sobre un no-dict caia en un except que ACTIVABA el paso."""
    assert _up(payload) is False

  def test_la_basura_no_produce_ningun_verbo(self):
    c = _comandos(_ParamsFalsos())
    assert c._v1_paso_velocidad('lorem ipsum', "speed_up", MQTTComandos.SPEED_UP_PLANOS, +1) is None
    assert c._v1_paso_velocidad('{"foo": 1}', "speed_down", MQTTComandos.SPEED_DOWN_PLANOS, -1) is None

  def test_el_formato_valido_se_traduce_a_cruise_delta_con_su_signo(self):
    """La magnitud sale de orbit_speed_increment y se acota al tope por orden del verbo
    (+-5 km/h): por la puerta v1 no se puede pedir mas que por la v2."""
    c = _comandos(_ParamsFalsos({"orbit_speed_increment": 3.0}))
    assert c._v1_paso_velocidad('{"speed_up": true}', "speed_up", MQTTComandos.SPEED_UP_PLANOS, +1) == \
      ("cruise_delta", {"delta_kph": 3.0})
    assert c._v1_paso_velocidad('-1', "speed_down", MQTTComandos.SPEED_DOWN_PLANOS, -1) == \
      ("cruise_delta", {"delta_kph": -3.0})

  def test_un_incremento_viejo_de_disco_no_da_mas_autoridad_de_la_declarada(self):
    c = _comandos(_ParamsFalsos({"orbit_speed_increment": 20.0}))
    assert c._v1_paso_velocidad('1', "speed_up", MQTTComandos.SPEED_UP_PLANOS, +1) == \
      ("cruise_delta", {"delta_kph": 5.0})
