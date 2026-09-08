"""The --skills wiring in run_gait.py: ref-loading, the threaded latest-frame
puller, and the mock feed factory. run_gait.py is written to run as a script
(bare `import residual_policy`), so load it with its own dir on sys.path."""
import importlib.util
import os
import sys
import time

import numpy as np
import pytest

from pi_pipeline.gait.skill_switch import GaitMode

_GAIT_DIR = os.path.join(os.path.dirname(__file__), "..", "gait")


@pytest.fixture(scope="module")
def rg():
    pytest.importorskip("onnxruntime")
    for p in (_GAIT_DIR, os.path.join(_GAIT_DIR, ".."), os.path.join(_GAIT_DIR, "..", "..")):
        sys.path.insert(0, os.path.abspath(p))
    spec = importlib.util.spec_from_file_location(
        "run_gait_under_test", os.path.join(_GAIT_DIR, "run_gait.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_skill_layer_loads_refs(rg):
    layer = rg.build_skill_layer(with_cliff_guard=True)
    # step_over ref came from tr_ref.npy -> (100, 8)
    assert layer._switch._ref[GaitMode.STEP_OVER].shape == (100, 8)
    out, info = layer.step(np.full(8, 10.0), gait_phase=0.0)
    assert out.shape == (8,) and info.mode is GaitMode.CRUISE


def test_build_skill_layer_without_cliff_guard(rg):
    layer = rg.build_skill_layer(with_cliff_guard=False)
    assert layer._cliff is None


def test_mock_feed_factory_and_latest_frame(rg):
    feed = rg._make_vision_feed("mock", "/dev/null", 0)
    vision = rg._LatestFrame(feed, stale_after=5.0).start()
    # let the pump thread deliver a frame
    for _ in range(50):
        if vision.latest():
            break
        time.sleep(0.02)
    assert vision.latest(), "mock feed never produced a frame"
    vision.set_look_down(True)
    vision.close()


def test_latest_frame_goes_stale(rg):
    feed = rg._make_vision_feed("mock", "/dev/null", 0)
    vision = rg._LatestFrame(feed, stale_after=0.05).start()
    time.sleep(0.2)
    assert vision.latest() == []          # last frame is older than stale_after
    vision.close()


def test_unknown_feed_kind_raises(rg):
    with pytest.raises(SystemExit):
        rg._make_vision_feed("lidar", "/dev/null", 0)
