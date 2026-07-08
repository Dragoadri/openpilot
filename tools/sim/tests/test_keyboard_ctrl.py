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
