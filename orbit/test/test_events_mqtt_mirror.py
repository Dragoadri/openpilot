"""Espejo MQTT de alertas (orbit/events_mqtt.mirror_alerts) y arranque del cliente.

Lo que se cubre es lo que estuvo roto un mes sin que nadie lo viera:

  - la version inline en selfdrived hacia `frozenset(...).discard("")` (AttributeError:
    frozenset es inmutable) dentro de un `except Exception: pass`. Aqui se exige que
    mirror_alerts acepte un frozenset y devuelva otro sin lanzar;
  - solo publica cuando CAMBIA el conjunto de alert_types vivos (100 Hz sin I/O);
  - sin broker configurado no se construye un cliente por alerta ni se lanza.
"""
import pytest

from openpilot.orbit import events_mqtt as ev


class _Alerta:
  def __init__(self, alert_type, t1="TAKE CONTROL", t2="", priority=5):
    self.alert_type = alert_type
    self.alert_text_1 = t1
    self.alert_text_2 = t2
    self.priority = priority


@pytest.fixture
def enviados(monkeypatch):
  out = []
  def enviar(a):
    out.append(a.alert_type)
    return True
  monkeypatch.setattr(ev, "send_alert", enviar)
  return out


def test_acepta_frozenset_y_no_lanza(enviados):
  prev = frozenset()
  nuevo = ev.mirror_alerts([_Alerta("commIssue/immediateDisable")], prev)
  assert isinstance(nuevo, frozenset)
  assert nuevo == frozenset({"commIssue/immediateDisable"})
  assert enviados == ["commIssue/immediateDisable"]


def test_solo_publica_cuando_cambia_el_conjunto(enviados):
  alertas = [_Alerta("a/x"), _Alerta("b/y")]
  prev = ev.mirror_alerts(alertas, frozenset())
  assert sorted(enviados) == ["a/x", "b/y"]
  for _ in range(100):
    assert ev.mirror_alerts(alertas, prev) is prev
  assert len(enviados) == 2, "sin cambio no se vuelve a publicar"


def test_las_alertas_sin_alert_type_no_cuentan(enviados):
  prev = ev.mirror_alerts([_Alerta(""), _Alerta(None)], frozenset())
  assert prev == frozenset()
  assert enviados == []


def test_al_apagarse_todas_vuelve_al_conjunto_vacio(enviados):
  prev = ev.mirror_alerts([_Alerta("a/x")], frozenset())
  prev = ev.mirror_alerts([], prev)
  assert prev == frozenset()
  assert enviados == ["a/x"]


def test_sin_broker_no_se_abre_cliente_ni_se_lanza(monkeypatch):
  monkeypatch.setattr(ev, "_load_broker", lambda: ("", 1883, None, None))
  monkeypatch.setattr(ev, "_mqtt_client", None)
  ev._avisos_dados.discard("sin_broker")
  construidos = []
  monkeypatch.setattr(ev.mqtt, "Client", lambda *a, **k: construidos.append(1))
  ev.warmup()
  assert ev._ensure_mqtt_client() is None
  assert construidos == [], "con broker vacio no se construye ningun cliente"
  assert "sin_broker" in ev._avisos_dados


def test_warmup_nunca_lanza(monkeypatch):
  def explota():
    raise RuntimeError("disco")
  monkeypatch.setattr(ev, "_ensure_mqtt_client", explota)
  ev.warmup()


def test_no_avanza_el_conjunto_hasta_que_mqtt_acepta_el_evento(monkeypatch):
  resultados = iter((False, True))
  monkeypatch.setattr(ev, "send_alert", lambda _a: next(resultados))
  alertas = [_Alerta("startup/permanent", t1="openpilot listo", priority=1)]

  prev = ev.mirror_alerts(alertas, frozenset())
  assert prev == frozenset(), "antes de on_connect hay que dejarlo pendiente"
  prev = ev.mirror_alerts(alertas, prev)
  assert prev == frozenset({"startup/permanent"})


def test_evento_por_defecto_de_prioridad_baja_se_publica(monkeypatch):
  publicaciones = []

  class Cliente:
    def publish(self, topic, payload, qos):
      publicaciones.append((topic, payload, qos))

  monkeypatch.setattr(ev, "_ensure_mqtt_client", lambda: Cliente())
  monkeypatch.setattr(ev, "_mqtt_connected", True)
  monkeypatch.setattr(ev, "_should_send_event", lambda *_a, **_k: True)
  monkeypatch.setattr(ev, "_get_dongle_id", lambda: "abc")

  assert ev.send_event_full("openpilot listo", "", 1,
                            event_name="startup", event_type="permanent",
                            alert_type="startup/permanent") is True
  assert len(publicaciones) == 1
  assert publicaciones[0][0] == "telemetry_mqtt/abc/event"


def test_alerta_sin_texto_usa_el_nombre_y_no_desaparece(monkeypatch):
  publicaciones = []

  class Cliente:
    def publish(self, topic, payload, qos):
      publicaciones.append(payload)

  monkeypatch.setattr(ev, "_ensure_mqtt_client", lambda: Cliente())
  monkeypatch.setattr(ev, "_mqtt_connected", True)
  monkeypatch.setattr(ev, "_should_send_event", lambda *_a, **_k: True)
  monkeypatch.setattr(ev, "_get_dongle_id", lambda: "abc")

  assert ev.send_alert(_Alerta("engagement/enable", t1="", t2="", priority=3)) is True
  assert '"title": "engagement"' in publicaciones[0]


def test_publish_desconectado_no_consume_cooldown_y_se_reintenta(monkeypatch):
  class Resultado:
    def __init__(self, rc):
      self.rc = rc

  class Cliente:
    rc = ev.mqtt.MQTT_ERR_NO_CONN

    def publish(self, *_a, **_k):
      return Resultado(self.rc)

  cliente = Cliente()
  monkeypatch.setattr(ev, "_ensure_mqtt_client", lambda: cliente)
  monkeypatch.setattr(ev, "_mqtt_connected", True)
  monkeypatch.setattr(ev, "_get_dongle_id", lambda: "abc")
  ev._event_last_sent.clear()

  def enviar():
    return ev.send_event_full("listo", "", 1, event_name="startup",
                              event_type="permanent", alert_type="startup/permanent")

  assert enviar() is False
  assert "startup/permanent" not in ev._event_last_sent
  cliente.rc = ev.mqtt.MQTT_ERR_SUCCESS
  assert enviar() is True


def test_on_connect_inmediato_no_es_pisado_por_el_arranque(monkeypatch):
  class Cliente:
    on_connect = None
    on_disconnect = None

    def max_queued_messages_set(self, _n): pass
    def reconnect_delay_set(self, **_kw): pass
    def connect_async(self, *_a, **_kw): pass
    def loop_start(self):
      # Reproduce el peor interleaving: el hilo MQTT confirma antes de que
      # _ensure_mqtt_client termine de guardar el cliente.
      self.on_connect(self, None, None, 0)

  monkeypatch.setattr(ev, "_load_broker", lambda: ("broker", 1883, None, None))
  monkeypatch.setattr(ev.mqtt, "Client", Cliente)
  monkeypatch.setattr(ev, "_mqtt_client", None)
  monkeypatch.setattr(ev, "_mqtt_connected", False)
  monkeypatch.setattr(ev, "_mqtt_broker", None)

  assert ev._ensure_mqtt_client() is not None
  assert ev._mqtt_connected is True
