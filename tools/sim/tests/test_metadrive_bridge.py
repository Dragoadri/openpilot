import pytest
import warnings

# Since metadrive depends on pkg_resources, and pkg_resources is deprecated as an API
warnings.filterwarnings("ignore", category=DeprecationWarning)

from openpilot.tools.sim.bridge.metadrive.metadrive_bridge import MetaDriveBridge
from openpilot.tools.sim.bridge.metadrive.metadrive_maps import get_map_config
from openpilot.tools.sim.tests.test_sim_bridge import TestSimBridgeBase

@pytest.mark.slow
class TestMetaDriveBridge(TestSimBridgeBase):
  @pytest.fixture(autouse=True)
  def setup_create_bridge(self, test_duration):
    self.test_duration = 30

  def create_bridge(self):
    return MetaDriveBridge(False, False, self.test_duration, True)


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
