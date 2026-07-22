"""Phase 1/7: sun-vector simulator + full virtual sensor synthesis."""

from tetralux.sim.sensors import frame_from_angles, simulate_sensor_frame
from tetralux.sim.simulator import generate_sweep, simulate_faces

__all__ = [
    "simulate_faces",
    "generate_sweep",
    "simulate_sensor_frame",
    "frame_from_angles",
]
