"""El modo de mando tiene que poder cambiarse, y tiene que caducar (bloqueante 2).

Antes de esto NADIE escribia OrbitCommandMode: CommandStateStore.set_mode existia y no lo
llamaba nadie, asi que el modo efectivo era siempre 0 (observador) y TODO verbo salvo
disarm_all contestaba MODE. El subsistema entero estaba muerto.
"""
import json

from openpilot.orbit.command_router import CommandRouter
from openpilot.orbit.command_spec import Mode, Phase, ahora_epoch_ms, ahora_mono, get_spec
from openpilot.orbit.command_state import CommandStateStore

DONGLE = "0123456789abcdef"
TOPIC = f"orbit/v2/cmd/{DONGLE}"


class _StoreSinDisco(CommandStateStore):
  """El store real, pero sin /data/params: aqui se prueba la maquina, no el disco."""

  def _get_params(self):
    return None


def _router(store):
  from openpilot.orbit.test.test_command_router_v2 import _GatesFalsos
  pub, ejec = [], []
  r = CommandRouter(DONGLE, gates=_GatesFalsos(), store=store,
                    publish=lambda t, p, q, ret: pub.append((t, json.loads(p), q, ret)))
  for v in ("lane_change", "disarm_all", "set_mode"):
    r.register_handler(v, lambda cmd: ejec.append(cmd))
  return r, pub, ejec


_N = [0]


def _sobre(verb, args, ttl_ms=5000):
  _N[0] += 1
  return json.dumps({
    "v": 2, "id": f"id-{_N[0]}", "seq": _N[0], "verb": verb, "args": args,
    "ts_ms": ahora_epoch_ms(), "mono_ms": int(ahora_mono() * 1000), "ttl_ms": ttl_ms,
    "mode": None, "actor": {"user_id": 1, "via": "api"},
  })


def _ultimo(pub):
  return [p for _, p, _, _ in pub][-1]


def test_sin_set_mode_una_maniobra_contesta_MODE():
  """La situacion que dejo muerto el subsistema: modo por defecto = observador."""
  store = _StoreSinDisco()
  r, pub, ejec = _router(store)
  r.handle_payload(TOPIC, _sobre("lane_change", {"direction": "left"}))
  r.drenar()
  assert _ultimo(pub)["reason"] == "MODE"
  assert not ejec


def test_set_mode_a_maniobra_desbloquea_el_cambio_de_carril():
  store = _StoreSinDisco()
  r, pub, ejec = _router(store)
  # El ejecutor real vive en MQTTComandos; aqui se llama al plano directamente, que es lo
  # que hace ese ejecutor. Lo que se prueba es que el modo tiene EFECTO sobre el router.
  spec = get_spec("set_mode")
  store.set_mode("maniobra", expira_s=spec.limits["expira_s"]["maniobra"])
  assert store.mode is Mode.MANEUVER

  r.handle_payload(TOPIC, _sobre("lane_change", {"direction": "left"}))
  r.drenar()
  assert len(ejec) == 1, "con el modo en maniobra el cambio de carril tiene que ejecutarse"
  assert _ultimo(pub)["phase"] == Phase.EXECUTING   # lo cierra el consumidor


def test_el_modo_caduca_y_vuelve_a_observador():
  store = _StoreSinDisco()
  store.set_mode("maniobra", expira_s=120.0)
  assert store.mode is Mode.MANEUVER
  # Vencer el plazo a mano y forzar el refresco del tick.
  store.mode_expiry_mono = ahora_mono() - 1.0
  store.refresh_params(forzar=True)
  assert store.mode is Mode.OBSERVER, "un modo sin caducidad deja el gate sin significado"


def test_bajar_a_observador_no_caduca():
  """No hay nada por debajo: darle caducidad a observador seria absurdo."""
  store = _StoreSinDisco()
  store.set_mode("observador", expira_s=900.0)
  assert store.mode is Mode.OBSERVER
  assert store.mode_expiry_mono == 0.0


def test_el_contrato_no_ofrece_banco_como_destino():
  """El modo fisico solo se arma en la pantalla del comma (seccion 4.1)."""
  opciones = get_spec("set_mode").args_schema["target_mode"].opciones
  assert "banco" not in opciones
  assert set(opciones) == {"observador", "copiloto", "maniobra"}


def test_pedir_banco_por_mqtt_se_rechaza_con_RANGE():
  store = _StoreSinDisco()
  store.set_mode("maniobra", expira_s=120.0)
  r, pub, _ = _router(store)
  r.handle_payload(TOPIC, _sobre("set_mode", {"target_mode": "banco"}))
  r.drenar()
  assert _ultimo(pub)["reason"] == "RANGE"
  assert store.mode is Mode.MANEUVER, "un rechazo no puede cambiar el modo"
