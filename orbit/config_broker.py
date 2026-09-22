#!/usr/bin/env python3
"""Configuracion de CONEXION con el servidor ORBIT: broker, puerto, backend y credenciales.

EL PROBLEMA QUE CIERRA

`orbit/config_mqtt.json` va DENTRO del arbol git, con "broker": "" de fabrica, y la
pantalla del comma (Ajustes -> ORBIT -> Servidor ORBIT -> EDITAR, y el modal SERVIDOR
de la home) escribia la IP del usuario encima de ese mismo fichero. Cualquier cosa que
devuelva el arbol a su estado de git se la lleva por delante:

  * el updater de openpilot hace `git reset --hard` + `git clean -xdff` sobre el overlay
    de staging (system/updated/updated.py, fetch_update) y otro `git reset --hard` sobre
    la copia finalizada (finalize_update); en el siguiente arranque launch_chffrplus.sh
    mueve esa copia a /data/openpilot. Resultado: tras CADA actualizacion OTA el broker
    vuelve a "" y hay que teclear la IP otra vez. Es la causa del "a veces al arrancar
    hay que volver a poner la IP".
  * una reinstalacion, un `git checkout`/`git reset` por SSH: lo mismo.

Aqui lo que escribe el usuario vive FUERA del arbol, en /data (el mismo sitio que
orbit_camera_config.json y orbit_privacy.json), donde ni el updater ni git tocan nada:

    /data/orbit_config_mqtt.json    lo que el usuario cambio (solo esas claves)
    orbit/config_mqtt.json          plantilla de fabrica, tracked: valores por defecto

`leer_config()` devuelve la plantilla con lo persistido POR ENCIMA. Asi una actualizacion
que cambie un valor por defecto (backend_port, p. ej.) sigue llegando al coche, y el
broker sigue siendo el del usuario. Un valor persistido VACIO no tapa a la plantilla:
editar la plantilla por SSH (como dice el README) sigue funcionando mientras nadie haya
puesto otra cosa desde la pantalla.

MIGRACION: la primera vez que un proceso lee la config y no existe el fichero persistente,
si la plantilla del arbol trae un broker no vacio (un dispositivo con la IP puesta por el
codigo viejo, antes de que el updater la borre) se copia a /data. Una vez por proceso, y
solo si hay algo que salvar.

En el PC / simulador no hay /data escribible: se lee y se escribe la plantilla, como
siempre, y este modulo no cambia nada.

Todas las funciones son baratas (un stat, un JSON de cinco claves) pero TOCAN DISCO: quien
las llame desde un hilo caliente debe cachear (events_mqtt lo hace con TTL de 5 s).
"""
import json
import os
import tempfile
import threading

try:
  from openpilot.common.swaglog import cloudlog
except ImportError:  # herramientas sueltas o PC sin el entorno completo (sin zmq)
  import logging
  cloudlog = logging.getLogger("orbit.config_broker")

_HERE = os.path.dirname(os.path.realpath(__file__))
RUTA_PLANTILLA = os.path.join(_HERE, "config_mqtt.json")
DIR_PERSISTENTE = "/data"
RUTA_PERSISTENTE = os.path.join(DIR_PERSISTENTE, "orbit_config_mqtt.json")
# Durante el swap OTA launch_chffrplus conserva el arbol anterior aqui. Es la
# unica copia que aun contiene la IP escrita por las versiones antiguas: el
# arbol nuevo ya llega con la plantilla reseteada por git.
RUTAS_LEGACY = ("/data/safe_staging/old_openpilot/orbit/config_mqtt.json",)

# Lo unico que se persiste. Cualquier otra clave del fichero de /data se ignora al leer:
# en lo que no es del usuario manda la plantilla.
CLAVES = ("broker", "broker_port", "backend_port", "username", "password")

VALORES_POR_DEFECTO = {
  "broker": "",
  "broker_port": 1883,
  "backend_port": 8010,
  "username": "",
  "password": "",
}

_lock = threading.Lock()
_migracion_hecha = False


def _leer_json(ruta: str) -> dict:
  try:
    with open(ruta) as f:
      data = json.load(f)
    if isinstance(data, dict):
      return data
  except (OSError, ValueError):
    pass
  return {}


def _escribir_json(ruta: str, data: dict) -> bool:
  """mkstemp + fsync + rename: nunca un fichero a medias (los lectores lo abren en caliente)."""
  directorio = os.path.dirname(ruta)
  try:
    os.makedirs(directorio, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directorio, prefix=".orbit_config_mqtt.", suffix=".tmp")
    try:
      with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
      # Puede contener usuario y password del broker.
      os.chmod(tmp, 0o600)
      os.replace(tmp, ruta)
      try:
        dir_fd = os.open(directorio, os.O_RDONLY)
        try:
          os.fsync(dir_fd)
        finally:
          os.close(dir_fd)
      except OSError:
        pass
    except Exception:
      try:
        os.remove(tmp)
      except OSError:
        pass
      raise
  except OSError:
    cloudlog.exception(f"[Orbit] no se pudo escribir {ruta}")
    return False
  return True


def _vacio(valor) -> bool:
  return valor is None or (isinstance(valor, str) and not valor.strip())


def _data_escribible() -> bool:
  return os.path.isdir(DIR_PERSISTENTE) and os.access(DIR_PERSISTENTE, os.W_OK)


def ruta_config() -> str:
  """Fichero que hay que VIGILAR (mtime) y escribir. En el comma, el de /data, exista o no
  todavia; en el PC, la plantilla del arbol."""
  return RUTA_PERSISTENTE if _data_escribible() else RUTA_PLANTILLA


def _migrar_si_hace_falta() -> None:
  """Salva la conexion vieja, incluso tras la primera OTA que instala este fix."""
  global _migracion_hecha
  if _migracion_hecha:
    return
  with _lock:
    if _migracion_hecha:
      return
    if not _data_escribible() or os.path.exists(RUTA_PERSISTENTE):
      _migracion_hecha = True
      return
    for ruta_legacy in (RUTA_PLANTILLA, *RUTAS_LEGACY):
      legacy = _leer_json(ruta_legacy)
      if _vacio(legacy.get("broker")):
        continue
      salvar = {k: legacy[k] for k in CLAVES if k in legacy and not _vacio(legacy[k])}
      if _escribir_json(RUTA_PERSISTENTE, salvar):
        _migracion_hecha = True
        cloudlog.warning(f"[Orbit] broker migrado de {ruta_legacy} a {RUTA_PERSISTENTE}: {salvar.get('broker')}")
      # Si fallo la escritura se deja pendiente para reintentar en la proxima lectura.
      return
    _migracion_hecha = True  # no habia nada que salvar en ninguna copia


def leer_config() -> dict:
  """Plantilla + persistido por encima. Nunca lanza: sin ficheros devuelve los valores por
  defecto, y un fichero corrupto cuenta como ausente."""
  _migrar_si_hace_falta()
  cfg = dict(VALORES_POR_DEFECTO)
  cfg.update(_leer_json(RUTA_PLANTILLA))
  ruta = ruta_config()
  if ruta != RUTA_PLANTILLA:
    persistido = _leer_json(ruta)
    for k in CLAVES:
      if k in persistido and not _vacio(persistido[k]):
        cfg[k] = persistido[k]
  return cfg


def escribir_config(cambios: dict) -> bool:
  """Persiste `cambios` (solo CLAVES) preservando lo demas. Devuelve False si no pudo."""
  _migrar_si_hace_falta()
  ruta = ruta_config()
  # El lock cubre todo el read-modify-write: dos pantallas/procesos del mismo
  # interprete no pueden perder claves distintas entre lectura y replace.
  with _lock:
    actual = _leer_json(ruta)
    if ruta == RUTA_PLANTILLA:
      nuevo = dict(actual)  # PC: se edita la plantilla entera, como hasta ahora
    else:
      nuevo = {k: actual[k] for k in CLAVES if k in actual}
    for k, v in cambios.items():
      if k in CLAVES:
        nuevo[k] = v
    return _escribir_json(ruta, nuevo)
