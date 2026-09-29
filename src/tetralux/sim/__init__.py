"""Phase 1/7: sun-vector simulator + full virtual sensor synthesis.

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `sim/` as a package and re-exports both of its modules.

This subpackage is the estimator run backwards. Instead of asking "given these
readings, where is the light?", it asks "given this light direction, what would
the sensors read?". That is what makes the estimator testable: the true
direction is an input, so the answer can be scored against it.

    simulator.py  the six photodiodes, via Lambert's cosine law
    sensors.py    the whole satellite: photodiodes, lux, temperature, colour and
                  magnetometer, assembled into a complete SensorFrame

The frames sensors.py produces are the SAME type real hardware produces, and
they are round-tripped through the real wire codec, so Virtual mode exercises
the genuine code path rather than a mock of it.

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
"""

from tetralux.sim.sensors import frame_from_angles, simulate_sensor_frame
from tetralux.sim.simulator import generate_sweep, simulate_faces

# Photodiodes only first, then whole frames: simple to complete.
__all__ = [
    "simulate_faces",         # six photodiode readings for one light direction
    "generate_sweep",         # a grid of directions across the hemisphere
    "simulate_sensor_frame",  # every instrument, as one wire-valid frame
    "frame_from_angles",      # the same, driven by azimuth/elevation
]
