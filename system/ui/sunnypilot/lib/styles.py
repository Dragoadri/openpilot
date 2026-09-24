"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from dataclasses import dataclass

import pyray as rl

from openpilot.selfdrive.ui import orbit_theme as t


@dataclass
class Base:
  # Widget/Control Base Dimensions
  ITEM_BASE_HEIGHT = 170
  ITEM_PADDING = 20
  ITEM_TEXT_FONT_SIZE = 50
  ITEM_DESC_FONT_SIZE = 40
  ITEM_DESC_V_OFFSET = 150
  ITEM_TEXT_VALUE_COLOR = t.TEXTO2  # ORBIT: value text -> MUTED
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
  BASE_BG_COLOR = t.SUP1  # NAVY (raised row bg)
  ON_BG_COLOR = rl.Color(22, 163, 74, 255)  # GREEN_DEEP (toggle ON track) -- no es navy, fuera de alcance
  OFF_BG_COLOR = rl.Color(51, 68, 95, 255)  # TOGGLE_OFF (muted navy off track) -- valor propio, no es un literal navy exacto
  ON_HOVER_BG_COLOR = rl.Color(74, 222, 128, 255)  # GREEN (ON hover) -- no es navy, fuera de alcance
  OFF_HOVER_BG_COLOR = t.BORDE  # HAIRLINE (OFF hover)
  DISABLED_ON_BG_COLOR = t.SUP2  # PANEL (disabled ON)
  DISABLED_OFF_BG_COLOR = t.SUP1  # NAVY (disabled OFF)
  ITEM_TEXT_COLOR = t.TEXTO1  # INK (primary text)
  ITEM_DISABLED_TEXT_COLOR = t.TEXTO3  # MUTED_DIM
  ITEM_DESC_TEXT_COLOR = t.TEXTO2  # MUTED (description text)

  # Toggle Control
  TOGGLE_ON_COLOR = ON_BG_COLOR
  TOGGLE_OFF_COLOR = OFF_BG_COLOR
  TOGGLE_KNOB_COLOR = rl.WHITE
  TOGGLE_DISABLED_ON_COLOR = DISABLED_ON_BG_COLOR
  TOGGLE_DISABLED_OFF_COLOR = DISABLED_OFF_BG_COLOR
  TOGGLE_DISABLED_KNOB_COLOR = t.TEXTO3  # ORBIT: MUTED_DIM knob

  # Multi Button Control -- ORBIT: selected -> PANEL, disabled overlay tinted MUTED_DIM
  MBC_TRANSPARENT = rl.Color(255, 255, 255, 0)
  MBC_BG_CHECKED_ENABLED = t.SUP2  # PANEL (selected)
  MBC_DISABLED = t.con_alfa(t.TEXTO3, 0x33 / 255)  # MUTED_DIM translucent overlay

  # Option Control -- ORBIT: HAIRLINE btn, PANEL pressed, INK text
  OPTION_CONTROL_CONTAINER_BG = OFF_BG_COLOR
  OPTION_CONTROL_BTN_ENABLED = t.BORDE  # HAIRLINE
  OPTION_CONTROL_BTN_PRESSED = t.SUP2  # PANEL (pressed)
  OPTION_CONTROL_BTN_DISABLED = DISABLED_OFF_BG_COLOR
  OPTION_CONTROL_TEXT_ENABLED = t.TEXTO1  # INK
  OPTION_CONTROL_TEXT_PRESSED = t.TEXTO1  # INK
  OPTION_CONTROL_TEXT_DISABLED = ITEM_DISABLED_TEXT_COLOR

  # Tree Button Colors -- ORBIT: primary GREEN_DEEP, neutral NAVY, disabled VOID, borders HAIRLINE
  BUTTON_PRIMARY_COLOR = rl.Color(22, 163, 74, 255)  # GREEN_DEEP (primary/confirm) -- no es navy, fuera de alcance
  BUTTON_NEUTRAL_GRAY = t.SUP1  # NAVY (neutral/ghost)
  BUTTON_DISABLED_BG_COLOR = t.FONDO  # VOID (disabled bg)
  TREE_DIALOG_TRANSPARENT = rl.Color(0, 0, 0, 0)
  TREE_DIALOG_SEARCH_BUTTON_PRESSED = t.SUP2  # PANEL (pressed)
  TREE_DIALOG_SEARCH_BUTTON_BORDER = t.con_alfa(t.BORDE, 200 / 255)  # HAIRLINE (border)

  # Vehicle Description Colors -- ORBIT: GREEN (ok), BLUE (info); YELLOW kept as caution
  GREEN = rl.Color(74, 222, 128, 255)  # GREEN (connected/ok) -- no es navy, fuera de alcance
  BLUE = t.ACCION  # BLUE (info/link)
  YELLOW = rl.Color(255, 213, 0, 255)  # caution (no palette equivalent)

  # Button Colors -- ORBIT: NAVY enabled, PANEL pressed, VOID disabled, MUTED_DIM text
  BUTTON_ENABLED_OFF = t.SUP1  # NAVY
  BUTTON_OFF_PRESSED = t.SUP2  # PANEL
  BUTTON_DISABLED = t.FONDO  # VOID
  BUTTON_TEXT_DISABLED = t.TEXTO3  # MUTED_DIM


style = DefaultStyleSP
