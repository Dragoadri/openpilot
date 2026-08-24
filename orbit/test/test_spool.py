"""Cola persistente de telemetria y reenvio diferido (seccion 7 del diseno v2).

Lo que se comprueba aqui es lo que hoy no existe y por eso la telemetria sin cobertura se
tira:

    Llenado hasta el tope ................... nunca se pasa de los 32 MB (aqui, del tope
                                              pequeno de la prueba)
    Descarte por prioridad .................. 'event' y 'trip' sobreviven; 'vehicle' y
                                              'perception' son los que caen
    Tope lleno de criticos .................. se rechaza lo que entra, NO se tira lo que
                                              ya estaba guardado
    Decimacion .............................. media hora a 2 Hz no se vuelca entera al
                                              volver la cobertura
    Reapertura tras corrupcion .............. la base se recrea y el proceso sigue
    Disco lleno ............................. el spool se desactiva SOLO y no lanza
    Backfill y presencia .................... un reenvio NO marca el coche como conectado
    Privacidad al DRENAR .................... el interruptor tapa tambien lo que ya estaba
                                              encolado, con cobertura (drenar) y sin ella
                                              (purgar_posicion), con el spool DESACTIVADO
                                              (que es cuando el fichero se queda en la
                                              eMMC sin nadie que lo drene ni lo borre) y
                                              pulsandolo A MITAD de una tanda de 200
    Perdidas reportadas ..................... una fila aceptada que luego muere sale por
                                              canales_perdidos(): guardar()==True no es
                                              garantia de entrega

La ultima es la que importa de verdad: la app pinta "conectado" con la marca de tiempo de
la ultima telemetria, asi que un volcado de lo de hace una hora que refresque esa marca
convierte un coche apagado en un coche en linea.
"""
import dataclasses
import json
import os
import sqlite3
import threading

import pytest

from openpilot.orbit.spool import (CANALES_CRITICOS, CANALES_DECIMABLES, CANALES_ODOMETRIA, CANALES_POSICION,
                                   CANALES_SILENCIADOS, PRIO_CRITICA, PRIO_DECIMABLE, PRIO_NORMAL,
                                   MuestraSpool, Spool, prioridad_de)

T0 = 1_700_000_000_000   # epoch ms de referencia de las pruebas
DONGLE = "0123456789abcdef"


# --------------------------------------------------------------------------- utilidades

def _spool(tmp_path, **kwargs):
  s = Spool(ruta=str(tmp_path / "spool"), **kwargs)
  assert s.activo, s.motivo
  return s


def _cuerpo(relleno=300, **campos):
  d = {"relleno": "x" * relleno}
  d.update(campos)
  return d


def _por_prioridad(spool):
  return dict(spool._con.execute("SELECT prioridad, COUNT(*) FROM cola GROUP BY 1").fetchall())


class Publicador:
  """Doble del camino de publicacion de mqtt_envio_general, incluida la parte que MARCA
  PRESENCIA. Es a proposito: si el spool la tocase, se veria aqui."""

  def __init__(self, salen=True):
    self.vistas = []
    self.salen = salen
    self.last_seen_ms = None   # lo que la app lee como "conectado ahora"

  def __call__(self, muestra):
    if not self.salen:
      return False
    self.vistas.append(muestra)
    if not muestra.backfill:
      self.last_seen_ms = muestra.ts_ms   # SOLO la telemetria viva marca presencia
    return True


# --------------------------------------------------------------------------- prioridad

def test_prioridad_de_los_canales_de_la_seccion_7():
  assert CANALES_CRITICOS == {"event", "trip"}
  assert CANALES_DECIMABLES == {"vehicle", "perception"}
  for canal in CANALES_CRITICOS:
    assert prioridad_de(canal) == PRIO_CRITICA
  for canal in CANALES_DECIMABLES:
    assert prioridad_de(canal) == PRIO_DECIMABLE
  for canal in ("openpilot", "health", "road", "pos", "canal_que_no_existe"):
    assert prioridad_de(canal) == PRIO_NORMAL
  # El orden importa: la poda sacrifica de menor a mayor.
  assert PRIO_DECIMABLE < PRIO_NORMAL < PRIO_CRITICA


def test_pos_no_se_spoolea_por_defecto(tmp_path):
  s = _spool(tmp_path)
  assert s.guardar("pos", {"lat": 40.4, "lon": -3.7}, ts_ms=T0) is False
  assert s.flush() == 0
  assert s.estado()["contadores"]["no_spooleadas"] == 1

  s2 = Spool(ruta=str(tmp_path / "otro"), spool_pos=True)
  assert s2.guardar("pos", {"lat": 40.4, "lon": -3.7}, ts_ms=T0) is True
  assert s2.flush() == 1


# -------------------------------------------------------------------------- en memoria

def test_guardar_no_toca_el_disco(tmp_path):
  """guardar() se llama desde el bucle de telemetria: si escribiese, seria I/O de disco
  en el camino equivocado. Solo flush() baja a SQLite."""
  s = _spool(tmp_path)
  for i in range(10):
    assert s.guardar("vehicle", _cuerpo(), ts_ms=T0 + i)
  assert s.estado()["filas"] == 0
  assert s.estado()["en_ram"] == 10
  assert s.flush() == 10
  assert s.estado()["filas"] == 10
  assert s.estado()["en_ram"] == 0


def test_la_cola_en_ram_esta_acotada_y_no_tira_criticos(tmp_path):
  s = _spool(tmp_path, max_filas_ram=8)
  for i in range(4):
    assert s.guardar("event", _cuerpo(code=i), ts_ms=T0 + i)
  for i in range(40):
    s.guardar("vehicle", _cuerpo(), ts_ms=T0 + 100 + i)

  estado = s.estado()
  assert estado["en_ram"] <= 8
  assert estado["contadores"]["evictadas_ram"] > 0
  s.flush()
  # Los cuatro eventos siguen: en RAM solo se sacrifica lo no critico.
  assert s._con.execute("SELECT COUNT(*) FROM cola WHERE canal='event'").fetchone()[0] == 4


def test_ram_llena_de_criticos_rechaza_en_vez_de_tirar(tmp_path):
  s = _spool(tmp_path, max_filas_ram=4)
  for i in range(4):
    assert s.guardar("event", _cuerpo(code=i), ts_ms=T0 + i)
  assert s.guardar("event", _cuerpo(code=99), ts_ms=T0 + 99) is False
  assert s.estado()["contadores"]["rechazadas_ram"] == 1
  assert s.estado()["en_ram"] == 4


def test_cuerpo_invalido_se_rechaza(tmp_path):
  s = _spool(tmp_path)
  assert s.guardar("vehicle", "[1, 2, 3]", ts_ms=T0) is False          # JSON, pero no objeto
  assert s.guardar("vehicle", 42, ts_ms=T0) is False                   # ni siquiera JSON
  assert s.guardar("vehicle", {"x": float("nan")}, ts_ms=T0) is False  # NaN no es JSON valido
  assert s.guardar("vehicle", _cuerpo(relleno=200_000), ts_ms=T0) is False
  assert s.estado()["contadores"]["rechazadas_cuerpo"] == 4
  assert s.flush() == 0


# ------------------------------------------------------------------------ tope y poda

def test_llenado_hasta_el_tope_no_pasa_del_tope(tmp_path):
  tope = 128 * 1024
  s = _spool(tmp_path, tope_bytes=tope, max_filas_ram=64)
  for i in range(600):
    s.guardar("vehicle", _cuerpo(v=i), ts_ms=T0 + i * 500)
    if i % 20 == 0:
      s.flush()
      assert s.estado()["bytes"] <= tope
  s.flush()

  estado = s.estado()
  assert estado["activo"] is True
  assert estado["bytes"] <= tope
  assert estado["filas"] < 600                      # ha habido poda de verdad
  assert estado["contadores"]["evictadas_disco"] > 0


def test_descarte_por_prioridad_event_y_trip_sobreviven(tmp_path):
  tope = 128 * 1024
  s = _spool(tmp_path, tope_bytes=tope, max_filas_ram=64)
  criticos = 0
  for i in range(600):
    s.guardar("vehicle", _cuerpo(v=i), ts_ms=T0 + i * 500)
    s.guardar("perception", _cuerpo(lead=i), ts_ms=T0 + i * 500)
    if i % 60 == 0:
      s.guardar("event", _cuerpo(relleno=50, code=i), ts_ms=T0 + i * 500)
      s.guardar("trip", _cuerpo(relleno=50, trip=i), ts_ms=T0 + i * 500)
      criticos += 2
    if i % 20 == 0:
      s.flush()
  s.flush()

  assert s.estado()["bytes"] <= tope
  assert s.estado()["contadores"]["evictadas_disco"] > 0
  # Ni un solo critico se ha ido; los decimables son los que han pagado la poda.
  vivos = dict(s._con.execute("SELECT canal, COUNT(*) FROM cola GROUP BY 1").fetchall())
  assert vivos.get("event", 0) == criticos // 2
  assert vivos.get("trip", 0) == criticos // 2
  assert vivos.get("vehicle", 0) + vivos.get("perception", 0) < 1200


def test_normales_caen_antes_que_criticos(tmp_path):
  """Sin decimables que sacrificar, la poda pasa a los normales; los criticos siguen sin
  tocarse."""
  tope = 96 * 1024
  s = _spool(tmp_path, tope_bytes=tope, max_filas_ram=32)
  for i in range(400):
    s.guardar("health", _cuerpo(h=i), ts_ms=T0 + i * 500)
    if i % 40 == 0:
      s.guardar("event", _cuerpo(relleno=50, code=i), ts_ms=T0 + i * 500)
    if i % 10 == 0:
      s.flush()
  s.flush()

  por_prio = _por_prioridad(s)
  assert por_prio.get(PRIO_CRITICA, 0) == 10
  assert por_prio.get(PRIO_NORMAL, 0) < 400
  assert s.estado()["bytes"] <= tope


def test_tope_lleno_de_criticos_rechaza_lo_nuevo_y_no_tira_lo_viejo(tmp_path):
  """'event' y 'trip' NUNCA se descartan. Cuando el tope se alcanza y ya no queda nada
  sacrificable, lo que se rechaza es lo que ENTRA."""
  tope = 96 * 1024
  s = _spool(tmp_path, tope_bytes=tope, max_filas_ram=16)
  guardadas = 0
  for i in range(400):
    s.guardar("event", _cuerpo(relleno=400, code=i), ts_ms=T0 + i * 100)
    if i % 10 == 0:
      s.flush()
      filas = s.estado()["filas"]
      assert filas >= guardadas   # jamas baja: lo guardado no se descarta
      guardadas = filas
  s.flush()

  estado = s.estado()
  assert estado["activo"] is True
  assert estado["bytes"] <= tope
  assert estado["contadores"]["evictadas_disco"] == 0
  assert estado["contadores"]["rechazadas_tope"] > 0
  # El primer evento que entro sigue estando.
  assert s._con.execute("SELECT MIN(id) FROM cola").fetchone()[0] == 1


# ------------------------------------------------------------------------- decimacion

def test_decimacion_al_reenviar(tmp_path):
  """Media hora de 'vehicle' a 2 Hz no se vuelca entera cuando vuelve la cobertura."""
  s = _spool(tmp_path, ventana_decimacion_ms=5000)
  for i in range(3600):                      # 30 min a 2 Hz
    s.guardar("vehicle", _cuerpo(relleno=20, v=i), ts_ms=T0 + i * 500)
    if i % 100 == 0:
      s.flush()                              # el bucle de 1 Hz del hilo ORBIT
  s.flush()
  assert s.estado()["filas"] == 3600

  pub = Publicador()
  total = 0
  while True:
    res = s.drenar(pub, max_filas=500)
    total += res.publicadas
    if res.restantes == 0:
      break
  assert total == 360                        # 30 min / 5 s
  assert s.estado()["contadores"]["decimadas"] == 3600 - 360

  # Y lo reenviado esta repartido en el tiempo, no son los 360 primeros.
  ts = [m.ts_ms for m in pub.vistas]
  assert ts == sorted(ts)
  assert all(b - a >= 5000 for a, b in zip(ts, ts[1:], strict=False))
  assert ts[-1] - ts[0] >= 1_790_000        # cubre casi los 30 min


def test_los_criticos_no_se_deciman_y_salen_primero(tmp_path):
  s = _spool(tmp_path, ventana_decimacion_ms=5000)
  for i in range(20):
    s.guardar("vehicle", _cuerpo(relleno=20, v=i), ts_ms=T0 + i * 500)
    s.guardar("event", _cuerpo(relleno=20, code=i), ts_ms=T0 + i * 500)
    s.guardar("trip", _cuerpo(relleno=20, trip=i), ts_ms=T0 + i * 500)
  s.flush()

  pub = Publicador()
  res = s.drenar(pub, max_filas=1000)
  canales = [m.canal for m in pub.vistas]
  assert canales.count("event") == 20        # ni uno decimado
  assert canales.count("trip") == 20
  assert canales.count("vehicle") == 2       # 10 s de muestras / ventana de 5 s
  assert res.decimadas == 18
  # Los criticos salen antes: si la cobertura se cae otra vez, ya han salido.
  assert set(canales[:40]) == {"event", "trip"}


def test_la_decimacion_arranca_de_cero_en_cada_ventana_sin_cobertura(tmp_path):
  s = _spool(tmp_path, ventana_decimacion_ms=5000)
  s.guardar("vehicle", _cuerpo(relleno=20), ts_ms=T0)
  s.flush()
  pub = Publicador()
  assert s.drenar(pub).publicadas == 1
  assert s.estado()["filas"] == 0

  # Segundo corte de cobertura, con muestras separadas menos de la ventana del anterior.
  s.guardar("vehicle", _cuerpo(relleno=20), ts_ms=T0 + 1000)
  s.flush()
  assert s.drenar(pub).publicadas == 1


# ---------------------------------------------------------------- backfill y presencia

def test_el_backfill_no_toca_la_presencia(tmp_path):
  """Un coche que reenvia lo de hace una hora NO esta conectado ahora."""
  s = _spool(tmp_path, ventana_decimacion_ms=0)
  hace_una_hora = T0 - 3_600_000
  for i in range(5):
    s.guardar("vehicle", _cuerpo(relleno=20, v=i), ts_ms=hace_una_hora + i * 500, dongle=DONGLE)
  s.guardar("event", _cuerpo(relleno=20, code=7), ts_ms=hace_una_hora, dongle=DONGLE)
  s.flush()

  pub = Publicador()
  res = s.drenar(pub, dongle=DONGLE, max_filas=100)
  assert res.publicadas == 6
  # 1) el publicador nunca vio una muestra que se pudiese confundir con telemetria viva
  assert pub.last_seen_ms is None
  # 2) la marca va en el OBJETO
  assert all(m.backfill is True for m in pub.vistas)
  # 3) y tambien DENTRO del cuerpo JSON que se publica, que es lo que ve el backend
  for m in pub.vistas:
    datos = json.loads(m.cuerpo)
    assert datos["backfill"] is True
    assert datos["ts_ms"] == m.ts_ms
    # 4) el sello es el de la CAPTURA, no el de ahora
    assert datos["ts_ms"] <= hace_una_hora + 5000


def test_el_reenvio_conserva_el_cuerpo_original(tmp_path):
  s = _spool(tmp_path)
  s.guardar("openpilot", {"engaged": True, "alerta": None, "vEgo": 12.5}, ts_ms=T0)
  s.flush()
  pub = Publicador()
  s.drenar(pub)
  datos = json.loads(pub.vistas[0].cuerpo)
  assert datos["engaged"] is True
  assert datos["alerta"] is None
  assert datos["vEgo"] == 12.5
  assert datos["backfill"] is True


def test_muestras_de_otro_dongle_no_se_reenvian(tmp_path):
  """Tras un re-enrolamiento, la telemetria del dongle anterior no se puede atribuir al
  nuevo: seria un vehiculo contando kilometros de otro."""
  s = _spool(tmp_path)
  s.guardar("event", _cuerpo(relleno=20, code=1), ts_ms=T0, dongle="viejo")
  s.guardar("event", _cuerpo(relleno=20, code=2), ts_ms=T0 + 1, dongle=DONGLE)
  s.guardar("event", _cuerpo(relleno=20, code=3), ts_ms=T0 + 2)   # sin identidad: se reenvia
  s.flush()

  pub = Publicador()
  res = s.drenar(pub, dongle=DONGLE)
  assert res.otro_dongle == 1
  assert res.publicadas == 2
  assert [json.loads(m.cuerpo)["code"] for m in pub.vistas] == [2, 3]
  assert s.estado()["filas"] == 0


# ------------------------------------------------------------------------ corte y fallo

def test_si_el_publish_no_sale_no_se_borra_nada(tmp_path):
  s = _spool(tmp_path, ventana_decimacion_ms=0)
  for i in range(5):
    s.guardar("event", _cuerpo(relleno=20, code=i), ts_ms=T0 + i)
  s.flush()

  pub = Publicador(salen=False)
  res = s.drenar(pub)
  assert res.corte is True
  assert res.publicadas == 0
  assert s.estado()["filas"] == 5     # se conserva entero

  pub.salen = True
  res = s.drenar(pub)
  assert res.publicadas == 5
  assert s.estado()["filas"] == 0


def test_un_corte_a_media_tanda_no_decima_la_muestra_que_no_salio(tmp_path):
  """La ventana de decimacion solo avanza con lo que SALIO. Si avanzase al intentarlo, la
  muestra que se quedo se decimaria a si misma en la pasada siguiente y se perderia."""
  s = _spool(tmp_path, ventana_decimacion_ms=5000)
  s.guardar("vehicle", _cuerpo(relleno=20, v=1), ts_ms=T0)
  s.guardar("vehicle", _cuerpo(relleno=20, v=2), ts_ms=T0 + 6000)
  s.flush()

  class UnaYCae:
    def __init__(self):
      self.vistas = []
    def __call__(self, m):
      if len(self.vistas) >= 1:
        return False
      self.vistas.append(m)
      return True

  pub = UnaYCae()
  res = s.drenar(pub)
  assert res.publicadas == 1 and res.corte is True
  assert s.estado()["filas"] == 1

  pub2 = Publicador()
  res = s.drenar(pub2)
  assert res.publicadas == 1
  assert res.decimadas == 0
  assert json.loads(pub2.vistas[0].cuerpo)["v"] == 2


def test_un_publicador_que_lanza_no_rompe_el_drenaje(tmp_path):
  s = _spool(tmp_path)
  s.guardar("event", _cuerpo(relleno=20, code=1), ts_ms=T0)
  s.flush()

  def revienta(_muestra):
    raise RuntimeError("el socket se fue")

  res = s.drenar(revienta)
  assert res.corte is True
  assert s.estado()["filas"] == 1


def test_una_fila_ilegible_se_descarta_sin_atascar_la_cola(tmp_path):
  s = _spool(tmp_path)
  s.guardar("event", _cuerpo(relleno=20, code=1), ts_ms=T0)
  s.flush()
  # Corrupcion a nivel de fila (bitrot, escritura a medias): no puede dejar la cola
  # atascada para siempre reintentando la misma fila.
  s._con.execute("INSERT INTO cola(canal, prioridad, ts_ms, cuerpo, dongle) VALUES ('event', 2, ?, '{no soy json', '')", (T0,))

  pub = Publicador()
  res = s.drenar(pub)
  assert res.ilegibles == 1
  assert res.publicadas == 1
  assert s.estado()["filas"] == 0


# ------------------------------------------------------------- corrupcion y disco lleno

def test_reapertura_tras_corrupcion(tmp_path):
  ruta = str(tmp_path / "spool")
  s = Spool(ruta=ruta)
  assert s.guardar("event", _cuerpo(relleno=20, code=1), ts_ms=T0)
  assert s.flush() == 1
  s.cerrar()

  with open(os.path.join(ruta, "spool.db"), "r+b") as f:
    f.seek(0)
    f.write(b"esto no es una base de datos" * 20)

  s2 = Spool(ruta=ruta)
  # La base se recrea: se pierde lo diferido, pero el spool arranca y sigue sirviendo.
  assert s2.activo is True
  assert s2.motivo == ""
  assert s2.estado()["filas"] == 0

  assert s2.guardar("event", _cuerpo(relleno=20, code=2), ts_ms=T0 + 1)
  assert s2.flush() == 1
  pub = Publicador()
  assert s2.drenar(pub).publicadas == 1
  assert json.loads(pub.vistas[0].cuerpo)["code"] == 2


def test_base_de_datos_de_una_version_anterior_se_reutiliza(tmp_path):
  """Reapertura normal: lo diferido de un arranque anterior sigue ahi."""
  ruta = str(tmp_path / "spool")
  s = Spool(ruta=ruta)
  s.guardar("trip", _cuerpo(relleno=20, trip=1), ts_ms=T0)
  s.flush()
  s.cerrar()

  s2 = Spool(ruta=ruta)
  assert s2.activo is True
  assert s2.estado()["filas"] == 1
  pub = Publicador()
  assert s2.drenar(pub).publicadas == 1


def test_disco_lleno_desactiva_el_spool_sin_lanzar(tmp_path):
  """Si el disco se llena, el spool se apaga SOLO. Lo que no puede hacer es tumbar la
  telemetria viva propagando la excepcion al bucle de publicacion."""
  s = _spool(tmp_path)

  class ConexionLlena:
    def __init__(self, real):
      self._real = real
    def execute(self, *args, **kwargs):
      raise sqlite3.OperationalError("database or disk is full")
    def executemany(self, *args, **kwargs):
      raise sqlite3.OperationalError("database or disk is full")
    def close(self):
      self._real.close()

  s._con = ConexionLlena(s._con)
  assert s.guardar("vehicle", _cuerpo(), ts_ms=T0) is True   # RAM, todavia no se sabe
  assert s.flush() == 0

  estado = s.estado()
  assert estado["activo"] is False
  assert "disk is full" in estado["motivo"]

  # Desactivado = no-op absoluto, nunca una excepcion hacia el llamante.
  assert s.guardar("event", _cuerpo(), ts_ms=T0) is False
  assert s.flush() == 0
  assert s.drenar(Publicador()).publicadas == 0
  assert s.hay_pendientes() is False
  s.cerrar()


def test_ruta_imposible_desactiva_el_spool(tmp_path):
  s = Spool(ruta=str(tmp_path / "fichero"))   # se crea como fichero, no como directorio
  s.cerrar()
  (tmp_path / "bloqueado").write_text("no soy un directorio")
  s2 = Spool(ruta=str(tmp_path / "bloqueado"))
  assert s2.activo is False
  assert s2.motivo
  assert s2.guardar("event", _cuerpo(), ts_ms=T0) is False
  assert s2.estado()["activo"] is False


def test_errores_transitorios_no_matan_el_spool_a_la_primera(tmp_path):
  """Un error de SQLite que no es ni disco lleno ni corrupcion (p. ej. 'database is
  locked') no puede apagar el spool en el primer intento."""
  s = _spool(tmp_path)
  real = s._con

  class ConexionOcupada:
    def __init__(self, real):
      self._real = real
      self.fallos = 0
    def execute(self, sql, *args, **kwargs):
      if sql.startswith("BEGIN"):
        self.fallos += 1
        raise sqlite3.OperationalError("database is locked")
      return self._real.execute(sql, *args, **kwargs)
    def executemany(self, *args, **kwargs):
      return self._real.executemany(*args, **kwargs)
    def close(self):
      self._real.close()

  s._con = ConexionOcupada(real)
  for _ in range(3):
    s.guardar("vehicle", _cuerpo(), ts_ms=T0)
    assert s.flush() == 0
    assert s.activo is True

  s._con = real
  assert s.guardar("vehicle", _cuerpo(), ts_ms=T0)
  assert s.flush() == 1
  assert s.activo is True


# ------------------------------------------------------------------------------ estado

def test_estado_es_serializable_para_el_healthcheck(tmp_path):
  s = _spool(tmp_path)
  s.guardar("event", _cuerpo(relleno=20, code=1), ts_ms=T0)
  s.flush()
  estado = s.estado()
  json.dumps(estado)   # va dentro del healthcheck: tiene que ser JSON puro
  assert estado["filas"] == 1
  assert estado["bytes"] > 0
  assert estado["tope_bytes"] == 32 * 1024 * 1024
  assert estado["contadores"]["escritas"] == 1
  assert s.hay_pendientes() is True


def test_muestra_es_inmutable():
  m = MuestraSpool(canal="event", cuerpo="{}", ts_ms=T0)
  assert m.backfill is True
  with pytest.raises(dataclasses.FrozenInstanceError):
    m.canal = "vehicle"


def test_pragmas_del_diseno(tmp_path):
  """WAL + synchronous=NORMAL es lo que dice la seccion 7. auto_vacuum incremental no lo
  dice, pero sin el borrar filas no devuelve espacio al sistema de ficheros y el tope de
  32 MB no se podria respetar nunca."""
  s = _spool(tmp_path)
  assert s._con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
  assert s._con.execute("PRAGMA synchronous").fetchone()[0] == 1   # NORMAL
  assert s._con.execute("PRAGMA auto_vacuum").fetchone()[0] == 2   # INCREMENTAL


def test_el_flush_hace_un_solo_commit_por_lote(tmp_path):
  """Commit por LOTES: 200 muestras son una transaccion, no 200. En eMMC la diferencia
  es entre un fsync y doscientos."""
  s = _spool(tmp_path)

  class ConexionContada:
    def __init__(self, real):
      self._real = real
      self.begins = 0
      self.commits = 0
    def execute(self, sql, *args, **kwargs):
      if sql.startswith("BEGIN"):
        self.begins += 1
      elif sql.startswith("COMMIT"):
        self.commits += 1
      return self._real.execute(sql, *args, **kwargs)
    def executemany(self, *args, **kwargs):
      return self._real.executemany(*args, **kwargs)
    def close(self):
      self._real.close()

  contada = ConexionContada(s._con)
  s._con = contada
  for i in range(200):
    s.guardar("vehicle", _cuerpo(relleno=20, v=i), ts_ms=T0 + i)
  assert s.flush() == 200
  assert contada.begins == 1
  assert contada.commits == 1


def test_guardar_desde_otro_hilo_mientras_se_vuelca(tmp_path):
  """guardar() lo llama el bucle de telemetria y flush()/drenar() pueden estar en marcha:
  no se puede perder ni duplicar una muestra por eso."""
  s = _spool(tmp_path, max_filas_ram=100_000)
  fin = threading.Event()
  guardadas = []

  def productor():
    for i in range(2000):
      if s.guardar("event", _cuerpo(relleno=20, code=i), ts_ms=T0 + i):
        guardadas.append(i)
    fin.set()

  hilo = threading.Thread(target=productor)
  hilo.start()
  escritas = 0
  while not fin.is_set():
    escritas += s.flush()
  hilo.join()
  escritas += s.flush()

  assert len(guardadas) == 2000
  assert escritas == 2000
  assert s.estado()["filas"] == 2000
  codigos = [r[0] for r in s._con.execute("SELECT json_extract(cuerpo, '$.code') FROM cola ORDER BY id")]
  assert codigos == list(range(2000))


# ------------------------------------------------------------------------ privacidad

def _encolar_traza(s, calles=("Calle Mayor", "Gran Via", "Paseo del Prado")):
  """Lo que deja en la cola un rato circulando sin cobertura: por donde se va y a que
  velocidad. `road` es on-change, asi que cada via distinta es un mensaje."""
  for i, calle in enumerate(calles):
    assert s.guardar("road", _cuerpo(0, d={"road_name": calle}), ts_ms=T0 + i * 1000)
  assert s.guardar("vehicle", _cuerpo(0, d={"speed_kph": 50.0}), ts_ms=T0)
  return len(calles)


def test_los_canales_de_posicion_incluyen_la_derivada():
  """`road` no es menos posicion por ser derivada: la secuencia de nombres de via ES el
  recorrido. Si solo estuviera `pos`, el drenaje seguiria publicando la traza."""
  assert CANALES_POSICION == {"pos", "road"}


def test_el_mute_puesto_DESPUES_de_encolar_no_publica_la_secuencia_de_calles(tmp_path):
  """El caso que el filtro de la CAPTURA no puede ver, porque pasa despues de capturar:
  el coche circula sin cobertura y encola N mensajes `road`, el conductor pulsa el
  interruptor, y vuelve la cobertura. Sin comprobar la privacidad al drenar sale la
  secuencia entera de nombres de calle, que es la traza reconstruida."""
  s = _spool(tmp_path)
  calles = _encolar_traza(s)
  s.flush()

  pub = Publicador()
  res = s.drenar(pub, privacidad=True)
  assert res.privadas == calles
  assert [m.canal for m in pub.vistas] == ["vehicle"], "el mute es de POSICION, no de todo"
  assert "Calle Mayor" not in json.dumps([m.cuerpo for m in pub.vistas])

  # Y no se CONSERVA: quitar el interruptor despues no puede resucitar la traza.
  pub2 = Publicador()
  assert s.drenar(pub2, privacidad=False).publicadas == 0
  assert pub2.vistas == []
  assert s.estado()["filas"] == 0
  assert s.estado()["contadores"]["descartadas_privacidad"] == calles


def test_la_purga_de_privacidad_no_espera_a_que_vuelva_la_cobertura(tmp_path):
  """Filtrar SOLO al drenar deja un agujero: sin enlace no se drena nada, asi que un mute
  pulsado en mitad del corte deja la traza en disco, lista para salir entera en cuanto el
  conductor lo quite antes de recuperar cobertura."""
  s = _spool(tmp_path)
  calles = _encolar_traza(s)
  s.flush()

  assert s.purgar_posicion() == calles
  assert s.estado()["filas"] == 1                    # la muestra de `vehicle` sigue
  pub = Publicador()
  s.drenar(pub, privacidad=False)                    # el interruptor ya no esta puesto
  assert [m.canal for m in pub.vistas] == ["vehicle"]
  assert s.purgar_posicion() == 0
  assert s.estado()["contadores"]["descartadas_privacidad"] == calles


def test_la_purga_alcanza_lo_que_sigue_en_ram_y_tambien_pos(tmp_path):
  """La cola de RAM tambien tiene posicion entre flush y flush."""
  s = Spool(ruta=str(tmp_path / "spool"), spool_pos=True)
  assert s.activo, s.motivo
  try:
    assert s.guardar("pos", _cuerpo(0, d={"lat": 40.4, "lon": -3.7}), ts_ms=T0)
    assert s.guardar("road", _cuerpo(0, d={"road_name": "Gran Via"}), ts_ms=T0)
    assert s.guardar("health", _cuerpo(0, d={"temp_c": 40}), ts_ms=T0)
    assert s.estado()["en_ram"] == 3

    assert s.purgar_posicion() == 2                  # sin pasar por disco
    assert s.estado()["en_ram"] == 1
    assert s.flush() == 1
    assert s.canales_perdidos() == {"pos": 1, "road": 1}
  finally:
    s.cerrar()


# --------------------------------------------------------------------------- perdidas

def test_la_eviccion_de_ram_reporta_la_fila_que_tira(tmp_path):
  """guardar() ya habia devuelto True por ella, asi que el llamante dejo puesto el sello
  del canal on-change y dio el estado por entregado."""
  s = _spool(tmp_path, max_filas_ram=2)
  assert s.guardar("openpilot", _cuerpo(0, d={"eng": True}), ts_ms=T0)
  assert s.guardar("road", _cuerpo(0, d={"road_name": "Gran Via"}), ts_ms=T0)
  assert s.guardar("event", _cuerpo(0, code=1), ts_ms=T0)   # entra evictando la mas vieja

  assert s.estado()["contadores"]["evictadas_ram"] == 1
  assert s.canales_perdidos() == {"openpilot": 1}
  assert s.canales_perdidos() == {}, "canales_perdidos() vacia el registro al leerlo"


def test_la_poda_del_disco_reporta_lo_que_tira_por_canal(tmp_path):
  """`openpilot` y `road` son PRIO_NORMAL: la poda se los lleva cuando no quedan
  decimables, y hasta ahora desaparecian sin que nadie se enterase."""
  s = _spool(tmp_path, tope_bytes=96 * 1024, max_filas_ram=32)
  for i in range(400):
    s.guardar("openpilot", _cuerpo(v=i), ts_ms=T0 + i * 500)
    if i % 10 == 0:
      s.flush()
  s.flush()

  podadas = s.estado()["contadores"]["evictadas_disco"]
  assert podadas > 0
  assert s.canales_perdidos() == {"openpilot": podadas}


def test_los_criticos_nuevos_rechazados_por_el_tope_no_desaparecen_en_silencio(tmp_path):
  """'event' y 'trip' no se descartan NUNCA una vez escritos, y eso sigue siendo verdad.
  Lo que se rechaza con la cola llena de criticos es lo que ENTRA -- y guardar() ya habia
  dicho True por ello, asi que la perdida era invisible desde fuera. No se puede deshacer
  (son mensajes unicos): lo unico que se puede hacer es contarla y decirla."""
  s = _spool(tmp_path, tope_bytes=96 * 1024, max_filas_ram=16)
  for i in range(400):
    s.guardar("event", _cuerpo(relleno=400, code=i), ts_ms=T0 + i * 100)
    if i % 10 == 0:
      s.flush()
  s.flush()

  cont = s.estado()["contadores"]
  assert cont["evictadas_disco"] == 0          # lo guardado sigue intacto
  assert cont["rechazadas_tope"] > 0
  assert cont["perdidas_criticas"] == cont["rechazadas_tope"]
  assert s.canales_perdidos() == {"event": cont["rechazadas_tope"]}


def test_un_fallo_de_escritura_reporta_el_lote_entero(tmp_path):
  s = _spool(tmp_path)

  class ConexionQueNoEscribe:
    def __init__(self, real):
      self._real = real
    def execute(self, sql, *args, **kwargs):
      return self._real.execute(sql, *args, **kwargs)
    def executemany(self, *args, **kwargs):
      raise sqlite3.OperationalError("database is locked")
    def close(self):
      self._real.close()

  s._con = ConexionQueNoEscribe(s._con)
  assert s.guardar("openpilot", _cuerpo(0, d={"eng": True}), ts_ms=T0)
  assert s.guardar("event", _cuerpo(0, code=1), ts_ms=T0)
  assert s.flush() == 0
  assert s.activo is True                      # 'locked' no es fatal

  assert s.estado()["contadores"]["perdidas_error"] == 2
  assert s.canales_perdidos() == {"openpilot": 1, "event": 1}
  assert s.estado()["contadores"]["perdidas_criticas"] == 1


def test_el_apagado_en_caliente_reporta_lo_que_tira_de_la_ram(tmp_path):
  """_desactivar() vacia la cola de RAM: esas filas tambien se aceptaron y tambien mueren.
  Y el registro se lee con el spool ya desactivado, que es cuando hace falta."""
  s = _spool(tmp_path)
  assert s.guardar("openpilot", _cuerpo(0, d={"eng": True}), ts_ms=T0)
  assert s.guardar("road", _cuerpo(0, d={"road_name": "Gran Via"}), ts_ms=T0)

  s._desactivar("disco lleno de mentira")
  assert s.activo is False
  assert s.canales_perdidos() == {"openpilot": 1, "road": 1}


def _matar_spool(s, mensaje="database or disk is full"):
  """Deja el spool DESACTIVADO como lo dejaria un disco lleno, pero con su fichero intacto
  en el disco: exactamente el estado en el que el interruptor se quedaba sin efecto."""
  real = s._con

  class ConexionRota:
    def __init__(self, real):
      self._real = real
    def execute(self, *args, **kwargs):
      raise sqlite3.OperationalError(mensaje)
    def executemany(self, *args, **kwargs):
      raise sqlite3.OperationalError(mensaje)
    def close(self):
      self._real.close()

  s._con = ConexionRota(real)
  s.guardar("vehicle", _cuerpo(), ts_ms=T0)
  s.flush()
  assert s.activo is False, s.motivo
  return s


def test_el_mute_alcanza_la_cola_con_el_spool_DESACTIVADO(tmp_path):
  """El agujero que dejaba abierta la capa anterior. drenar() salia por `if not self.activo`
  en su primera linea y la mitad de DISCO de purgar_posicion() estaba detras del mismo
  `not self.activo`; y _desactivar() cierra la conexion pero NO borra el fichero. Con el
  disco lleno o la base corrupta, las filas `road` ya escritas se quedaban en la eMMC con el
  mute puesto hasta que reiniciase el proceso -- y si para entonces el conductor lo habia
  quitado, el arranque siguiente las publicaba enteras."""
  s = _spool(tmp_path)
  calles = _encolar_traza(s)
  assert s.flush() == calles + 1
  _matar_spool(s)

  # El fichero SIGUE AHI: es lo que hace que esto importe.
  ruta = s._ruta_db()
  assert os.path.exists(ruta)
  con = sqlite3.connect(ruta)
  assert con.execute("SELECT COUNT(*) FROM cola WHERE canal='road'").fetchone()[0] == calles
  con.close()

  assert s.purgar_posicion() == calles
  con = sqlite3.connect(ruta)
  try:
    assert con.execute("SELECT COUNT(*) FROM cola WHERE canal='road'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM cola WHERE canal='vehicle'").fetchone()[0] == 1, \
      "el mute es de posicion, no un borrado de la cola entera"
  finally:
    con.close()
  assert s.estado()["contadores"]["descartadas_privacidad"] == calles
  # Y sigue desactivado: purgar no resucita el spool.
  assert s.activo is False


def test_si_la_base_no_se_puede_ni_abrir_la_purga_borra_el_fichero(tmp_path):
  """Segundo intento de _purgar_sin_conexion. Con la base corrupta no hay forma de borrar
  solo las filas de posicion, y dejarla escrita significa que el arranque siguiente la
  encuentre. Se tira entera y se dice en el log: el interruptor es una ORDEN, y un spool
  desactivado no vuelve a drenar en toda la vida del proceso."""
  s = _spool(tmp_path)
  _encolar_traza(s)
  s.flush()
  ruta = s._ruta_db()
  _matar_spool(s)

  with open(ruta, "wb") as f:
    f.write(b"esto ya no es una base de datos" * 100)

  assert s.purgar_posicion() == 0            # no se sabe cuantas habia: no se podia leer
  assert not os.path.exists(ruta)
  assert s.estado()["contadores"]["purgas_destructivas"] == 1


def test_pulsar_el_mute_a_MITAD_de_tanda_corta_la_tanda(tmp_path):
  """Una tanda son hasta 200 publicaciones seguidas. Leyendo el interruptor UNA vez al
  empezar, pulsarlo dentro de la tanda no la cortaba y seguian saliendo nombres de calle
  detras del "ya no emito"."""
  s = _spool(tmp_path)
  for i in range(6):
    assert s.guardar("road", _cuerpo(0, d={"road_name": f"Calle {i}"}), ts_ms=T0 + i * 1000)
  s.flush()

  interruptor = {"puesto": False}

  class PublicadorQuePulsa(Publicador):
    def __call__(self, muestra):
      salio = super().__call__(muestra)
      if len(self.vistas) == 2:
        interruptor["puesto"] = True     # el conductor lo pulsa aqui
      return salio

  pub = PublicadorQuePulsa()
  res = s.drenar(pub, privacidad=lambda: interruptor["puesto"])
  assert len(pub.vistas) == 2, "el mute tiene que cortar la tanda en curso"
  assert res.publicadas == 2
  assert res.privadas == 4
  assert s.estado()["filas"] == 0, "lo silenciado no se conserva esperando a que se quite"


def test_un_testigo_que_lanza_conserva_el_ultimo_valor(tmp_path):
  """Ni encender el silencio por un error transitorio (tiraria telemetria que nadie pidio
  tirar) ni apagarlo (publicaria lo que el conductor acaba de silenciar)."""
  s = _spool(tmp_path)
  _encolar_traza(s)
  s.flush()

  def testigo():
    raise RuntimeError("Params no responde")

  pub = Publicador()
  res = s.drenar(pub, privacidad=testigo)
  assert res.privadas == 0 and res.publicadas == 4, "sin valor previo, no se silencia nada"


def test_el_resumen_de_viaje_tambien_se_calla_con_el_mute(tmp_path):
  """DECISION documentada: `trip` no es posicion (dist_km, v_max_kph, v_med_kph: ni una
  coordenada), pero "43,2 km entre las 22:15 y las 22:47" leido junto al sitio donde el
  coche duerme reconstruye el trayecto. La seccion 9 pide "posicion y camara COMO MINIMO".

  Lo delicado es que `trip` es PRIO_CRITICA: "los criticos jamas se descartan" protege
  contra PERDIDAS DEL SISTEMA, no contra un silencio PEDIDO por quien va dentro. Por eso el
  descarte no cuenta como perdida critica ni grita en el log."""
  assert "trip" in CANALES_SILENCIADOS and "trip" in CANALES_ODOMETRIA
  assert "trip" not in CANALES_POSICION, "no es posicion; se silencia por otro motivo"
  assert "trip" in CANALES_CRITICOS

  s = _spool(tmp_path)
  assert s.guardar("trip", _cuerpo(0, d={"ev": "end", "dist_km": 43.2}), ts_ms=T0)
  assert s.guardar("event", _cuerpo(0, d={"code": 1}), ts_ms=T0 + 1)
  s.flush()

  pub = Publicador()
  res = s.drenar(pub, privacidad=True)
  assert res.privadas == 1
  assert [m.canal for m in pub.vistas] == ["event"], "el mute no calla los eventos"

  c = s.estado()["contadores"]
  assert c["descartadas_privacidad"] == 1
  assert c["silenciadas_criticas"] == 1
  assert c["perdidas_criticas"] == 0, "un silencio PEDIDO no es una perdida"
  assert "trip" not in s.canales_perdidos(), "no hay sello que deshacer ni alarma que dar"


def test_la_purga_baja_a_disco_aunque_lo_encolado_sea_solo_trip(tmp_path):
  """`_hay_posicion` es el atajo que evita barrer 32 MB cada segundo. Si mirase solo
  CANALES_POSICION, un lote de solo `trip` lo dejaria en False y la purga no bajaria."""
  s = _spool(tmp_path)
  assert s.guardar("trip", _cuerpo(0, d={"ev": "end", "dist_km": 43.2}), ts_ms=T0)
  assert s.flush() == 1
  s._hay_posicion = False          # como si el flush no lo hubiera marcado
  s.flush()                        # no hay nada que volcar: el flag lo pone el lote
  s._hay_posicion = True
  assert s.purgar_posicion() == 1
  assert s.estado()["filas"] == 0
