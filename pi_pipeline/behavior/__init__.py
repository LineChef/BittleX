"""Autonomous behaviour: what G2 does on its own between conversations.

`ModeController` is the top-level switch (converse / idle / explore); `Explorer`
decides wander/investigate intent during EXPLORE; `Novelty` tracks what's been
seen so "curious" pulls toward the unseen. All pure logic, driven by the
`BehaviorParams` the personality produces.
"""
from .explore import ExploreAction, ExploreConfig, ExploreDecision, Explorer
from .idle_posture import IdlePosture, IdlePostureConfig, Posture, PostureAction
from .mode_controller import Mode, ModeConfig, ModeController
from .novelty import Novelty, NoveltyConfig

__all__ = [
    "ModeController", "Mode", "ModeConfig",
    "Explorer", "ExploreAction", "ExploreDecision", "ExploreConfig",
    "Novelty", "NoveltyConfig",
    "IdlePosture", "IdlePostureConfig", "Posture", "PostureAction",
]
