#!/usr/bin/env python3
"""Cola persistente de telemetria y reenvio diferido (seccion 7 del diseno v2).

Hoy, sin cobertura, la telemetria se TIRA: el bucle de publicacion comprueba la conexion
y si no la hay no encola nada ("Si no hay conexion, simplemente no enviar (no encolar)").
Este modulo es la cola que faltaba.

QUE GARANTIZA

  1. SQLite en /data/orbit_spool con WAL + synchronous=NORMAL, commit por LOTES y tope
     duro de 32 MB (paginas vivas de la base + WAL).

  2. PRIORIDAD, que es lo importante del diseno:
       - 'event' y 'trip' NUNCA se descartan una vez ESCRITOS EN DISCO. Ni por tope ni por
         decimacion. Si la base se llena SOLO de criticos, se rechaza lo que entra en
         vez de tirar lo que ya hay (ver _hacer_hueco). La letra pequena importa y hasta
         ahora no estaba escrita: lo que se rechaza en ese caso es un critico NUEVO, y
         guardar() ya habia devuelto True porque la fila solo estaba en RAM. Esa perdida
         no se puede deshacer (un `event` es un mensaje unico): se cuenta aparte en
         perdidas_criticas, se grita en el log y sale por canales_perdidos().
       - 'vehicle' y 'perception' se DECIMAN al reenviar: no tiene sentido volcar media
         hora de muestras a 2 Hz cuando vuelve la cobertura. Ademas son los primeros en
         caer cuando hay que hacer sitio.
       - 'pos' NO se spoolea por defecto: es dato personal y el canal que mas ocupa.
         Se activa explicitamente con spool_pos=True.

  3. EL BACKFILL VA MARCADO. Cada muestra reenviada sale con "backfill": true y con el
     ts_ms del instante en que se CAPTURO, no el de ahora. Un coche que vuelca lo de
     hace una hora no esta conectado ahora, y la app pinta "conectado" con la marca de
     tiempo de la ultima telemetria. Por eso la marca va DENTRO del cuerpo JSON que se
     publica y no solo en un campo del objeto de python: asi el consumidor no puede
     confundir un reenvio con una muestra viva aunque el publicador se despiste.
     Regla para quien integre esto: en el camino de drenar() NO se toca OrbitLastPublish,
     ni el heartbeat de presencia, ni nada que signifique "esta vivo".

  4. ACOTADO EN RAM Y EN DISCO, y nunca tumba la telemetria viva: si el disco esta lleno
     o la base esta corrupta el spool se DESACTIVA SOLO, lo dice en estado()["motivo"] y
     guardar() pasa a ser un no-op que devuelve False. No lanza hacia el llamante.

  5. GUARDAR NO ES ENTREGAR, Y EL SPOOL LO DICE. guardar() devuelve True cuando la fila
     entra en la cola de RAM, no cuando sale por el cable, y entre una cosa y otra hay
     CUATRO sitios donde esa fila muere sin publicarse: la eviccion de RAM (_hueco_ram),
     el rechazo del lote entero en flush() con el tope alcanzado o con la escritura
     fallida, la poda del disco (_hacer_hueco) y el apagado en caliente (_desactivar).
     Cada una de esas perdidas se anota POR CANAL y el llamante la recoge -- y la vacia --
     con canales_perdidos(). Para que sirve: el motor de telemetria SELLA el estado de los
     canales on-change al proponerlo, asi que una muestra sellada que se pierde deja el
     canal callado hasta el keepalive (`openpilot` 60 s en NORMAL, `road` INFINITO en
     AHORRO: nunca). Quien integre esto tiene que vaciar canales_perdidos() en cada
     mantenimiento y deshacer el sello de los canales que salgan.

  6. LA PRIVACIDAD SE COMPRUEBA TAMBIEN AL DRENAR. El interruptor maestro retira las
     fuentes de posicion en la CAPTURA, pero eso no toca lo que ya estaba encolado, y una
     hora de canal `road` es la secuencia de nombres de calle: la traza reconstruida.
     Con el mute puesto, drenar() DESCARTA (no publica y no conserva) lo que es de
     CANALES_SILENCIADOS, y purgar_posicion() lo borra sin esperar a que vuelva la
     cobertura -- que es el caso que el filtro del drenaje no cubre por si solo, porque sin
     enlace no se drena nada y la traza se queda en disco hasta que el conductor quita el
     mute. Tres detalles que no son adorno:

       - CANALES_SILENCIADOS es CANALES_POSICION mas `trip`. El resumen de viaje no lleva
         coordenadas, pero si distancia y horas, y eso junto a un unico punto conocido
         reconstruye el trayecto. Ver el comentario de CANALES_ODOMETRIA.
       - `privacidad` puede ser un TESTIGO llamable y se vuelve a preguntar antes de cada
         fila: una tanda son hasta 200 publicaciones seguidas y leer el interruptor solo al
         empezar dejaba salir la tanda entera despues de pulsarlo.
       - la purga funciona TAMBIEN con el spool desactivado, que es cuando el fichero se
         queda en la eMMC sin nadie que lo drene ni lo borre (_purgar_sin_conexion).

DONDE SE PUEDE LLAMAR CADA COSA

  guardar()          RAM pura (deque acotada + lock). Se puede llamar desde el bucle de
                     telemetria sin pensar.
  canales_perdidos() RAM pura tambien: es leer y vaciar un diccionario pequeno.
  flush(), drenar()  TOCAN DISCO, purgar_posicion() tambien -- y esta ULTIMA toca disco
  y purgar_posicion  aunque el spool este desactivado, que es justo cuando hace falta. Van
                     en el bucle de 1 Hz del hilo ORBIT. NUNCA desde el callback de paho
                     (hilo de RED: un handler lento tira el PINGRESP y con el la conexion)
                     ni desde nada que cuelgue de controlsd (100 Hz).

Los canales son los LOGICOS de la seccion 7 (vehicle, openpilot, health, event,
perception, road, trip, pos), no los nombres de los mensajes cereal.

COMO SE INTEGRA (en el bucle de 1 Hz de mqtt_envio_general)

    spool = get_spool()

    # a) el publish vivo no salio -> a la cola
    info = self.mqttc.publish(topic, cuerpo, qos=0)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
      spool.guardar(canal, cuerpo, dongle=self.DongleID)

    # b) sin conexion: ni se intenta, se encola directamente
    if not self.conectado:
      spool.guardar(canal, cuerpo, dongle=self.DongleID)

    # c) una vez por ciclo: se vuelca, se respeta el interruptor de privacidad y, con
    #    enlace vivo, se reenvia una tanda. El interruptor va como TESTIGO (la funcion,
    #    no su valor) para que pulsarlo corte la tanda en curso.
    if self._privacidad_silenciada():
      spool.purgar_posicion()      # tambien con el spool desactivado
    spool.flush()
    if self.conectado:
      spool.drenar(self._publicar_diferida, dongle=self.DongleID,
                   privacidad=self._privacidad_silenciada)

    # d) y SIEMPRE, lo que el spool acepto y luego no pudo conservar: el sello del canal
    #    on-change se deshace o el estado se queda sin publicar hasta el keepalive
    for canal, _cuantas in spool.canales_perdidos().items():
      self.motor_v2.invalidar_sello(canal)

    def _publicar_diferida(self, muestra):
      # OJO: aqui NO se toca OrbitLastPublish ni el heartbeat de presencia.
      info = self.mqttc.publish(f"orbit/v2/tel/{self.DongleID}/{muestra.canal}", muestra.cuerpo, qos=0)
      return info.rc == mqtt.MQTT_ERR_SUCCESS

Y UN AVISO SOBRE LA PRESENCIA. El reenvio va por orbit/v2/tel/, no por el namespace
legacy telemetry_mqtt/. Pero eso NO basta: la app de hoy marca contacto con la LLEGADA
del mensaje, sin mirar el contenido, y lo hace en los DOS caminos (orbit-iov,
app/lib/services/mqtt_service.dart: _deviceLastSeen[deviceId] = DateTime.now(), una vez
en _registrarActividad() detras de ingerirCanal() para v2 y otra en _updateDeviceData()
para v1, con umbral de 10 s). Mientras siga asi, drenar el spool pinta "visto ahora" un
coche que puede llevar un rato apagado. Saltarse la presencia cuando backfill == true
vive en el backend y en la app, no aqui; lo unico que puede hacer el firmware es marcarlo
en el cuerpo, que es lo que hace _muestra().
"""
import json
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass

from openpilot.common.swaglog import cloudlog

# ------------------------------------------------------------------------------ ajustes

RUTA_SPOOL = "/data/orbit_spool"
FICHERO_DB = "spool.db"

# Tope duro del diseno. Cuenta paginas VIVAS de la base (page_count - freelist) mas el
# tamano del WAL, que es fichero de verdad y tambien ocupa la eMMC.
TOPE_BYTES = 32 * 1024 * 1024

# Al podar se baja hasta esta fraccion del tope: sin histeresis se poda en cada flush.
FRACCION_OBJETIVO = 0.85

# Margen por sobrecarga de pagina/indice al estimar lo que va a ocupar un lote.
FACTOR_SOBRECARGA = 1.35

MAX_FILAS_RAM = 512          # cola en RAM entre flush y flush
MAX_CUERPO_BYTES = 64 * 1024  # una muestra mas grande que esto no es telemetria
LOTE_DRENAJE = 200           # filas por tanda de reenvio
LOTE_PODA = 500              # filas por tanda de poda
PAGINAS_AUTOCHECKPOINT = 64  # ~256 KB de WAL antes de que SQLite haga checkpoint solo
MAX_ERRORES_SEGUIDOS = 5     # errores de SQLite no fatales antes de rendirse

# Ventana de decimacion del reenvio: de los canales decimables se reenvia como mucho una
# muestra cada VENTANA_DECIMACION_MS. A 2 Hz eso es 1 de cada 10.
VENTANA_DECIMACION_MS = 5000

# ------------------------------------------------------------------------- prioridades

PRIO_DECIMABLE = 0   # se decima al reenviar y es lo primero que cae al podar
PRIO_NORMAL = 1      # se reenvia entero, cae al podar solo si ya no quedan decimables
PRIO_CRITICA = 2     # jamas se descarta

CANALES_CRITICOS = frozenset({"event", "trip"})
CANALES_DECIMABLES = frozenset({"vehicle", "perception"})
CANALES_NO_SPOOLEADOS = frozenset({"pos"})

# Canales que dicen DONDE ESTA (o donde ha estado) el coche. Son los que el interruptor
# maestro de privacidad tiene que tapar tambien en la cola, no solo en la captura:
#
#   - `pos` son lat/lon crudas y no se spoolea por defecto (CANALES_NO_SPOOLEADOS), pero
#     con spool_pos=True si esta en disco;
#   - `road` es posicion DERIVADA y no es menos posicion por serlo: publica `road_name`,
#     el nombre de la calle por la que se va. Es on-change, asi que N mensajes encolados
#     durante un corte de cobertura son N nombres de calle en orden, que es exactamente
#     el recorrido. Ademas es PRIO_NORMAL: puede sobrevivir horas en disco.
CANALES_POSICION = frozenset({"pos", "road"})

# Odometria: NO dice donde, dice CUANTO. El resumen de `trip` lleva dist_km, v_max_kph,
# v_med_kph, duracion y numero de desenganches; ni una coordenada ni un nombre de via.
#
# Aun asi entra en el silencio del interruptor, y la razon no es que sea posicion: es que
# "he recorrido 43,2 km entre las 22:15 y las 22:47" leido junto a UN solo punto conocido
# (el sitio donde el coche aparca todas las noches) reconstruye el trayecto casi tan bien
# como la traza, y repetido a diario dibuja la rutina. La seccion 9 dice "posicion y camara
# COMO MINIMO", asi que ampliar esta dentro del contrato; y el interruptor tiene que ser
# facil de explicar: "con esto puesto el coche no cuenta por donde vas ni cuanto has ido".
#
# Que `trip` sea PRIO_CRITICA no lo salva, y ese es el punto delicado: "los criticos jamas
# se descartan" protege contra PERDIDAS DEL SISTEMA (tope, poda, decimacion, fallo de
# escritura), no contra un silencio PEDIDO por quien va dentro del coche. Por eso el
# descarte por privacidad no se contabiliza como perdida critica ni grita en el log: va a
# `descartadas_privacidad` y a `silenciadas_criticas` (ver _silenciar).
CANALES_ODOMETRIA = frozenset({"trip"})

# Lo que el interruptor maestro tapa en la cola. Es lo que miran drenar() y
# purgar_posicion(); CANALES_POSICION se conserva aparte porque es una afirmacion distinta
# ("esto es posicion") y hay codigo y pruebas que preguntan justo eso.
CANALES_SILENCIADOS = CANALES_POSICION | CANALES_ODOMETRIA

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS cola (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  canal     TEXT    NOT NULL,
  prioridad INTEGER NOT NULL,
  ts_ms     INTEGER NOT NULL,
  cuerpo    TEXT    NOT NULL,
  dongle    TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cola_orden ON cola(prioridad DESC, id ASC);
"""

# Sintomas de "esto ya no se arregla solo": disco lleno, base corrupta, fs de solo
# lectura. Cualquiera de ellos desactiva el spool en el acto.
_SINTOMAS_FATALES = (
  "disk is full",
  "no space",
  "disk i/o error",
  "readonly",
  "read-only",
  "not a database",
  "malformed",
  "corrupt",
  "unable to open database",
)


def _epoch_ms() -> int:
  """Instante de PARED en epoch milisegundos enteros (seccion 3.2 del diseno).

  time.time esta prohibido en este arbol (casi siempre lo que se quiere es un plazo, y un
  plazo con reloj de pared salta cuando entra el NTP). Aqui si se quiere pared: es el
  sello de cuando se capturo la muestra, y es justo lo que hace que el backend sepa que
  un reenvio es viejo. Los plazos internos van con time.monotonic().
  """
  return time.time_ns() // 1_000_000


def prioridad_de(canal: str) -> int:
  """Prioridad de un canal logico de la seccion 7. Lo desconocido es NORMAL: un canal
  nuevo no se decima ni se tira por sorpresa, pero tampoco entra en el grupo de los que
  no se descartan nunca."""
  if canal in CANALES_CRITICOS:
    return PRIO_CRITICA
  if canal in CANALES_DECIMABLES:
    return PRIO_DECIMABLE
  return PRIO_NORMAL


def _es_fatal(e: Exception) -> bool:
  mensaje = str(e).lower()
  return any(s in mensaje for s in _SINTOMAS_FATALES)


@dataclass(frozen=True)
class MuestraSpool:
  """Una muestra lista para republicar. `cuerpo` ya es el JSON definitivo: lleva dentro
  "backfill": true y el "ts_ms" de captura. Publicalo tal cual."""
  canal: str
  cuerpo: str
  ts_ms: int
  dongle: str = ""
  backfill: bool = True


@dataclass
class ResumenDrenaje:
  publicadas: int = 0
  decimadas: int = 0
  ilegibles: int = 0
  otro_dongle: int = 0
  privadas: int = 0     # posicion encolada que el mute descarta al drenar
  restantes: int = 0
  corte: bool = False   # el publicador dijo que no salio: se para y se conserva


class Spool:
  """Cola persistente de telemetria. Un solo escritor (el hilo ORBIT); guardar() se puede
  llamar desde cualquier hilo porque solo toca RAM."""

  def __init__(self, ruta: str = RUTA_SPOOL, tope_bytes: int = TOPE_BYTES,
               max_filas_ram: int = MAX_FILAS_RAM, ventana_decimacion_ms: int = VENTANA_DECIMACION_MS,
               spool_pos: bool = False, max_cuerpo_bytes: int = MAX_CUERPO_BYTES):
    self.ruta = str(ruta)
    self.tope_bytes = int(tope_bytes)
    self.max_filas_ram = max(1, int(max_filas_ram))
    self.ventana_decimacion_ms = int(ventana_decimacion_ms)
    self.spool_pos = bool(spool_pos)
    self.max_cuerpo_bytes = int(max_cuerpo_bytes)

    self.activo = False
    self.motivo = ""

    self._lock_ram = threading.Lock()
    self._lock_db = threading.RLock()
    # Lock HOJA: _perder() se llama con _lock_ram o con _lock_db cogidos, asi que este no
    # puede coger ningun otro ni llamar a nada que lo haga.
    self._lock_perdidas = threading.Lock()
    self._pendientes: deque = deque()
    # Filas que se ACEPTARON (guardar() dijo True) y luego se perdieron sin publicarse,
    # por canal. El llamante las vacia con canales_perdidos() y deshace el sello.
    self._perdidos: dict = {}
    # Optimista al reves a proposito: mientras no se demuestre lo contrario se asume que
    # PUEDE haber posicion en disco, para que la primera purga con el mute puesto mire de
    # verdad. Solo una purga que termina bien lo pone a False.
    self._hay_posicion = True
    self._con = None
    self._errores_seguidos = 0
    # Ultimo ts REENVIADO por canal decimable. Solo avanza cuando el publish sale de
    # verdad: si avanzase al intentarlo, un corte a mitad de tanda haria que la fila que
    # no salio se decimase a si misma en la siguiente pasada.
    self._ultimo_ts_reenviado: dict = {}
    self._contadores = {
      "guardadas": 0,          # aceptadas en RAM
      "escritas": 0,           # volcadas a disco
      "no_spooleadas": 0,      # canal excluido (pos)
      "rechazadas_cuerpo": 0,  # no serializable / demasiado grande
      "rechazadas_ram": 0,     # cola en RAM llena de criticos
      "rechazadas_tope": 0,    # disco lleno de criticos: se rechaza lo nuevo
      "evictadas_ram": 0,      # descartadas en RAM para hacer sitio
      "evictadas_disco": 0,    # podadas del disco para hacer sitio
      "perdidas_error": 0,     # lote perdido por fallo de escritura
      "perdidas_criticas": 0,  # de lo anterior, 'event'/'trip': no hay forma de deshacerlo
      "descartadas_privacidad": 0,  # encolado tirado por el interruptor maestro (posicion + odometria)
      "silenciadas_criticas": 0,    # de lo anterior, 'trip': descarte PEDIDO, no una perdida
      "purgas_destructivas": 0,     # veces que hubo que borrar la base entera para purgar
      "publicadas": 0,
      "decimadas": 0,
      "ilegibles": 0,
      "otro_dongle": 0,
    }
    self._abrir()

  # ------------------------------------------------------------------------ apertura

  def _ruta_db(self) -> str:
    return os.path.join(self.ruta, FICHERO_DB)

  def _abrir(self) -> None:
    try:
      os.makedirs(self.ruta, exist_ok=True)
    except OSError as e:
      self._desactivar(f"no se puede crear {self.ruta}: {e}")
      return

    if self._conectar():
      return

    # Segunda oportunidad: base ilegible, truncada o corrupta. Se tira y se rehace. La
    # telemetria diferida de un arranque anterior no vale un spool que no arranca nunca.
    cloudlog.warning("[ORBIT spool] base ilegible: se recrea desde cero")
    if not self._borrar_base():
      self._desactivar("base corrupta y no se puede borrar")
      return
    if not self._conectar():
      self._desactivar("base corrupta y no se puede recrear")

  def _conectar(self) -> bool:
    con = None
    try:
      # isolation_level=None: autocommit. Las transacciones se abren a mano (BEGIN/COMMIT)
      # justo alrededor del lote, que es lo que significa "commit por lotes".
      # check_same_thread=False: el acceso se serializa con _lock_db, no con el hilo.
      con = sqlite3.connect(self._ruta_db(), timeout=1.0, isolation_level=None, check_same_thread=False)
      # auto_vacuum incremental ANTES de crear tablas: sin el, borrar filas no devuelve
      # el espacio al sistema de ficheros y el fichero se queda pegado al tope para
      # siempre, con lo que la poda acabaria vaciando la cola entera sin bajar de 32 MB.
      con.execute("PRAGMA auto_vacuum=INCREMENTAL")
      if con.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
        con.execute("VACUUM")
      con.execute("PRAGMA journal_mode=WAL")
      con.execute("PRAGMA synchronous=NORMAL")
      con.execute(f"PRAGMA wal_autocheckpoint={PAGINAS_AUTOCHECKPOINT}")
      con.execute(f"PRAGMA journal_size_limit={PAGINAS_AUTOCHECKPOINT * 4096}")
      con.executescript(_ESQUEMA)
      pendientes = con.execute("SELECT COUNT(*) FROM cola").fetchone()[0]
    except (sqlite3.Error, OSError) as e:
      cloudlog.warning(f"[ORBIT spool] apertura fallida: {e}")
      if con is not None:
        try:
          con.close()
        except sqlite3.Error:
          pass
      return False

    self._con = con
    self.activo = True
    self.motivo = ""
    self._errores_seguidos = 0
    if pendientes:
      cloudlog.warning(f"[ORBIT spool] {pendientes} muestras diferidas de un arranque anterior")
    return True

  def _borrar_base(self) -> bool:
    ok = True
    for sufijo in ("", "-wal", "-shm"):
      try:
        os.remove(self._ruta_db() + sufijo)
      except FileNotFoundError:
        pass
      except OSError as e:
        cloudlog.warning(f"[ORBIT spool] no se pudo borrar {self._ruta_db()}{sufijo}: {e}")
        ok = False
    return ok

  def _desactivar(self, motivo: str) -> None:
    """Apagado en caliente. El spool es un extra: si falla, la telemetria viva sigue.

    Cierra la conexion y tira la cola de RAM, pero NO borra el fichero: puede haber
    criticos escritos que el arranque siguiente todavia pueda reenviar. Eso deja una
    responsabilidad abierta y esta cubierta en _purgar_sin_conexion: mientras el fichero
    exista, el interruptor de privacidad tiene que poder llegar a el.
    """
    if self.activo or not self.motivo:
      cloudlog.error(f"[ORBIT spool] desactivado: {motivo}")
    self.activo = False
    self.motivo = motivo
    with self._lock_ram:
      # Lo que estuviera en RAM se pierde aqui: es la CUARTA via de perdida silenciosa y
      # se reporta como las otras tres. canales_perdidos() sigue leyendose desactivado.
      for fila in self._pendientes:
        self._perder(fila[0])
      self._pendientes.clear()
    con, self._con = self._con, None
    if con is not None:
      try:
        con.close()
      except sqlite3.Error:
        pass

  def _fallo_db(self, e: Exception, que: str) -> None:
    if _es_fatal(e):
      self._desactivar(f"{que}: {e}")
      return
    self._errores_seguidos += 1
    cloudlog.warning(f"[ORBIT spool] {que}: {e} ({self._errores_seguidos}/{MAX_ERRORES_SEGUIDOS})")
    if self._errores_seguidos >= MAX_ERRORES_SEGUIDOS:
      self._desactivar(f"{MAX_ERRORES_SEGUIDOS} errores seguidos de SQLite, ultimo: {e}")

  def _rollback(self) -> None:
    if self._con is None:
      return
    try:
      self._con.execute("ROLLBACK")
    except sqlite3.Error:
      pass

  # ------------------------------------------------------------------------- perdidas

  def _perder(self, canal: str, n: int = 1) -> None:
    """Anota que `n` filas de `canal` que ya se habian ACEPTADO mueren sin publicarse.

    guardar() devolvio True por ellas, asi que el llamante NO reacciono: creyo que la
    muestra estaba a salvo y dejo puesto el sello del canal on-change. Este registro es
    la segunda oportunidad de enterarse; lo vacia canales_perdidos().

    Se llama desde dentro de _lock_ram o de _lock_db, asi que aqui no se coge ningun otro
    lock ni se llama a nada que pueda cogerlo.
    """
    if n <= 0:
      return
    with self._lock_perdidas:
      self._perdidos[canal] = self._perdidos.get(canal, 0) + int(n)
    if canal in CANALES_CRITICOS:
      # Un critico perdido no se arregla deshaciendo ningun sello: `event` y `trip` son
      # mensajes UNICOS. Lo unico que se puede hacer es que no sea silencioso.
      self._contadores["perdidas_criticas"] += int(n)
      cloudlog.error(f"[ORBIT spool] {n} muestra(s) criticas de '{canal}' perdidas sin publicar")

  def _silenciar(self, canal: str, n: int = 1) -> None:
    """Anota `n` filas de `canal` descartadas POR EL INTERRUPTOR de privacidad.

    No es lo mismo que _perder y por eso no comparte camino: una perdida es un fallo del
    sistema y un silencio es una ORDEN de quien va dentro del coche. La diferencia se ve
    en `trip`, que es PRIO_CRITICA: mandarlo por _perder lo contaria en perdidas_criticas
    y gritaria un cloudlog.error por cada resumen de viaje que el mute tapa, que es ruido
    sobre una decision correcta.

    Los canales que NO son criticos SI pasan ademas por _perder, porque su sello de
    on-change sigue puesto y hay que deshacerlo; deshacerlo no publica nada mientras el
    mute siga puesto (con el mute el canal se queda sin fuente en la captura), y en cuanto
    se quite vuelve a proponer estado en vez de callarse hasta el keepalive.

    Se llama desde dentro de _lock_ram o de _lock_db, igual que _perder.
    """
    if n <= 0:
      return
    self._contadores["descartadas_privacidad"] += int(n)
    if canal in CANALES_CRITICOS:
      self._contadores["silenciadas_criticas"] += int(n)
      return
    self._perder(canal, n)

  def canales_perdidos(self) -> dict:
    """{canal: cuantas} de lo aceptado que se perdio, y VACIA el registro.

    RAM pura. El llamante tiene UNA oportunidad por lectura: lo que devuelve ya no vuelve
    a salir. Se lee tambien con el spool desactivado, porque _desactivar() tira la cola de
    RAM y esas filas tambien se perdieron.
    """
    with self._lock_perdidas:
      perdidos, self._perdidos = self._perdidos, {}
    return perdidos

  # -------------------------------------------------------------------------- guardar

  def _a_texto(self, cuerpo) -> str | None:
    """Normaliza el cuerpo a JSON de OBJETO. Se exige objeto porque el reenvio tiene que
    poder meterle dentro la marca de backfill: un cuerpo que no es objeto no se puede
    marcar y acabaria publicandose como si fuese una muestra viva."""
    if isinstance(cuerpo, str):
      texto = cuerpo
      if texto.lstrip()[:1] != "{":
        self._contadores["rechazadas_cuerpo"] += 1
        return None
    elif isinstance(cuerpo, dict):
      try:
        # allow_nan=False por la misma razon que en el camino vivo: json.dumps emite por
        # defecto el literal NaN, que no es JSON valido (RFC 8259), y el consumidor
        # revienta con el mensaje entero.
        texto = json.dumps(cuerpo, allow_nan=False)
      except (ValueError, TypeError):
        self._contadores["rechazadas_cuerpo"] += 1
        return None
    else:
      self._contadores["rechazadas_cuerpo"] += 1
      return None

    if len(texto) > self.max_cuerpo_bytes:
      self._contadores["rechazadas_cuerpo"] += 1
      return None
    return texto

  def guardar(self, canal: str, cuerpo, ts_ms: int | None = None, dongle: str = "") -> bool:
    """Encola una muestra. SOLO RAM: no toca disco, no bloquea, no lanza.

    `cuerpo` es el JSON ya serializado del camino vivo (str) o el dict sin serializar.
    Devuelve True si quedo encolada.
    """
    if not self.activo:
      return False

    canal = str(canal)
    if canal in CANALES_NO_SPOOLEADOS and not self.spool_pos:
      self._contadores["no_spooleadas"] += 1
      return False

    texto = self._a_texto(cuerpo)
    if texto is None:
      return False

    fila = (canal, prioridad_de(canal), int(ts_ms) if ts_ms is not None else _epoch_ms(), texto, str(dongle or ""))
    with self._lock_ram:
      if len(self._pendientes) >= self.max_filas_ram and not self._hueco_ram():
        # Cola en RAM llena de criticos. Se rechaza lo que entra (incluso critico) antes
        # que tirar lo que ya hay: mismo criterio que en disco.
        self._contadores["rechazadas_ram"] += 1
        return False
      self._pendientes.append(fila)
    self._contadores["guardadas"] += 1
    return True

  def _hueco_ram(self) -> bool:
    """Tira la fila NO critica mas antigua de la cola en RAM. Se llama con _lock_ram.

    La fila que cae ya se habia aceptado: se anota en _perder para que el llamante pueda
    deshacer su sello. Antes desaparecia sin que nadie se enterase.
    """
    for i, fila in enumerate(self._pendientes):
      if fila[1] != PRIO_CRITICA:
        del self._pendientes[i]
        self._contadores["evictadas_ram"] += 1
        self._perder(fila[0])
        return True
    return False

  # ---------------------------------------------------------------------------- flush

  def flush(self) -> int:
    """Vuelca a disco lo que haya en RAM, en UN commit. Devuelve filas escritas.

    TOCA DISCO: hilo ORBIT, nunca el callback de paho.
    """
    if not self.activo:
      return 0

    with self._lock_ram:
      if not self._pendientes:
        return 0
      lote = list(self._pendientes)
      self._pendientes.clear()

    with self._lock_db:
      if not self.activo or self._con is None:
        return 0

      bytes_lote = int(sum(len(f[3]) for f in lote) * FACTOR_SOBRECARGA)
      if not self._hacer_hueco(bytes_lote):
        if not self.activo or self._con is None:
          # _hacer_hueco desactivo el spool (disco lleno al medir o al podar): esto no es
          # un tope alcanzado, es un fallo, y el contador tiene que decirlo.
          self._contadores["perdidas_error"] += len(lote)
        else:
          # Tope alcanzado y solo quedan criticos. No se descartan LOS GUARDADOS: se
          # rechaza lo nuevo, criticos incluidos. guardar() ya habia dicho True por este
          # lote, asi que la unica forma de que el llamante se entere es _perder.
          self._contadores["rechazadas_tope"] += len(lote)
        for fila in lote:
          self._perder(fila[0])
        return 0

      try:
        self._con.execute("BEGIN")
        self._con.executemany("INSERT INTO cola(canal, prioridad, ts_ms, cuerpo, dongle) VALUES (?,?,?,?,?)", lote)
        self._con.execute("COMMIT")
      except (sqlite3.Error, OSError) as e:
        self._rollback()
        self._contadores["perdidas_error"] += len(lote)
        for fila in lote:
          self._perder(fila[0])
        self._fallo_db(e, "escritura del lote")
        return 0

      self._errores_seguidos = 0
      self._contadores["escritas"] += len(lote)
      if any(f[0] in CANALES_SILENCIADOS for f in lote):
        # Hay algo silenciable en disco: la proxima purga con el mute puesto tiene trabajo.
        # Sin esta marca habria que barrer la tabla entera cada segundo para averiguarlo.
        # OJO: la condicion es CANALES_SILENCIADOS y no CANALES_POSICION, o un lote que
        # solo trajera `trip` dejaria la marca a False y la purga no bajaria a disco.
        self._hay_posicion = True
      # Segunda pasada: la estimacion de arriba es una estimacion. Si el lote real dejo
      # el fichero por encima del tope, se poda ahora.
      self._hacer_hueco(0)
      return len(lote)

  # ----------------------------------------------------------------------------- tope

  def _bytes_usados(self) -> int:
    """Paginas VIVAS de la base (las libres se devuelven al fs con incremental_vacuum)
    mas el WAL, que tambien es fichero."""
    if self._con is None:
      return 0
    try:
      page_size = self._con.execute("PRAGMA page_size").fetchone()[0]
      page_count = self._con.execute("PRAGMA page_count").fetchone()[0]
      libres = self._con.execute("PRAGMA freelist_count").fetchone()[0]
      usados = max(0, int(page_count) - int(libres)) * int(page_size)
    except (sqlite3.Error, TypeError, IndexError) as e:
      self._fallo_db(e, "lectura de tamano")
      return 0
    try:
      usados += os.path.getsize(self._ruta_db() + "-wal")
    except OSError:
      pass
    return usados

  def _compactar(self) -> None:
    """Devuelve al sistema de ficheros lo que la poda acaba de liberar."""
    if self._con is None:
      return
    try:
      self._con.execute("PRAGMA incremental_vacuum")
      self._con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as e:
      cloudlog.warning(f"[ORBIT spool] compactacion fallida: {e}")

  def _hacer_hueco(self, bytes_extra: int) -> bool:
    """Poda hasta que quepan `bytes_extra` sin pasar del tope. Devuelve False si ya no se
    puede podar mas (solo quedan criticos) y aun asi no cabe.

    Orden de sacrificio: decimables primero, normales despues, criticos JAMAS.
    """
    if self._con is None:
      return False
    usados = self._bytes_usados()
    if self._con is None:
      return False   # medir el tamano ya desactivo el spool (disco lleno / base ida)
    if usados + bytes_extra <= self.tope_bytes:
      return True

    objetivo = max(0, int(self.tope_bytes * FRACCION_OBJETIVO) - bytes_extra)
    for prio in (PRIO_DECIMABLE, PRIO_NORMAL):
      while usados > objetivo:
        if self._con is None:
          return False
        try:
          # Se lee tambien el canal: la fila podada estaba aceptada y hay que decir de que
          # canal era para que su sello se pueda deshacer.
          podadas = self._con.execute(
            "SELECT id, canal FROM cola WHERE prioridad=? ORDER BY id ASC LIMIT ?", (prio, LOTE_PODA)).fetchall()
          ids = [f[0] for f in podadas]
          if not ids:
            break
          marcas = ",".join("?" * len(ids))
          self._con.execute("BEGIN")
          self._con.execute(f"DELETE FROM cola WHERE id IN ({marcas})", ids)  # marcas son placeholders, no datos
          self._con.execute("COMMIT")
        except (sqlite3.Error, OSError) as e:
          self._rollback()
          self._fallo_db(e, "poda")
          return False
        self._contadores["evictadas_disco"] += len(ids)
        for _fid, canal in podadas:
          self._perder(canal)
        self._compactar()
        usados = self._bytes_usados()
      if usados + bytes_extra <= self.tope_bytes:
        return True

    # Solo quedan criticos por encima del tope. No se tocan.
    self._compactar()
    return self._con is not None and self._bytes_usados() + bytes_extra <= self.tope_bytes

  # --------------------------------------------------------------------------- drenar

  def _muestra(self, canal: str, ts_ms: int, cuerpo: str, dongle: str):
    """Reconstruye el cuerpo con la marca de backfill dentro. None si es ilegible."""
    try:
      datos = json.loads(cuerpo)
    except (ValueError, TypeError):
      return None
    if not isinstance(datos, dict):
      return None
    # La marca va en el CUERPO, no solo en el objeto: el consumidor no puede confundir un
    # reenvio con una muestra viva ni aunque el publicador la pierda por el camino.
    datos["backfill"] = True
    datos["ts_ms"] = int(ts_ms)
    try:
      texto = json.dumps(datos, allow_nan=False)
    except (ValueError, TypeError):
      return None
    return MuestraSpool(canal=canal, cuerpo=texto, ts_ms=int(ts_ms), dongle=dongle, backfill=True)

  def _testigo_privacidad(self, privacidad, anterior: bool) -> bool:
    """Resuelve el estado del interruptor AHORA. `privacidad` puede ser un bool o un
    testigo llamable que se vuelve a preguntar fila a fila.

    Si el testigo lanza se conserva el valor anterior: ni encender el silencio por un
    error transitorio (tiraria telemetria que nadie pidio tirar) ni apagarlo (publicaria
    lo que el conductor acaba de silenciar).
    """
    if callable(privacidad):
      try:
        return bool(privacidad())
      except Exception:
        cloudlog.exception("[ORBIT spool] el testigo de privacidad lanzo; se conserva el ultimo valor")
        return anterior
    return bool(privacidad)

  def drenar(self, publicar, dongle: str | None = None, max_filas: int = LOTE_DRENAJE,
             ventana_decimacion_ms: int | None = None, privacidad=False) -> ResumenDrenaje:
    """Reenvia una tanda de muestras diferidas. TOCA DISCO: hilo ORBIT, nunca paho.

    `publicar(muestra: MuestraSpool) -> bool` publica y devuelve si SALIO de verdad
    (rc == 0). En cuanto devuelve False se corta la tanda y NO se borra nada: lo que no
    salio se conserva para la siguiente.

    `dongle`: si se pasa, las filas grabadas con OTRA identidad se descartan sin
    publicarlas. Reenviar la telemetria del dongle anterior bajo el nuevo la atribuiria a
    un vehiculo que no es.

    `privacidad`: estado del interruptor maestro. Con el puesto, lo que sea de
    CANALES_SILENCIADOS se DESCARTA: no se publica y tampoco se conserva. Conservarlo seria
    dejar la traza en disco esperando a que se quite el mute, y descartar al drenar es lo
    que cierra la secuencia real -- encolar sin cobertura, pulsar el interruptor, volver la
    cobertura --, que el filtro de la captura no ve porque ocurre despues de capturar.

    PUEDE SER UN TESTIGO LLAMABLE, y conviene que lo sea: una tanda publica hasta
    LOTE_DRENAJE (200) filas seguidas, asi que leer el interruptor UNA vez al empezar deja
    una ventana en la que pulsar el mute no corta la tanda en curso y siguen saliendo
    nombres de calle detras del "ya no emito". Con un testigo se vuelve a preguntar antes
    de CADA fila y el silencio empieza en la siguiente. El testigo tiene que ser barato
    (el del firmware es un bool cacheado a 1 Hz) y no puede volver a entrar en el spool.

    QUIEN LLAME A ESTO NO PUEDE TOCAR LA PRESENCIA: ni OrbitLastPublish, ni el heartbeat,
    ni nada que signifique "el coche esta conectado ahora".
    """
    res = ResumenDrenaje()
    if not self.activo:
      return res
    ventana = self.ventana_decimacion_ms if ventana_decimacion_ms is None else int(ventana_decimacion_ms)
    privado = self._testigo_privacidad(privacidad, False)

    with self._lock_db:
      if not self.activo or self._con is None:
        return res
      try:
        # Criticos primero: si la cobertura se vuelve a caer a mitad de tanda, lo que ya
        # salio es lo que no se podia perder. Dentro de cada prioridad, orden de llegada.
        filas = self._con.execute(
          "SELECT id, canal, prioridad, ts_ms, cuerpo, dongle FROM cola ORDER BY prioridad DESC, id ASC LIMIT ?",
          (max(1, int(max_filas)),)).fetchall()
      except (sqlite3.Error, OSError) as e:
        self._fallo_db(e, "lectura de la cola")
        return res

      borrar = []
      for fid, canal, prio, ts_ms, cuerpo, dng in filas:
        if dongle is not None and dng and dng != dongle:
          borrar.append(fid)
          res.otro_dongle += 1
          continue

        # El interruptor se relee ANTES de cada fila: pulsarlo a mitad de tanda corta la
        # tanda en la fila siguiente en vez de dejar salir las 200.
        privado = self._testigo_privacidad(privacidad, privado)
        if privado and canal in CANALES_SILENCIADOS:
          # No se publica y no se conserva: el silencio es PEDIDO, no un fallo (ver
          # _silenciar, que por eso no lo cuenta como perdida critica).
          borrar.append(fid)
          res.privadas += 1
          self._silenciar(canal)
          continue

        if prio == PRIO_DECIMABLE and ventana > 0:
          ultimo = self._ultimo_ts_reenviado.get(canal)
          # ts < ultimo (reloj hacia atras) NO decima: ante la duda, se reenvia.
          if ultimo is not None and 0 <= ts_ms - ultimo < ventana:
            borrar.append(fid)
            res.decimadas += 1
            continue

        muestra = self._muestra(canal, ts_ms, cuerpo, dng or (dongle or ""))
        if muestra is None:
          borrar.append(fid)
          res.ilegibles += 1
          self._perder(canal)   # aceptada y perdida: mismo caso que una poda
          continue

        try:
          salio = bool(publicar(muestra))
        except Exception:
          cloudlog.exception("[ORBIT spool] el publicador lanzo; se conserva la muestra")
          salio = False
        if not salio:
          res.corte = True
          break

        borrar.append(fid)
        res.publicadas += 1
        if prio == PRIO_DECIMABLE:
          self._ultimo_ts_reenviado[canal] = ts_ms

      if borrar and self._con is not None:
        try:
          marcas = ",".join("?" * len(borrar))
          self._con.execute("BEGIN")
          self._con.execute(f"DELETE FROM cola WHERE id IN ({marcas})", borrar)  # marcas son placeholders, no datos
          self._con.execute("COMMIT")
          self._compactar()
        except (sqlite3.Error, OSError) as e:
          self._rollback()
          self._fallo_db(e, "borrado tras reenvio")

      res.restantes = self._filas()
      if res.restantes == 0:
        # Cola vacia: la proxima ventana sin cobertura empieza a decimar de cero.
        self._ultimo_ts_reenviado.clear()

    self._contadores["publicadas"] += res.publicadas
    self._contadores["decimadas"] += res.decimadas
    self._contadores["ilegibles"] += res.ilegibles
    self._contadores["otro_dongle"] += res.otro_dongle
    return res

  # ------------------------------------------------------------------------ privacidad

  def purgar_posicion(self) -> int:
    """Borra de la cola lo que el interruptor maestro tapa. TOCA DISCO. Devuelve cuantas.

    Es la mitad del interruptor que el filtro de drenar() no puede cubrir: drenar solo
    corre con enlace, asi que si el mute se pulsa en mitad de un corte de cobertura la
    traza se queda escrita esperando, y basta con que el conductor lo quite antes de que
    vuelva la red para que salga entera. Esto la borra en el acto, con red o sin ella.

    FUNCIONA TAMBIEN CON EL SPOOL DESACTIVADO. Antes salia por `if not self.activo` igual
    que drenar(), y _desactivar() cierra la conexion pero NO borra el fichero: con el disco
    lleno o la base corrupta, lo ya escrito se quedaba en la eMMC con el mute puesto hasta
    que reiniciara el proceso. Ver _purgar_sin_conexion.

    Se llama a 1 Hz mientras el mute este puesto, asi que NO puede barrer la tabla cada
    vez: `cola` no tiene indice por canal y un DELETE ... WHERE canal IN (...) es un
    recorrido completo de hasta 32 MB. Por eso se mira primero `_hay_posicion`, que solo
    se pone a True cuando flush() escribe de verdad un canal silenciable (y arranca en
    True por si la base viene de otro arranque).
    """
    n = 0
    with self._lock_ram:
      if any(fila[0] in CANALES_SILENCIADOS for fila in self._pendientes):
        quedan = deque()
        for fila in self._pendientes:
          if fila[0] in CANALES_SILENCIADOS:
            n += 1
            self._silenciar(fila[0])
          else:
            quedan.append(fila)
        self._pendientes = quedan

    with self._lock_db:
      if self._con is None or not self.activo:
        # Spool desactivado: la conexion esta cerrada, pero el fichero sigue en el disco.
        n += self._purgar_sin_conexion()
      elif self._hay_posicion:
        n += self._purgar_con_conexion()
    if n:
      cloudlog.warning(f"[ORBIT spool] interruptor de privacidad: {n} muestras descartadas de la cola")
    return n

  def _purgar_con_conexion(self) -> int:
    """Camino normal de la purga. Se llama con _lock_db y con el spool activo."""
    canales = tuple(sorted(CANALES_SILENCIADOS))
    marcas = ",".join("?" * len(canales))
    try:
      cuenta = self._con.execute(
        f"SELECT canal, COUNT(*) FROM cola WHERE canal IN ({marcas}) GROUP BY canal",  # marcas son placeholders
        canales).fetchall()
      if cuenta:
        self._con.execute("BEGIN")
        self._con.execute(f"DELETE FROM cola WHERE canal IN ({marcas})", canales)  # marcas son placeholders
        self._con.execute("COMMIT")
        self._compactar()
    except (sqlite3.Error, OSError) as e:
      self._rollback()
      self._fallo_db(e, "purga de privacidad")
      return 0
    n = 0
    for canal, cuantas in cuenta:
      n += int(cuantas)
      self._silenciar(canal, int(cuantas))
    # Solo aqui: la tabla ya no tiene nada silenciable y la purga del segundo que viene es
    # un no-op de verdad, sin tocar disco.
    self._hay_posicion = False
    return n

  def _purgar_sin_conexion(self) -> int:
    """Purga con el spool DESACTIVADO. Se llama con _lock_db. TOCA DISCO.

    El agujero que cierra: _desactivar() cierra la conexion y deja spool.db donde estaba.
    drenar() salia por `if not self.activo` en su primera linea, y la mitad de DISCO de
    purgar_posicion() estaba detras del mismo `not self.activo` (su mitad de RAM si corria,
    pero _desactivar ya habia vaciado esa cola). Resultado: las filas `road` ya escritas se
    quedaban en la eMMC con el mute puesto -- ni se purgaban ni se drenaban -- hasta que
    reiniciase el proceso; y si para entonces el conductor habia quitado el interruptor, el
    arranque siguiente las encontraba y las publicaba enteras.

    Dos intentos, en este orden:

      1. abrir la base el tiempo justo de BORRAR lo silenciado y cerrarla. Cubre la
         desactivacion por errores transitorios acumulados (MAX_ERRORES_SEGUIDOS), que es
         el caso comun y en el que la base esta sana.
      2. si eso falla -- corrupta, disco lleno, sistema de ficheros de solo lectura --,
         BORRAR EL FICHERO ENTERO. Se pierde la telemetria diferida, criticos incluidos, y
         se dice en el log. Es la decision correcta y no una rendicion: un spool
         desactivado no vuelve a drenar en toda la vida del proceso, asi que lo que se tira
         aqui no iba a salir por el cable de todas formas, y dejarlo escrito solo sirve
         para que lo publique el arranque siguiente. El interruptor es una orden.

    No reactiva el spool ni toca `motivo`: sigue desactivado por lo que sea que lo apago.
    """
    ruta = self._ruta_db()
    if not os.path.exists(ruta):
      return 0
    canales = tuple(sorted(CANALES_SILENCIADOS))
    marcas = ",".join("?" * len(canales))
    con = None
    try:
      con = sqlite3.connect(ruta, timeout=1.0, isolation_level=None, check_same_thread=False)
      cuenta = con.execute(
        f"SELECT canal, COUNT(*) FROM cola WHERE canal IN ({marcas}) GROUP BY canal",  # marcas son placeholders
        canales).fetchall()
      if cuenta:
        con.execute("BEGIN")
        con.execute(f"DELETE FROM cola WHERE canal IN ({marcas})", canales)  # marcas son placeholders
        con.execute("COMMIT")
      con.close()
      con = None
    except (sqlite3.Error, OSError) as e:
      if con is not None:
        try:
          con.close()
        except sqlite3.Error:
          pass
      cloudlog.error(f"[ORBIT spool] purga con el spool desactivado fallida ({e}): se borra la base entera")
      self._contadores["purgas_destructivas"] += 1
      self._borrar_base()
      self._hay_posicion = False
      # No se sabe cuantas filas habia: la base no se podia leer. Queda el contador.
      return 0
    n = 0
    for canal, cuantas in cuenta:
      n += int(cuantas)
      self._silenciar(canal, int(cuantas))
    self._hay_posicion = False
    return n

  # ---------------------------------------------------------------------------- varios

  def _filas(self) -> int:
    if self._con is None:
      return 0
    try:
      return int(self._con.execute("SELECT COUNT(*) FROM cola").fetchone()[0])
    except (sqlite3.Error, TypeError, IndexError):
      return 0

  def hay_pendientes(self) -> bool:
    """True si queda algo por reenviar (en RAM o en disco)."""
    if not self.activo:
      return False
    with self._lock_ram:
      if self._pendientes:
        return True
    with self._lock_db:
      return self._filas() > 0

  def estado(self) -> dict:
    """Foto para el healthcheck. Barata: no recorre la cola."""
    with self._lock_ram:
      en_ram = len(self._pendientes)
    with self._lock_db:
      filas = self._filas()
      usados = self._bytes_usados() if self.activo else 0
    return {
      "activo": self.activo,
      "motivo": self.motivo,
      "ruta": self.ruta,
      "filas": filas,
      "en_ram": en_ram,
      "bytes": usados,
      "tope_bytes": self.tope_bytes,
      "contadores": dict(self._contadores),
    }

  def cerrar(self) -> None:
    """Vuelca lo pendiente y cierra. Idempotente."""
    if self.activo:
      try:
        self.flush()
      except Exception:
        cloudlog.exception("[ORBIT spool] flush de cierre fallido")
    with self._lock_db:
      con, self._con = self._con, None
      self.activo = False
      if con is not None:
        try:
          con.close()
        except sqlite3.Error:
          pass


# ------------------------------------------------------------------------- singleton

_spool = None
_spool_lock = threading.Lock()


def get_spool(**kwargs) -> Spool:
  """Instancia unica del proceso de telemetria. Los kwargs solo cuentan en la primera
  llamada (igual que get_command_plane)."""
  global _spool
  with _spool_lock:
    if _spool is None:
      _spool = Spool(**kwargs)
    return _spool
