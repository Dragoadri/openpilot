"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from dataclasses import dataclass

import pyray as rl


@dataclass
class Base:
  # Widget/Control Base Dimensions
  ITEM_BASE_HEIGHT = 170
  ITEM_PADDING = 20
  ITEM_TEXT_FONT_SIZE = 50
  ITEM_DESC_FONT_SIZE = 40
  ITEM_DESC_V_OFFSET = 150
  ITEM_TEXT_VALUE_COLOR = rl.Color(147, 180, 230, 255)  # ORBIT: value text -> MUTED
  CLOSE_BTN_SIZE = 160

  TEXT_PADDING = 20

  # Toggle Control
  TOGGLE_HEIGHT = 120
  TOGGLE_WIDTH = int(TOGGLE_HEIGHT * 1.75)
  TOGGLE_BG_HEIGHT = TOGGLE_HEIGHT - 20

  # Button Control
  BUTTON_ACTION_WIDTH = 300
  BUTTON_HEIGHT = 120

  # Simple Button Control
  SIMPLE_BUTTON_WIDTH = 800
  SIMPLE_BUTTON_HEIGHT = 150


@dataclass
class DefaultStyleSP(Base):
  # Base Colors -- ORBIT: row/track bg NAVY, ON GREEN_DEEP, OFF TOGGLE_OFF, text INK/MUTED
  BASE_BG_COLOR = rl.Color(22, 35, 58, 255)  # NAVY (raised row bg)
  ON_BG_COLOR = rl.Color(22, 163, 74, 255)  # GREEN_DEEP (toggle ON track)
  OFF_BG_COLOR = rl.Color(51, 68, 95, 255)  # TOGGLE_OFF (muted navy off track)
  ON_HOVER_BG_COLOR = rl.Color(74, 222, 128, 255)  # GREEN (ON hover)
  OFF_HOVER_BG_COLOR = rl.Color(43, 62, 95, 255)  # HAIRLINE (OFF hover)
  DISABLED_ON_BG_COLOR = rl.Color(27, 44, 72, 255)  # PANEL (disabled ON)
  DISABLED_OFF_BG_COLOR = rl.Color(22, 35, 58, 255)  # NAVY (disabled OFF)
  ITEM_TEXT_COLOR = rl.Color(226, 236, 255, 255)  # INK (primary text)
  ITEM_DISABLED_TEXT_COLOR = rl.Color(92, 117, 153, 255)  # MUTED_DIM
  ITEM_DESC_TEXT_COLOR = rl.Color(147, 180, 230, 255)  # MUTED (description text)

  # Toggle Control
  TOGGLE_ON_COLOR = ON_BG_COLOR
  TOGGLE_OFF_COLOR = OFF_BG_COLOR
  TOGGLE_KNOB_COLOR = rl.WHITE
  TOGGLE_DISABLED_ON_COLOR = DISABLED_ON_BG_COLOR
  TOGGLE_DISABLED_OFF_COLOR = DISABLED_OFF_BG_COLOR
  TOGGLE_DISABLED_KNOB_COLOR = rl.Color(92, 117, 153, 255)  # ORBIT: MUTED_DIM knob

  # Multi Button Control -- ORBIT: selected -> PANEL, disabled overlay tinted MUTED_DIM
  MBC_TRANSPARENT = rl.Color(255, 255, 255, 0)
  MBC_BG_CHECKED_ENABLED = rl.Color(27, 44, 72, 255)  # PANEL (selected)
  MBC_DISABLED = rl.Color(92, 117, 153, 0x33)  # MUTED_DIM translucent overlay

  # Option Control -- ORBIT: HAIRLINE btn, PANEL pressed, INK text
  OPTION_CONTROL_CONTAINER_BG = OFF_BG_COLOR
  OPTION_CONTROL_BTN_ENABLED = rl.Color(43, 62, 95, 255)  # HAIRLINE
  OPTION_CONTROL_BTN_PRESSED = rl.Color(27, 44, 72, 255)  # PANEL (pressed)
  OPTION_CONTROL_BTN_DISABLED = DISABLED_OFF_BG_COLOR
  OPTION_CONTROL_TEXT_ENABLED = rl.Color(226, 236, 255, 255)  # INK
  OPTION_CONTROL_TEXT_PRESSED = rl.Color(226, 236, 255, 255)  # INK
  OPTION_CONTROL_TEXT_DISABLED = ITEM_DISABLED_TEXT_COLOR

  # Tree Button Colors -- ORBIT: primary GREEN_DEEP, neutral NAVY, disabled VOID, borders HAIRLINE
  BUTTON_PRIMARY_COLOR = rl.Color(22, 163, 74, 255)  # GREEN_DEEP (primary/confirm)
  BUTTON_NEUTRAL_GRAY = rl.Color(22, 35, 58, 255)  # NAVY (neutral/ghost)
  BUTTON_DISABLED_BG_COLOR = rl.Color(11, 18, 32, 255)  # VOID (disabled bg)
  TREE_DIALOG_TRANSPARENT = rl.Color(0, 0, 0, 0)
  TREE_DIALOG_SEARCH_BUTTON_PRESSED = rl.Color(27, 44, 72, 255)  # PANEL (pressed)
  TREE_DIALOG_SEARCH_BUTTON_BORDER = rl.Color(43, 62, 95, 200)  # HAIRLINE (border)

  # Vehicle Description Colors -- ORBIT: GREEN (ok), BLUE (info); YELLOW kept as caution
  GREEN = rl.Color(74, 222, 128, 255)  # GREEN (connected/ok)
  BLUE = rl.Color(125, 180, 255, 255)  # BLUE (info/link)
  YELLOW = rl.Color(255, 213, 0, 255)  # caution (no palette equivalent)

  # Button Colors -- ORBIT: NAVY enabled, PANEL pressed, VOID disabled, MUTED_DIM text
  BUTTON_ENABLED_OFF = rl.Color(22, 35, 58, 255)  # NAVY
  BUTTON_OFF_PRESSED = rl.Color(27, 44, 72, 255)  # PANEL
  BUTTON_DISABLED = rl.Color(11, 18, 32, 255)  # VOID
  BUTTON_TEXT_DISABLED = rl.Color(92, 117, 153, 255)  # MUTED_DIM


style = DefaultStyleSP
