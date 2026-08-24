#!/usr/bin/env python3
"""Configuracion DESEADA vs REPORTADA (seccion 8 del diseno v2).

EL PROBLEMA QUE CIERRA

Hoy la misma configuracion vive en TRES sitios que no se hablan: Params en el coche,
tablas en el backend y SharedPreferences en el movil. No hay reconciliacion: cada lado
cree que el suyo es el bueno y el ultimo que escribe gana sin saber contra que. El puente
entre ellos son cuatro params-buzon (JetsonConfigMqttPayload, SteerTorqueModeMqttPayload,
JetsonObstacleApplyTargetMqttPayload, JetsonObstacleStatusMqttPayload) que la UI del comma
rellena y mqtt_envio_general vacia republicando el JSON tal cual, sin validar nada.

Aqui hay dos topics y un sobre:

    orbit/v2/cfg/desired/<dongle>    retenido, qos 1, lo publica SOLO el backend
    orbit/v2/cfg/reported/<dongle>   retenido, qos 1, lo publica el firmware TRAS APLICAR

    {"version": 17, "ts_ms": 1755960000000, "source": "backend",
     "values": {"jetson_ip": "192.168.1.50", "jpeg_quality": 80}}

Gana la version mas alta. EMPATE A FAVOR DE `comma_ui`: el coche siempre puede corregir en
local, porque es el unico lado que puede tener a alguien delante sin red.

EL AGUJERO CONCRETO QUE ESTO SUSTITUYE, Y HASTA DONDE LLEGA

`telemetry_config/<dongle>/jetson_config` estaba en la lista RETAIN_PERMITIDO de
mqtt_comandos, no pasaba por el CommandRouter y reescribia `jetson_ip` en
orbit/config_jetson.json. Ese campo decide DE QUE MAQUINA llega JetsonObstaclePulse, es
decir de que maquina vienen los offsets de direccion del modo 3 (COMMA+JETSON), que es el
modo de producto y que NO exige armado de banco cuando se elige en la pantalla del comma.
El propio docstring de handle_jetson_config lo documentaba y remitia a F4. Con este modulo
ese topic deja de estar suscrito: la IP solo entra por el sobre de configuracion.

Lo que esto SI mejora, comprobable linea a linea:

  1. `jetson_ip` y `comma_ip` pasan por _valida_ip: tienen que ser IPv4 de rango PRIVADO,
     loopback o link-local. Antes se escribia la cadena que viniera, sin mirarla (el
     handler viejo hacia `current_config[key] = data[key]` dentro de un for sobre la lista
     de campos). Una IP publica ya no se puede escribir por ningun camino remoto.
  2. La version es MONOTONA: un retenido viejo re-entregado en cada reconexion se
     descarta por version, no por un `_version` que ponia el propio emisor y que solo se
     comparaba dentro del JSON de la Jetson.
  3. Un sobre que dice `source: "comma_ui"` viniendo del cable se RECHAZA: es la unica
     fuente que gana los empates y no puede venir de fuera del coche.
  4. Las claves de ACTUADOR no son configuracion. `steer_mode` y `steer_apply_target` son
     de SOLO REPORTE: se publican para que la app pinte el estado real, y un `desired` que
     intente escribirlas se rechaza con motivo. Mover el volante sigue siendo un VERBO,
     con su modo, su gate y su ACK.
  5. `privacy_mute` es de SOLO REPORTE por el mismo motivo del reves: la seccion 9 declara
     innegociable que el interruptor local funcione sin red, y un backend comprometido no
     puede quitarlo a distancia.

Lo que esto NO hace, y conviene no confundir: **no autentica a nadie**. Mientras D1 siga
en pie (broker abierto, sin TLS, anonimo) cualquiera que conozca el dongle puede publicar
en `cfg/desired`. Lo que cambia es que ya no puede escribir CUALQUIER COSA: hay un
vocabulario cerrado, tipos, rangos y una version que no retrocede. El campo `sig` queda
reservado para el dia que D1 cambie.

DONDE SE PUEDE LLAMAR CADA COSA

  BusConfig.recibir()      RAM pura (parseo + un lock). Es lo UNICO que toca el callback
                           de paho, que es el hilo de RED: un handler lento se come el
                           PINGRESP y con el la conexion.
  BusConfig.tomar()        RAM pura. Hilo del loop ORBIT.
  leer_config_jetson()     TOCAN DISCO (flock + fsync + rename). Hilo del loop ORBIT,
  escribir_config_jetson() nunca paho y nunca nada que cuelgue de controlsd (100 Hz).
"""
import ipaddress
import json
import os
import threading
from dataclasses import dataclass, field
from types import MappingProxyType

from openpilot.common.swaglog import cloudlog
from openpilot.orbit.command_spec import ahora_epoch_ms

# ------------------------------------------------------------------------------- topics

TOPIC_CFG_DESIRED = "orbit/v2/cfg/desired/{}"
TOPIC_CFG_REPORTED = "orbit/v2/cfg/reported/{}"

# Version del contrato (seccion 3.2: el sobre lleva "v": 2).
CFG_VERSION = 2

# ------------------------------------------------------------------------------ fuentes

FUENTE_BACKEND = "backend"
FUENTE_COMMA_UI = "comma_ui"
FUENTE_ARRANQUE = "arranque"   # solo interna: el reported que se publica al conectar

# Fuentes que se aceptan EN EL CABLE dentro de un `desired`. `comma_ui` no esta: es la
# unica que gana los empates y solo la puede poner este proceso.
FUENTES_REMOTAS = frozenset({FUENTE_BACKEND})

# Un sobre de configuracion son unas pocas claves cortas. Cualquier cosa mayor que esto es
# ruido o un intento de que el parseo cueste tiempo en el hilo de red.
MAX_BYTES_SOBRE = 8 * 1024

# ------------------------------------------------------------------------------ destinos

DEST_PARAM = "param"      # Params del comma. put() EXIGE tipo nativo (ver `tipo_param`)
DEST_JETSON = "jetson"    # orbit/config_jetson.json
DEST_CAMARA = "camara"    # CameraSender.apply_config(), que tiene sus propios filtros


@dataclass(frozen=True)
class Clave:
  """Una clave configurable: que es, que valores acepta y donde aterriza.

  `escribible` False = SOLO REPORTE. Sale en `reported` para que la app pinte el estado
  real, y un `desired` que la traiga se rechaza con motivo en vez de aplicarse a medias.
  """
  nombre: str
  tipo: str                       # bool | int | float | enum | ip
  destino: str
  dest_nombre: str
  desc: str
  minimo: float | None = None
  maximo: float | None = None
  valores: tuple = ()
  escribible: bool = True
  tipo_param: str = ""            # tipo NATIVO que exige Params.put (bool|int|float|str)


def _c(nombre, tipo, destino, dest_nombre, desc, **kw) -> Clave:
  return Clave(nombre=nombre, tipo=tipo, destino=destino, dest_nombre=dest_nombre, desc=desc, **kw)


# Perfiles de telemetria (seccion 7). Se repiten aqui como literales a proposito: importar
# telemetria_v1 desde este modulo lo ataria al motor de telemetria, y este modulo lo usa
# tambien el hilo de mando, que no tiene nada que ver con ella. El test cruzado comprueba
# que no divergen.
PERFILES = ("ahorro", "normal", "diagnostico")

CLAVES = MappingProxyType({c.nombre: c for c in (
  # --- enlace con la Jetson (orbit/config_jetson.json). El agujero de §8.
  _c("jetson_enabled", "bool", DEST_JETSON, "jetson_enabled",
     "Enlace ZMQ con la Jetson encendido"),
  _c("jetson_ip", "ip", DEST_JETSON, "jetson_ip",
     "IP de la Jetson. SOLO rango privado/loopback/link-local: decide de que maquina vienen los offsets de direccion del modo 3"),
  _c("comma_ip", "ip", DEST_JETSON, "comma_ip",
     "IP del comma que la Jetson usa para responder. Mismo rango que jetson_ip"),
  _c("jetson_img_port", "int", DEST_JETSON, "jetson_img_port",
     "Puerto ZMQ de imagenes", minimo=1024, maximo=65535),
  _c("jetson_torque_port", "int", DEST_JETSON, "jetson_torque_port",
     "Puerto ZMQ de par", minimo=1024, maximo=65535),
  _c("jpeg_quality", "int", DEST_JETSON, "jpeg_quality",
     "Calidad JPEG de las imagenes que van a la Jetson", minimo=10, maximo=95),

  # --- telemetria y camara (seccion 9: esto se va del panel del comma a la app)
  _c("telemetry_profile", "enum", DEST_PARAM, "OrbitTelemetryProfile",
     "Perfil de telemetria v2: ahorro | normal | diagnostico",
     valores=PERFILES, tipo_param="str"),
  # `camera_type` solo admite "road" y no es una omision: loggerd publica el thumbnail
  # rapido UNICAMENTE desde la road cam, asi que CameraSender._normalize_camera_type
  # convierte "wide" en "road" (aceptarlo aqui dejaria a la app con un deseado que el
  # reportado nunca alcanza: "aplicando..." para siempre) y RECHAZA "driver", porque
  # encender el habitaculo en vivo desde el movil es un tratamiento con base juridica
  # propia (§15) y exige confirmacion fisica en la pantalla del comma.
  _c("camera_enabled", "bool", DEST_CAMARA, "image_sending_enabled",
     "Envio de imagenes de camara. El interruptor LOCAL de privacidad gana siempre"),
  _c("camera_interval_s", "int", DEST_CAMARA, "send_frequency_seconds",
     "Segundos entre imagenes", valores=(1, 2, 5, 10, 30, 60)),
  _c("camera_type", "enum", DEST_CAMARA, "camera_type",
     "Camara publicada. Hoy solo 'road' EXISTE, y ni 'wide' ni 'driver' son alias de ella",
     valores=("road",)),
  _c("speed_increment_kph", "float", DEST_PARAM, "orbit_speed_increment",
     "Paso de crucero en km/h. El consumidor lo acota ademas a [1,5], el tope por orden del verbo cruise_delta",
     minimo=1.0, maximo=50.0, tipo_param="float"),

  # --- los 8 toggles de telemetria v1 (seccion 9: se van a la app). El nombre de la clave
  # ES el nombre del param a proposito: una traduccion mas es una fuente de verdad mas.
  _c("carState_toggle", "bool", DEST_PARAM, "carState_toggle", "Canal v1 carState", tipo_param="bool"),
  _c("carControl_toggle", "bool", DEST_PARAM, "carControl_toggle", "Canal v1 carControl", tipo_param="bool"),
  _c("controlsState_toggle", "bool", DEST_PARAM, "controlsState_toggle", "Canal v1 controlsState", tipo_param="bool"),
  _c("liveCalibration_toggle", "bool", DEST_PARAM, "liveCalibration_toggle", "Canal v1 liveCalibration", tipo_param="bool"),
  _c("gpsLocationExternal_toggle", "bool", DEST_PARAM, "gpsLocationExternal_toggle", "Canal v1 gpsLocationExternal", tipo_param="bool"),
  _c("gpsLocation_toggle", "bool", DEST_PARAM, "gpsLocation_toggle", "Canal v1 gpsLocation", tipo_param="bool"),
  _c("drivingModelData_toggle", "bool", DEST_PARAM, "drivingModelData_toggle", "Canal v1 drivingModelData", tipo_param="bool"),
  _c("radarState_toggle", "bool", DEST_PARAM, "radarState_toggle", "Canal v1 radarState", tipo_param="bool"),

  # --- SOLO REPORTE. Ni el backend ni la app las escriben por aqui.
  _c("steer_mode", "int", DEST_PARAM, "SteerTorqueMode",
     "0 Comma · 1 Jetson · 2 TestMax · 3 Comma+Jetson. SOLO REPORTE: cambiarlo mueve el volante y es el VERBO torque_mode",
     minimo=0, maximo=3, escribible=False, tipo_param="int"),
  _c("steer_apply_target", "enum", DEST_PARAM, "JetsonObstacleApplyTarget",
     "Donde se suma el esquive del modo 3. SOLO REPORTE, por lo mismo que steer_mode",
     valores=("curvature", "torque"), escribible=False, tipo_param="str"),
  _c("privacy_mute", "bool", DEST_PARAM, "OrbitPrivacyMute",
     "Interruptor maestro LOCAL de privacidad. SOLO REPORTE: §9 lo declara innegociable sin red y quitarlo a distancia lo anularia",
     escribible=False, tipo_param="bool"),
)})

CLAVES_ESCRIBIBLES = frozenset(k for k, c in CLAVES.items() if c.escribible)
CLAVES_SOLO_REPORTE = frozenset(k for k, c in CLAVES.items() if not c.escribible)

# Motivos de rechazo. Son los que viajan en `reported.rechazos` y los que la app pinta.
#
# Los de arriba son del CONTRATO: la causa es el propio sobre `desired`, asi que se pueden
# recalcular de el en cualquier momento. Los de abajo son de APLICACION: el valor era
# valido, el contrato lo acepto y aun asi no aterrizo (Params lanzo, el JSON de la Jetson
# no se pudo escribir, no habia CameraSender). Su causa NO esta en el sobre sino en el
# destino, y por eso se comprueba de otra forma: la causa muere cuando el valor pedido
# acaba puesto de verdad.
MOT_DESCONOCIDA = "clave_desconocida"
MOT_SOLO_REPORTE = "solo_reporte"
MOT_TIPO = "tipo"
MOT_RANGO = "rango"
MOT_VALOR = "valor"

MOT_NO_APLICADO = "no_aplicado"
MOT_SIN_CAMARA = "sin_camera_sender"
MOTIVOS_DE_APLICACION = frozenset({MOT_NO_APLICADO, MOT_SIN_CAMARA})

# UN RECHAZO SIN PODA ES UN VETO PERMANENTE. `reported.rechazos` no es decorativo: el
# backend NO adopta las claves que salen ahi, asi que un rechazo que no muere nunca deja
# esa clave bloqueada para siempre -- el coche publica el valor bueno y el backend sigue
# sin poder tomarlo. Cada motivo tiene que declarar de que depende su causa para que se
# pueda comprobar si sigue viva; los de APLICACION ya lo hacian, los de contrato no.
#
# Los dos de abajo hablan del VALOR pedido: "8.8.8.8 esta fuera de rango" es un veredicto
# sobre ese valor, y deja de ser la ultima palabra sobre esa clave en cuanto alguien la
# corrige EN LOCAL, delante del coche. Esa correccion es exactamente el caso que protege la
# regla del empate de la seccion 8 ("el coche siempre puede corregir sin red"), asi que el
# rechazo tiene que morir con ella o el backend no adoptara jamas el valor corregido.
MOTIVOS_DE_VALOR = frozenset({MOT_TIPO, MOT_RANGO, MOT_VALOR})

# Estos dos NO hablan del valor sino de la CLAVE: `steer_apply_target` no se escribe por
# aqui aunque se pida con el valor perfecto, y una clave que no esta en el catalogo no
# existe se ponga lo que se ponga. No hay cambio local que pueda matarlos, asi que viven
# mientras viva el `desired` que los causo y solo los recalcula el `desired` siguiente.
MOTIVOS_DE_CLAVE = frozenset({MOT_DESCONOCIDA, MOT_SOLO_REPORTE})

MOTIVOS = MOTIVOS_DE_APLICACION | MOTIVOS_DE_VALOR | MOTIVOS_DE_CLAVE

# Indice inverso (destino, nombre_en_el_destino) -> nombre de CONTRATO.
_CLAVE_POR_DESTINO = MappingProxyType({(c.destino, c.dest_nombre): c.nombre for c in CLAVES.values()})


def clave_de_destino(destino: str, dest_nombre: str) -> str:
  """Nombre de CONTRATO de un destino. Es el unico que puede viajar en `rechazos`.

  `reported.rechazos` no lo lee nadie en el vocabulario de los destinos: la app resuelve
  cada clave contra el catalogo del contrato y TIRA lo que no reconoce, y el backend la
  cruza contra `desired.values`, que tambien esta en claves de contrato. Un rechazo que
  saliera como `OrbitTelemetryProfile` o `image_sending_enabled` no llegaria a ninguno de
  los dos: desapareceria en silencio, que es justo lo que el rechazo existe para evitar.

  Para la mayoria de claves el nombre coincide (los 8 toggles v1, todo lo de la Jetson) y
  por eso el fallo no se veia; donde NO coincide es en telemetry_profile,
  speed_increment_kph, camera_enabled y camera_interval_s.
  """
  return _CLAVE_POR_DESTINO.get((destino, dest_nombre), dest_nombre)


# --------------------------------------------------------------------------- validacion

# Redes desde las que se acepta una IP de enlace. Se enumeran a mano y no con
# `IPv4Address.is_private` a proposito: esa propiedad es "no globalmente enrutable" y ahi
# dentro caben tambien los rangos de DOCUMENTACION (192.0.2.0/24, 198.51.100.0/24,
# 203.0.113.0/24) y el CGNAT (100.64.0.0/10), que no son la LAN del coche.
_REDES_LOCALES = tuple(ipaddress.ip_network(r) for r in (
  "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",   # RFC 1918
  "127.0.0.0/8",                                     # loopback (Jetson en la misma caja)
  "169.254.0.0/16",                                  # link-local (cable directo sin DHCP)
))


def _valida_ip(valor):
  """IPv4 de la LAN del coche (_REDES_LOCALES). Cadena vacia = desconfigurar.

  Antes esto no existia: el handler viejo escribia la cadena que llegase. Una IP publica
  aqui significa que el enlace de par de la Jetson (modo 3) sale a internet, y ese enlace
  suma offsets de direccion.
  """
  if not isinstance(valor, str):
    return None, MOT_TIPO
  texto = valor.strip()
  if texto == "":
    return "", None            # desconfigurar es legitimo y es el valor de fabrica
  try:
    ip = ipaddress.ip_address(texto)
  except ValueError:
    return None, MOT_VALOR
  if ip.version != 4:
    return None, MOT_VALOR     # el resto del subsistema (ZMQ, config_jetson) es IPv4
  if ip.is_unspecified or ip.is_multicast:
    return None, MOT_VALOR
  if not any(ip in red for red in _REDES_LOCALES):
    return None, MOT_RANGO
  return str(ip), None


def _valida_uno(clave: Clave, valor):
  """(valor_normalizado, motivo). `motivo` None = aceptado.

  Los bool se exigen bool DE VERDAD: en este arbol ya hubo un `bool('false')` que
  disparaba un cambio de carril, y en Python `isinstance(True, int)` es True, asi que un
  int tiene que rechazar el bool explicitamente o `true` acabaria valiendo 1.
  """
  if clave.tipo == "bool":
    if not isinstance(valor, bool):
      return None, MOT_TIPO
    return valor, None

  if clave.tipo == "ip":
    return _valida_ip(valor)

  if clave.tipo == "enum":
    if not isinstance(valor, str):
      return None, MOT_TIPO
    return (valor, None) if valor in clave.valores else (None, MOT_VALOR)

  if clave.tipo == "int":
    if isinstance(valor, bool) or not isinstance(valor, int):
      return None, MOT_TIPO
    if clave.valores and valor not in clave.valores:
      return None, MOT_VALOR
    if clave.minimo is not None and valor < clave.minimo:
      return None, MOT_RANGO
    if clave.maximo is not None and valor > clave.maximo:
      return None, MOT_RANGO
    return valor, None

  if clave.tipo == "float":
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
      return None, MOT_TIPO
    num = float(valor)
    if num != num or num in (float("inf"), float("-inf")):
      return None, MOT_VALOR   # NaN/inf: json.dumps los emite como literales invalidos
    if clave.minimo is not None and num < clave.minimo:
      return None, MOT_RANGO
    if clave.maximo is not None and num > clave.maximo:
      return None, MOT_RANGO
    return num, None

  return None, MOT_TIPO


def valida(values: dict) -> tuple[dict, dict]:
  """(aceptados, rechazos). NUNCA lanza: un sobre malo no puede tumbar nada.

  Un sobre con una clave mala NO se descarta entero: se aplica lo que vale y se dice en
  `reported.rechazos` lo que no, porque si no la app se queda en "aplicando..." para
  siempre sin saber por que.
  """
  aceptados, rechazos = {}, {}
  if not isinstance(values, dict):
    return aceptados, rechazos
  for nombre, valor in values.items():
    clave = CLAVES.get(nombre)
    if clave is None:
      rechazos[str(nombre)[:64]] = MOT_DESCONOCIDA
      continue
    if not clave.escribible:
      rechazos[nombre] = MOT_SOLO_REPORTE
      continue
    normalizado, motivo = _valida_uno(clave, valor)
    if motivo is not None:
      rechazos[nombre] = motivo
      continue
    aceptados[nombre] = normalizado
  return aceptados, rechazos


# ------------------------------------------------------------------------------- sobre

@dataclass(frozen=True)
class Sobre:
  version: int
  ts_ms: int
  source: str
  values: dict = field(default_factory=dict)
  rechazos: dict = field(default_factory=dict)

  def a_dict(self) -> dict:
    d = {"v": CFG_VERSION, "version": int(self.version), "ts_ms": int(self.ts_ms),
         "source": self.source, "values": dict(self.values)}
    if self.rechazos:
      d["rechazos"] = dict(self.rechazos)
    return d

  def a_json(self) -> str:
    return json.dumps(self.a_dict(), separators=(",", ":"), sort_keys=True, allow_nan=False)


def parse_sobre(payload, remoto: bool = True) -> Sobre | None:
  """Parsea un sobre de configuracion. None si no lo es. RAM pura, NUNCA lanza.

  `remoto` True = viene del cable, asi que `source` tiene que estar en FUENTES_REMOTAS:
  `comma_ui` gana los empates y no puede venir de fuera del coche. False se usa para
  releer lo que este mismo proceso guardo en Params.
  """
  if isinstance(payload, (bytes, bytearray)):
    try:
      payload = payload.decode("utf-8", errors="strict")
    except (UnicodeDecodeError, AttributeError):
      return None
  if not isinstance(payload, str) or not payload.strip():
    return None
  if len(payload) > MAX_BYTES_SOBRE:
    cloudlog.warning(f"[ORBIT cfg] sobre descartado: {len(payload)} bytes > {MAX_BYTES_SOBRE}")
    return None
  try:
    datos = json.loads(payload)
  except (ValueError, TypeError):
    return None
  if not isinstance(datos, dict):
    return None

  version = datos.get("version")
  if isinstance(version, bool) or not isinstance(version, int) or version < 0:
    return None

  ts_ms = datos.get("ts_ms")
  if isinstance(ts_ms, bool) or not isinstance(ts_ms, int) or ts_ms < 0:
    # No se usa como frescura -- un retenido viejo sigue siendo configuracion valida --
    # pero tiene que ser un entero de epoch ms, que es el unico formato temporal del
    # contrato (seccion 3.2: ni string ni ISO-8601).
    return None

  source = datos.get("source")
  if not isinstance(source, str) or not source:
    return None
  if remoto and source not in FUENTES_REMOTAS:
    cloudlog.warning(f"[ORBIT cfg] sobre remoto descartado: source={source!r} no es del backend")
    return None

  values = datos.get("values")
  if not isinstance(values, dict):
    return None
  if len(values) > len(CLAVES):
    return None

  rechazos = datos.get("rechazos")
  return Sobre(version=version, ts_ms=ts_ms, source=source, values=values,
               rechazos=rechazos if isinstance(rechazos, dict) else {})


def gana(entrante: Sobre | None, local: Sobre | None) -> bool:
  """Resolucion de la seccion 8: gana la version mas alta, EMPATE A FAVOR DE comma_ui.

  El empate no es un detalle de estilo: es lo que garantiza que alguien delante del coche
  pueda corregir un ajuste sin pedirle permiso a una red que puede no existir.
  """
  if entrante is None:
    return False
  if local is None:
    return True
  if entrante.version != local.version:
    return entrante.version > local.version
  if entrante.source == local.source:
    return False                                     # mismo emisor, misma version: no hay nada nuevo
  return entrante.source == FUENTE_COMMA_UI


def gana_a_todos(entrante: Sobre | None, *locales: Sobre | None) -> bool:
  """`entrante` solo gana si le gana a TODO lo que el coche ya sabe. None no cuenta.

  Existe porque el coche no tiene UN sobre local, tiene DOS: el ultimo `desired` aceptado
  (siempre source backend, porque parse_sobre(remoto=True) no acepta otra cosa) y el ultimo
  `reported` publicado (siempre comma_ui, que es la palabra del coche sobre lo que HAY).

  Comparar solo contra el `desired` deja la regla del empate SIN EFECTO en produccion: los
  dos lados de esa comparacion son backend, asi que el empate nunca se evalua contra un
  comma_ui y se lo lleva el backend. El caso no es raro, es EL caso: `_siguiente_version`
  del backend es max(deseada, reportada)+1 sobre lo que EL sabe, asi que mientras no haya
  ingerido el ultimo `reported` emite justo la version que empata con la del coche -- que
  es el escenario (corregir en local, sin red) para el que la regla existe. Y por debajo de
  la version del `reported` pasaba lo mismo por goleada: se rompia tambien "gana la version
  mas alta", porque la mas alta era la del coche y nadie la miraba.
  """
  if entrante is None:
    return False
  return all(gana(entrante, local) for local in locales)


def siguiente_version(*sobres) -> int:
  """Version para un cambio LOCAL: una mas que la mayor que se conozca.

  Con `siguiente_version` + source comma_ui, un ajuste hecho en la pantalla del comma gana
  siempre al ultimo `desired` conocido, tambien si el backend estaba por delante.
  """
  mayor = 0
  for s in sobres:
    if s is not None:
      mayor = max(mayor, int(s.version))
  return mayor + 1


def sobre_local(values: dict, rechazos: dict | None = None, version: int | None = None,
                anteriores=()) -> Sobre:
  """Sobre `reported` con fuente comma_ui y sello de pared."""
  return Sobre(version=int(version) if version is not None else siguiente_version(*anteriores),
               ts_ms=ahora_epoch_ms(), source=FUENTE_COMMA_UI,
               values=dict(values), rechazos=dict(rechazos or {}))


# ------------------------------------------------------------------------------ el plan

@dataclass
class Plan:
  """Lo que hay que escribir para que `reported` pueda decir "aplicado".

  Se separa de la escritura a proposito: decidir es RAM y se puede probar sin disco;
  escribir toca Params (mkstemp+fsync), un JSON con flock y el CameraSender.
  """
  params: dict = field(default_factory=dict)    # {clave_param: valor NATIVO}
  jetson: dict = field(default_factory=dict)    # {campo: valor} de config_jetson.json
  camara: dict = field(default_factory=dict)    # vocabulario de CameraSender.apply_config

  def vacio(self) -> bool:
    return not (self.params or self.jetson or self.camara)


def plan_aplicacion(values: dict) -> Plan:
  """Reparte valores YA VALIDADOS por destino. No toca nada.

  Los valores de DEST_PARAM salen con el tipo NATIVO que exige Params.put: put("1") sobre
  un param INT lanza TypeError y el ajuste se pierde en silencio.
  """
  plan = Plan()
  for nombre, valor in values.items():
    clave = CLAVES.get(nombre)
    if clave is None or not clave.escribible:
      continue
    if clave.destino == DEST_PARAM:
      plan.params[clave.dest_nombre] = _nativo(clave, valor)
    elif clave.destino == DEST_JETSON:
      plan.jetson[clave.dest_nombre] = valor
    elif clave.destino == DEST_CAMARA:
      plan.camara[clave.dest_nombre] = valor
  return plan


def _nativo(clave: Clave, valor):
  """Valor con el tipo que exige Params.put para ESE param."""
  if clave.tipo_param == "bool":
    return bool(valor)
  if clave.tipo_param == "int":
    return int(valor)
  if clave.tipo_param == "float":
    return float(valor)
  return str(valor)


# ------------------------------------------------------------------- config_jetson.json

def leer_config_jetson(ruta: str) -> dict:
  """Contenido actual del JSON de la Jetson. {} si no se puede leer. TOCA DISCO."""
  try:
    with open(ruta) as f:
      datos = json.load(f)
    return datos if isinstance(datos, dict) else {}
  except (OSError, ValueError):
    return {}


def escribir_config_jetson(ruta: str, campos: dict) -> tuple[bool, dict]:
  """Lee-modifica-escribe con flock y rename atomico. (cambio, config_final). TOCA DISCO.

  El flock es contra OTROS PROCESOS (la UI Qt del comma escribe el mismo fichero con
  QSaveFile); el rename es para que un lector nunca vea el fichero a medias. Es la misma
  mecanica que tenia handle_jetson_config, movida aqui porque ahora el escritor es el hilo
  del loop y no el callback de paho.
  """
  if not campos:
    return False, leer_config_jetson(ruta)
  import fcntl
  lock_path = ruta + ".lock"
  try:
    lock_fd = open(lock_path, "w")
  except OSError as e:
    cloudlog.warning(f"[ORBIT cfg] no se pudo abrir el lock de {ruta}: {e}")
    return False, {}
  try:
    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
    actual = leer_config_jetson(ruta)
    cambio = any(actual.get(k) != v for k, v in campos.items())
    if not cambio:
      return False, actual
    actual.update(campos)
    # `_version` lo escribia el handler viejo para su propio anti-eco. Se mantiene porque
    # la UI Qt del comma todavia lo compara, pero ya NO es quien ordena: eso es `version`
    # del sobre, que es monotona y la lleva este modulo.
    actual["_version"] = str(ahora_epoch_ms())
    tmp = ruta + ".tmp"
    with open(tmp, "w") as f:
      json.dump(actual, f, indent=4, sort_keys=True)
      f.flush()
      os.fsync(f.fileno())
    os.replace(tmp, ruta)
    return True, actual
  except OSError as e:
    cloudlog.warning(f"[ORBIT cfg] escritura de {ruta} fallida: {e}")
    return False, {}
  finally:
    try:
      fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
    except OSError:
      pass
    lock_fd.close()


# ---------------------------------------------------------------------------- el buzon

class BusConfig:
  """Buzon de una sola casilla entre el hilo de RED (paho) y el hilo del loop ORBIT.

  Una casilla y no una cola porque `cfg/desired` es ESTADO RETENIDO, no una secuencia de
  ordenes: si llegan dos, el bueno es el ultimo. Asi el hilo de red no puede hacer crecer
  nada, que es la otra mitad de "el hot path es sagrado".
  """

  def __init__(self):
    self._lock = threading.Lock()
    self._pendiente: Sobre | None = None
    self.recibidos = 0
    self.descartados = 0

  def recibir(self, payload) -> bool:
    """Callback de paho: HILO DE RED. Parseo y un lock, nada mas. Nunca lanza."""
    try:
      sobre = parse_sobre(payload, remoto=True)
    except Exception:
      cloudlog.exception("[ORBIT cfg] parse_sobre lanzo (no deberia)")
      return False
    if sobre is None:
      with self._lock:
        self.descartados += 1
      return False
    with self._lock:
      # Si ya habia uno sin atender, gana el que mandaria de todas formas.
      if self._pendiente is not None and not gana(sobre, self._pendiente):
        self.descartados += 1
        return False
      self._pendiente = sobre
      self.recibidos += 1
    return True

  def tomar(self) -> Sobre | None:
    """Hilo del loop ORBIT: saca el pendiente y vacia la casilla."""
    with self._lock:
      sobre, self._pendiente = self._pendiente, None
    return sobre

  def estado(self) -> dict:
    with self._lock:
      return {"pendiente": self._pendiente is not None,
              "recibidos": self.recibidos, "descartados": self.descartados}


_bus = None
_bus_lock = threading.Lock()


def get_bus() -> BusConfig:
  """Buzon unico del proceso. Lo escribe mqtt_comandos (hilo de red) y lo vacia
  mqtt_envio_general (hilo del loop), que son dos objetos distintos: por eso es un
  singleton de modulo y no un atributo, igual que get_command_plane y get_spool."""
  global _bus
  with _bus_lock:
    if _bus is None:
      _bus = BusConfig()
    return _bus


# -------------------------------------------------------------------------- descriptor

def descriptor() -> dict:
  """Vocabulario completo, para el backend y la app. Sin esto cada lado se inventa el
  suyo, que es exactamente como nacieron las tres fuentes de verdad de la seccion 8."""
  return {
    "v": CFG_VERSION,
    "topics": {"desired": TOPIC_CFG_DESIRED, "reported": TOPIC_CFG_REPORTED},
    "sobre": {"version": "int monotono", "ts_ms": "int epoch ms", "source": "backend|comma_ui",
              "values": "{clave: valor}", "rechazos": "{clave: motivo} solo en reported"},
    "resolucion": "gana version mas alta; empate a favor de comma_ui",
    "claves": {c.nombre: {"tipo": c.tipo, "escribible": c.escribible, "destino": c.destino,
                          "minimo": c.minimo, "maximo": c.maximo,
                          "valores": list(c.valores), "desc": c.desc}
               for c in CLAVES.values()},
  }


if __name__ == "__main__":
  print(json.dumps(descriptor(), indent=2, ensure_ascii=False))
