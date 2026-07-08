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
