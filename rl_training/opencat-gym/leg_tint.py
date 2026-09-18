"""Tint each leg-joint's link toward red as the policy's residual action for
that joint approaches its degree budget -- makes "which joint is correcting,
and how hard, right now" visible in any replay (GUI or headless/GIF), not
just inferable from a separate chart.

Usage: call setup_leg_tint(env) once after the URDF loads (records each
joint-link's original color), then call apply_leg_tint(env, action) every
step before capturing/rendering a frame.
"""
import numpy as np
import pybullet as p

TINT_COLOR = np.array([0.85, 0.10, 0.12])   # target red at full deviation


def setup_leg_tint(env):
    """Record each joint-link's original RGBA so tinting can blend from it
    instead of overwriting it. Call once per env/robot load."""
    orig = {}
    for link in env.joint_id:
        shape_data = p.getVisualShapeData(env.robot_id)
        for entry in shape_data:
            if entry[1] == link:
                orig[link] = np.array(entry[7])   # rgbaColor
                break
        else:
            orig[link] = np.array([0.6, 0.6, 0.6, 1.0])   # fallback if not found
    env._leg_tint_orig = orig


def apply_leg_tint(env, action, scale_deg=None):
    """Blend each joint-link's color from its original toward red,
    proportional to |action| for that joint (clipped to the nominal [-1,1]
    action range, same convention as action_trace.py -- reflects the real
    applied correction, not a raw pre-clip policy output that can exceed the
    nominal budget)."""
    if not hasattr(env, "_leg_tint_orig"):
        setup_leg_tint(env)
    frac = np.abs(np.clip(np.asarray(action), -1.0, 1.0))   # [0,1] per joint
    for i, link in enumerate(env.joint_id):
        f = float(frac[i]) if i < len(frac) else 0.0
        orig = env._leg_tint_orig[link]
        blended = orig[:3] * (1 - f) + TINT_COLOR * f
        p.changeVisualShape(env.robot_id, link,
                             rgbaColor=[blended[0], blended[1], blended[2], orig[3]])


def reset_leg_tint(env):
    """Restore original colors (e.g. after an episode reset creates a new
    robot body -- call setup_leg_tint again instead if robot_id changed)."""
    if not hasattr(env, "_leg_tint_orig"):
        return
    for link, orig in env._leg_tint_orig.items():
        p.changeVisualShape(env.robot_id, link, rgbaColor=list(orig))
