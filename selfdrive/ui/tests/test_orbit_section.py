from openpilot.selfdrive.ui import orbit_theme as t
from openpilot.selfdrive.ui.widgets import orbit_icons
from openpilot.selfdrive.ui.widgets import orbit_section as s


def test_geometria_cabecera_no_recorta_ni_toca_el_titulo():
  x0 = 8.0
  icon_x, title_x = s._geometria_cabecera(x0)
  # El borde izquierdo REAL del icono (icon_x - sobresale) no puede quedar
  # a la izquierda del margen original (regresion: quedaba en rect.x - 8.7).
  assert icon_x - s._ICONO_SOBRESALE >= x0
  # El borde derecho REAL del icono (icon_x + tam + sobresale, donde vive el
  # satelite) tiene que quedar antes del titulo, no encima de su primera letra.
  assert icon_x + s._ICONO_TAM + s._ICONO_SOBRESALE < title_x


def test_toda_seccion_tiene_glifo():
  # Cada clave de orbit_theme.SECCION (con el fallback _GLIFO_POR_SECCION de
  # la cabecera, p.ej. cabina->enlace) debe resolver a un glifo real de
  # orbit_icons, o draw_orbit_icon petaria en pleno render.
  for seccion in t.SECCION:
    glifo = s._GLIFO_POR_SECCION.get(seccion, seccion)
    assert glifo in orbit_icons.GLIFOS, f'{seccion} -> {glifo} no esta en GLIFOS'
