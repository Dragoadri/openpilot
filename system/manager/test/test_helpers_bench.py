"""restore_car_params_for_bench: modo banco (ForceOnroad) sin coche.

manager la llama al pasar a onroad con ForceOnroad activo, justo despues del
clear_all(CLEAR_ON_ONROAD_TRANSITION) que borra CarParams/CarParamsSP. card nunca
los repone (no hay CAN), asi que sin esta restauracion selfdrived, controlsd, modeld,
plannerd, radard, paramsd, lagd, torqued y calibrationd se quedarian bloqueados en
params.get("CarParams", block=True).
"""
import cereal.messaging as messaging
from cereal import car, custom
from openpilot.common.params import Params
from openpilot.system.manager.helpers import restore_car_params_for_bench


def _fake_persistent(params: Params) -> tuple[bytes, bytes]:
  cp = car.CarParams.new_message()
  cp.carFingerprint = "HYUNDAI_TUCSON_4TH_GEN"
  cp.brand = "hyundai"
  cp_bytes = cp.to_bytes()
  cp_sp_bytes = custom.CarParamsSP.new_message().to_bytes()
  # put() es asincrono: sin block=True el get() inmediato del helper puede no verlo aun
  params.put("CarParamsPersistent", cp_bytes, block=True)
  params.put("CarParamsSPPersistent", cp_sp_bytes, block=True)
  return cp_bytes, cp_sp_bytes


class TestRestoreCarParamsForBench:

  def test_copies_persistent_params(self):
    params = Params()
    cp_bytes, cp_sp_bytes = _fake_persistent(params)
    params.remove("CarParams")
    params.remove("CarParamsSP")

    fallback = restore_car_params_for_bench(params)

    assert fallback is False
    assert params.get("CarParams") == cp_bytes
    assert params.get("CarParamsSP") == cp_sp_bytes
    cp = messaging.log_from_bytes(params.get("CarParams"), car.CarParams)
    assert cp.carFingerprint == "HYUNDAI_TUCSON_4TH_GEN"

  def test_mock_car_when_device_never_saw_a_car(self):
    params = Params()
    for k in ("CarParamsPersistent", "CarParamsSPPersistent", "CarParams", "CarParamsSP"):
      params.remove(k)

    fallback = restore_car_params_for_bench(params)

    assert fallback is True
    cp = messaging.log_from_bytes(params.get("CarParams"), car.CarParams)
    assert cp.brand == "mock"
    assert cp.dashcamOnly  # el stack arranca en modo dashcam con "Car Unrecognized"
    cp_sp = messaging.log_from_bytes(params.get("CarParamsSP"), custom.CarParamsSP)
    assert cp_sp is not None

  def test_missing_sp_twin_gets_an_empty_but_valid_one(self):
    params = Params()
    cp_bytes, _ = _fake_persistent(params)
    params.remove("CarParamsSPPersistent")
    params.remove("CarParamsSP")

    fallback = restore_car_params_for_bench(params)

    assert fallback is False
    assert params.get("CarParams") == cp_bytes
    cp_sp = messaging.log_from_bytes(params.get("CarParamsSP"), custom.CarParamsSP)
    assert cp_sp is not None
