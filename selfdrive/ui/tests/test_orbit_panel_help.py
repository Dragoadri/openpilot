"""El panel ORBIT tiene un boton de definiciones y su dialogo explica la terminologia.

El usuario pidio un boton en el menu que diga que son ARMAR y DESARMAR y el resto de
conceptos que no quedan claros. Es un test de AST a proposito (igual que
test_orbit_panel_refs.py): no importa pyray ni Params, asi que corre en cualquier PC
sin build ni ventana.

Lo que se comprueba:
  * el panel crea un boton "Qué significa esto" y lo mete en la lista de items,
  * existe el metodo `_show_help` que abre un dialogo informativo,
  * el texto del dialogo define ARMAR, DESARMAR, MODO, ENLACE y BANCO ARMADO.
"""
import ast
from pathlib import Path

UI_DIR = Path(__file__).resolve().parents[1]
PANEL = UI_DIR / "sunnypilot" / "layouts" / "settings" / "orbit_panel.py"


def _leer() -> ast.Module:
  return ast.parse(PANEL.read_text(encoding="utf-8"), filename=str(PANEL))


def _metodos_clase(tree: ast.Module, clase: str) -> set[str]:
  for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == clase:
      return {sub.name for sub in node.body if isinstance(sub, ast.FunctionDef)}
  raise AssertionError(f"no existe la clase {clase}")


def _textos(tree: ast.Module) -> list[str]:
  """Todas las cadenas literales del fichero (para buscar el copy del dialogo)."""
  return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_el_panel_tiene_boton_de_definiciones():
  tree = _leer()
  src = PANEL.read_text(encoding="utf-8")
  # El boton se crea y se anade a la lista de items del scroller.
  assert "Qué significa esto" in src, "falta el boton de definiciones"
  assert "self._help_button" in src, "falta el atributo del boton"
  assert "self._help_button," in src, "el boton no esta en la lista de items"


def test_show_help_abre_un_dialogo_informativo():
  metodos = _metodos_clase(_leer(), "OrbitLayout")
  assert "_show_help" in metodos, "falta el metodo _show_help"
  src = PANEL.read_text(encoding="utf-8")
  # Es informativo (sin confirmacion) y usa rich=True para que el texto largo
  # se desplace en vez de recortarse con scissor.
  assert "rich=True" in src, "_show_help no usa el dialogo con scroll"
  assert "ConfirmDialog(msg, tr(\"OK\"), rich=True)" in src, "_show_help no abre el dialogo informativo"


def test_el_dialogo_define_la_terminologia():
  textos = _textos(_leer())
  for termino in ("ARMAR (modo banco)", "DESARMAR TODO",
                  "MODO (observador / copiloto / maniobra)", "ENLACE", "BANCO ARMADO"):
    assert any(termino in t for t in textos), f"el dialogo no define {termino}"


if __name__ == "__main__":
  test_el_panel_tiene_boton_de_definiciones()
  test_show_help_abre_un_dialogo_informativo()
  test_el_dialogo_define_la_terminologia()
  print("OK")
