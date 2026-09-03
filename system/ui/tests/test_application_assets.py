"""Un asset ilegible no puede tumbar el proceso que lo carga.

En el dispositivo, un PNG que no se puede decodificar (fichero corrupto,
puntero git-lfs sin descargar, ruta que ya no existe) hace que raylib devuelva
una imagen de 0x0. El codigo de escalado dividia por esas dimensiones y el
ZeroDivisionError mataba al spinner de arranque y a la UI en bucle: pantalla
con el logo de AGNOS para siempre y luego negra, sin ningun mensaje. La carga
debe degradar a "no se pinta nada", igual que hace raylib con las fuentes.
"""
import pyray as rl
import pytest

from openpilot.system.ui.lib.application import gui_app

LFS_POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 427473\n"


@pytest.fixture(scope="module")
def hidden_window():
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(64, 64, "test_application_assets")
  if not rl.is_window_ready():
    pytest.skip("no display available for raylib")
  yield
  rl.close_window()


@pytest.mark.parametrize("content", [LFS_POINTER, b"", b"not a png at all"], ids=["lfs_pointer", "empty", "garbage"])
def test_unreadable_image_with_target_size_does_not_raise(hidden_window, tmp_path, content):
  bad = tmp_path / "icon.png"
  bad.write_bytes(content)

  image = gui_app._load_image_from_path(bad.as_posix(), 360, 360, alpha_premultiply=True, keep_aspect_ratio=True)
  assert image.width == 0 and image.height == 0

  texture = gui_app._load_texture_from_image(image)
  assert texture.id == 0  # se pinta "nada", no se explota


def test_missing_file_does_not_raise(hidden_window, tmp_path):
  image = gui_app._load_image_from_path((tmp_path / "nope.png").as_posix(), 100, 50, keep_aspect_ratio=False)
  assert image.width == 0 and image.height == 0
