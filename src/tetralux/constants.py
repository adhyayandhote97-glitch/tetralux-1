"""Cross-phase constants for Tetralux-1.

Single source of truth for the six cube-face definitions and the numerical
epsilon guard, shared by the simulator (Phase 1) and the estimation engine
(Phase 2) so they can never disagree.
"""

from __future__ import annotations

import numpy as np

# Canonical face ordering. Used everywhere so per-face iteration and any future
# fixed-length telemetry packing stay consistent.
FACE_NAMES: list[str] = ["+x", "-x", "+y", "-y", "+z", "-z"]

# Outward unit normal for each face, in the CubeSat body frame.
FACE_NORMALS: dict[str, np.ndarray] = {
    "+x": np.array([1.0, 0.0, 0.0]),
    "-x": np.array([-1.0, 0.0, 0.0]),
    "+y": np.array([0.0, 1.0, 0.0]),
    "-y": np.array([0.0, -1.0, 0.0]),
    "+z": np.array([0.0, 0.0, 1.0]),
    "-z": np.array([0.0, 0.0, -1.0]),
}

# Low-signal / divide-by-zero guard threshold (see docs/architecture.md §3).
MIN_EPSILON: float = 1e-9
