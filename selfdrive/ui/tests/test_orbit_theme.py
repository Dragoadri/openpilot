# Contraste de la paleta Grafito del firmware (misma identidad que la app ORBIT).
from openpilot.selfdrive.ui import orbit_theme as t


def _hex(c):
  return (c.r << 16) | (c.g << 8) | c.b


def test_valores_exactos():
  esperado = {
    'FONDO': 0x0A0E14, 'SUP1': 0x131A24, 'SUP2': 0x19222F, 'SUP3': 0x212C3C,
    'BORDE': 0x263243, 'BORDE_FUERTE': 0x6E7F97,
    'TEXTO1': 0xE8EEF6, 'TEXTO2': 0xA2B1C6, 'TEXTO3': 0x93A2B8,
    'PULSO': 0x22D3EE, 'ACCION': 0x86B9F7, 'SOBRE_ACCION': 0x05141E,
    'OK': 0x4ADE80, 'OK_PROFUNDO': 0x16A34A, 'AVISO': 0xF5C842,
    'PELIGRO': 0xFF8A8A, 'FRENO': 0xB91C1C, 'SOBRE_FRENO': 0xFFFFFF, 'AZUL_PROFUNDO': 0x2563EB,
  }
  for nombre, valor in esperado.items():
    assert _hex(getattr(t, nombre)) == valor, nombre
  assert set(t.SECCION) == {'vehiculo', 'mapa', 'viajes', 'cabina', 'mando', 'registro',
                            'ajustes', 'cuenta', 'ayuda', 'desarrollo'}
  assert _hex(t.SECCION['cabina']) == 0x22D3EE
  assert _hex(t.SECCION['mando']) == 0xB3A7F2


def _fondos():
  superficies = [t.FONDO, t.SUP1, t.SUP2, t.SUP3]
  mas_clara = max(t.SECCION.values(), key=lambda c: t._luminancia(c))
  return superficies + [t.mezcla(t.PULSO, 0.22, t.FONDO), t.mezcla(mas_clara, 0.12, t.FONDO)]


def test_texto_y_tintas_llegan_a_aa():
  for nombre in ('TEXTO1', 'TEXTO2', 'TEXTO3', 'PULSO', 'ACCION', 'OK', 'AVISO', 'PELIGRO'):
    for f in _fondos():
      assert t.contraste(getattr(t, nombre), f) >= 4.5, nombre


def test_secciones_se_leen():
  for nombre, c in t.SECCION.items():
    for f in _fondos():
      assert t.contraste(c, f) >= 4.5, nombre


def test_borde_fuerte_y_rellenos():
  for f in (t.FONDO, t.SUP1, t.SUP2, t.SUP3):
    assert t.contraste(t.BORDE_FUERTE, f) >= 3.0
  assert t.contraste(t.SOBRE_ACCION, t.ACCION) >= 4.5
  assert t.contraste(t.SOBRE_FRENO, t.FRENO) >= 4.5


def test_con_alfa():
  assert t.con_alfa(t.PULSO, 0.5).a == 127
  assert t.con_alfa(t.PULSO, 2.0).a == 255
