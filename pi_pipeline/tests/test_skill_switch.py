import numpy as np

from pi_pipeline.gait.skill_switch import (
    GaitMode,
    SkillRefs,
    SkillSwitch,
    SkillSwitchConfig,
    Source,
)

# synthetic refs (RADIANS, URDF order) -- distinct, easy to recognise in degrees
STEP = np.tile(np.linspace(0.0, 0.4, 4)[:, None], (1, 8))   # (4,8) ramp 0..~23deg
INSPECT = np.full((2, 8), -0.5)                             # (2,8) ~ -28.6 deg (crouch)
REFS = SkillRefs(step_over=STEP, inspect=INSPECT)           # stand defaults to zeros (1,8)
CFG = SkillSwitchConfig(blend_in_steps=2, blend_out_steps=2, play_ticks_per_cycle=4)

RL = np.full(8, 10.0)   # a fixed RL joint output, degrees


def sw():
    return SkillSwitch(REFS, CFG)


def test_cruise_passes_rl_through():
    s = sw()
    for _ in range(5):
        out, src = s.update(GaitMode.CRUISE, RL)
        assert src is Source.RL
        assert np.allclose(out, RL)


def test_careful_keeps_rl_but_scales_speed():
    s = sw()
    out, src = s.update(GaitMode.CAREFUL, RL)
    assert src is Source.RL and np.allclose(out, RL)
    assert s.speed_scale == 0.6
    s.update(GaitMode.CRUISE, RL)
    assert s.speed_scale == 1.0


def _reach_skill(s, mode):
    """Drive `mode` until the skill frame is live. Blend-in is one `begin` tick
    plus `blend_in_steps` ticks; the last returns SCRIPTED. Returns (out, src)."""
    out, src = s.update(mode, RL)                     # begin
    for _ in range(CFG.blend_in_steps):
        out, src = s.update(mode, RL)
    return out, src


def test_refs_are_converted_to_degrees():
    s = sw()
    out, src = _reach_skill(s, GaitMode.INSPECT)      # -> holding on crouch frame 0
    assert src is Source.SCRIPTED
    assert np.allclose(out, np.rad2deg(-0.5), atol=1e-6)


def test_step_over_full_lifecycle():
    s = sw()
    seq = []
    out, src = s.update(GaitMode.STEP_OVER, RL)       # begin -> BLEND
    seq.append(src)
    for _ in range(CFG.blend_in_steps):               # blend in (last -> SCRIPTED)
        seq.append(s.update(GaitMode.CRUISE, RL)[1])
    for _ in range(CFG.play_ticks_per_cycle):         # play one cycle, then auto blend-out
        seq.append(s.update(GaitMode.CRUISE, RL)[1])
    for _ in range(CFG.blend_out_steps):              # blend out (last -> RL)
        seq.append(s.update(GaitMode.CRUISE, RL)[1])
    tail, src = s.update(GaitMode.CRUISE, RL)
    assert src is Source.RL and np.allclose(tail, RL)
    assert Source.BLEND in seq and Source.SCRIPTED in seq
    assert seq.index(Source.SCRIPTED) > 0
    assert seq[-1] is Source.RL                       # ended back on the learned walk


def test_blend_in_interpolates_rl_to_skill_frame0():
    s = sw()
    first, _ = s.update(GaitMode.STEP_OVER, RL)       # t=0 -> == RL pose
    assert np.allclose(first, RL)
    mid, src = s.update(GaitMode.CRUISE, RL)          # t=1/2 -> halfway to frame0 (=0 deg)
    assert src is Source.BLEND
    assert np.allclose(mid, RL * 0.5, atol=1e-6)      # halfway between 10 and 0


def test_inspect_holds_until_cruise_requested():
    s = sw()
    _reach_skill(s, GaitMode.INSPECT)                 # -> holding
    for _ in range(6):
        out, src = s.update(GaitMode.INSPECT, RL)
        assert src is Source.SCRIPTED                 # holds indefinitely
    s.update(GaitMode.CRUISE, RL)                     # release -> blend_out
    for _ in range(CFG.blend_out_steps - 1):
        s.update(GaitMode.CRUISE, RL)
    out, src = s.update(GaitMode.CRUISE, RL)
    assert src is Source.RL


def test_halt_preempts_a_running_step_over():
    s = sw()
    _reach_skill(s, GaitMode.STEP_OVER)               # step-over playing
    s.update(GaitMode.STEP_OVER, RL)                  # play a tick
    s.update(GaitMode.HALT, RL)                       # HALT preempts -> re-begins on HALT
    assert s.active_skill is GaitMode.HALT
    out, src = _reach_skill(s, GaitMode.HALT)         # blend into the stand, hold
    assert src is Source.SCRIPTED
    assert np.allclose(out, 0.0, atol=1e-6)           # stand ref is zeros


def test_latch_ignores_new_skill_request_mid_skill():
    s = sw()
    _reach_skill(s, GaitMode.STEP_OVER)               # playing STEP_OVER
    s.update(GaitMode.INSPECT, RL)                    # ignored (latch_skill=True)
    assert s.active_skill is GaitMode.STEP_OVER


def test_reset_returns_to_cruise():
    s = sw()
    _reach_skill(s, GaitMode.STEP_OVER)
    assert s.source is Source.SCRIPTED
    s.reset()
    out, src = s.update(GaitMode.CRUISE, RL)
    assert src is Source.RL and np.allclose(out, RL)
    assert s.active_skill is None
