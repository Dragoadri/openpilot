"""Diagnóstico de arranque: registro persistente, fase AGNOS narrada y pantalla de emergencia.

Fijan tres cosas que no se pueden comprobar en el dispositivo cuando se queda
en el logo: que el registro nunca rompe nada y no crece sin límite, que la fase
AGNOS hace exactamente lo que hacía upstream (verify → reboot, si no → updater)
pero contando en pantalla y con tope de intentos, y que la pantalla de
emergencia arranca con solo pyray.
"""
import os
import subprocess
import sys

import pytest

from openpilot.orbit import agnos_update as au
from openpilot.orbit import boot_log
from openpilot.orbit import install_repair as ir


# --- boot_log -----------------------------------------------------------------

def test_boot_log_appends_with_timestamp_and_rotates(tmp_path, monkeypatch):
  log = tmp_path / "boot.log"
  monkeypatch.setenv("ORBIT_BOOT_LOG", str(log))
  assert boot_log.path() == str(log)
  for i in range(boot_log.MAX_LINES + 50):
    boot_log.append(f"linea {i}")
  lines = log.read_text().splitlines()
  assert len(lines) == boot_log.MAX_LINES
  assert lines[-1].endswith(f"linea {boot_log.MAX_LINES + 49}")
  assert lines[0][:4].isdigit()  # empieza por la fecha


def test_boot_log_never_raises_on_unwritable_path(tmp_path):
  boot_log.append("x", log_path=str(tmp_path / "no" / "existe" / "boot.log"))
  assert boot_log.tail(str(tmp_path / "nada"), 5) == []


def test_boot_log_cli(tmp_path):
  log = tmp_path / "boot.log"
  r = subprocess.run([sys.executable, os.path.join(os.path.dirname(boot_log.__file__), "boot_log.py"), "hola", "mundo"],
                     env={**os.environ, "ORBIT_BOOT_LOG": str(log)}, capture_output=True, text=True, timeout=30)
  assert r.returncode == 0 and "hola mundo" in log.read_text() and "[ORBIT boot] hola mundo" in r.stdout


# --- agnos_update -------------------------------------------------------------

class Recorder:
  def __init__(self, verify_rc: int, updater_rc: int = 0):
    self.calls: list[list[str]] = []
    self.rebooted = 0
    self.verify_rc = verify_rc
    self.updater_rc = updater_rc

  def run(self, cmd, cwd, timeout, log, on_line=None, env=None):
    self.calls.append(cmd)
    return self.verify_rc if "--verify" in cmd else self.updater_rc

  def reboot(self, log):
    self.rebooted += 1


@pytest.fixture
def fast(monkeypatch):
  monkeypatch.setattr(au.time, "sleep", lambda s: None)


def test_agnos_matching_version_does_nothing_and_clears_attempts(tmp_path, fast):
  attempts = tmp_path / "attempts.json"
  attempts.write_text('{"target": "18.4", "count": 2}')
  rec = Recorder(verify_rc=0)
  out = au.update("/x/agnos.py", "/x/agnos.json", "18.4", log=lambda m: None, feedback=ir.Feedback(enabled=False),
                  current="18.4", attempts_file=str(attempts), run=rec.run, do_reboot=rec.reboot)
  assert out == "ok" and rec.calls == [] and not attempts.exists()


def test_agnos_other_slot_ready_swaps_and_reboots(tmp_path, fast):
  rec = Recorder(verify_rc=0)
  msgs = []
  out = au.update("/x/agnos.py", "/x/agnos.json", "18.4", log=msgs.append, feedback=ir.Feedback(enabled=False),
                  current="12.8", attempts_file=str(tmp_path / "a.json"), run=rec.run, do_reboot=rec.reboot)
  assert out == "reboot" and rec.rebooted == 1
  assert rec.calls == [["/x/agnos.py", "--verify", "/x/agnos.json"]]
  assert any("12.8" in m and "18.4" in m for m in msgs)  # la narración dice de qué versión a cuál


def test_agnos_not_ready_runs_updater_and_does_not_reboot_itself(tmp_path, fast):
  rec = Recorder(verify_rc=1, updater_rc=0)
  out = au.update("/x/agnos.py", "/x/agnos.json", "18.4", log=lambda m: None, feedback=ir.Feedback(enabled=False),
                  current="12.8", attempts_file=str(tmp_path / "a.json"), run=rec.run, do_reboot=rec.reboot)
  assert out == "updater" and rec.rebooted == 0
  assert rec.calls[1] == ["/x/updater", "/x/agnos.py", "/x/agnos.json"]


def test_agnos_gives_up_after_max_attempts(tmp_path, fast):
  attempts = tmp_path / "a.json"
  rec = Recorder(verify_rc=0)
  results = []
  for _ in range(au.MAX_ATTEMPTS + 2):
    results.append(au.update("/x/agnos.py", "/x/agnos.json", "18.4", log=lambda m: None, feedback=ir.Feedback(enabled=False),
                             current="12.8", attempts_file=str(attempts), run=rec.run, do_reboot=rec.reboot))
  assert results == ["reboot"] * au.MAX_ATTEMPTS + ["skipped", "skipped"]
  assert rec.rebooted == au.MAX_ATTEMPTS  # tras el tope no se reinicia más: el fallo queda visible


def test_agnos_attempts_reset_when_target_changes(tmp_path):
  attempts = tmp_path / "a.json"
  assert au.bump_attempts("12.8", "18.4", str(attempts)) == 1
  assert au.bump_attempts("12.8", "18.4", str(attempts)) == 2
  assert au.bump_attempts("12.8", "19.0", str(attempts)) == 1


def test_agnos_main_never_fails(tmp_path, monkeypatch):
  monkeypatch.setenv("ORBIT_BOOT_LOG", str(tmp_path / "boot.log"))
  monkeypatch.setattr(ir, "LOG_PATH", str(tmp_path / "repair.log"))
  monkeypatch.setattr(ir, "spinner_enabled", lambda: False)
  monkeypatch.setattr(au, "update", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
  assert au.main(["agnos_update.py", "/x/agnos.py", "/x/agnos.json", "18.4"]) == 0
  assert au.main(["agnos_update.py"]) == 0
  assert "boom" in (tmp_path / "boot.log").read_text()


# --- failsafe_screen ----------------------------------------------------------

def test_failsafe_build_lines_prioritises_and_truncates(tmp_path):
  from openpilot.orbit import failsafe_screen as fs
  a = tmp_path / "a.log"
  a.write_text("\n".join(f"a{i} " + "x" * 300 for i in range(50)) + "\n")
  b = tmp_path / "b.log"
  b.write_text("")
  lines = fs.build_lines([str(a), str(b), str(tmp_path / "missing.log")], rows=20)
  assert len(lines) <= 20
  assert lines[0].startswith("== ") and all(len(ln) <= fs.MAX_COLS for ln in lines)
  assert any("vacio" in ln for ln in lines) and any("missing.log" in ln for ln in lines)


def test_failsafe_screen_renders_one_frame_with_only_pyray(tmp_path):
  pytest.importorskip("pyray")
  log = tmp_path / "boot.log"
  log.write_text("2026-09-03 12:00:00 arranque comma 3X\n2026-09-03 12:00:05 manager.py: terminado rc=1\n")
  script = os.path.join(os.path.dirname(boot_log.__file__), "failsafe_screen.py")
  r = subprocess.run([sys.executable, script, "--once", str(log), str(tmp_path / "nada")],
                     env={**os.environ, "ORBIT_FAILSAFE_HIDDEN": "1"}, capture_output=True, text=True, timeout=60)
  if "Failed to initialize" in r.stderr or "GLFW" in r.stderr and r.returncode != 0:
    pytest.skip("no display available for raylib")
  assert r.returncode == 0, r.stderr[-800:]
