#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Esquive de obstáculos para el modo 3 (COMMA+JETSON).

Modelo "estado continuo" + OVERRIDE absoluto (v4, 2026-05-19):
  - La Jetson envía un JSON {"obstacle": bool, "intensity": float} cuando
    quiere cambiar de estado.
  - El Comma se queda con el ÚLTIMO mensaje recibido y actúa según él:
      · obstacle=true  → Jetson manda; aplica `intensity` como valor
        ABSOLUTO (no como offset sobre Comma). intensity=0 cuenta: fuerza
        torque=0 / curvatura=0 (volante neutro / línea recta).
      · obstacle=false → Jetson cede; manda el modelo de Comma.
  - YA NO existe `duration_ms`.
  - YA NO existe watchdog: el último valor se mantiene hasta que llegue
    otro. Si la Jetson manda `true` y luego se queda callada, el esquive
    sigue activo hasta que la propia Jetson mande `false`, o el conductor
    intervenga (volante/freno), o el control lateral del openpilot se
    desactive (latActive=false).

Sub-target (controlsd lee JetsonObstacleApplyTarget):
  - "torque":    actuators.steer = clamp(intensity, -1, 1)  (override)
  - "curvature": desired_curvature = intensity * max_curv   (override)
                 steeringAngleDeg  = intensity * max_angle   (override)

A diferencia de orbit_steering_pulse.py (cruceta MQTT, valores fijos,
dos fases), este módulo:
  - lee el último mensaje de la Jetson desde Params (productor: zmq_client en
    otro proceso, no globals)
  - escala intensity [-1,+1] al valor target de ángulo y curvatura
  - cancela por volante presionado, freno, lat inactivo o por recibir un
    mensaje con obstacle=false (no por intensity=0; eso ahora es válido)

Convención de signo: negativo = derecha, positivo = izquierda
(coherente con controlsd.py:894-897).
"""
from __future__ import annotations
from typing import Tuple


# Defaults (sembrados al param la primera vez que se lee y devuelve None)
DEFAULT_MAX_ANGLE       = 25.0     # grados — para |intensity|=1.0
DEFAULT_MAX_CURV        = 0.030    # 1/m  — para |intensity|=1.0


class ObstaclePulseState:
    """Estado del esquive activo. Una instancia por proceso controlsd."""

    def __init__(self) -> None:
        self.active: bool = False
        self.intensity: float = 0.0          # ya clampeado a [-1, +1]
        self.last_payload_ts: float = 0.0    # ts (wall-clock) del último mensaje; informativo

    def ingest_new_message(self, payload: dict, now: float) -> None:
        """Carga un mensaje recibido de la Jetson (sustituye el actual).

        Modelo "estado continuo" + override absoluto:
          - obstacle=true  → activo SIEMPRE, sin importar intensity (incluye 0).
                             intensity=0 es válido y significa "neutralizar
                             el volante / ir recto". La Jetson manda.
          - obstacle=false → idle. El modelo de Comma manda.
        """
        obstacle = bool(payload.get("obstacle", False))
        intensity = float(payload.get("intensity", 0.0))

        # Clamp intensity
        if intensity < -1.0:
            intensity = -1.0
        elif intensity > 1.0:
            intensity = 1.0

        self.last_payload_ts = now

        # obstacle=False → idle. (intensity=0 con obstacle=true ya NO es idle).
        if not obstacle:
            self.active = False
            self.intensity = 0.0
            return

        self.active = True
        self.intensity = intensity

    def get_offsets(self, now: float, carstate, lat_active: bool,
                    max_angle: float = DEFAULT_MAX_ANGLE,
                    max_curv: float = DEFAULT_MAX_CURV) -> Tuple[float, float, str]:
        """Devuelve (angle_target_deg, curv_target, status) para este frame.

        Sem��ntica OVERRIDE: el caller usa estos valores como TARGET ABSOLUTO
        (asignación), no como offset (suma). Si self.intensity es 0, los
        targets son 0 → torque 0 / curvatura 0.

        status ∈ {"", "DODGING_LEFT", "DODGING_RIGHT", "DODGING_HOLD",
                  "CANCELED_DRIVER", "BSM_BLOCKED_LEFT", "BSM_BLOCKED_RIGHT"}
          - DODGING_HOLD: obstacle=true + intensity=0 (volante neutralizado).
          - BSM_BLOCKED_*: la Jetson quería esquivar a ese lado pero el BSM
            detectó un coche; el caller NO debe aplicar el override (deja
            que mande el modelo de Comma). El estado activo se mantiene:
            si el BSM se libera en el siguiente frame, vuelve a aplicar.
        """
        if not self.active:
            return 0.0, 0.0, ""

        # Cancellation priority order (highest to lowest):
        #   1. lat_inactive — sistema sin control lateral, sin status visible
        #   2. driver override (steering/brake) → CANCELED_DRIVER
        #   3. BSM bloquea el lado al que se quiere esquivar → BSM_BLOCKED_*
        # Sin watchdog: mientras no llegue obstacle=false ni se desactive
        # lateral ni intervenga el conductor, el esquive se mantiene con
        # el último valor recibido.

        # Cancelación: lat inactivo (no es del conductor, status vacío)
        if not lat_active:
            self._reset()
            return 0.0, 0.0, ""

        # Cancelación: conductor (volante o freno)
        if carstate.steeringPressed or carstate.brakePressed:
            self._reset()
            return 0.0, 0.0, "CANCELED_DRIVER"

        # BSM: si la Jetson quiere esquivar a un lado y el BSM detecta un
        # coche en ese lado, NO esquivamos. Mismo criterio que el cambio de
        # carril manual en desire_helper.py: si el coche no tiene BSM
        # disponible, getattr devuelve False → no bloquea.
        # Convención: intensity > 0 → izquierda, < 0 → derecha, 0 → recto.
        left_bs = bool(getattr(carstate, 'leftBlindspot', False))
        right_bs = bool(getattr(carstate, 'rightBlindspot', False))
        if self.intensity > 0.0 and left_bs:
            return 0.0, 0.0, "BSM_BLOCKED_LEFT"
        if self.intensity < 0.0 and right_bs:
            return 0.0, 0.0, "BSM_BLOCKED_RIGHT"

        # Valor target absoluto proporcional a intensity (0 incluido).
        angle_tgt = self.intensity * max_angle
        curv_tgt  = self.intensity * max_curv
        if self.intensity == 0.0:
            status = "DODGING_HOLD"
        elif self.intensity < 0.0:
            status = "DODGING_RIGHT"
        else:
            status = "DODGING_LEFT"
        return angle_tgt, curv_tgt, status

    def _reset(self) -> None:
        self.active = False
        self.intensity = 0.0
