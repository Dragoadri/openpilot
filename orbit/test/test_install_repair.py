"""La auto-reparacion del arranque no puede ser nunca el motivo de que el coche no arranque.

Estos tests fijan el contrato del script que corre en launch_chffrplus.sh ANTES de
la comprobacion de AGNOS y del build: acota todo lo que toca la red con timeout,
mata a sus hijos si se pasan, informa por el spinner sin depender de que exista, y
devuelve 0 pase lo que pase. Tambien fijan la deteccion: que se repare SOLO lo que
esta roto, y que los modelos big_* (solo USB-GPU, 310 MB que el comma no usa) ni
se descarguen ni cuenten como instalacion incompleta.
"""
import os
import time
import urllib.error

import pytest

from openpilot.orbit import install_check
from openpilot.orbit import install_repair as ir

LFS_POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 427473\n"


def make_tree(root, *, pointers=(), drop_sentinels=()):
  """Arbol minimo que install_check considera sano, con roturas opcionales."""
  (root / ".git").mkdir(parents=True, exist_ok=True)  # repair() exige un repo git para actuar
  for sentinel in install_check._SUBMODULE_SENTINELS:
    if install_check._SUBMODULE_SENTINELS[sentinel] in drop_sentinels:
      continue
    p = root / sentinel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
  for rel in pointers:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(LFS_POINTER)
  return str(root)


# --- deteccion ---------------------------------------------------------------

def test_inspect_healthy_tree_reports_nothing(tmp_path):
  st = install_check.inspect_install(make_tree(tmp_path))
  assert st.missing_submodules == [] and st.lfs_pointers == []
  assert install_check.run_install_check(str(tmp_path)) == []


def test_inspect_reports_pointer_and_missing_submodule(tmp_path):
  base = make_tree(tmp_path, pointers=["selfdrive/assets/fonts/Inter-Regular.png"], drop_sentinels=["panda"])
  st = install_check.inspect_install(base)
  assert st.missing_submodules == ["panda"]
  assert st.lfs_pointers == ["selfdrive/assets/fonts/Inter-Regular.png"]
  problems = install_check.run_install_check(base)
  assert len(problems) == 2


def test_usbgpu_only_models_are_not_an_install_problem(tmp_path):
  base = make_tree(tmp_path, pointers=["selfdrive/modeld/models/big_driving_vision.onnx",
                                       "selfdrive/modeld/models/big_driving_on_policy.onnx"])
  assert install_check.inspect_install(base).lfs_pointers == []
  # ...pero el modelo que SI usa el comma sigue contando
  base = make_tree(tmp_path, pointers=["selfdrive/modeld/models/driving_vision.onnx"])
  assert install_check.inspect_install(base).lfs_pointers == ["selfdrive/modeld/models/driving_vision.onnx"]


# --- utilidades --------------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
  ("Downloading LFS objects:  45% (118/263), 60 MB | 2.1 MB/s", "118/263 (60 MB)"),
  ("Downloading LFS objects:   0% (0/1), 0 B | 0 B/s", "0/1 (0 B)"),
  ("Downloading LFS objects: 100% (263/263), 420 MB | 16.7 MB/s, done.", "263/263 (420 MB)"),
  ("Git LFS: (1 of 3 files) 2.00 MB / 6.00 MB", None),
  ("batch request: missing protocol", None),
  ("", None),
])
def test_parse_lfs_progress(line, expected):
  assert ir.parse_lfs_progress(line) == expected


def test_run_logged_streams_cr_separated_progress_and_returns_rc(tmp_path):
  seen = []
  rc = ir.run_logged(["bash", "-c", "printf 'a 10%%\\ra 50%%\\rdone\\n'; echo err >&2; exit 3"],
                     cwd=str(tmp_path), timeout=10, log=seen.append)
  assert rc == 3
  assert seen == ["a 10%", "a 50%", "done", "err"]


def test_run_logged_timeout_kills_child(tmp_path):
  seen = []
  t0 = time.monotonic()
  rc = ir.run_logged(["bash", "-c", "sleep 30"], cwd=str(tmp_path), timeout=0.3, log=seen.append)
  assert rc == ir.TIMEOUT_RC
  assert time.monotonic() - t0 < 5
  assert any("timeout" in s for s in seen)


def test_run_logged_missing_binary_is_an_error_code_not_an_exception(tmp_path):
  seen = []
  rc = ir.run_logged(["/nonexistent/binary"], cwd=str(tmp_path), timeout=1, log=seen.append)
  assert rc != 0 and seen


class FakeSpinner:
  instances: list = []

  def __init__(self):
    self.updates: list[str] = []
    self.closed = False
    FakeSpinner.instances.append(self)

  def update(self, text):
    self.updates.append(text)

  def close(self):
    self.closed = True


class ExplodingSpinner:
  def __init__(self):
    raise OSError("no display")


def test_feedback_rate_limits_and_closes():
  clock = [100.0]
  fb = ir.Feedback(spinner_factory=FakeSpinner, enabled=True, min_interval=0.5, clock=lambda: clock[0])
  fb.text("uno")
  fb.text("dos")            # demasiado pronto: se descarta
  clock[0] += 1.0
  fb.text("tres")
  fb.text("cuatro", force=True)
  fb.close()
  sp = FakeSpinner.instances[-1]
  assert sp.updates == ["uno", "tres", "cuatro"]
  assert sp.closed


def test_feedback_swallows_spinner_failures():
  fb = ir.Feedback(spinner_factory=ExplodingSpinner, enabled=True)
  fb.text("hola", force=True)  # no lanza
  fb.close()

  class Broken(FakeSpinner):
    def update(self, text):
      raise BrokenPipeError()
  fb = ir.Feedback(spinner_factory=Broken, enabled=True)
  fb.text("hola", force=True)
  fb.close()


def test_feedback_disabled_never_builds_a_spinner():
  before = len(FakeSpinner.instances)
  fb = ir.Feedback(spinner_factory=FakeSpinner, enabled=False)
  fb.text("x", force=True)
  fb.close()
  assert len(FakeSpinner.instances) == before


def test_wait_for_network_retries_until_any_http_answer():
  attempts = []

  def opener(url, timeout):
    attempts.append(url)
    if len(attempts) < 3:
      raise urllib.error.URLError("unreachable")
    raise urllib.error.HTTPError(url, 405, "nope", {}, None)  # el servidor contesta: hay red

  clock = [0.0]
  slept = []
  ok = ir.wait_for_network("https://example.invalid/info/lfs", deadline_s=60, feedback=ir.Feedback(enabled=False),
                           log=lambda _m: None, opener=opener, clock=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
  assert ok and len(attempts) == 3 and len(slept) == 2


def test_wait_for_network_gives_up_at_deadline():
  clock = [0.0]

  def opener(url, timeout):
    raise urllib.error.URLError("unreachable")

  ok = ir.wait_for_network("https://example.invalid/info/lfs", deadline_s=10, feedback=ir.Feedback(enabled=False),
                           log=lambda _m: None, opener=opener, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
  assert ok is False


def test_lfs_url_comes_from_lfsconfig(tmp_path):
  (tmp_path / ".lfsconfig").write_text("[lfs]\n\turl = https://gitlab.example/x.git/info/lfs\n\tlocksverify = false\n")
  assert ir.lfs_url(str(tmp_path)) == "https://gitlab.example/x.git/info/lfs"
  assert ir.lfs_url(str(tmp_path / "nowhere")) == ir.DEFAULT_LFS_URL


# --- reparacion --------------------------------------------------------------

def test_repair_lfs_skips_pull_when_git_lfs_is_missing(tmp_path, monkeypatch):
  calls = []
  monkeypatch.setattr(ir, "git_lfs_available", lambda basedir: False)
  monkeypatch.setattr(ir, "run_logged", lambda cmd, **kw: calls.append(cmd) or 0)
  ir.repair_lfs(str(tmp_path), log=lambda _m: None, feedback=ir.Feedback(enabled=False))
  assert calls == []


def test_repair_lfs_waits_for_network_before_pulling(tmp_path, monkeypatch):
  calls = []
  monkeypatch.setattr(ir, "git_lfs_available", lambda basedir: True)
  monkeypatch.setattr(ir, "wait_for_network", lambda *a, **kw: False)
  monkeypatch.setattr(ir, "run_logged", lambda cmd, **kw: calls.append(cmd) or 0)
  ir.repair_lfs(str(tmp_path), log=lambda _m: None, feedback=ir.Feedback(enabled=False))
  assert calls == []


def test_repair_lfs_pull_excludes_usbgpu_models_and_forces_progress(tmp_path, monkeypatch):
  calls = []
  monkeypatch.setattr(ir, "git_lfs_available", lambda basedir: True)
  monkeypatch.setattr(ir, "wait_for_network", lambda *a, **kw: True)

  def fake_run(cmd, cwd, timeout, log, on_line=None, env=None):
    calls.append((cmd, cwd, timeout, env))
    return 0
  monkeypatch.setattr(ir, "run_logged", fake_run)

  ir.repair_lfs(str(tmp_path), log=lambda _m: None, feedback=ir.Feedback(enabled=False))
  cmds = [c[0] for c in calls]
  assert cmds[0][:3] == ["git", "lfs", "install"] and "--local" in cmds[0] and "--skip-repo" in cmds[0]
  pull = cmds[1]
  assert pull[:3] == ["git", "lfs", "pull"]
  assert any(a.startswith("--exclude=") and "big_" in a for a in pull)
  _, cwd, timeout, env = calls[1]
  assert cwd == str(tmp_path) and 0 < timeout <= ir.LFS_PULL_TIMEOUT_S
  assert env["GIT_LFS_FORCE_PROGRESS"] == "1"


def test_repair_only_touches_what_is_broken(tmp_path, monkeypatch):
  done = []
  monkeypatch.setattr(ir, "repair_lfs", lambda basedir, log, feedback: done.append("lfs"))
  monkeypatch.setattr(ir, "repair_submodules", lambda basedir, log, feedback: done.append("submodules"))
  fb = ir.Feedback(enabled=False)

  base = make_tree(tmp_path / "ok")
  assert ir.repair(base, log=lambda _m: None, feedback=fb) == []
  assert done == []

  base = make_tree(tmp_path / "lfs", pointers=["selfdrive/assets/fonts/Inter-Regular.png"])
  remaining = ir.repair(base, log=lambda _m: None, feedback=fb)
  assert done == ["lfs"] and len(remaining) == 1  # el fake no arregla nada: queda pendiente y se informa

  done.clear()
  base = make_tree(tmp_path / "sub", drop_sentinels=["panda"])
  ir.repair(base, log=lambda _m: None, feedback=fb)
  assert done == ["submodules"]


def test_main_never_fails(monkeypatch, tmp_path):
  monkeypatch.setattr(ir, "LOG_PATH", str(tmp_path / "log"))
  monkeypatch.setattr(ir, "repair", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
  monkeypatch.setattr(ir, "spinner_enabled", lambda: False)
  assert ir.main() == 0
  assert "boom" in (tmp_path / "log").read_text()


def test_main_healthy_tree_is_fast_and_quiet(monkeypatch, tmp_path):
  monkeypatch.setattr(ir, "LOG_PATH", str(tmp_path / "log"))
  monkeypatch.setattr(ir, "BASEDIR", make_tree(tmp_path / "tree"))
  monkeypatch.setattr(ir, "spinner_enabled", lambda: False)
  monkeypatch.setattr(ir, "run_logged", lambda *a, **kw: pytest.fail("no debe ejecutar nada en un arbol sano"))
  assert ir.main() == 0
  assert not os.path.exists(tmp_path / "log")  # ni un log: coste cero en el arranque normal
