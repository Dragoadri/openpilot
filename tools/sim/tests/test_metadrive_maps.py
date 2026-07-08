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
