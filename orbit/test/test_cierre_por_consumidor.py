"""El ACK de un verbo lo cierra el CONSUMIDOR, no el router (ALTA 2 de la auditoria).

Antes de esto, command_router publicaba APPLIED en cuanto el handler retornaba. Para
lane_change eso significaba anunciar "Hecho" en la app cuando lo unico cierto es que
habia un flag en disco: quien decide es desire_helper, que puede rechazarlo por sus
propios gates (velocidad, latActive, angulo muerto, pedales, cinturon...).

El canal de resultado estaba DOBLEMENTE roto: OrbitCmdResult no estaba registrado en
common/params_keys.h, y aunque lo estuviera nadie lo leia. Estos tests fijan las dos
mitades del arreglo.
"""
import json

from openpilot.orbit.command_router import CommandRouter
from openpilot.orbit.command_spec import Mode, Phase, ahora_epoch_ms, ahora_mono, get_spec

DONGLE = "0123456789abcdef"
TOPIC = f"orbit/v2/cmd/{DONGLE}"



def _router(verbo="lane_change"):
  # Se reutiliza el doble de plano de estado de la bateria de la seccion 12 en vez de
  # escribir otro: dos dobles distintos del mismo objeto acaban divergiendo.
  from openpilot.orbit.test.test_command_router_v2 import _GatesFalsos, _store
  publicados = []
  ejecutados = []
  r = CommandRouter(DONGLE, gates=_GatesFalsos(), store=_store(Mode.MANEUVER),
                    publish=lambda t, p, q, ret: publicados.append((t, json.loads(p), q, ret)))
  r.register_handler(verbo, lambda cmd: ejecutados.append(cmd))
  return r, publicados, ejecutados


def _sobre(verb="lane_change", args=None, ttl_ms=3000):
  return json.dumps({
    "v": 2, "id": f"test-{verb}", "seq": 1, "verb": verb,
    "args": args if args is not None else {"direction": "left"},
    "ts_ms": ahora_epoch_ms(), "mono_ms": int(ahora_mono() * 1000),
    "ttl_ms": ttl_ms, "mode": "maniobra", "actor": {"user_id": 1, "via": "api"},
  })


def _fases(pub):
  return [p["phase"] for _, p, _, _ in pub]


def test_la_tabla_declara_que_lane_change_lo_cierra_el_consumidor():
  assert get_spec("lane_change").cierra_consumidor is True
  # Un verbo que se agota en escribir su Param NO espera a nadie.
  assert get_spec("disarm_all").cierra_consumidor is False


def test_sin_veredicto_el_comando_se_queda_en_executing():
  r, pub, ejec = _router()
  r.handle_payload(TOPIC, _sobre())
  r.drenar()
  assert len(ejec) == 1, "el handler tiene que haberse ejecutado"
  assert _fases(pub)[-1] == Phase.EXECUTING
  assert Phase.APPLIED not in _fases(pub), "APPLIED sin que el consumidor haya confirmado"


def test_el_veredicto_del_consumidor_cierra_con_applied():
  r, pub, _ = _router()
  r.handle_payload(TOPIC, _sobre())
  r.drenar()
  r._cerrar_con_resultado({"v": 2, "verb": "lane_change", "id": "test-lane_change",
                           "phase": "applied", "reason": "OK", "detail": ""})
  assert _fases(pub)[-1] == Phase.APPLIED


def test_el_rechazo_del_consumidor_cierra_con_failed_y_su_motivo():
  r, pub, _ = _router()
  r.handle_payload(TOPIC, _sobre())
  r.drenar()
  r._cerrar_con_resultado({"v": 2, "verb": "lane_change", "id": "test-lane_change",
                           "phase": "rejected", "reason": "GATE_BLIND_SPOT",
                           "detail": "vehiculo en el angulo muerto"})
  ultimo = [p for _, p, _, _ in pub][-1]
  assert ultimo["phase"] == Phase.FAILED
  assert ultimo["reason"] == "GATE_BLIND_SPOT"
  assert "angulo muerto" in ultimo["detail"]


def test_un_veredicto_de_otro_comando_no_inventa_un_ack():
  r, pub, _ = _router()
  r.handle_payload(TOPIC, _sobre())
  r.drenar()
  antes = len(pub)
  r._cerrar_con_resultado({"id": "de-otra-sesion", "phase": "applied", "reason": "OK"})
  assert len(pub) == antes, "se publico un ACK por un veredicto que no era de este comando"


def test_si_el_consumidor_no_contesta_se_declara_no_result_y_no_applied():
  r, pub, _ = _router()
  r.handle_payload(TOPIC, _sobre())
  r.drenar()
  # Vencer el plazo a mano: el limite es TTL + MARGEN_RESULTADO_S.
  with r._lock:
    for cid, (verbo, _lim) in list(r._pendientes.items()):
      r._pendientes[cid] = (verbo, ahora_mono() - 1.0)
  r._caducar_pendientes()
  ultimo = [p for _, p, _, _ in pub][-1]
  assert ultimo["phase"] == Phase.FAILED
  assert ultimo["reason"] == "NO_RESULT"
  assert Phase.APPLIED not in _fases(pub)


def test_el_veredicto_se_consume_una_sola_vez():
  """Si no se borrase el param, el mismo veredicto cerraria tambien el comando siguiente."""
  r, pub, _ = _router()
  r.handle_payload(TOPIC, _sobre())
  r.drenar()
  veredicto = {"id": "test-lane_change", "phase": "applied", "reason": "OK"}
  r._cerrar_con_resultado(veredicto)
  n = len(pub)
  r._cerrar_con_resultado(veredicto)
  assert len(pub) == n, "el mismo veredicto cerro dos veces"


def test_disarm_all_no_espera_a_nadie():
  """Bajar autoridad se confirma en el acto: no depende de que un consumidor conteste."""
  r, pub, _ = _router(verbo="disarm_all")
  r.handle_payload(TOPIC, _sobre("disarm_all", args={}))
  r.drenar()
  assert _fases(pub)[-1] == Phase.APPLIED
  assert not r._pendientes
