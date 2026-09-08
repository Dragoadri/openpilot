"""ForceOnroad (modo banco): hardwared debe pasar a started=True sin ignicion del panda
(sin ningun pandaStates publicado), y OffroadMode debe seguir ganando.

Corre el hilo real de hardwared (hardware_thread) en este proceso, con Params aislados
por el conftest, y observa deviceState por msgq.
"""
import queue
import threading
import time

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.system.hardware.hardwared import hardware_thread
from openpilot.system.version import terms_version, training_version, terms_version_sp


def _wait_started(sm: messaging.SubMaster, expected: bool, timeout: float) -> bool:
  t_end = time.monotonic() + timeout
  while time.monotonic() < t_end:
    sm.update(200)
    if sm.updated['deviceState'] and sm['deviceState'].started == expected:
      return True
  return False


class TestHardwaredForceOnroad:

  def test_force_onroad_without_panda_and_offroad_mode_wins(self):
    params = Params()
    # condiciones de arranque que hardwared exige aunque la ignicion este forzada
    params.put("HasAcceptedTerms", terms_version, block=True)
    params.put("HasAcceptedTermsSP", terms_version_sp, block=True)
    params.put("CompletedTrainingVersion", training_version, block=True)
    params.put_bool("ForceOnroad", True, block=True)

    sm = messaging.SubMaster(['deviceState'])
    end_event = threading.Event()
    hw_queue: queue.Queue = queue.Queue(maxsize=1)
    t = threading.Thread(target=hardware_thread, args=(end_event, hw_queue), daemon=True)
    t.start()
    try:
      assert _wait_started(sm, True, timeout=15.0), "ForceOnroad no puso deviceState.started sin pandaStates"

      # Always Offroad (OffroadMode) gana al modo banco
      params.put_bool("OffroadMode", True, block=True)
      assert _wait_started(sm, False, timeout=10.0), "OffroadMode no ha vetado el modo banco"

      # sin OffroadMode y sin ForceOnroad: offroad normal (no hay ignicion real)
      params.put_bool("OffroadMode", False, block=True)
      params.put_bool("ForceOnroad", False, block=True)
      time.sleep(2.0)
      assert _wait_started(sm, False, timeout=5.0)
      assert not sm['deviceState'].started
    finally:
      end_event.set()
      t.join(timeout=5.0)
