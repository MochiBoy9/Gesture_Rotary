"""Synthetic MediaPipe-style hands for testing (mirrored/selfie image)."""
import math

import numpy as np

from rotary.gestures import HandFrame

_MCPS = {5: (-0.025, -0.085), 9: (-0.005, -0.090), 13: (0.015, -0.085), 17: (0.034, -0.076)}
_SEGS = {5: (0.040, 0.025, 0.022), 9: (0.045, 0.028, 0.024), 13: (0.042, 0.026, 0.022), 17: (0.032, 0.020, 0.019)}
_FLEX = (1.4, 1.7, 1.0)  # mcp, pip, dip at a full fist


def _unit(v):
    return v / np.linalg.norm(v)


def make_hand(flex=0.0, roll_deg=0.0, palm=True, handed="Right", center=(0.5, 0.5),
              size=0.25, aspect=4 / 3, pinch=False, finger_flex=None, index_push=0.0) -> HandFrame:
    """Right hand, palm toward camera, fingers up; then flipped / rolled / placed."""
    w = np.zeros((21, 3))
    normal = np.array([0.0, 0.0, -1.0])  # toward the camera
    for i, (mcp, (x, y)) in enumerate(_MCPS.items()):
        f = flex if finger_flex is None else finger_flex[i]
        w[mcp] = (x, y, 0.0)
        d = _unit(w[mcp])
        pos, total = w[mcp].copy(), 0.0
        flexes = [fa * f for fa in _FLEX]
        if mcp == 5 and index_push:          # straight index finger tipped toward the camera
            flexes = [math.radians(index_push), 0.0, 0.0]
        for j, (seg, fa) in enumerate(zip(_SEGS[mcp], flexes)):
            total += fa
            pos = pos + seg * (math.cos(total) * d + math.sin(total) * normal)
            w[mcp + 1 + j] = pos
    w[1:5] = [(-0.025, -0.020, -0.010), (-0.045, -0.040, -0.020),
              (-0.058, -0.060, -0.025), (-0.066, -0.080, -0.030)]
    if flex > 0.5:
        w[4] = (-0.010, -0.070, -0.040)
    if pinch:
        w[4] = w[8] + (0.006, 0.006, 0.0)

    if handed == "Left":            # a left palm is the mirror image of a right palm
        w[:, 0] *= -1
    if not palm:                    # back of the hand: mirror again, curls go away from camera
        w[:, 0] *= -1
        w[:, 2] *= -1

    r = math.radians(roll_deg)
    rot = np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])
    w[:, :2] = w[:, :2] @ rot.T

    k = size / 0.09
    palm_c = w[[0, 5, 9, 13, 17], :2].mean(axis=0)
    img = np.zeros((21, 3))
    img[:, 0] = center[0] + (w[:, 0] - palm_c[0]) * k / aspect
    img[:, 1] = center[1] + (w[:, 1] - palm_c[1]) * k
    img[:, 2] = w[:, 2] * k
    return HandFrame(landmarks=img, world=w - w.mean(axis=0), handedness=handed, score=0.95, aspect=aspect)
