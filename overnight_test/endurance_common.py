"""Shared pieces of the overnight endurance test.

TEMPORARY: everything in overnight_test/ is a one-off and can be deleted with
the folder. Nothing here edits the project; the project's estimation code is
imported read-only from the single-file ground station.
"""
from __future__ import annotations

import importlib.util
import math
import re
import sys
from pathlib import Path
from typing import Optional, Sequence

HERE = Path(__file__).resolve().parent
LOG_DIR = HERE / "test_logs"

# The ground station actually used for the project (the single file). Its
# decode_json_frame / process / sun_angles are what the dashboard runs.
DEFAULT_ESTIMATOR = Path.home() / "Downloads" / "attempt to code" / "personal_project_final_V2.py"

# Canonical face order, same as the firmware and FACE_NAMES in the single file.
FACES = ["+x", "-x", "+y", "-y", "+z", "-z"]
# CSV-safe column suffixes for each face.
TAGS = ["px", "nx", "py", "ny", "pz", "nz"]

PACKET_COLUMNS = (
    ["host_iso", "host_mono", "parse_ok", "reject_reason", "seq", "ts_ms"]
    + [f"pd_{t}" for t in TAGS]
    + [f"lux_{t}" for t in TAGS]
    + ["mag_x", "mag_y", "mag_z"]
    + [f"opt{i}_{k}" for i in range(4) for k in ("X", "Y", "Z", "lux")]
    + [f"temp_{t}" for t in TAGS]
    + ["flags", "chk"]
    + ["est_x", "est_y", "est_z", "est_az_deg", "est_el_deg", "saturated_faces"]
    + ["raw"]
)
EVENT_COLUMNS = ["host_iso", "host_mono", "event", "port", "detail"]
MARKER_COLUMNS = ["host_iso", "host_mono", "pose_id", "az_ref_deg", "el_ref_deg",
                  "parse_ok", "last_seq", "text"]


def load_estimator(path: Optional[str] = None):
    """Import the single-file ground station as a module, without changing it."""
    p = Path(path).expanduser() if path else DEFAULT_ESTIMATOR
    if not p.exists():
        raise FileNotFoundError(f"estimator file not found: {p}")
    name = "tetralux_single_file"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    # dataclasses look their module up in sys.modules while the file executes
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- pose markers: "P3 az=45 el=0" -------------------------------------------

_NUM = r"([-+]?\d+(?:\.\d*)?|[-+]?\.\d+)"
_AZ = re.compile(r"\baz\s*=\s*" + _NUM, re.I)
_EL = re.compile(r"\bel\s*=\s*" + _NUM, re.I)


def parse_marker(text: str):
    """'P3 az=45 el=0' -> ('P3', 45.0, 0.0); anything else -> None."""
    parts = text.strip().replace(",", " ").split()
    if not parts or "=" in parts[0]:
        return None
    az, el = _AZ.search(text), _EL.search(text)
    if not az or not el:
        return None
    return parts[0], float(az.group(1)), float(el.group(1))


# ---- angle maths (same formulas as the single file's angles_to_vector,
# ---- angular_error (formula 11) and repeatability (formula 12)) --------------

def angles_to_vector(az_deg: float, el_deg: float):
    az, el = math.radians(az_deg), math.radians(el_deg)
    return (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    if n == 0:
        raise ValueError("zero vector")
    return tuple(c / n for c in v)


def angle_between_deg(a, b) -> float:
    a, b = _unit(a), _unit(b)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    return math.degrees(math.acos(dot))


def pose_stats(vectors: Sequence[Sequence[float]], az_ref: float, el_ref: float) -> dict:
    """Average the estimated vectors, compare to the reference direction.

    error_deg  = arccos(mean_unit . ref_unit)            (accuracy, target <= 10 deg)
    std_deg    = population std of per-frame errors      (repeatability, target <= 5 deg)
    """
    ref = angles_to_vector(az_ref, el_ref)
    if not vectors:
        return {"n": 0, "error_deg": None, "std_deg": None, "mean_vector": None,
                "spread_deg": None}
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(3)]
    try:
        mean_u = _unit(mean)
    except ValueError:
        return {"n": len(vectors), "error_deg": None, "std_deg": None,
                "mean_vector": None, "spread_deg": None}
    per_frame = [angle_between_deg(v, ref) for v in vectors]
    mu = sum(per_frame) / len(per_frame)
    std = math.sqrt(sum((e - mu) ** 2 for e in per_frame) / len(per_frame))
    spread = [angle_between_deg(v, mean_u) for v in vectors]
    return {
        "n": len(vectors),
        "error_deg": angle_between_deg(mean_u, ref),
        "std_deg": std,
        "mean_vector": mean_u,
        # how far single frames sit from their own average (scatter, no reference)
        "spread_deg": max(spread),
    }
