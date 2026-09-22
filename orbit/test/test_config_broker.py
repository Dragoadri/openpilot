"""La IP del broker sobrevive al updater: vive en /data, fuera del arbol git.

orbit/config_mqtt.json es un fichero TRACKED con "broker": "" y la pantalla del comma
escribia la IP encima. El updater (system/updated/updated.py) hace `git reset --hard` y
`git clean -xdff` sobre el overlay y otro `git reset --hard` sobre la copia finalizada que
launch_chffrplus.sh mueve a /data/openpilot en el arranque siguiente: tras cada OTA el
broker volvia a "" y habia que teclearlo otra vez. Lo que fijan estos tests:

    Ruta ................. con /data escribible se vigila y escribe /data/orbit_config_mqtt.json;
                           sin /data (PC), la plantilla del arbol, como siempre.
    Lectura .............. plantilla + persistido por encima; un persistido VACIO no tapa a
                           la plantilla; un fichero corrupto cuenta como ausente y no lanza.
    Escritura ............ solo la clave cambiada, preservando el resto; la plantilla del
                           arbol NO se toca en el comma.
    Migracion ............ una IP dejada en la plantilla por el codigo viejo se copia a
                           /data la primera vez; con la plantilla de fabrica no se crea nada.
"""
import json
import os

import pytest

from openpilot.orbit import config_broker as cb


@pytest.fixture
def rutas(tmp_path, monkeypatch):
  """Plantilla y /data falsos, y la migracion 'sin hacer' para este proceso."""
  plantilla = tmp_path / "arbol" / "config_mqtt.json"
  plantilla.parent.mkdir()
  plantilla.write_text(json.dumps({"broker": "", "broker_port": 1883, "backend_port": 8010,
                                   "username": "", "password": ""}))
  data = tmp_path / "data"
  data.mkdir()
  monkeypatch.setattr(cb, "RUTA_PLANTILLA", str(plantilla))
  monkeypatch.setattr(cb, "DIR_PERSISTENTE", str(data))
  monkeypatch.setattr(cb, "RUTA_PERSISTENTE", str(data / "orbit_config_mqtt.json"))
  monkeypatch.setattr(cb, "_migracion_hecha", False)
  return plantilla, data / "orbit_config_mqtt.json"


def _leer(p):
  return json.loads(p.read_text())


# ------------------------------------------------------------------------------ ruta

def test_con_data_escribible_se_vigila_el_fichero_persistente_aunque_no_exista(rutas):
  plantilla, persistente = rutas
  assert not persistente.exists()
  assert cb.ruta_config() == str(persistente)


def test_sin_data_se_usa_la_plantilla_del_arbol(rutas, monkeypatch):
  plantilla, _ = rutas
  monkeypatch.setattr(cb, "DIR_PERSISTENTE", str(plantilla.parent / "no_existe"))
  assert cb.ruta_config() == str(plantilla)


# --------------------------------------------------------------------------- lectura

def test_sin_persistido_se_lee_la_plantilla(rutas):
  cfg = cb.leer_config()
  assert cfg["broker"] == ""
  assert cfg["broker_port"] == 1883
  assert cfg["backend_port"] == 8010


def test_lo_persistido_tapa_a_la_plantilla_y_lo_demas_sigue_siendo_de_la_plantilla(rutas):
  plantilla, persistente = rutas
  persistente.write_text(json.dumps({"broker": "192.0.2.10"}))
  cfg = cb.leer_config()
  assert cfg["broker"] == "192.0.2.10"
  assert cfg["broker_port"] == 1883
  assert cfg["backend_port"] == 8010
  # una OTA que cambie un valor por defecto sigue llegando al coche
  plantilla.write_text(json.dumps({"broker": "", "broker_port": 1883, "backend_port": 9000}))
  assert cb.leer_config()["backend_port"] == 9000
  assert cb.leer_config()["broker"] == "192.0.2.10"


def test_un_persistido_vacio_no_tapa_a_la_plantilla(rutas):
  plantilla, persistente = rutas
  plantilla.write_text(json.dumps({"broker": "10.0.0.5", "broker_port": 1883}))
  persistente.write_text(json.dumps({"broker": ""}))
  assert cb.leer_config()["broker"] == "10.0.0.5"


def test_un_persistido_corrupto_cuenta_como_ausente_y_no_lanza(rutas):
  plantilla, persistente = rutas
  plantilla.write_text(json.dumps({"broker": "10.0.0.5"}))
  persistente.write_text("{ esto no es json")
  assert cb.leer_config()["broker"] == "10.0.0.5"


def test_sin_ningun_fichero_devuelve_los_valores_por_defecto(rutas):
  plantilla, _ = rutas
  plantilla.unlink()
  cfg = cb.leer_config()
  assert cfg["broker"] == ""
  assert cfg["broker_port"] == 1883
  assert cfg["backend_port"] == 8010


# ------------------------------------------------------------------------- escritura

def test_escribir_persiste_fuera_del_arbol_y_no_toca_la_plantilla(rutas):
  plantilla, persistente = rutas
  antes = plantilla.read_text()
  assert cb.escribir_config({"broker": "192.0.2.10"})
  assert _leer(persistente) == {"broker": "192.0.2.10"}
  assert plantilla.read_text() == antes
  assert cb.leer_config()["broker"] == "192.0.2.10"


def test_escribir_preserva_las_otras_claves_persistidas(rutas):
  _, persistente = rutas
  persistente.write_text(json.dumps({"broker": "192.0.2.10", "username": "orbit", "password": "s3cr3t"}))
  assert cb.escribir_config({"broker": "192.0.2.11"})
  assert _leer(persistente) == {"broker": "192.0.2.11", "username": "orbit", "password": "s3cr3t"}


def test_escribir_ignora_claves_que_no_son_de_conexion(rutas):
  _, persistente = rutas
  assert cb.escribir_config({"broker": "192.0.2.10", "jetson_ip": "10.0.0.2"})
  assert _leer(persistente) == {"broker": "192.0.2.10"}


def test_escribir_no_deja_temporales(rutas):
  _, persistente = rutas
  assert cb.escribir_config({"broker": "192.0.2.10"})
  assert sorted(os.listdir(persistente.parent)) == ["orbit_config_mqtt.json"]


def test_en_el_pc_se_edita_la_plantilla_entera_como_hasta_ahora(rutas, monkeypatch):
  plantilla, persistente = rutas
  monkeypatch.setattr(cb, "DIR_PERSISTENTE", str(plantilla.parent / "no_existe"))
  assert cb.escribir_config({"broker": "192.0.2.10"})
  assert not persistente.exists()
  cfg = _leer(plantilla)
  assert cfg["broker"] == "192.0.2.10"
  assert cfg["backend_port"] == 8010   # el resto de keys de la plantilla se preserva


def test_si_no_se_puede_escribir_devuelve_false(rutas, monkeypatch):
  monkeypatch.setattr(cb, "_escribir_json", lambda ruta, data: False)
  assert cb.escribir_config({"broker": "192.0.2.10"}) is False


# ------------------------------------------------------------------------- migracion

def test_la_ip_dejada_en_la_plantilla_por_el_codigo_viejo_se_migra_a_data(rutas):
  plantilla, persistente = rutas
  plantilla.write_text(json.dumps({"broker": "10.0.0.5", "broker_port": 1884, "backend_port": 8010,
                                   "username": "", "password": ""}))
  assert cb.leer_config()["broker"] == "10.0.0.5"
  assert persistente.exists()
  assert _leer(persistente) == {"broker": "10.0.0.5", "broker_port": 1884, "backend_port": 8010}
  # y a partir de ahi manda lo migrado, aunque la plantilla vuelva a fabrica (OTA)
  plantilla.write_text(json.dumps({"broker": "", "broker_port": 1883}))
  cfg = cb.leer_config()
  assert cfg["broker"] == "10.0.0.5"
  assert cfg["broker_port"] == 1884


def test_con_la_plantilla_de_fabrica_no_se_crea_nada(rutas):
  _, persistente = rutas
  cb.leer_config()
  assert not persistente.exists()


def test_la_migracion_no_pisa_un_persistido_que_ya_existe(rutas):
  plantilla, persistente = rutas
  persistente.write_text(json.dumps({"broker": "192.0.2.10"}))
  plantilla.write_text(json.dumps({"broker": "10.0.0.5"}))
  assert cb.leer_config()["broker"] == "192.0.2.10"
  assert _leer(persistente) == {"broker": "192.0.2.10"}


def test_primera_ota_recupera_la_ip_del_arbol_anterior(rutas, tmp_path, monkeypatch):
  """Tras el swap, la plantilla nueva ya esta limpia pero old_openpilot conserva
  el config que escribia la UI antigua. Ese es el orden real de la primera OTA."""
  _, persistente = rutas
  vieja = tmp_path / "safe_staging" / "old_openpilot" / "orbit" / "config_mqtt.json"
  vieja.parent.mkdir(parents=True)
  vieja.write_text(json.dumps({"broker": "10.0.0.9", "broker_port": 1884,
                               "backend_port": 8010, "username": "orbit", "password": "clave"}))
  monkeypatch.setattr(cb, "RUTAS_LEGACY", (str(vieja),))

  cfg = cb.leer_config()

  assert cfg["broker"] == "10.0.0.9"
  assert _leer(persistente) == {
    "broker": "10.0.0.9", "broker_port": 1884, "backend_port": 8010,
    "username": "orbit", "password": "clave",
  }


def test_migracion_fallida_se_reintenta(rutas, monkeypatch):
  plantilla, persistente = rutas
  plantilla.write_text(json.dumps({"broker": "10.0.0.5"}))
  real = cb._escribir_json
  intentos = 0

  def falla_una_vez(ruta, data):
    nonlocal intentos
    intentos += 1
    return False if intentos == 1 else real(ruta, data)

  monkeypatch.setattr(cb, "_escribir_json", falla_una_vez)
  assert cb.leer_config()["broker"] == "10.0.0.5"
  assert not persistente.exists()
  assert cb.leer_config()["broker"] == "10.0.0.5"
  assert persistente.exists()


def test_la_migracion_es_una_vez_por_proceso(rutas):
  plantilla, persistente = rutas
  cb.leer_config()                       # plantilla de fabrica: no migra, pero ya "esta hecha"
  plantilla.write_text(json.dumps({"broker": "10.0.0.5"}))
  cb.leer_config()
  assert not persistente.exists()
