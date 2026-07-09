"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl
import time
from dataclasses import dataclass
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.sunnylink.api import UNREGISTERED_SUNNYLINK_DONGLE_ID
from openpilot.system.ui.lib.multilang import tr_noop


PING_TIMEOUT_NS = 80_000_000_000  # 80 seconds in nanoseconds
METRIC_HEIGHT = 126
METRIC_MARGIN = 30
METRIC_START_Y = 300
HOME_BTN = rl.Rectangle(60, 860, 180, 180)


# Color scheme — ORBIT palette (dark in-car ground station)
class Colors:
  # Neutrals: white -> INK, white-dim separators -> HAIRLINE, faint grey -> MUTED_DIM
  WHITE = rl.Color(226, 236, 255, 255)       # INK
  WHITE_DIM = rl.Color(43, 62, 95, 255)      # HAIRLINE
  GRAY = rl.Color(92, 117, 153, 255)         # MUTED_DIM

  # Status colors: good -> GREEN, warning -> AMBER, danger -> keep red, progress -> BLUE, disabled -> MUTED_DIM
  GOOD = rl.Color(74, 222, 128, 255)         # GREEN
  WARNING = rl.Color(245, 200, 66, 255)      # AMBER
  DANGER = rl.Color(201, 34, 49, 255)
  PROGRESS = rl.Color(125, 180, 255, 255)    # BLUE
  DISABLED = rl.Color(92, 117, 153, 255)     # MUTED_DIM

  # UI elements: borders -> HAIRLINE, button -> INK, pressed -> CYAN (alpha preserved)
  METRIC_BORDER = rl.Color(43, 62, 95, 255)  # HAIRLINE
  BUTTON_NORMAL = rl.Color(226, 236, 255, 255)  # INK
  BUTTON_PRESSED = rl.Color(34, 211, 238, 166)  # CYAN


@dataclass(slots=True)
class MetricData:
  label: str
  value: str
  color: rl.Color

  def update(self, label: str, value: str, color: rl.Color):
    self.label = label
    self.value = value
    self.color = color


class SidebarSP:
  def __init__(self):
    self._sunnylink_status = MetricData(tr_noop("SUNNYLINK"), tr_noop("OFFLINE"), Colors.WARNING)

  def _update_sunnylink_status(self):
    if not ui_state.params.get_bool("SunnylinkEnabled"):
      self._sunnylink_status.update(tr_noop("SUNNYLINK"), tr_noop("DISABLED"), Colors.DISABLED)
      return

    last_ping = ui_state.params.get("LastSunnylinkPingTime") or 0
    dongle_id = ui_state.params.get("SunnylinkDongleId")

    is_online = last_ping and (time.monotonic_ns() - last_ping) < PING_TIMEOUT_NS
    is_temp_fault = ui_state.params.get_bool("SunnylinkTempFault")
    is_registering = not is_temp_fault and dongle_id in (None, "", UNREGISTERED_SUNNYLINK_DONGLE_ID)

    # Determine status/color pair based on priority
    if last_ping:
      status, color = (tr_noop("ONLINE"), Colors.GOOD) if is_online else (tr_noop("ERROR"), Colors.DANGER)
    elif is_temp_fault:
      status, color = (tr_noop("FAULT"), Colors.WARNING)
    elif is_registering:
      status, color = (tr_noop("REGIST..."), Colors.PROGRESS)
    else:
      status, color = (tr_noop("OFFLINE"), Colors.DANGER)

    self._sunnylink_status.update(tr_noop("SUNNYLINK"), status, color)

  def _draw_metrics_w_sunnylink(self, rect: rl.Rectangle, _temp, _panda, _connect):
    metrics = [_temp, _panda, _connect, self._sunnylink_status]
    start_y = int(rect.y) + METRIC_START_Y
    available_height = max(0, int(HOME_BTN.y) - METRIC_MARGIN - METRIC_HEIGHT - start_y)
    spacing = available_height / max(1, len(metrics) - 1)

    return metrics, start_y, spacing
