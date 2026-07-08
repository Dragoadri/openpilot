# MetaDrive Sim Mod-Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-sim mod-menu to the MetaDrive simulator so a user can, at runtime, swap map presets (incl. roundabout), toggle/tune traffic, and spawn cars and obstacles on demand to test avoidance and lead-car response — driven by terminal hotkeys with an on-screen HUD.

**Architecture:** Reuse the existing 3-process input chain (keyboard → `Queue` → bridge → `Pipe` → metadrive process). A new command vocabulary travels that chain to a `ModMenu` object living inside the metadrive process, which mutates `env.engine` (spawns) and requests `env.reset()`-based changes (traffic, map). A single input source (the terminal) avoids keyboard-focus conflicts; the HUD is display-only via Panda3D `OnscreenText` in the `--render` window.

**Tech Stack:** Python (openpilot `tools/sim`), MetaDrive commaai `minimal` fork v0.4.2.3, Panda3D, multiprocessing (`Queue`/`Pipe`).

## Global Constraints

- **Indentation is 2 spaces** across all `tools/sim` Python (match existing files). No tabs, no 4-space.
- **Backward compatible by default:** `./run_bridge.py` with no new flags must reproduce today's world exactly — map `loop`, `traffic_density=0.0`, no render window. New `MetaDriveBridge.__init__` params are keyword args with defaults placed AFTER the existing positional params, so `MetaDriveBridge(False, False, test_duration, True)` (used by `tools/sim/tests/test_metadrive_bridge.py`) keeps working.
- **MetaDrive is not installed in `ORBITPILOT/.venv`.** It lives in the sibling `SICUEM/openpilot/.venv`. To run any sim test or the sim itself, metadrive must be importable. Either run `uv sync --extra tools` in ORBITPILOT once, or run the commands with the SICUEM venv's Python. Test commands below assume `python`/`pytest` resolve metadrive; if you get `ModuleNotFoundError: metadrive`, prefix with the tools venv.
- **Minimal-fork asset limits (verified):** only `TrafficWarning` has a mesh; `TrafficCone`/`TrafficBarrier` raise `IOError` on construct unless their class `MODEL` is preloaded. NPC vehicles render as boxes. Do not rely on visual car fidelity.
- **Map cache trap:** changing the map at runtime requires `env.engine.map_manager.clear_stored_maps()` before `env.reset()`, and mutation of `env.config["map_config"]` (NOT `env.config["map"]`).
- DRY, YAGNI, TDD, frequent commits. One logical change per commit.

## File Structure

**New files**
- `tools/sim/bridge/metadrive/metadrive_maps.py` — map preset library (`MAP_NAMES`, `get_map_config`, `create_map`). Pure geometry/config; the only new file that imports metadrive (for the `MapGenerateMethod` enum).
- `tools/sim/bridge/metadrive/metadrive_command.py` — command vocabulary constants + `is_mod_command`. Pure strings, no imports.
- `tools/sim/bridge/metadrive/metadrive_modmenu.py` — `ModMenu` class (runs in the metadrive process): state, `apply`, spawn/obstacle/traffic/map actions, HUD. Metadrive imports are LAZY (inside methods) so the class + dispatch is unit-testable without metadrive.
- `tools/sim/preview_map.py` — standalone map previewer.

**Modified files**
- `tools/sim/bridge/metadrive/metadrive_bridge.py` — use `metadrive_maps`; add `map`/`traffic`/`render`/`track_size` kwargs; add `build_config()`; set `use_render`/`multi_thread_render`; pass mod-menu opts to the world.
- `tools/sim/bridge/metadrive/metadrive_world.py` — add `mod_cmd` pipe + `send_command()`; thread the receiver + mod-menu opts into the process.
- `tools/sim/bridge/metadrive/metadrive_process.py` — build `ModMenu`, poll the mod-cmd pipe, apply pending traffic/map resets, draw HUD.
- `tools/sim/bridge/common.py` — route `mod_*` `CONTROL_COMMAND`s to `world.send_command`.
- `tools/sim/lib/keyboard_ctrl.py` — add mod-menu hotkeys via a pure `key_to_command`.
- `tools/sim/run_bridge.py` — add CLI flags and thread them through.
- `tools/sim/README.md` — document maps, hotkeys, previewer, caveats.
- `tools/sim/tests/test_metadrive_bridge.py` — (verify unchanged-behaviour still passes; no code change expected).

**Execution phases** (stop points for review): Phase 1 = Tasks 1–3 (foundation). Phase 2 = Tasks 4–7 (channel + rock-solid spawn/obstacle/clear). Phase 3 = Tasks 8–9 (traffic + HUD, needs render). Phase 4 = Task 10 (map switch, spike). Phase 5 = Tasks 11–12 (previewer + docs).

---

### Task 1: Map preset library

**Files:**
- Create: `tools/sim/bridge/metadrive/metadrive_maps.py`
- Test: `tools/sim/tests/test_metadrive_maps.py`

**Interfaces:**
- Produces: `create_map(track_size: int = 60) -> dict` (the current closed loop); `get_map_config(name: str, track_size: int = 60) -> dict`; `MAP_NAMES: list[str]` (cycle order). Every returned dict has keys `type`, `lane_num`, `lane_width`, `config`.

- [ ] **Step 1: Write the failing test**

```python
# tools/sim/tests/test_metadrive_maps.py
from metadrive.component.map.pg_map import MapGenerateMethod
from openpilot.tools.sim.bridge.metadrive import metadrive_maps as m


def test_map_names_nonempty_and_loop_first():
  assert m.MAP_NAMES[0] == "loop"
  assert "roundabout" in m.MAP_NAMES


def test_loop_is_closed_pg_map_file():
  cfg = m.get_map_config("loop", track_size=60)
  assert cfg["type"] == MapGenerateMethod.PG_MAP_FILE
  assert cfg["config"][0] is None            # first block must be None (implicit start block)
  ids = [b["id"] for b in cfg["config"][1:]]
  assert ids == ["S", "C", "S", "C", "S", "C", "S", "C"]


def test_roundabout_is_block_sequence_with_O():
  cfg = m.get_map_config("roundabout")
  assert cfg["type"] == MapGenerateMethod.BIG_BLOCK_SEQUENCE
  assert "O" in cfg["config"]                 # config is a block-letter string


def test_every_named_map_builds_a_valid_dict():
  for name in m.MAP_NAMES:
    cfg = m.get_map_config(name)
    assert set(cfg) >= {"type", "lane_num", "lane_width", "config"}


def test_unknown_map_falls_back_to_loop():
  assert m.get_map_config("does-not-exist") == m.get_map_config("loop")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tools/sim/tests/test_metadrive_maps.py -v`
Expected: FAIL with `ModuleNotFoundError` for `metadrive_maps` (module not created yet).

- [ ] **Step 3: Write minimal implementation**

```python
# tools/sim/bridge/metadrive/metadrive_maps.py
from metadrive.component.map.pg_map import MapGenerateMethod


def straight_block(length):
  return {"id": "S", "pre_block_socket_index": 0, "length": length}


def curve_block(length, angle=45, direction=0):
  return {"id": "C", "pre_block_socket_index": 0, "length": length,
          "radius": length, "angle": angle, "dir": direction}


def create_map(track_size=60):
  # The historical default: a closed 4-straight / 4-curve loop for endless driving.
  curve_len = track_size * 2
  return dict(
    type=MapGenerateMethod.PG_MAP_FILE,
    lane_num=2,
    lane_width=4.5,
    config=[
      None,
      straight_block(track_size),
      curve_block(curve_len, 90),
      straight_block(track_size),
      curve_block(curve_len, 90),
      straight_block(track_size),
      curve_block(curve_len, 90),
      straight_block(track_size),
      curve_block(curve_len, 90),
    ],
  )


def _sequence_map(block_sequence, lane_num=3, lane_width=3.5):
  # A procedurally-built map from a block-letter string (S,C,O,X,T,r,R,...).
  # Entry/exit straights flank special blocks so the ego routes in and out.
  return dict(
    type=MapGenerateMethod.BIG_BLOCK_SEQUENCE,
    lane_num=lane_num,
    lane_width=lane_width,
    config=block_sequence,
  )


# name -> builder(track_size) -> map_config dict
_BUILDERS = {
  "loop":           lambda ts: create_map(ts),
  "roundabout":     lambda ts: _sequence_map("SOS"),
  "intersection_x": lambda ts: _sequence_map("SXS"),
  "intersection_t": lambda ts: _sequence_map("STS"),
  "highway":        lambda ts: _sequence_map("SSSS", lane_num=3),
  "ramps":          lambda ts: _sequence_map("SrRS", lane_num=3),
}

# Cycle order for the mod-menu (loop stays first = current default).
MAP_NAMES = ["loop", "roundabout", "intersection_x", "intersection_t", "highway", "ramps"]


def get_map_config(name, track_size=60):
  builder = _BUILDERS.get(name, _BUILDERS["loop"])
  return builder(track_size)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tools/sim/tests/test_metadrive_maps.py -v`
Expected: PASS (5 tests). If `ModuleNotFoundError: metadrive`, run with the tools venv (see Global Constraints).

- [ ] **Step 5: Commit**

```bash
git add tools/sim/bridge/metadrive/metadrive_maps.py tools/sim/tests/test_metadrive_maps.py
git commit -m "feat(sim): map preset library with roundabout/intersection/highway"
```

---

### Task 2: Command vocabulary

**Files:**
- Create: `tools/sim/bridge/metadrive/metadrive_command.py`
- Test: `tools/sim/tests/test_metadrive_command.py`

**Interfaces:**
- Produces: string constants `LEAD, CUTIN, OBSTACLE, OBSTACLE_SIDE, TRAFFIC_TOGGLE, TRAFFIC_UP, TRAFFIC_DOWN, MAP_NEXT, MAP_PREV, CLEAR, HUD`; set `ALL`; `is_mod_command(info) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tools/sim/tests/test_metadrive_command.py
from openpilot.tools.sim.bridge.metadrive import metadrive_command as c


def test_all_constants_are_mod_prefixed_and_unique():
  assert len(c.ALL) == 11
  assert all(cmd.startswith("mod_") for cmd in c.ALL)


def test_is_mod_command_true_for_known():
  assert c.is_mod_command(c.LEAD)
  assert c.is_mod_command("mod_clear")


def test_is_mod_command_false_for_others():
  assert not c.is_mod_command("reset")
  assert not c.is_mod_command("mod_bogus")
  assert not c.is_mod_command(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tools/sim/tests/test_metadrive_command.py -v`
Expected: FAIL with `ModuleNotFoundError` for `metadrive_command`.

- [ ] **Step 3: Write minimal implementation**

```python
# tools/sim/bridge/metadrive/metadrive_command.py
# Mod-menu command vocabulary. Plain strings so both the bridge process and the
# metadrive process can share them without importing metadrive.

LEAD = "mod_lead"                  # stopped car ahead (lead / hard-brake test)
CUTIN = "mod_cutin"               # moving IDM car in adjacent lane
OBSTACLE = "mod_obstacle"         # obstacle centred in lane (dodge / stop test)
OBSTACLE_SIDE = "mod_obstacle_side"  # obstacle offset into the lane
TRAFFIC_TOGGLE = "mod_traffic_toggle"
TRAFFIC_UP = "mod_traffic_up"
TRAFFIC_DOWN = "mod_traffic_down"
MAP_NEXT = "mod_map_next"
MAP_PREV = "mod_map_prev"
CLEAR = "mod_clear"               # remove everything spawned
HUD = "mod_hud"                   # toggle the on-screen HUD

ALL = {
  LEAD, CUTIN, OBSTACLE, OBSTACLE_SIDE, TRAFFIC_TOGGLE, TRAFFIC_UP,
  TRAFFIC_DOWN, MAP_NEXT, MAP_PREV, CLEAR, HUD,
}


def is_mod_command(info):
  return isinstance(info, str) and info in ALL
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tools/sim/tests/test_metadrive_command.py -v`
Expected: PASS (3 tests). This test needs no metadrive.

- [ ] **Step 5: Commit**

```bash
git add tools/sim/bridge/metadrive/metadrive_command.py tools/sim/tests/test_metadrive_command.py
git commit -m "feat(sim): mod-menu command vocabulary"
```

---

### Task 3: Keyboard hotkeys

**Files:**
- Modify: `tools/sim/lib/keyboard_ctrl.py`
- Test: `tools/sim/tests/test_keyboard_ctrl.py`

**Interfaces:**
- Consumes: `metadrive_command` constants (Task 2).
- Produces: `key_to_command(c: str) -> str | None` (pure key→command-string map). `keyboard_poll_thread` uses it.

- [ ] **Step 1: Write the failing test**

```python
# tools/sim/tests/test_keyboard_ctrl.py
from openpilot.tools.sim.lib.keyboard_ctrl import key_to_command
from openpilot.tools.sim.bridge.metadrive import metadrive_command as c


def test_existing_keys_unchanged():
  assert key_to_command("1") == "cruise_up"
  assert key_to_command("w") == "throttle_1.0"
  assert key_to_command("r") == "reset"
  assert key_to_command("q") == "quit"


def test_mod_keys_map_to_commands():
  assert key_to_command("l") == c.LEAD
  assert key_to_command("k") == c.CUTIN
  assert key_to_command("o") == c.OBSTACLE
  assert key_to_command("p") == c.OBSTACLE_SIDE
  assert key_to_command("t") == c.TRAFFIC_TOGGLE
  assert key_to_command("m") == c.MAP_NEXT
  assert key_to_command("n") == c.MAP_PREV
  assert key_to_command("c") == c.CLEAR
  assert key_to_command("h") == c.HUD


def test_traffic_density_keys():
  assert key_to_command("+") == c.TRAFFIC_UP
  assert key_to_command("=") == c.TRAFFIC_UP
  assert key_to_command("-") == c.TRAFFIC_DOWN


def test_unknown_key_returns_none():
  assert key_to_command("Q") is None
  assert key_to_command("5") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tools/sim/tests/test_keyboard_ctrl.py -v`
Expected: FAIL with `ImportError: cannot import name 'key_to_command'`.

- [ ] **Step 3: Write minimal implementation**

Add the import and a pure mapping near the top of `tools/sim/lib/keyboard_ctrl.py` (after the existing imports):

```python
from openpilot.tools.sim.bridge.metadrive import metadrive_command as mod

_KEYMAP = {
  "1": "cruise_up",
  "2": "cruise_down",
  "3": "cruise_cancel",
  "w": f"throttle_{1.0}",
  "a": f"steer_{-0.15}",
  "s": f"brake_{1.0}",
  "d": f"steer_{0.15}",
  "z": "blinker_left",
  "x": "blinker_right",
  "i": "ignition",
  "r": "reset",
  "q": "quit",
  # --- mod-menu ---
  "l": mod.LEAD,
  "k": mod.CUTIN,
  "o": mod.OBSTACLE,
  "p": mod.OBSTACLE_SIDE,
  "t": mod.TRAFFIC_TOGGLE,
  "+": mod.TRAFFIC_UP,
  "=": mod.TRAFFIC_UP,
  "-": mod.TRAFFIC_DOWN,
  "m": mod.MAP_NEXT,
  "n": mod.MAP_PREV,
  "c": mod.CLEAR,
  "h": mod.HUD,
}


def key_to_command(c):
  return _KEYMAP.get(c)
```

Update `KEYBOARD_HELP` to document the new keys:

```python
KEYBOARD_HELP = """
  | key  |   functionality       |
  |------|-----------------------|
  |  1   | Cruise Resume / Accel |
  |  2   | Cruise Set    / Decel |
  |  3   | Cruise Cancel         |
  |  r   | Reset Simulation      |
  |  i   | Toggle Ignition       |
  |  q   | Exit all              |
  | wasd | Control manually      |
  |------| --- MOD-MENU --------- |
  |  l   | Spawn stopped lead car|
  |  k   | Spawn cut-in NPC (IDM)|
  |  o/p | Obstacle ahead / side |
  |  t   | Toggle traffic        |
  | +/-  | Traffic density up/dn |
  | m/n  | Next / prev map       |
  |  c   | Clear spawned objects |
  |  h   | Toggle HUD            |
"""
```

Replace the `if c == '1': ... elif ...` chain in `keyboard_poll_thread` with the table-driven version:

```python
def keyboard_poll_thread(q: 'Queue[QueueMessage]'):
  print_keyboard_help()

  while True:
    c = getch()
    cmd = key_to_command(c)
    if cmd is None:
      print_keyboard_help()
      continue
    q.put(control_cmd_gen(cmd))
    if cmd == "quit":
      break
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tools/sim/tests/test_keyboard_ctrl.py -v`
Expected: PASS (4 tests). Needs no metadrive (imports only `metadrive_command`, which is pure).

- [ ] **Step 5: Commit**

```bash
git add tools/sim/lib/keyboard_ctrl.py tools/sim/tests/test_keyboard_ctrl.py
git commit -m "feat(sim): mod-menu keyboard hotkeys via pure key_to_command"
```

---

### Task 4: Route mod commands through the bridge dispatch

**Files:**
- Modify: `tools/sim/bridge/common.py:132-161` (the `CONTROL_COMMAND` dispatch block)

**Interfaces:**
- Consumes: `metadrive_command.is_mod_command` (Task 2); a `world.send_command(cmd)` (added in Task 5).
- Produces: nothing new; wires keyboard `mod_*` commands to the world.

> This task's true test is the end-to-end run in Task 7 (the wiring crosses two processes and heavy imports make a unit test impractical). Keep the change to the two lines below.

- [ ] **Step 1: Add the import** near the other imports at the top of `tools/sim/bridge/common.py`:

```python
from openpilot.tools.sim.bridge.metadrive import metadrive_command
```

- [ ] **Step 2: Add the dispatch branch.** In `_run`, inside `if message.type == QueueMessageType.CONTROL_COMMAND:`, add a first branch BEFORE the `m = message.info.split('_')` line so mod commands are handled whole:

```python
        if message.type == QueueMessageType.CONTROL_COMMAND:
          if metadrive_command.is_mod_command(message.info):
            self.world.send_command(message.info)
            continue
          m = message.info.split('_')
          if m[0] == "steer":
```

Note: the `continue` skips the legacy `split('_')` parsing for mod commands. Leave the rest of the elif chain unchanged.

- [ ] **Step 3: Sanity import check**

Run: `python -c "import openpilot.tools.sim.bridge.common"`
Expected: no error (needs the tools venv; this only confirms the import/edit is syntactically valid).

- [ ] **Step 4: Commit**

```bash
git add tools/sim/bridge/common.py
git commit -m "feat(sim): route mod_* commands to world.send_command"
```

---

### Task 5: ModMenu class (dispatch + tracking + clear)

**Files:**
- Create: `tools/sim/bridge/metadrive/metadrive_modmenu.py`
- Test: `tools/sim/tests/test_metadrive_modmenu.py`

**Interfaces:**
- Consumes: `metadrive_command` (Task 2), `metadrive_maps.MAP_NAMES`/`get_map_config` (Task 1).
- Produces: `ModMenu(env, opts: dict)` where `opts = {"map_name","track_size","render","traffic_density"}`; attributes `spawned_ids: list`, `traffic_density: float`, `pending_reset: bool`, `pending_map: str|None`, `map_idx: int`; methods `apply(cmd)`, `clear()`, `on_reset()`, `map_config_for(name)`, `draw_hud()`, `create_hud()`, `toggle_hud()`, plus spawn helpers. Metadrive imports are lazy (inside methods).
- Produces: module-level pure helper `ahead_pose(lane, ego_position, distance, lateral=0.0) -> (pos, heading)`.

- [ ] **Step 1: Write the failing test** (uses fakes; no metadrive needed)

```python
# tools/sim/tests/test_metadrive_modmenu.py
from openpilot.tools.sim.bridge.metadrive.metadrive_modmenu import ModMenu, ahead_pose
from openpilot.tools.sim.bridge.metadrive import metadrive_command as c


class FakeLane:
  length = 1000.0
  def local_coordinates(self, pos):
    return (100.0, 0.0)                       # ego at longitudinal 100, centred
  def position(self, lon, lat):
    return [lon, lat]                          # trivial mapping for assertions
  def heading_theta_at(self, lon):
    return 0.0
  def width_at(self, lon):
    return 3.5


class FakeEngine:
  def __init__(self):
    self.cleared = []
  def clear_objects(self, ids):
    self.cleared.append(list(ids))
    return ids


class FakeEnv:
  def __init__(self):
    self.engine = FakeEngine()
    self.config = {"traffic_density": 0.0, "map_config": {}}
    self.vehicle = None                        # not needed for dispatch tests


def make_modmenu():
  return ModMenu(FakeEnv(), {"map_name": "loop", "track_size": 60,
                             "render": False, "traffic_density": 0.0})


def test_ahead_pose_projects_along_lane():
  pos, heading = ahead_pose(FakeLane(), [0, 0], 40.0, lateral=0.0)
  assert pos == [140.0, 0.0]                   # 100 + 40 longitudinal, 0 lateral
  assert heading == 0.0


def test_clear_calls_engine_and_empties_tracking():
  mm = make_modmenu()
  mm.spawned_ids = ["a", "b"]
  mm.apply(c.CLEAR)
  assert mm.env.engine.cleared == [["a", "b"]]
  assert mm.spawned_ids == []


def test_traffic_toggle_sets_density_and_requests_reset():
  mm = make_modmenu()
  mm.apply(c.TRAFFIC_TOGGLE)
  assert mm.traffic_density == 0.1
  assert mm.pending_reset is True
  mm.pending_reset = False
  mm.apply(c.TRAFFIC_TOGGLE)
  assert mm.traffic_density == 0.0
  assert mm.pending_reset is True


def test_traffic_up_down_clamped():
  mm = make_modmenu()
  mm.apply(c.TRAFFIC_DOWN)
  assert mm.traffic_density == 0.0             # clamped at 0
  mm.apply(c.TRAFFIC_UP)
  assert abs(mm.traffic_density - 0.05) < 1e-9


def test_map_next_prev_cycles_and_sets_pending():
  mm = make_modmenu()
  mm.apply(c.MAP_NEXT)
  assert mm.map_idx == 1
  assert mm.pending_map == "roundabout"
  mm.apply(c.MAP_PREV)
  assert mm.map_idx == 0
  assert mm.pending_map == "loop"


def test_on_reset_clears_tracking_only():
  mm = make_modmenu()
  mm.spawned_ids = ["x"]
  mm.on_reset()
  assert mm.spawned_ids == []
  assert mm.env.engine.cleared == []           # on_reset does not call clear_objects


def test_unknown_command_is_noop():
  mm = make_modmenu()
  mm.apply("mod_bogus")                         # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tools/sim/tests/test_metadrive_modmenu.py -v`
Expected: FAIL with `ModuleNotFoundError` for `metadrive_modmenu`.

- [ ] **Step 3: Write minimal implementation**

```python
# tools/sim/bridge/metadrive/metadrive_modmenu.py
from openpilot.tools.sim.bridge.metadrive import metadrive_command as cmd
from openpilot.tools.sim.bridge.metadrive.metadrive_maps import MAP_NAMES, get_map_config

TRAFFIC_STEP = 0.05
TRAFFIC_ON_DEFAULT = 0.1


def ahead_pose(lane, ego_position, distance, lateral=0.0):
  # Pure geometry: project a pose `distance` metres ahead of the ego along its lane.
  lon, lat = lane.local_coordinates(ego_position)
  s = min(lon + distance, getattr(lane, "length", lon + distance))
  pos = lane.position(s, lat + lateral)
  heading = lane.heading_theta_at(s)
  return pos, heading


class ModMenu:
  def __init__(self, env, opts):
    self.env = env
    self.track_size = opts.get("track_size", 60)
    self.render = opts.get("render", False)
    self.traffic_density = opts.get("traffic_density", 0.0)
    name = opts.get("map_name", "loop")
    self.map_idx = MAP_NAMES.index(name) if name in MAP_NAMES else 0
    self.spawned_ids = []
    self.pending_reset = False       # process should apply traffic + reset()
    self.pending_map = None          # process should switch map + reset()
    self.hud = None
    self.hud_visible = True

  # ---- dispatch ----------------------------------------------------------
  def apply(self, command):
    if command == cmd.LEAD:
      self.spawn_lead()
    elif command == cmd.CUTIN:
      self.spawn_cutin()
    elif command == cmd.OBSTACLE:
      self.spawn_obstacle(0.0)
    elif command == cmd.OBSTACLE_SIDE:
      self.spawn_obstacle(2.0)
    elif command == cmd.CLEAR:
      self.clear()
    elif command == cmd.HUD:
      self.toggle_hud()
    elif command == cmd.TRAFFIC_TOGGLE:
      self.traffic_density = 0.0 if self.traffic_density >= 0.01 else TRAFFIC_ON_DEFAULT
      self.pending_reset = True
    elif command == cmd.TRAFFIC_UP:
      self.traffic_density = min(1.0, self.traffic_density + TRAFFIC_STEP)
      self.pending_reset = True
    elif command == cmd.TRAFFIC_DOWN:
      self.traffic_density = max(0.0, self.traffic_density - TRAFFIC_STEP)
      self.pending_reset = True
    elif command == cmd.MAP_NEXT:
      self.map_idx = (self.map_idx + 1) % len(MAP_NAMES)
      self.pending_map = MAP_NAMES[self.map_idx]
    elif command == cmd.MAP_PREV:
      self.map_idx = (self.map_idx - 1) % len(MAP_NAMES)
      self.pending_map = MAP_NAMES[self.map_idx]
    self.draw_hud()

  def map_config_for(self, name):
    return get_map_config(name, self.track_size)

  # ---- object lifecycle --------------------------------------------------
  def clear(self):
    eng = self.env.engine
    if not self.spawned_ids:
      return
    tm = getattr(eng, "traffic_manager", None)
    if tm is not None and hasattr(tm, "_traffic_vehicles"):
      tm._traffic_vehicles = [v for v in tm._traffic_vehicles if v.id not in self.spawned_ids]
    eng.clear_objects(list(self.spawned_ids))
    self.spawned_ids = []

  def on_reset(self):
    # env.reset() destroys all spawned objects and rebuilds traffic; just drop our refs.
    self.spawned_ids = []

  # ---- spawns (lazy metadrive imports) -----------------------------------
  def _ego_lane(self):
    ego = self.env.vehicle
    if ego is None or getattr(ego, "navigation", None) is None:
      return None, None
    return ego, ego.lane

  def spawn_lead(self):
    from metadrive.component.vehicle.vehicle_type import DefaultVehicle
    ego, lane = self._ego_lane()
    if lane is None:
      return
    pos, heading = ahead_pose(lane, ego.position, 40.0)
    v = self.env.engine.spawn_object(
      DefaultVehicle,
      vehicle_config=dict(spawn_position_heading=(pos, heading), spawn_velocity=None),
    )
    self.spawned_ids.append(v.id)

  def spawn_cutin(self):
    import numpy as np
    from metadrive.component.vehicle.vehicle_type import DefaultVehicle
    from metadrive.policy.idm_policy import IDMPolicy
    ego, lane = self._ego_lane()
    if lane is None:
      return
    lon, lat = lane.local_coordinates(ego.position)
    s = lon + 25.0
    w = lane.width_at(s)
    pos = lane.position(s, lat + w)
    heading = lane.heading_theta_at(s)
    speed = 8.0
    vel = [speed * np.cos(heading), speed * np.sin(heading)]
    eng = self.env.engine
    tm = eng.traffic_manager
    v = tm.spawn_object(
      DefaultVehicle,
      vehicle_config=dict(spawn_position_heading=(pos, heading),
                          spawn_velocity=vel, spawn_velocity_car_frame=False),
    )
    tm.add_policy(v.id, IDMPolicy, v, eng.generate_seed())
    tm._traffic_vehicles.append(v)             # required so before_step drives it
    self.spawned_ids.append(v.id)

  def spawn_obstacle(self, lateral=0.0):
    from metadrive.component.static_object.traffic_object import TrafficWarning
    ego, lane = self._ego_lane()
    if lane is None:
      return
    pos, heading = ahead_pose(lane, ego.position, 30.0, lateral)
    obj = self.env.engine.spawn_object(
      TrafficWarning, lane=lane, position=pos, heading_theta=heading, static=True,
    )
    self.spawned_ids.append(obj.id)

  # ---- HUD ---------------------------------------------------------------
  def create_hud(self):
    if not self.render:
      return
    from direct.gui.OnscreenText import OnscreenText
    from panda3d.core import TextNode
    self.hud = OnscreenText(
      text="", parent=self.env.engine.aspect2d, pos=(-1.31, 0.92), scale=0.045,
      fg=(1, 1, 1, 1), bg=(0, 0, 0, 0.55), align=TextNode.ALeft, mayChange=True,
    )
    self.draw_hud()

  def toggle_hud(self):
    if self.hud is None:
      return
    self.hud_visible = not self.hud_visible
    self.hud.show() if self.hud_visible else self.hud.hide()

  def draw_hud(self):
    if self.hud is None or not self.hud_visible:
      return
    traffic = ("ON %.2f" % self.traffic_density) if self.traffic_density >= 0.01 else "OFF"
    self.hud.setText(
      "MOD-MENU  [h]\n"
      "map: %s\n"
      "traffic: %s\n"
      "spawned: %d\n"
      "[l]lead [k]cut-in\n"
      "[o]obst [p]side\n"
      "[t]traffic  +/-\n"
      "[m/n]map  [c]clear\n"
      "[r]reset [wasd]drive"
      % (MAP_NAMES[self.map_idx], traffic, len(self.spawned_ids))
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tools/sim/tests/test_metadrive_modmenu.py -v`
Expected: PASS (7 tests). Needs no metadrive (lazy imports keep the class importable; fakes exercise dispatch/tracking).

- [ ] **Step 5: Commit**

```bash
git add tools/sim/bridge/metadrive/metadrive_modmenu.py tools/sim/tests/test_metadrive_modmenu.py
git commit -m "feat(sim): ModMenu dispatch, object tracking, spawn helpers, HUD"
```

---

### Task 6: Wire the command pipe through the world

**Files:**
- Modify: `tools/sim/bridge/metadrive/metadrive_world.py` (`__init__`, add `send_command`)

**Interfaces:**
- Consumes: bridge passes a `modmenu_opts` dict into `MetaDriveWorld`.
- Produces: `MetaDriveWorld.send_command(cmd: str)`; a `mod_cmd_recv` connection passed into `metadrive_process` (used in Task 7).

> Verified end-to-end in Task 7's run. Keep changes minimal and mechanical.

- [ ] **Step 1: Add the pipe.** In `MetaDriveWorld.__init__`, next to the other `Pipe()` creations (after `self.vehicle_state_send, self.vehicle_state_recv = Pipe()`), add:

```python
    self.mod_cmd_send, self.mod_cmd_recv = Pipe()
```

- [ ] **Step 2: Accept and forward mod-menu opts.** Change the constructor signature and the `metadrive_process` partial. Signature:

```python
  def __init__(self, status_q, config, test_duration, test_run, dual_camera=False, modmenu_opts=None):
```

Store it right after `self.test_run = test_run`:

```python
    self.modmenu_opts = modmenu_opts or {}
```

Add `self.mod_cmd_recv` and `self.modmenu_opts` to the `functools.partial(metadrive_process, ...)` argument list, at the END (after `test_run`):

```python
    self.metadrive_process = multiprocessing.Process(name="metadrive process", target=
                              functools.partial(metadrive_process, dual_camera, config,
                                                self.camera_array, self.wide_camera_array, self.image_lock,
                                                self.controls_recv, self.simulation_state_send,
                                                self.vehicle_state_send, self.exit_event, self.op_engaged,
                                                test_duration, self.test_run,
                                                self.mod_cmd_recv, self.modmenu_opts))
```

- [ ] **Step 3: Add `send_command`.** Add this method to `MetaDriveWorld` (e.g. after `reset`):

```python
  def send_command(self, cmd):
    self.mod_cmd_send.send(cmd)
```

- [ ] **Step 4: Sanity import check**

Run: `python -c "import openpilot.tools.sim.bridge.metadrive.metadrive_world"`
Expected: no error (needs tools venv). This confirms the edited module imports; the process signature change is consumed in Task 7.

- [ ] **Step 5: Commit**

```bash
git add tools/sim/bridge/metadrive/metadrive_world.py
git commit -m "feat(sim): add mod-command pipe and send_command to MetaDriveWorld"
```

---

### Task 7: Build ModMenu in the process; apply commands, traffic, map, HUD

**Files:**
- Modify: `tools/sim/bridge/metadrive/metadrive_process.py` (signature, build ModMenu, loop)

**Interfaces:**
- Consumes: `mod_cmd_recv` + `modmenu_opts` from Task 6; `ModMenu` (Task 5); `get_map_config` (Task 1).
- Produces: nothing downstream; this is where commands take effect.

> Verified by the Phase-2 integration run at the end of this task.

- [ ] **Step 1: Extend the signature.** Change `metadrive_process(...)` to accept the two new trailing params:

```python
def metadrive_process(dual_camera: bool, config: dict, camera_array, wide_camera_array, image_lock,
                      controls_recv: Connection, simulation_state_send: Connection, vehicle_state_send: Connection,
                      exit_event, op_engaged, test_duration, test_run,
                      mod_cmd_recv: Connection = None, modmenu_opts: dict = None):
```

- [ ] **Step 2: Build the ModMenu** after `env = MetaDriveEnv(config)` and the first `reset()`. Add the import at the top of the file:

```python
from openpilot.tools.sim.bridge.metadrive.metadrive_modmenu import ModMenu
from openpilot.tools.sim.bridge.metadrive.metadrive_maps import get_map_config
```

After the existing `lane_idx_prev = reset()` line, add:

```python
  modmenu = ModMenu(env, modmenu_opts or {})
  modmenu.create_hud()
```

- [ ] **Step 3: Poll and apply commands** inside the main `while not exit_event.is_set():` loop. Right after the existing `if controls_recv.poll(0):` block (the one that reads steer/gas/should_reset), add:

```python
      if mod_cmd_recv is not None:
        while mod_cmd_recv.poll(0):
          modmenu.apply(mod_cmd_recv.recv())

        if modmenu.pending_reset:
          modmenu.pending_reset = False
          env.config["traffic_density"] = modmenu.traffic_density
          lane_idx_prev = reset()
          modmenu.on_reset()

        if modmenu.pending_map is not None:
          name = modmenu.pending_map
          modmenu.pending_map = None
          env.config["map_config"] = get_map_config(name, modmenu.track_size)
          env.engine.map_manager.clear_stored_maps()   # bust the store_map cache
          lane_idx_prev = reset()
          modmenu.on_reset()
          modmenu.create_hud()                          # recreate HUD after engine reset
```

Note: `create_hud()` is a no-op when `render` is False. Re-creating after a map reset is defensive (aspect2d nodes can be dropped on heavy resets); `ModMenu.create_hud` guards on `self.render`.

- [ ] **Step 4: Draw the HUD each rendered frame.** Inside the `if rk.frame % 5 == 0:` block, after `road_image[...] = get_cam_as_rgb("rgb_road")`, add:

```python
      modmenu.draw_hud()
```

- [ ] **Step 5: Integration run (rock-solid core, no render yet).**

Prereq: a terminal running openpilot sim per `tools/sim/README.md` (launch_openpilot.sh) plus the bridge. Minimal check for THIS task — spawn + clear without render:

Run (from repo root, tools venv):
```bash
cd tools/sim && ./run_bridge.py
```
Then in that terminal press: `l` (spawn lead), `k` (cut-in), `o` (obstacle), `c` (clear).
Expected: no crashes/tracebacks in the bridge or metadrive process; the metadrive process log stays alive; pressing `c` after spawns prints no error. (Visual confirmation of the cars comes in Task 8 with `--render`.)

If `env.vehicle`/`navigation` is None on a very early keypress, the guards make it a no-op — press again after the car is driving.

- [ ] **Step 6: Commit**

```bash
git add tools/sim/bridge/metadrive/metadrive_process.py
git commit -m "feat(sim): apply mod commands, runtime traffic + map switch, HUD in process"
```

---

### Task 8: Bridge kwargs, build_config, render flag, CLI

**Files:**
- Modify: `tools/sim/bridge/metadrive/metadrive_bridge.py` (`__init__`, add `build_config`, `spawn_world`)
- Modify: `tools/sim/run_bridge.py` (CLI flags + threading)
- Test: `tools/sim/tests/test_metadrive_bridge.py` (add a build_config assertion; keep existing behaviour)

**Interfaces:**
- Consumes: `metadrive_maps.get_map_config` (Task 1); `MetaDriveWorld(..., modmenu_opts=...)` (Task 6).
- Produces: `MetaDriveBridge(dual_camera, high_quality, test_duration=inf, test_run=False, map="loop", traffic=0.0, render=False, track_size=60)`; `MetaDriveBridge.build_config() -> dict`.

- [ ] **Step 1: Write the failing test.** Append to `tools/sim/tests/test_metadrive_bridge.py`:

```python
from openpilot.tools.sim.bridge.metadrive.metadrive_bridge import MetaDriveBridge
from openpilot.tools.sim.bridge.metadrive.metadrive_maps import get_map_config


def test_default_build_config_is_backward_compatible():
  b = MetaDriveBridge(False, False)
  cfg = b.build_config()
  assert cfg["traffic_density"] == 0.0
  assert cfg["use_render"] is False
  assert cfg["map_config"] == get_map_config("loop", 60)


def test_build_config_reflects_kwargs():
  b = MetaDriveBridge(False, False, map="roundabout", traffic=0.2, render=True)
  cfg = b.build_config()
  assert cfg["traffic_density"] == 0.2
  assert cfg["use_render"] is True
  assert cfg["multi_thread_render"] is False           # safety when rendering
  assert cfg["map_config"] == get_map_config("roundabout", 60)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tools/sim/tests/test_metadrive_bridge.py -k build_config -v`
Expected: FAIL with `AttributeError: 'MetaDriveBridge' object has no attribute 'build_config'`.

- [ ] **Step 3: Implement.** In `tools/sim/bridge/metadrive/metadrive_bridge.py`:

Replace the `from ... import` of the old `create_map`/`MapGenerateMethod` block usage by importing the maps module, and DELETE the local `straight_block`/`curve_block`/`create_map` defs (now in `metadrive_maps.py`). Add near the top:

```python
from openpilot.tools.sim.bridge.metadrive.metadrive_maps import get_map_config
```

(Remove the now-unused `from metadrive.component.map.pg_map import MapGenerateMethod` if nothing else uses it in this file.)

Change `__init__` to accept and store the new kwargs:

```python
  def __init__(self, dual_camera, high_quality, test_duration=math.inf, test_run=False,
               map="loop", traffic=0.0, render=False, track_size=60):
    super().__init__(dual_camera, high_quality)

    self.should_render = render
    self.test_run = test_run
    self.test_duration = test_duration if self.test_run else math.inf
    self.map = map
    self.traffic = traffic
    self.track_size = track_size
```

Extract config building into `build_config` and make `spawn_world` use it:

```python
  def build_config(self):
    sensors = {
      "rgb_road": (RGBCameraRoad, W, H, )
    }
    if self.dual_camera:
      sensors["rgb_wide"] = (RGBCameraWide, W, H)

    return dict(
      use_render=self.should_render,
      vehicle_config=dict(
        enable_reverse=False,
        render_vehicle=False,
        image_source="rgb_road",
      ),
      sensors=sensors,
      image_on_cuda=_cuda_enable,
      image_observation=True,
      interface_panel=[],
      out_of_route_done=False,
      on_continuous_line_done=False,
      crash_vehicle_done=False,
      crash_object_done=False,
      arrive_dest_done=False,
      traffic_density=self.traffic,
      map_config=get_map_config(self.map, self.track_size),
      decision_repeat=1,
      physics_world_step_size=self.TICKS_PER_FRAME/100,
      preload_models=False,
      show_logo=False,
      anisotropic_filtering=False,
      # Safety when a visible window coexists with CUDA offscreen cameras.
      multi_thread_render=not self.should_render,
    )

  def spawn_world(self, queue: Queue):
    config = self.build_config()
    modmenu_opts = dict(map_name=self.map, track_size=self.track_size,
                        render=self.should_render, traffic_density=self.traffic)
    return MetaDriveWorld(queue, config, self.test_duration, self.test_run,
                          self.dual_camera, modmenu_opts=modmenu_opts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tools/sim/tests/test_metadrive_bridge.py -k build_config -v`
Expected: PASS (2 tests). Then run the full file to confirm the existing tests still pass:
Run: `pytest tools/sim/tests/test_metadrive_bridge.py -v`
Expected: existing tests PASS (positional `MetaDriveBridge(False, False, test_duration, True)` still valid).

- [ ] **Step 5: Add CLI flags.** In `tools/sim/run_bridge.py`, extend `create_bridge` and `parse_args`:

```python
def create_bridge(dual_camera, high_quality, map="loop", traffic=0.0, render=False, track_size=60):
  queue: Any = Queue()

  simulator_bridge = MetaDriveBridge(dual_camera, high_quality, map=map, traffic=traffic,
                                     render=render, track_size=track_size)
  simulator_process = simulator_bridge.run(queue)

  return queue, simulator_process, simulator_bridge


def parse_args(add_args=None):
  parser = argparse.ArgumentParser(description='Bridge between the simulator and openpilot.')
  parser.add_argument('--joystick', action='store_true')
  parser.add_argument('--high_quality', action='store_true')
  parser.add_argument('--dual_camera', action='store_true')
  parser.add_argument('--map', default='loop', help='map preset: loop, roundabout, intersection_x, intersection_t, highway, ramps')
  parser.add_argument('--traffic', type=float, default=0.0, help='traffic density 0.0-1.0 (0 disables; expensive)')
  parser.add_argument('--render', action='store_true', help='open the MetaDrive window with the mod-menu HUD')
  parser.add_argument('--track-size', type=int, default=60, dest='track_size', help='loop preset size')

  return parser.parse_args(add_args)
```

Update the `__main__` block to thread them:

```python
  queue, simulator_process, simulator_bridge = create_bridge(
    args.dual_camera, args.high_quality, map=args.map, traffic=args.traffic,
    render=args.render, track_size=args.track_size)
```

- [ ] **Step 6: Verify CLI parses**

Run: `python tools/sim/run_bridge.py --help`
Expected: help text lists `--map`, `--traffic`, `--render`, `--track-size`.

- [ ] **Step 7: Commit**

```bash
git add tools/sim/bridge/metadrive/metadrive_bridge.py tools/sim/run_bridge.py tools/sim/tests/test_metadrive_bridge.py
git commit -m "feat(sim): map/traffic/render/track-size flags + build_config"
```

---

### Task 9: Render + HUD verification spike

**Files:** none (verification only; fixes land in the file they belong to).

**Goal:** Confirm `--render` opens a window, the mod-menu HUD shows, spawns are visible, and openpilot still receives camera frames.

- [ ] **Step 1: Launch with render.**

Run (tools venv, with openpilot sim running per README):
```bash
cd tools/sim && ./run_bridge.py --render
```
Expected: a MetaDrive window opens showing the road; the HUD panel appears top-left with `map: loop`, `traffic: OFF`, `spawned: 0`, and the hotkey legend.

- [ ] **Step 2: Exercise the mod-menu visually.** Press `l`, `k`, `o`, `p` — confirm box-cars / warning obstacle appear ahead; `spawned:` count rises. Press `c` — they vanish, count resets. Press `h` — HUD hides/shows.
Expected: objects appear at ~30–40 m ahead; openpilot's camera view (in its own UI) is not black — i.e. the offscreen camera still works alongside the window.

- [ ] **Step 3: If the camera view is black or CUDA/GL errors appear:** confirm `multi_thread_render=False` is set when rendering (Task 8, `build_config`). It already is; if problems persist, additionally set `image_on_cuda=False` in `build_config` when `self.should_render` is True (add `image_on_cuda=_cuda_enable and not self.should_render,`). Re-run Step 1. Document whichever combination works in `tools/sim/README.md` (Task 12).

- [ ] **Step 4: Commit** (only if a fix was needed)

```bash
git add tools/sim/bridge/metadrive/metadrive_bridge.py
git commit -m "fix(sim): stabilize render window alongside offscreen cameras"
```

---

### Task 10: Live map switch verification spike

**Files:** none (verification; the switch logic already landed in Task 7).

**Goal:** Confirm cycling maps at runtime works and the ego routes through a roundabout; establish the fallback if not.

- [ ] **Step 1: Cycle maps live.**

Run: `cd tools/sim && ./run_bridge.py --render`
Press `m` repeatedly. Expected: HUD `map:` cycles loop → roundabout → intersection_x → ... ; after a brief regeneration pause the new geometry appears and the ego re-spawns on it. Engage openpilot and confirm it drives the roundabout in and out.

- [ ] **Step 2: If a map switch crashes or the ego fails to route** (e.g. roundabout produces no valid start→dest route): keep launch-time selection working (`--map roundabout` already builds correctly at construction) and DISABLE runtime cycling by making `MAP_NEXT`/`MAP_PREV` a no-op with a log line. Edit `tools/sim/bridge/metadrive/metadrive_modmenu.py` `apply`:

```python
    elif command == cmd.MAP_NEXT or command == cmd.MAP_PREV:
      print("[mod-menu] live map switch disabled; relaunch with --map <name>")
```

Expected after fix: `./run_bridge.py --map roundabout --render` shows and drives the roundabout from launch.

- [ ] **Step 3: Commit** (whichever outcome)

```bash
git add tools/sim/bridge/metadrive/metadrive_modmenu.py
git commit -m "chore(sim): confirm live map switch (or fall back to launch-time --map)"
```

---

### Task 11: Standalone map previewer

**Files:**
- Create: `tools/sim/preview_map.py`

**Interfaces:**
- Consumes: `metadrive_maps.get_map_config`/`MAP_NAMES`.

- [ ] **Step 1: Implement.**

```python
#!/usr/bin/env python3
# Preview a map preset in a MetaDrive window without launching openpilot.
# Usage: ./preview_map.py --map roundabout   (q or Ctrl-C to quit)
import argparse

from metadrive.envs.metadrive_env import MetaDriveEnv

from openpilot.tools.sim.bridge.metadrive.metadrive_maps import get_map_config, MAP_NAMES


def main():
  parser = argparse.ArgumentParser(description="Preview a MetaDrive map preset.")
  parser.add_argument("--map", default="roundabout", help="one of: " + ", ".join(MAP_NAMES))
  parser.add_argument("--track-size", type=int, default=60, dest="track_size")
  args = parser.parse_args()

  env = MetaDriveEnv(dict(
    use_render=True,
    map_config=get_map_config(args.map, args.track_size),
    traffic_density=0.0,
  ))
  try:
    env.reset()
    print(f"Previewing '{args.map}'. Close the window or Ctrl-C to quit.")
    while True:
      _, _, terminated, truncated, _ = env.step([0.0, 0.0])
      env.render()
      if terminated or truncated:
        env.reset()
  except KeyboardInterrupt:
    pass
  finally:
    env.close()


if __name__ == "__main__":
  main()
```

- [ ] **Step 2: Make executable + run.**

Run:
```bash
chmod +x tools/sim/preview_map.py
cd tools/sim && ./preview_map.py --map roundabout
```
Expected: a window shows the roundabout geometry; no openpilot needed. Repeat with `--map intersection_x`, `--map highway`.

- [ ] **Step 3: Commit**

```bash
git add tools/sim/preview_map.py
git commit -m "feat(sim): standalone map previewer"
```

---

### Task 12: Documentation

**Files:**
- Modify: `tools/sim/README.md`

- [ ] **Step 1: Add a "Maps & Mod-Menu" section** to `tools/sim/README.md`:

````markdown
## Maps & Mod-Menu

Pick a map and (optionally) enable traffic and the on-screen mod-menu at launch:

```bash
./run_bridge.py --map roundabout --render          # drive a roundabout with the HUD
./run_bridge.py --map intersection_x --traffic 0.1 # a 4-way with light traffic
```

Map presets: `loop` (default, endless track), `roundabout`, `intersection_x`,
`intersection_t`, `highway`, `ramps`. Preview any map without openpilot:

```bash
./preview_map.py --map roundabout
```

### Mod-menu hotkeys (press in the run_bridge terminal)

| key | action | key | action |
|-----|--------|-----|--------|
| `l` | spawn stopped lead car | `t` | toggle traffic |
| `k` | spawn cut-in NPC (IDM)  | `+`/`-` | traffic density up/down |
| `o` | obstacle ahead (in lane)| `m`/`n` | next / previous map |
| `p` | obstacle offset to side | `c` | clear spawned objects |
| `h` | toggle HUD              | `r` | reset · `wasd` drive |

### Caveats (minimal MetaDrive fork)

- NPC vehicles and cones/barriers render as **boxes** (car/cone/barrier 3D
  meshes are stripped from the minimal assets). The default obstacle is a
  traffic **warning** sign, which is the only static object with a real mesh.
  Physics/collision and IDM behaviour are unaffected — good for testing
  avoidance and lead-car response, not for visual fidelity.
- Traffic is CPU-expensive; it is off by default.
- Real maps (Waymo/nuScenes/OSM via `ScenarioEnv`) are **not supported** here:
  they need the separate `scenarionet` package, converted datasets, and the 3D
  models the minimal fork strips. Do not wire `ScenarioEnv` into the bridge.
````

- [ ] **Step 2: Commit**

```bash
git add tools/sim/README.md
git commit -m "docs(sim): document map presets, mod-menu hotkeys, and fork caveats"
```

---

## Self-Review Notes (author checklist)

- **Spec coverage:** map presets+roundabout (T1), traffic toggle/density (T5/T7), spawn cars/obstacles on demand (T5/T6/T7), obstacle-to-dodge (T5 `OBSTACLE`/`OBSTACLE_SIDE`), HUD mod-menu (T5/T7/T9), previewer (T11), CLI + backward compat (T8), hotkeys (T3), docs + caveats (T12). Real-map dead-end explicitly out-of-scope (T12). All spec sections mapped.
- **Type consistency:** `send_command` (T6) matches the call in T4; `modmenu_opts` keys (`map_name`/`track_size`/`render`/`traffic_density`) are produced in T8 `spawn_world`, threaded in T6, consumed in T5 `ModMenu.__init__`; `get_map_config(name, track_size)` signature identical across T1/T5/T7/T8/T11; `metadrive_process` trailing params `mod_cmd_recv`/`modmenu_opts` match between T6 (partial) and T7 (signature).
- **Risks isolated as spikes:** render coexistence (T9) and live map switch (T10) each carry an explicit fallback that still delivers the feature.
