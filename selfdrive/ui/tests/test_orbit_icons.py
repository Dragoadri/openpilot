import math

from openpilot.selfdrive.ui.widgets import orbit_icons as ic


def test_glifos_de_la_app_y_enlace():
  assert set(ic.GLIFOS) >= {'vehiculo', 'mapa', 'cuenta', 'cabina', 'mando', 'registro',
                            'viajes', 'ajustes', 'ayuda', 'desarrollo', 'enlace'}


def test_satelite_en_la_orbita_inclinada():
  r = math.radians(-24)
  x, y = ic.posicion_satelite(0.0)
  assert math.isclose(x, 12 + 19 * math.cos(r), abs_tol=1e-9)
  assert math.isclose(y, 12 + 19 * math.sin(r), abs_tol=1e-9)
