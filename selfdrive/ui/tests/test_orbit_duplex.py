import math

from openpilot.selfdrive.ui.widgets import orbit_duplex as dx


def test_bajada_va_por_la_izquierda_de_arriba_abajo():
  assert dx.tramo_bajada(0.0) == (240.0, 240.0)
  assert dx.tramo_bajada(1.0) == (120.0, 240.0)
  ini, fin = dx.tramo_bajada(1.0)
  x, _ = dx.punto(0, 0, 1, (ini + fin) / 2)   # 180°: lado izquierdo
  assert x < -0.99


def test_subida_va_por_la_derecha_de_abajo_arriba():
  assert dx.tramo_subida(0.0) == (60.0, 60.0)
  assert dx.tramo_subida(1.0) == (-60.0, 60.0)
  ini, fin = dx.tramo_subida(1.0)
  x, _ = dx.punto(0, 0, 1, (ini + fin) / 2)   # 0°: lado derecho
  assert x > 0.99


def test_progreso_se_acota():
  assert dx.tramo_bajada(-1) == dx.tramo_bajada(0)
  assert dx.tramo_subida(5) == dx.tramo_subida(1)


def test_punto_en_pantalla_y_hacia_abajo():
  x, y = dx.punto(10, 20, 2, 90)   # 90° = abajo (y crece hacia abajo)
  assert math.isclose(x, 10, abs_tol=1e-9) and math.isclose(y, 22)
