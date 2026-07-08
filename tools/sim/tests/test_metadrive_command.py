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
