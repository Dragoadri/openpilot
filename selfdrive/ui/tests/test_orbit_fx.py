from openpilot.selfdrive.ui.widgets import orbit_fx as fx


def test_easing_endpoints_and_clamping():
  assert fx.ease_out_cubic(0.0) == 0.0
  assert fx.ease_out_cubic(1.0) == 1.0
  assert fx.ease_out_cubic(-1.0) == 0.0   # clamps below
  assert fx.ease_out_cubic(2.0) == 1.0    # clamps above
  assert abs(fx.ease_out_back(0.0)) < 1e-9
  assert abs(fx.ease_out_back(1.0) - 1.0) < 1e-9
  # ease_out_back must overshoot past 1.0 somewhere in (0, 1)
  assert max(fx.ease_out_back(i / 100.0) for i in range(101)) > 1.0


def test_pulse01_range_and_periodicity():
  vals = [fx.pulse01(t / 100.0, period=1.0) for t in range(200)]
  assert all(0.0 <= v <= 1.0 for v in vals)
  assert abs(fx.pulse01(0.0, 1.0) - fx.pulse01(1.0, 1.0)) < 1e-9


def test_col_sets_and_clamps_alpha():
  c = fx.col(fx.CYAN, 2.0)
  assert (c.r, c.g, c.b, c.a) == (fx.CYAN.r, fx.CYAN.g, fx.CYAN.b, 255)
  assert fx.col(fx.CYAN, -1.0).a == 0
  assert fx.col(fx.CYAN, 0.5).a == 127


def test_starfield_deterministic_per_seed():
  a, b = fx.Starfield(n=30, seed=7), fx.Starfield(n=30, seed=7)
  assert a.stars == b.stars
  assert a.rings == b.rings
  c = fx.Starfield(n=30, seed=8)
  assert a.stars != c.stars


def test_cascade_start_and_settle():
  c = fx.Cascade(stagger=0.07, duration=0.35, rise=24.0)
  a0, dy0, s0 = c.values(0.0, index=3)   # index 3 has not started at t=0
  assert a0 == 0.0 and dy0 == 24.0 and s0 == 0.98
  a1, dy1, s1 = c.values(10.0, index=3)  # long settled
  assert a1 == 1.0 and dy1 == 0.0 and s1 == 1.0
