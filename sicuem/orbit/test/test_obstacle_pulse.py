"""Tests unitarios del esquive de obstáculos (modo 3 COMMA+JETSON).

Modelo "estado continuo" (v3, 2026-05-12):
  - El payload no lleva `duration_ms`.
  - NO hay watchdog: el Comma se queda con el último valor recibido
    indefinidamente hasta que la Jetson mande otro mensaje, o el conductor
    intervenga, o se desactive el control lateral.
"""
import unittest
from unittest.mock import MagicMock

from openpilot.sicuem.orbit.orbit_obstacle_pulse import (
    ObstaclePulseState,
    DEFAULT_MAX_ANGLE,
    DEFAULT_MAX_CURV,
)


def _carstate(steering_pressed=False, brake_pressed=False,
              left_blindspot=False, right_blindspot=False):
    cs = MagicMock()
    cs.steeringPressed = steering_pressed
    cs.brakePressed = brake_pressed
    cs.leftBlindspot = left_blindspot
    cs.rightBlindspot = right_blindspot
    return cs


class TestObstaclePulseState(unittest.TestCase):

    def test_idle_returns_zero_offsets(self):
        s = ObstaclePulseState()
        a, c, st = s.get_offsets(now=0.0, carstate=_carstate(), lat_active=True)
        self.assertEqual(a, 0.0)
        self.assertEqual(c, 0.0)
        self.assertEqual(st, "")

    def test_ingest_basic_left(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.4}, now=10.0)
        self.assertTrue(s.active)
        self.assertAlmostEqual(s.intensity, 0.4)

    def test_offsets_proportional_to_intensity(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5}, now=10.0)
        a, c, st = s.get_offsets(now=10.3, carstate=_carstate(), lat_active=True)
        self.assertAlmostEqual(a, -0.5 * DEFAULT_MAX_ANGLE)
        self.assertAlmostEqual(c, -0.5 * DEFAULT_MAX_CURV)
        self.assertEqual(st, "DODGING_RIGHT")

    def test_offsets_left_status(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.7}, now=10.0)
        a, c, st = s.get_offsets(now=10.3, carstate=_carstate(), lat_active=True)
        self.assertGreater(a, 0)
        self.assertGreater(c, 0)
        self.assertEqual(st, "DODGING_LEFT")

    def test_last_value_persists_indefinitely(self):
        """Sin watchdog: si la Jetson manda obstacle=true y luego se queda
        callada durante mucho tiempo, el esquive sigue activo con la última
        intensity hasta que llegue otro mensaje o intervenga el conductor."""
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5}, now=10.0)
        # 60 segundos sin recibir nada → sigue esquivando igualmente
        a, c, st = s.get_offsets(now=70.0, carstate=_carstate(), lat_active=True)
        self.assertAlmostEqual(a, -0.5 * DEFAULT_MAX_ANGLE)
        self.assertAlmostEqual(c, -0.5 * DEFAULT_MAX_CURV)
        self.assertEqual(st, "DODGING_RIGHT")

    def test_cancel_steering_pressed(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5}, now=10.0)
        a, c, st = s.get_offsets(now=10.3, carstate=_carstate(steering_pressed=True), lat_active=True)
        self.assertEqual((a, c), (0.0, 0.0))
        self.assertEqual(st, "CANCELED_DRIVER")
        self.assertFalse(s.active)

    def test_cancel_brake_pressed(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.5}, now=10.0)
        _, _, st = s.get_offsets(now=10.3, carstate=_carstate(brake_pressed=True), lat_active=True)
        self.assertEqual(st, "CANCELED_DRIVER")

    def test_cancel_lat_inactive(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5}, now=10.0)
        a, c, st = s.get_offsets(now=10.3, carstate=_carstate(), lat_active=False)
        self.assertEqual((a, c, st), (0.0, 0.0, ""))
        self.assertFalse(s.active)

    def test_clamp_intensity(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 99.0}, now=0.0)
        self.assertEqual(s.intensity, 1.0)
        s.ingest_new_message({"obstacle": True, "intensity": -99.0}, now=0.0)
        self.assertEqual(s.intensity, -1.0)

    def test_obstacle_false_cancels(self):
        """Mensaje con obstacle=false → idle inmediato."""
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5}, now=10.0)
        self.assertTrue(s.active)
        s.ingest_new_message({"obstacle": False, "intensity": 0.0}, now=10.2)
        self.assertFalse(s.active)
        a, c, st = s.get_offsets(now=10.25, carstate=_carstate(), lat_active=True)
        self.assertEqual((a, c, st), (0.0, 0.0, ""))

    def test_substitution_replaces(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5}, now=10.0)
        s.ingest_new_message({"obstacle": True, "intensity": 0.8}, now=10.3)
        self.assertAlmostEqual(s.intensity, 0.8)
        self.assertAlmostEqual(s.last_payload_ts, 10.3)

    def test_bsm_blocks_dodge_left(self):
        """Jetson quiere esquivar a la izquierda + BSM izq ocupado → no esquiva."""
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.6}, now=10.0)
        a, c, st = s.get_offsets(now=10.1,
                                 carstate=_carstate(left_blindspot=True),
                                 lat_active=True)
        self.assertEqual((a, c), (0.0, 0.0))
        self.assertEqual(st, "BSM_BLOCKED_LEFT")
        # El estado activo se mantiene: cuando el BSM se libere, vuelve a esquivar.
        self.assertTrue(s.active)

    def test_bsm_blocks_dodge_right(self):
        """Jetson quiere esquivar a la derecha + BSM der ocupado → no esquiva."""
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.4}, now=10.0)
        a, c, st = s.get_offsets(now=10.1,
                                 carstate=_carstate(right_blindspot=True),
                                 lat_active=True)
        self.assertEqual((a, c), (0.0, 0.0))
        self.assertEqual(st, "BSM_BLOCKED_RIGHT")
        self.assertTrue(s.active)

    def test_bsm_opposite_side_does_not_block(self):
        """Jetson esquiva a la izquierda + BSM derecho ocupado → sí esquiva."""
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.6}, now=10.0)
        a, c, st = s.get_offsets(now=10.1,
                                 carstate=_carstate(right_blindspot=True),
                                 lat_active=True)
        self.assertEqual(st, "DODGING_LEFT")
        self.assertAlmostEqual(a, 0.6 * DEFAULT_MAX_ANGLE)

    def test_bsm_does_not_block_hold(self):
        """intensity=0 (NEUTRO) no implica giro a ningún lado → BSM no aplica."""
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.0}, now=10.0)
        a, c, st = s.get_offsets(now=10.1,
                                 carstate=_carstate(left_blindspot=True,
                                                    right_blindspot=True),
                                 lat_active=True)
        self.assertEqual(st, "DODGING_HOLD")
        self.assertEqual((a, c), (0.0, 0.0))

    def test_bsm_releases_dodge_resumes(self):
        """BSM bloquea, luego se libera → siguiente frame vuelve a esquivar."""
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.5}, now=10.0)
        # frame 1: BSM izq ocupado
        _, _, st1 = s.get_offsets(now=10.1,
                                  carstate=_carstate(left_blindspot=True),
                                  lat_active=True)
        self.assertEqual(st1, "BSM_BLOCKED_LEFT")
        # frame 2: BSM libre → esquiva con la última intensity recibida
        a2, c2, st2 = s.get_offsets(now=10.2,
                                    carstate=_carstate(left_blindspot=False),
                                    lat_active=True)
        self.assertEqual(st2, "DODGING_LEFT")
        self.assertAlmostEqual(a2, 0.5 * DEFAULT_MAX_ANGLE)
        self.assertAlmostEqual(c2, 0.5 * DEFAULT_MAX_CURV)

    def test_bsm_missing_attrs_does_not_block(self):
        """Coche sin atributos BSM (getattr → False) → nunca bloquea."""
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.5}, now=10.0)
        # carstate sin leftBlindspot/rightBlindspot
        cs = MagicMock(spec=['steeringPressed', 'brakePressed'])
        cs.steeringPressed = False
        cs.brakePressed = False
        _, _, st = s.get_offsets(now=10.1, carstate=cs, lat_active=True)
        self.assertEqual(st, "DODGING_LEFT")

    def test_zero_intensity_obstacle_true_is_active_hold(self):
        """obstacle=true + intensity=0 → active=True, status DODGING_HOLD.

        Semántica override (v4): intensity=0 con obstacle=true significa
        'neutralizar el volante' (target absoluto = 0), NO 'ceder a Comma'.
        """
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.0}, now=10.0)
        self.assertTrue(s.active)
        a, c, st = s.get_offsets(now=10.1, carstate=_carstate(), lat_active=True)
        self.assertEqual(st, "DODGING_HOLD")
        self.assertEqual(a, 0.0)
        self.assertEqual(c, 0.0)


class TestObstacleApplyTargetBranch(unittest.TestCase):
    """Tests de la bifurcación apply_target en controlsd modo 3.

    No invocan controlsd directamente (demasiado pesado). Replican la
    lógica del bloque modificado en una función auxiliar y verifican
    sus tres ramas con semántica OVERRIDE:
      - target='curvature' + active=True  -> ASIGNA curvature/angle (no suma)
      - target='torque'    + active=True  -> pisa actuators.steer
      - active=False                       -> no toca nada
    """

    @staticmethod
    def _apply(target, angle_tgt, curv_tgt, intensity, active, actuators, state_dc):
        """Réplica de la lógica de aplicación de controlsd.py modo 3.
        Espejo de lo que está implementado en controlsd.py — si cambia
        allá, también cambia aquí.
        """
        import math
        if active:
            if target == "torque":
                i = intensity
                if math.isnan(i):
                    i = 0.0
                actuators.steer = max(-1.0, min(1.0, i))
            else:
                actuators.steeringAngleDeg = angle_tgt
                state_dc["desired_curvature"] = curv_tgt
        return actuators, state_dc

    def test_curvature_target_overrides_values(self):
        """Curvature mode con semántica OVERRIDE: asigna, no suma."""
        act = MagicMock()
        act.steer = 0.0
        act.steeringAngleDeg = 5.0     # valor de Comma — debe sobrescribirse
        state = {"desired_curvature": 0.02}  # valor de Comma — sobrescrito
        self._apply("curvature", angle_tgt=-2.0, curv_tgt=-0.01,
                    intensity=-0.5, active=True, actuators=act, state_dc=state)
        self.assertAlmostEqual(act.steeringAngleDeg, -2.0)
        self.assertAlmostEqual(state["desired_curvature"], -0.01)
        self.assertEqual(act.steer, 0.0)  # no se toca

    def test_curvature_target_zero_forces_straight(self):
        """intensity=0 en curvature mode → target=0 → recto, ignorando Comma."""
        act = MagicMock()
        act.steer = 0.0
        act.steeringAngleDeg = 7.5     # Comma quería girar
        state = {"desired_curvature": 0.025}
        self._apply("curvature", angle_tgt=0.0, curv_tgt=0.0,
                    intensity=0.0, active=True, actuators=act, state_dc=state)
        self.assertEqual(act.steeringAngleDeg, 0.0)
        self.assertEqual(state["desired_curvature"], 0.0)

    def test_torque_target_overwrites_steer(self):
        act = MagicMock()
        act.steer = 0.3   # lo que dejó el LaC
        act.steeringAngleDeg = 5.0
        state = {"desired_curvature": 0.02}
        self._apply("torque", angle_tgt=-2.0, curv_tgt=-0.01,
                    intensity=-0.4, active=True, actuators=act, state_dc=state)
        self.assertAlmostEqual(act.steer, -0.4)
        self.assertAlmostEqual(act.steeringAngleDeg, 5.0)  # no se toca
        self.assertAlmostEqual(state["desired_curvature"], 0.02)  # no se toca

    def test_torque_target_zero_relaxes_wheel(self):
        """intensity=0 en torque mode → steer=0, ignorando Comma."""
        act = MagicMock()
        act.steer = 0.3   # Comma quería aplicar torque
        self._apply("torque", angle_tgt=0.0, curv_tgt=0.0,
                    intensity=0.0, active=True, actuators=act,
                    state_dc={"desired_curvature": 0.0})
        self.assertEqual(act.steer, 0.0)

    def test_torque_target_clips_intensity(self):
        act = MagicMock()
        act.steer = 0.0
        self._apply("torque", angle_tgt=0.0, curv_tgt=0.05,
                    intensity=1.7, active=True, actuators=act,
                    state_dc={"desired_curvature": 0.0})
        self.assertAlmostEqual(act.steer, 1.0)

    def test_torque_target_nan_intensity_becomes_zero(self):
        act = MagicMock()
        act.steer = 0.0
        self._apply("torque", angle_tgt=0.0, curv_tgt=0.05,
                    intensity=float("nan"), active=True, actuators=act,
                    state_dc={"desired_curvature": 0.0})
        self.assertEqual(act.steer, 0.0)

    def test_inactive_does_not_touch_anything(self):
        """obstacle=false → active=False → no se toca nada (manda Comma)."""
        act = MagicMock()
        act.steer = 0.3
        act.steeringAngleDeg = 5.0
        state = {"desired_curvature": 0.02}
        self._apply("torque", angle_tgt=0.0, curv_tgt=0.0,
                    intensity=0.5, active=False, actuators=act, state_dc=state)
        self.assertAlmostEqual(act.steer, 0.3)
        self.assertAlmostEqual(act.steeringAngleDeg, 5.0)
        self.assertAlmostEqual(state["desired_curvature"], 0.02)


if __name__ == "__main__":
    unittest.main()
