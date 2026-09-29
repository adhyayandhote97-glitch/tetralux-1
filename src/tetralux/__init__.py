"""Tetralux-1: a software-only digital twin of a CubeSat sun-direction system.

WHAT THIS FILE CONTRIBUTES
--------------------------
This is the top of the project. Its presence is what makes the `tetralux`
folder a PACKAGE rather than just a directory of files, which is what allows
`import tetralux.estimation.estimator` to work anywhere in the codebase.

WHAT __init__.py IS. Any folder containing this file is a package Python can
import from. The file itself runs when the package is first imported, so
whatever it contains becomes available immediately. It can be completely empty
and still do its job; several in this project are close to that.

WHY MOST OF THIS PROJECT'S __init__.py FILES RE-EXPORT NAMES. Compare:

    from tetralux.estimation.estimator import sun_vector   # without
    from tetralux.estimation import sun_vector             # with

Both work; the second is shorter and hides the fact that the code happens to
live in a file called estimator.py. That means the file could later be split in
two without changing a single caller, so the re-exports define a stable public
surface for each subpackage.

Those files also define `__all__`, a list naming the package's public API. It
controls what `from package import *` brings in, and more usefully it documents
what a package intends people to use. This top-level file deliberately exports
nothing: `tetralux` on its own is a namespace, and callers should reach for a
specific subpackage.

WHERE EVERYTHING LIVES
    constants.py      fixed numbers and face geometry, imported by nearly all
    frames.py         what one sensor reading looks like coming in
    record.py         what one processed result looks like going out
    calibration.py    the per-face numbers that make six sensors comparable
    pipeline.py       the spine: frame in, record out, every phase in order
    estimation/       the maths that finds the sun, formulas 1 to 5
    physics/          solar radiation pressure, formulas 6 to 10
    validation/       accuracy metrics, formulas 11 to 14
    spectral/         colour trust, formulas 15 to 18
    faults/           the three conditions that invalidate an estimate
    thermal/          temperature drift monitoring
    sim/              the simulator, the estimator run backwards
    telemetry/        the wire format and its checksum
    ingest/           receiving telemetry over WiFi or USB
    store/            writing sessions to disk and to Firebase
    dashboard/        the web interface

    groundstation.py    the CLI for real hardware
    calibration_tool.py the CLI that measures a prototype's calibration

SUGGESTED READING ORDER: constants.py, then estimation/estimator.py for the
core maths, then pipeline.py to see how everything is chained together.

New to Python? Read docs/python-primer.md first; it explains def, parameters,
return, classes, imports and the rest, once, using examples from this codebase.
"""

# The package version. The double underscores mark it as a name Python and its
# tooling recognise by convention; packaging tools read it to label a release.
__version__ = "0.1.0"
