"""Configuracion deseada vs reportada (seccion 8 del diseno v2).

Lo que se comprueba aqui es lo que hoy no existe y por eso hay TRES fuentes de verdad
divergentes (Params en el coche, tablas en el backend, SharedPreferences en el movil):

    El sobre ......................... {version, ts_ms, source, values}, epoch ms ENTERO
    Resolucion ....................... gana la version mas alta; EMPATE a favor de comma_ui
    Vocabulario cerrado .............. una clave que no esta en el catalogo se rechaza con
                                       motivo, no se escribe "por si acaso"
    jetson_ip acotada ................ el agujero conocido: quien reescribia ese campo
                                       decidia DE QUE MAQUINA vienen los offsets de
                                       direccion del modo 3. Ahora solo rango privado
    Nada de actuadores ............... steer_mode y steer_apply_target son SOLO REPORTE:
                                       moverlos es el verbo torque_mode, con su gate y ACK
    Privacidad no se manda en remoto . privacy_mute tambien es SOLO REPORTE, al reves: la
                                       seccion 9 lo declara innegociable sin red
    El topic viejo murio ............. telemetry_config/<dongle>/jetson_config ni se
                                       suscribe ni se atiende
    Tipos nativos .................... plan_aplicacion entrega lo que Params.put EXIGE
"""
import json

import pytest

from openpilot.orbit import config_v2 as cfg2

T0 = 1_700_000_000_000
DONGLE = "0123456789abcdef"


def _json(**campos):
  base = {"version": 1, "ts_ms": T0, "source": "backend", "values": {}}
  base.update(campos)
  return json.dumps(base)


# ---------------------------------------------------------------------------- el sobre

def test_el_sobre_minimo_se_parsea():
  s = cfg2.parse_sobre(_json(version=7, values={"jpeg_quality": 80}))
  assert (s.version, s.ts_ms, s.source) == (7, T0, "backend")
  assert s.values == {"jpeg_quality": 80}


@pytest.mark.parametrize("payload", [
  "", "   ", "no soy json", "[]", '"texto"', "{}",
  '{"version":"7","ts_ms":1,"source":"backend","values":{}}',     # version como string
  '{"version":7,"ts_ms":"1","source":"backend","values":{}}',     # ts_ms como string
  '{"version":7,"ts_ms":"2026-08-23T10:00:00Z","source":"backend","values":{}}',  # ISO-8601
  '{"version":-1,"ts_ms":1,"source":"backend","values":{}}',
  '{"version":7,"ts_ms":1,"source":"","values":{}}',
  '{"version":7,"ts_ms":1,"source":"backend"}',                   # sin values
  '{"version":7,"ts_ms":1,"source":"backend","values":[]}',       # values no es objeto
  '{"version":true,"ts_ms":1,"source":"backend","values":{}}',    # bool NO es int aqui
])
def test_un_sobre_mal_formado_no_se_parsea(payload):
  """El contrato tiene UN formato de instante: epoch ms ENTERO (seccion 3.2). Hoy el campo
  temporal viaja como int, como string y como ISO-8601 en el mismo topic; eso se acaba
  aqui, en el parser, no en cada consumidor."""
  assert cfg2.parse_sobre(payload) is None


def test_un_desired_que_dice_ser_comma_ui_se_rechaza():
  """`comma_ui` es la fuente que gana los EMPATES. Si se aceptase del cable, cualquiera que
  publique en el broker abierto (D1) podria empatar la version del coche y ganarle."""
  assert cfg2.parse_sobre(_json(source="comma_ui")) is None
  # ...y sin embargo se relee bien cuando es este proceso quien lo guardo en Params.
  assert cfg2.parse_sobre(_json(source="comma_ui"), remoto=False) is not None


def test_un_sobre_enorme_no_se_parsea():
  """El parseo corre en el hilo de RED de paho: un handler lento se come el PINGRESP."""
  gordo = json.dumps({"version": 1, "ts_ms": T0, "source": "backend",
                      "values": {"jetson_ip": "1" * (cfg2.MAX_BYTES_SOBRE + 10)}})
  assert cfg2.parse_sobre(gordo) is None


def test_el_sobre_va_y_vuelve_igual():
  s = cfg2.Sobre(version=3, ts_ms=T0, source="backend", values={"jpeg_quality": 80})
  ida = cfg2.parse_sobre(s.a_json())
  assert (ida.version, ida.ts_ms, ida.source, ida.values) == (3, T0, "backend", {"jpeg_quality": 80})
  assert json.loads(s.a_json())["v"] == cfg2.CFG_VERSION


# -------------------------------------------------------------------------- resolucion

def _s(version, source, **values):
  return cfg2.Sobre(version=version, ts_ms=T0, source=source, values=values)


def test_gana_la_version_mas_alta():
  assert cfg2.gana(_s(5, "backend"), _s(4, "comma_ui")) is True
  assert cfg2.gana(_s(3, "backend"), _s(4, "comma_ui")) is False
  assert cfg2.gana(_s(1, "backend"), None) is True
  assert cfg2.gana(None, _s(1, "backend")) is False


def test_el_empate_lo_gana_el_coche():
  """"El coche siempre puede corregir en local" no es un detalle de estilo: es lo unico
  que garantiza que alguien delante del vehiculo pueda deshacer un ajuste sin pedirle
  permiso a una red que puede no existir."""
  assert cfg2.gana(_s(5, "comma_ui"), _s(5, "backend")) is True
  assert cfg2.gana(_s(5, "backend"), _s(5, "comma_ui")) is False


def test_un_retenido_reentregado_no_vuelve_a_aplicarse():
  """El broker re-entrega cfg/desired en CADA reconexion. Misma version y misma fuente no
  es nada nuevo."""
  assert cfg2.gana(_s(5, "backend"), _s(5, "backend")) is False


def test_un_cambio_local_sube_por_encima_de_los_dos():
  assert cfg2.siguiente_version(_s(9, "backend"), _s(4, "comma_ui")) == 10
  assert cfg2.siguiente_version(None, None) == 1
  s = cfg2.sobre_local({"jpeg_quality": 80}, anteriores=(_s(9, "backend"),))
  assert (s.version, s.source) == (10, cfg2.FUENTE_COMMA_UI)


# -------------------------------------------------------------------------- validacion

@pytest.mark.parametrize("ip", ["192.168.1.50", "10.0.0.7", "172.16.3.4", "127.0.0.1", "169.254.1.1", ""])
def test_una_ip_de_red_local_vale(ip):
  ok, mal = cfg2.valida({"jetson_ip": ip})
  assert mal == {} and ok == {"jetson_ip": ip}


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.2.3.4", "203.0.113.9", "100.64.0.1", "192.0.2.5"])
def test_una_ip_publica_no_vale(ip):
  """EL AGUJERO CONOCIDO. jetson_ip decide DE QUE MAQUINA llega JetsonObstaclePulse, es
  decir de que maquina vienen los offsets de direccion del modo 3 (COMMA+JETSON), que es el
  modo de producto y que no exige armado de banco cuando se elige en la pantalla del comma.
  El handler viejo escribia la cadena que llegara, sin mirarla."""
  ok, mal = cfg2.valida({"jetson_ip": ip})
  assert ok == {} and mal == {"jetson_ip": cfg2.MOT_RANGO}


@pytest.mark.parametrize("ip", ["no soy una ip", "192.168.1.999", "0.0.0.0", "::1", 5, None, True])
def test_lo_que_ni_siquiera_es_una_ip_no_vale(ip):
  ok, mal = cfg2.valida({"jetson_ip": ip})
  assert ok == {} and set(mal) == {"jetson_ip"}


def test_una_clave_desconocida_se_rechaza_con_motivo():
  """Vocabulario CERRADO. Y con motivo: si el rechazo fuera mudo, la app se quedaria en
  "aplicando..." para siempre."""
  ok, mal = cfg2.valida({"jetson_ip": "10.0.0.1", "haz_lo_que_quieras": 1})
  assert ok == {"jetson_ip": "10.0.0.1"}
  assert mal == {"haz_lo_que_quieras": cfg2.MOT_DESCONOCIDA}


@pytest.mark.parametrize("clave", ["steer_mode", "steer_apply_target"])
def test_el_volante_no_es_configuracion(clave):
  """Cambiar el modo de torque MUEVE EL VOLANTE (el modo 1 se lo da a la Jetson, el 2 pone
  par maximo, el 3 suma offsets de esquive). Eso es el verbo torque_mode: modo banco,
  armado FISICO en la pantalla y ACK. Por el bus de configuracion no se pasa."""
  valor = 2 if clave == "steer_mode" else "torque"
  ok, mal = cfg2.valida({clave: valor})
  assert ok == {} and mal == {clave: cfg2.MOT_SOLO_REPORTE}
  assert clave in cfg2.CLAVES_SOLO_REPORTE


def test_la_privacidad_no_se_apaga_en_remoto():
  """Al reves que el volante y por el mismo principio: la seccion 9 declara innegociable
  que el interruptor funcione sin red y con el movil apagado. Si el backend pudiera
  escribirlo, dejaria de ser una garantia."""
  ok, mal = cfg2.valida({"privacy_mute": False})
  assert ok == {} and mal == {"privacy_mute": cfg2.MOT_SOLO_REPORTE}


@pytest.mark.parametrize("valor,motivo", [
  ("true", cfg2.MOT_TIPO), (1, cfg2.MOT_TIPO), (0, cfg2.MOT_TIPO), (None, cfg2.MOT_TIPO),
])
def test_un_bool_tiene_que_ser_un_bool(valor, motivo):
  """En este arbol un `bool('false')` acabo disparando un cambio de carril. Aqui la cadena
  "true" y el entero 1 se rechazan, no se interpretan."""
  ok, mal = cfg2.valida({"jetson_enabled": valor})
  assert ok == {} and mal == {"jetson_enabled": motivo}
  assert cfg2.valida({"jetson_enabled": True}) == ({"jetson_enabled": True}, {})


def test_un_entero_no_acepta_un_bool():
  """isinstance(True, int) es True en Python: sin rechazo explicito, `true` valdria 1."""
  ok, mal = cfg2.valida({"jpeg_quality": True})
  assert ok == {} and mal == {"jpeg_quality": cfg2.MOT_TIPO}


@pytest.mark.parametrize("valor,motivo", [(9, cfg2.MOT_RANGO), (96, cfg2.MOT_RANGO), (80, None)])
def test_los_rangos_se_respetan(valor, motivo):
  ok, mal = cfg2.valida({"jpeg_quality": valor})
  assert mal.get("jpeg_quality") == motivo
  assert ("jpeg_quality" in ok) is (motivo is None)


def test_los_puertos_privilegiados_no_valen():
  ok, mal = cfg2.valida({"jetson_img_port": 22})
  assert ok == {} and mal == {"jetson_img_port": cfg2.MOT_RANGO}


def test_los_enum_solo_aceptan_su_lista():
  assert cfg2.valida({"telemetry_profile": "normal"}) == ({"telemetry_profile": "normal"}, {})
  ok, mal = cfg2.valida({"telemetry_profile": "turbo"})
  assert ok == {} and mal == {"telemetry_profile": cfg2.MOT_VALOR}


@pytest.mark.parametrize("ct", ["driver", "wide"])
def test_la_camara_solo_acepta_la_que_existe(ct):
  """'driver': mismo criterio que CameraSender._normalize_camera_type, que ya lo rechaza --
  encender el habitaculo en vivo desde la app es un tratamiento con base juridica propia
  (§15). 'wide': loggerd no publica su thumbnail y CameraSender la convierte en 'road', asi
  que aceptarla dejaria a la app con un deseado que el reportado nunca alcanza. En los dos
  casos el motivo VIAJA en `reported` en vez de morir en un log del coche."""
  ok, mal = cfg2.valida({"camera_type": ct})
  assert ok == {} and mal == {"camera_type": cfg2.MOT_VALOR}
  assert cfg2.valida({"camera_type": "road"}) == ({"camera_type": "road"}, {})


def test_un_no_finito_no_entra():
  """json.dumps emite NaN/Infinity, que NO son JSON valido (RFC 8259): el consumidor
  revienta con el mensaje entero."""
  ok, mal = cfg2.valida({"speed_increment_kph": float("nan")})
  assert ok == {} and mal == {"speed_increment_kph": cfg2.MOT_VALOR}


def test_los_perfiles_no_divergen_del_motor_de_telemetria():
  """El vocabulario esta duplicado a proposito (config_v2 no importa el motor). Que no
  diverja se comprueba, no se confia."""
  from openpilot.orbit import telemetria_v1 as tel2
  assert set(cfg2.PERFILES) == {tel2.PERFIL_AHORRO, tel2.PERFIL_NORMAL, tel2.PERFIL_DIAG}
  for p in cfg2.PERFILES:
    assert tel2.perfil_valido(p) == p


# --------------------------------------------------------------------------- el reparto

def test_el_plan_reparte_por_destino_y_con_tipo_nativo():
  """Params.put EXIGE el tipo nativo del param: put("1") sobre un INT lanza TypeError y el
  ajuste se pierde en silencio."""
  ok, _ = cfg2.valida({"jetson_ip": "10.0.0.1", "jpeg_quality": 80,
                       "telemetry_profile": "ahorro", "speed_increment_kph": 3,
                       "carState_toggle": True, "camera_enabled": False})
  plan = cfg2.plan_aplicacion(ok)
  assert plan.jetson == {"jetson_ip": "10.0.0.1", "jpeg_quality": 80}
  assert plan.camara == {"image_sending_enabled": False}
  assert plan.params["OrbitTelemetryProfile"] == "ahorro"
  assert isinstance(plan.params["orbit_speed_increment"], float)
  assert plan.params["carState_toggle"] is True


def test_el_plan_nunca_toca_una_clave_de_solo_reporte():
  """Doble barrera: aunque alguien saltase el validador, el plan no las reparte."""
  plan = cfg2.plan_aplicacion({"steer_mode": 2, "privacy_mute": False, "jpeg_quality": 50})
  assert plan.params == {} and plan.camara == {}
  assert plan.jetson == {"jpeg_quality": 50}


def test_el_catalogo_declara_donde_aterriza_cada_clave():
  for nombre, clave in cfg2.CLAVES.items():
    assert clave.destino in (cfg2.DEST_PARAM, cfg2.DEST_JETSON, cfg2.DEST_CAMARA), nombre
    assert clave.dest_nombre and clave.desc, nombre
    if clave.destino == cfg2.DEST_PARAM:
      assert clave.tipo_param in ("bool", "int", "float", "str"), nombre


# ------------------------------------------------------------------ config_jetson.json

def test_la_escritura_del_json_es_atomica_y_no_reescribe_si_no_cambia(tmp_path):
  ruta = str(tmp_path / "config_jetson.json")
  (tmp_path / "config_jetson.json").write_text(json.dumps({"jetson_ip": "", "jpeg_quality": 10}))

  cambio, final = cfg2.escribir_config_jetson(ruta, {"jetson_ip": "10.0.0.1"})
  assert cambio is True
  assert final["jetson_ip"] == "10.0.0.1" and final["jpeg_quality"] == 10
  assert "_version" in final

  cambio2, _ = cfg2.escribir_config_jetson(ruta, {"jetson_ip": "10.0.0.1"})
  assert cambio2 is False, "sin cambio de campo no se toca el disco"
  assert not (tmp_path / "config_jetson.json.tmp").exists()
  assert cfg2.leer_config_jetson(ruta)["jetson_ip"] == "10.0.0.1"


def test_un_json_ilegible_se_lee_como_vacio(tmp_path):
  ruta = str(tmp_path / "roto.json")
  (tmp_path / "roto.json").write_text("{no soy json")
  assert cfg2.leer_config_jetson(ruta) == {}
  assert cfg2.leer_config_jetson(str(tmp_path / "no_existe.json")) == {}


# ------------------------------------------------------------------------------ el bus

def test_el_buzon_guarda_uno_y_se_vacia_al_tomarlo():
  bus = cfg2.BusConfig()
  assert bus.recibir(_json(version=1)) is True
  assert bus.recibir(_json(version=2)) is True
  s = bus.tomar()
  assert s.version == 2, "cfg/desired es ESTADO retenido: el bueno es el ultimo"
  assert bus.tomar() is None


def test_el_buzon_no_deja_que_uno_viejo_pise_al_nuevo():
  bus = cfg2.BusConfig()
  assert bus.recibir(_json(version=9)) is True
  assert bus.recibir(_json(version=2)) is False
  assert bus.tomar().version == 9


def test_el_buzon_no_lanza_nunca():
  """Corre en el callback de paho: una excepcion ahi mata el hilo de red en silencio."""
  bus = cfg2.BusConfig()
  for basura in (None, b"\xff\xfe", "", "{", 12345, ["lista"]):
    assert bus.recibir(basura) is False
  assert bus.tomar() is None
  assert bus.estado()["descartados"] == 6


def test_el_buzon_es_unico_por_proceso():
  assert cfg2.get_bus() is cfg2.get_bus()


# --------------------------------------------------------- el topic viejo esta muerto

def test_el_topic_de_jetson_config_ni_se_suscribe_ni_se_atiende():
  """telemetry_config/<dongle>/jetson_config aceptaba RETENIDO, no pasaba por el
  CommandRouter y reescribia jetson_ip campo a campo sin validar. Ya no existe: ni handler,
  ni suscripcion, ni permiso de retenido."""
  from openpilot.orbit.mqtt_comandos import MQTTComandos
  import inspect
  assert not hasattr(MQTTComandos, "handle_jetson_config")
  assert "/jetson_config" not in MQTTComandos.RETAIN_PERMITIDO
  fuente = inspect.getsource(MQTTComandos._on_connect)
  # Solo las lineas de CODIGO: el comentario que explica por que murio si lo nombra.
  codigo = [l.split("#")[0] for l in fuente.split("\n")]
  assert not any("jetson_config" in l for l in codigo), "sigue en la lista de suscripcion"
  assert "TOPIC_CFG_DESIRED" in fuente, "falta la suscripcion a cfg/desired"


def test_el_descriptor_declara_el_contrato_entero():
  d = cfg2.descriptor()
  assert d["topics"]["desired"] == "orbit/v2/cfg/desired/{}"
  assert d["topics"]["reported"] == "orbit/v2/cfg/reported/{}"
  assert set(d["claves"]) == set(cfg2.CLAVES)
  # Serializable: lo consumen el backend y la app.
  assert json.loads(json.dumps(d))["v"] == cfg2.CFG_VERSION


# ------------------------------------------------- el empate contra TODO lo que hay (B1)

def test_el_entrante_tiene_que_ganarle_a_LOS_DOS_sobres_locales():
  """El coche no tiene UN sobre local, tiene dos: el ultimo `desired` aceptado (siempre
  source backend, porque parse_sobre(remoto=True) no acepta otra cosa) y el ultimo
  `reported` publicado (siempre comma_ui, que es la palabra del coche sobre lo que HAY).

  Comparar solo contra el `desired` dejaba la regla del empate SIN EFECTO: el empate nunca
  se llegaba a evaluar contra un comma_ui, asi que lo ganaba el backend.
  """
  reportado = _s(2, "comma_ui", jpeg_quality=55)   # alguien lo corrigio en la pantalla
  deseado = _s(1, "backend", jpeg_quality=80)

  # El backend, que aun no ha ingerido ese reported, reemite justo la version que empata.
  entrante = _s(2, "backend", jpeg_quality=80)
  assert cfg2.gana(entrante, deseado) is True, "contra el desired solo, gana: ese es el fallo"
  assert cfg2.gana_a_todos(entrante, deseado, reportado) is False

  # Y en cuanto ingiere el reported y sube de version, gana el backend, como debe.
  assert cfg2.gana_a_todos(_s(3, "backend", jpeg_quality=80), deseado, reportado) is True


def test_un_desired_retrasado_no_le_gana_a_un_reported_mas_alto():
  """`_siguiente_version` del backend es max(deseada, reportada)+1 sobre lo que EL sabe:
  mientras no haya ingerido varios `reported` seguidos emite versiones por debajo de la
  del coche."""
  assert cfg2.gana_a_todos(_s(3, "backend"), _s(2, "backend"), _s(6, "comma_ui")) is False


def test_gana_a_todos_con_un_hueco_no_se_lo_inventa():
  """Un coche que aun no ha publicado `reported` no tiene con que comparar: None no puede
  bloquear ni conceder nada por si mismo."""
  assert cfg2.gana_a_todos(_s(1, "backend"), None, None) is True
  assert cfg2.gana_a_todos(None, None, None) is False


# ----------------------------------------------- los rechazos hablan del CONTRATO (D4)

def test_un_rechazo_viaja_con_la_clave_del_contrato_no_con_la_del_destino():
  """`reported.rechazos` lo resuelve la app contra el vocabulario del contrato y TIRA lo
  que no reconoce; el backend lo cruza contra `desired.values`, que tambien esta en claves
  de contrato. Un rechazo con el nombre del destino no llega a nadie."""
  assert cfg2.clave_de_destino(cfg2.DEST_PARAM, "OrbitTelemetryProfile") == "telemetry_profile"
  assert cfg2.clave_de_destino(cfg2.DEST_PARAM, "orbit_speed_increment") == "speed_increment_kph"
  assert cfg2.clave_de_destino(cfg2.DEST_CAMARA, "image_sending_enabled") == "camera_enabled"
  assert cfg2.clave_de_destino(cfg2.DEST_CAMARA, "send_frequency_seconds") == "camera_interval_s"
  # Las que ya coincidian siguen igual, y una desconocida no se inventa una traduccion.
  assert cfg2.clave_de_destino(cfg2.DEST_JETSON, "jetson_ip") == "jetson_ip"
  assert cfg2.clave_de_destino(cfg2.DEST_PARAM, "NoExiste") == "NoExiste"


def test_todo_rechazo_emitible_es_una_clave_del_contrato_o_un_motivo_conocido():
  """Barrido: ninguna traduccion de destino->contrato puede quedarse fuera del catalogo."""
  for clave in cfg2.CLAVES.values():
    assert cfg2.clave_de_destino(clave.destino, clave.dest_nombre) in cfg2.CLAVES
  assert cfg2.MOT_NO_APLICADO in cfg2.MOTIVOS_DE_APLICACION
  assert cfg2.MOT_SIN_CAMARA in cfg2.MOTIVOS_DE_APLICACION
  # Los del contrato NO son de aplicacion: su causa es el sobre, no el destino.
  for motivo in (cfg2.MOT_DESCONOCIDA, cfg2.MOT_SOLO_REPORTE, cfg2.MOT_TIPO,
                 cfg2.MOT_RANGO, cfg2.MOT_VALOR):
    assert motivo not in cfg2.MOTIVOS_DE_APLICACION


def test_cada_motivo_declara_de_que_depende_su_causa():
  """Un rechazo sin poda es un VETO PERMANENTE: el backend no adopta las claves que salen
  en `reported.rechazos`, asi que un motivo cuya causa nadie sabe comprobar deja esa clave
  bloqueada para siempre. Por eso cada motivo cae en EXACTAMENTE un grupo, y el grupo es
  el que dice como se mira si la causa sigue viva:

    APLICACION -> la causa esta en el destino: muere cuando el valor pedido acaba puesto.
    VALOR      -> la causa es el valor pedido: muere cuando alguien corrige la clave EN
                  LOCAL, que es el caso que protege la regla del empate de §8.
    CLAVE      -> la causa es la clave, no el valor: no hay cambio local que la mate.
  """
  grupos = (cfg2.MOTIVOS_DE_APLICACION, cfg2.MOTIVOS_DE_VALOR, cfg2.MOTIVOS_DE_CLAVE)
  emitibles = {cfg2.MOT_DESCONOCIDA, cfg2.MOT_SOLO_REPORTE, cfg2.MOT_TIPO, cfg2.MOT_RANGO,
               cfg2.MOT_VALOR, cfg2.MOT_NO_APLICADO, cfg2.MOT_SIN_CAMARA}
  assert cfg2.MOTIVOS == emitibles, "hay un motivo fuera del catalogo"
  for motivo in emitibles:
    assert sum(motivo in g for g in grupos) == 1, f"{motivo} no cae en exactamente un grupo"


def test_valida_no_emite_ningun_motivo_sin_grupo():
  """Barrido por el otro lado: lo que el contrato puede rechazar de verdad."""
  malos = {"no_existe": 1, "steer_mode": 1, "jetson_ip": "8.8.8.8", "jpeg_quality": 9,
           "camera_enabled": "si", "telemetry_profile": "turbo",
           "speed_increment_kph": float("nan")}
  aceptados, rechazos = cfg2.valida(malos)
  assert aceptados == {}
  assert set(rechazos) == set(malos)
  assert set(rechazos.values()) <= cfg2.MOTIVOS
  # y ninguno de estos es de APLICACION: su causa es el sobre, no el destino
  assert not (set(rechazos.values()) & cfg2.MOTIVOS_DE_APLICACION)
