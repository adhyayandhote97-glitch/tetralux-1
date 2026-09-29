"""Telemetry wire format: newline-delimited JSON with an 8-bit XOR checksum.

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `telemetry/` as a package and re-exports the codec from json_frame.py.

This subpackage is the border between the satellite and the ground station. The
firmware sends one line of text per reading; these three functions turn that
text into a SensorFrame and back again, and verify it was not corrupted on the
way.

The encoder and decoder must agree byte for byte with the Arduino, which is why
json_frame.py builds its JSON by hand rather than with json.dumps, and why the
decoder hashes the RAW received characters rather than anything re-serialized.

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
"""

from tetralux.telemetry.json_frame import (
    decode_json_frame,
    encode_json_frame,
    xor_checksum,
)

__all__ = [
    "decode_json_frame",   # text -> SensorFrame or RejectedFrame
    "encode_json_frame",   # SensorFrame -> the firmware's exact wire string
    "xor_checksum",        # the integrity check both sides compute
]
