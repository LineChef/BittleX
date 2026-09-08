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
BACK = np.full((4, 8), 0.2)                                 # (4,8) ~ 11.5 deg
REFS = SkillRefs(step_over=STEP, inspect=INSPECT, back_out=BACK)
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


def test_blend_in_goes_via_stance():
    stance = np.full(8, 2.0)                          # rad
    step = np.full((4, 8), 0.7)                       # rad, frame 0 = 0.7
    s = SkillSwitch(SkillRefs(step_over=step, inspect=INSPECT, stance=stance), CFG)
    first, _ = s.update(GaitMode.STEP_OVER, RL)       # begin -> from_pose == RL
    assert np.allclose(first, RL)
    mid, src = s.update(GaitMode.CRUISE, RL)          # t=1/2 -> AT the stance waypoint
    assert src is Source.BLEND
    assert np.allclose(mid, np.rad2deg(2.0), atol=1e-6)
    end, src = s.update(GaitMode.CRUISE, RL)          # t=1 -> at skill frame 0
    assert src is Source.SCRIPTED
    assert np.allclose(end, np.rad2deg(0.7), atol=1e-6)


def test_phase_gate_waits_for_stance_window():
    s = sw()   # default windows ((0,.15),(.5,.65))
    out, src = s.update(GaitMode.STEP_OVER, RL, gait_phase=0.30)
    assert src is Source.RL and np.allclose(out, RL)          # pending, RL still drives
    for gp in (0.33, 0.38, 0.45):
        out, src = s.update(GaitMode.STEP_OVER, RL, gait_phase=gp)
        assert src is Source.RL                               # still waiting
    out, src = s.update(GaitMode.STEP_OVER, RL, gait_phase=0.52)  # enters a stance window
    assert src is Source.BLEND
    assert s.active_skill is GaitMode.STEP_OVER


def test_phase_gate_times_out():
    s = SkillSwitch(REFS, SkillSwitchConfig(blend_in_steps=2, max_pending_ticks=3))
    for _ in range(3):
        assert s.update(GaitMode.STEP_OVER, RL, gait_phase=0.30)[1] is Source.RL
    assert s.update(GaitMode.STEP_OVER, RL, gait_phase=0.30)[1] is Source.BLEND  # gave up waiting


def test_halt_ignores_phase_gate():
    s = sw()
    out, src = s.update(GaitMode.HALT, RL, gait_phase=0.30)   # bad phase, HALT is immediate
    assert src is Source.BLEND and s.active_skill is GaitMode.HALT


def test_pending_aborts_if_request_drops():
    s = sw()
    s.update(GaitMode.STEP_OVER, RL, gait_phase=0.30)         # pending
    out, src = s.update(GaitMode.CRUISE, RL, gait_phase=0.30)  # request withdrawn
    assert src is Source.RL and s.active_skill is None


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


def test_back_out_is_a_timed_skill_that_auto_releases():
    s = sw()
    out, src = _reach_skill(s, GaitMode.BACK_OUT)        # blend in -> playing
    assert src is Source.SCRIPTED and s.active_skill is GaitMode.BACK_OUT
    assert np.allclose(out, np.rad2deg(0.2), atol=1e-6)  # BACK ref frame 0
    srcs = [s.update(GaitMode.CRUISE, RL)[1]
            for _ in range(CFG.play_ticks_per_cycle + CFG.blend_out_steps + 1)]
    assert srcs[-1] is Source.RL                         # played its cycle, handed back
    assert s.active_skill is None
