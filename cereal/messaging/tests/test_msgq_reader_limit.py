"""Regression test for the msgq per-service reader limit (NUM_READERS).

Every SubMaster registers one msgq reader on each service it subscribes to and
reader slots are never released. Upstream msgq allowed 15 readers per service;
the 16th registration evicted every reader and, with 16+ live readers, the
eviction repeated forever, so every SubMaster that checked ``carState`` saw it
"not alive"/"freq not ok" and published its output with ``valid=False``
(permanent "Communication Issue Between Processes" on the device).

This fork has 16 live readers on ``carState`` (12 openpilot daemons + loggerd +
sunnypilot's locationd_llk + 2 ORBIT SubMasters in manager), so msgq was forked
with ``NUM_READERS 31``. This test reproduces the field failure shape with 20
SubMasters identical to calibrationd's: it fails on msgq with NUM_READERS 15
(all_checks ~0 %) and passes with the fork (100 %).
"""
import time

import cereal.messaging as messaging

N_READERS = 20
N_CYCLES = 60
WARMUP_CYCLES = 20
CYCLE_S = 0.05  # cameraOdometry at 20 Hz, carState at 100 Hz (5 per cycle)


def _publish_cycle(pm: messaging.PubMaster) -> None:
  for _ in range(5):
    cs = messaging.new_message('carState', valid=True)
    cs.carState.vEgo = 10.0
    pm.send('carState', cs)
  co = messaging.new_message('cameraOdometry', valid=True)
  pm.send('cameraOdometry', co)


class TestMsgqReaderLimit:

  def test_many_submasters_keep_all_checks(self):
    # publisher first: msgq_init_publisher resets the reader table
    pm = messaging.PubMaster(['carState', 'cameraOdometry'])

    # same shape as selfdrive/locationd/calibrationd.py
    sms = [messaging.SubMaster(['cameraOdometry', 'carState'], poll='cameraOdometry') for _ in range(N_READERS)]
    probe = sms[0]

    checks_ok = 0
    carstate_updated = 0
    measured = 0
    for cycle in range(N_CYCLES):
      _publish_cycle(pm)
      time.sleep(CYCLE_S)
      for sm in sms:
        sm.update(0)
      if cycle >= WARMUP_CYCLES:
        measured += 1
        checks_ok += probe.all_checks()
        carstate_updated += probe.updated['carState']

    assert measured > 0
    frac_ok = checks_ok / measured
    frac_cs = carstate_updated / measured
    assert frac_ok >= 0.9, f"all_checks ok only {frac_ok:.0%} of cycles with {N_READERS} readers (msgq reader limit hit?)"
    assert frac_cs >= 0.95, f"carState received only {frac_cs:.0%} of cycles with {N_READERS} readers (readers being evicted?)"
