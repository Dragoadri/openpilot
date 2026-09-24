# La paleta navy antigua no vuelve: toda la UI toma el color de orbit_theme.
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[1]   # selfdrive/ui
NAVY = [(11, 18, 32), (22, 35, 58), (27, 44, 72), (43, 62, 95), (226, 236, 255),
        (147, 180, 230), (92, 117, 153), (125, 180, 255), (37, 99, 235)]
PERMITIDOS = {'orbit_theme.py'}


def test_sin_paleta_navy():
  malos = []
  for f in RAIZ.rglob('*.py'):
    if 'tests' in f.parts or f.name in PERMITIDOS:
      continue
    texto = f.read_text()
    for r, g, b in NAVY:
      if re.search(rf'rl\.Color\(\s*{r}\s*,\s*{g}\s*,\s*{b}\s*[,)]', texto):
        malos.append(f'{f.relative_to(RAIZ)}: ({r},{g},{b})')
  assert not malos, '\n'.join(malos)
