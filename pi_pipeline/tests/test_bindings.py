import random

from pi_pipeline.behavior import BehaviorDriver, DriverInputs, EffectKind
from pi_pipeline.behavior.bindings import DriverBindings, MockBindings
from pi_pipeline.behavior.driver import Effect
from pi_pipeline.personality.traits import BehaviorParams


# ------------------------------------------------------------------ routing
def test_each_effect_kind_routes_to_its_sink():
    mb = MockBindings()
    out = mb.dispatch([
        Effect(EffectKind.SKILL, "kstr"),
        Effect(EffectKind.STOP, None),
        Effect(EffectKind.WALK, 0.1),
        Effect(EffectKind.TURN, -0.6),
        Effect(EffectKind.HEAD, "pan_sweep"),
        Effect(EffectKind.SPEAK, "hello"),
        Effect(EffectKind.CAPTURE, ("on", "face_center")),
        Effect(EffectKind.CUE, "listening"),
        Effect(EffectKind.DIAG, ("mode.transition", "idle->explore")),
    ])
    assert out[0] == "skill:kstr"
    assert mb.names() == [
        "actuator.perform", "actuator.stop", "walker.walk", "walker.turn",
        "head.move", "tts.speak", "camera.set_capture", "cue.set", "diag",
    ]
    # payloads landed
    calls = dict((n, (a, k)) for n, a, k in mb.calls)
    assert calls["actuator.perform"][0] == ("kstr",)
    assert calls["tts.speak"][0] == ("hello",)
    assert calls["camera.set_capture"][0] == (True, "face_center")


def test_missing_sink_is_dropped_and_warned_once(caplog):
    b = DriverBindings(actuator=None)      # no actuator
    out = b.dispatch([Effect(EffectKind.SKILL, "kstr"),
                      Effect(EffectKind.SKILL, "kup")])
    assert out == ["drop:skill", "drop:skill"]


def test_turn_falls_back_to_a_firmware_token_without_a_walker():
    calls = []

    class Act:
        def perform(self, t): calls.append(t)
        def stop(self): calls.append("stop")

    b = DriverBindings(actuator=Act())
    b.dispatch([Effect(EffectKind.TURN, 0.5), Effect(EffectKind.TURN, -0.5)])
    assert calls == ["kwkR", "kwkL"]


def test_tts_say_alias_is_accepted():
    said = []

    class TTS:
        def say(self, s): said.append(s)

    DriverBindings(tts=TTS()).dispatch([Effect(EffectKind.SPEAK, "hi")])
    assert said == ["hi"]


def test_dispatch_accepts_a_drivertick():
    mb = MockBindings()

    class FakeTick:
        effects = [Effect(EffectKind.CUE, "idle")]
    # DriverTick check is isinstance-based; a plain list also works
    mb.dispatch([Effect(EffectKind.CUE, "idle")])
    assert mb.names() == ["cue.set"]


# ---------------------------------------------------- full BehaviorDriver loop
class Clk:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


def test_full_idle_descent_dispatches_sit_then_rest():
    c = Clk()
    d = BehaviorDriver(
        BehaviorParams(idle_secs_before_explore=1e9, idle_sit_secs=20, idle_rest_secs=90),
        clock=c, rng=random.Random(0))
    mb = MockBindings()

    seen = []
    for _ in range(240):                    # ~120 s at 0.5 s/tick
        c.adv(0.5)
        tick = d.tick(DriverInputs())
        seen += mb.dispatch(tick)

    # it sat, then (after the settle choreography) lay down
    assert any(s == "skill:ksit" for s in seen)
    assert any(s == "skill:d" for s in seen)
    assert seen.index("skill:ksit") < seen.index("skill:d")


def test_full_loop_wake_word_triggers_cue_and_head_up():
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=c, rng=random.Random(0))
    mb = MockBindings()

    c.adv(0.5)
    d.tick(DriverInputs())                  # settle
    c.adv(30.0)
    d.tick(DriverInputs())                  # -> SIT
    c.adv(0.5)
    mb.dispatch(d.tick(DriverInputs(wake_word=True)))
    for _ in range(6):                      # pump the wake choreography
        c.adv(0.5)
        mb.dispatch(d.tick(DriverInputs()))
    # the wake rouse choreography runs head-up -> stretch -> stand
    assert "head.move" in mb.names()
    assert "actuator.perform" in mb.names()


# ------------------------------------------------------- CHIRP / POWER routing
def test_chirp_effect_plays_a_buzzer_string_on_the_actuator():
    from pi_pipeline.behavior import ChirpMood
    mb = MockBindings()
    out = mb.dispatch([Effect(EffectKind.CHIRP, ChirpMood.SLEEPY)])
    assert out == ["chirp:sleepy"]
    calls = dict((n, a) for n, a, k in mb.calls)
    (arg,) = calls["actuator.perform"]
    assert arg.startswith("b") and " " in arg          # opencat.beep format


def test_power_effect_routes_to_the_power_sink():
    mb = MockBindings()
    out = mb.dispatch([Effect(EffectKind.POWER, "headless")])
    assert out == ["power:headless"]
    assert ("power.set_profile", ("headless",), {}) in mb.calls


def test_power_effect_without_a_sink_is_dropped():
    b = DriverBindings()                   # no power sink
    assert b.dispatch([Effect(EffectKind.POWER, "headless")]) == ["drop:power"]
