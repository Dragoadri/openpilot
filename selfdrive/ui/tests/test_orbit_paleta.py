# La paleta navy antigua no vuelve: toda la UI toma el color de orbit_theme.
# Cubre selfdrive/ui (la app ORBIT) y system/ui (fila/botón/toggle/lista que
# comparten paleta con el panel ORBIT y el diálogo QR — Ruling F-R5).
import pathlib
import re

UI_DIR = pathlib.Path(__file__).resolve().parents[1]        # selfdrive/ui
RAIZ_REPO = UI_DIR.parents[1]                                # raíz del repo
RAICES = [UI_DIR, RAIZ_REPO / 'system' / 'ui']
NAVY = [(11, 18, 32), (22, 35, 58), (27, 44, 72), (43, 62, 95), (226, 236, 255),
        (147, 180, 230), (92, 117, 153), (125, 180, 255), (37, 99, 235)]
# Ficheros/motivo: literal fuera de alcance de esta ola (no es "navy": es
# GREEN/GREEN_DEEP/CYAN/AMBER, o ya no queda ninguno tras la retokenización).
PERMITIDOS = {'orbit_theme.py'}


def _canal(v: int) -> str:
  return rf'(?:{v}|0[xX]{v:02x})'


def _patrones(r: int, g: int, b: int):
  # Forma decimal ("rl.Color(11, 18, 32, ...)") y forma hexadecimal por canal
  # ("rl.Color(0x0B, 0x12, 0x20, ...)"), como en orbit_panel.py antes de la Tarea 9.
  return rf'\(\s*{_canal(r)}\s*,\s*{_canal(g)}\s*,\s*{_canal(b)}\s*[,)]'


def test_sin_paleta_navy():
  malos = []
  for raiz in RAICES:
    for f in raiz.rglob('*.py'):
      if 'tests' in f.parts or f.name in PERMITIDOS:
        continue
      texto = f.read_text()
      for r, g, b in NAVY:
        if re.search(_patrones(r, g, b), texto, re.IGNORECASE):
          malos.append(f'{f.relative_to(RAIZ_REPO)}: ({r},{g},{b})')
  assert not malos, '\n'.join(malos)
