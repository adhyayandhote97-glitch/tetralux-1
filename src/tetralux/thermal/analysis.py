"""Temperature analysis for the six DS18B20 sensors (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
Six DS18B20 temperature sensors are mounted on the cube's face frames, one per
face. This file watches them and reports whether the satellite is thermally
stable.

WHY A SUN SENSOR CARES ABOUT TEMPERATURE. A photodiode's sensitivity changes as
it warms. The calibration in calibration.py was measured at one temperature, so
as the hardware heats those gain figures become progressively less true and the
estimated sun direction drifts, slowly and silently. Nothing in the estimate
itself reveals this; the numbers stay plausible while getting steadily worse.

Watching temperature is what makes that visible. A face warming faster than
DRIFT_THRESHOLD_C_PER_MIN raises a flag, so the system can say its own output is
becoming less trustworthy rather than reporting a drifting answer with unchanged
confidence.

WHAT IT REPORTS PER SENSOR
    the current temperature, or None if the sensor did not respond
    the drift rate in degrees per minute (formula 14)
    a rolling mean over the last 60 readings, which smooths out sensor noise
    a drift flag, true when the rate exceeds the threshold

DESIGN NOTE. Like RollingValidator, this is a stateful CLASS rather than a
function, because drift is a comparison between now and a moment ago, so
something must remember the previous reading. Per sensor, independently: one
dead DS18B20 must not stop the other five from being analysed.

WHERE IT SITS IN THE FLOW
    validation/metrics.py  supplies formula 14, the drift rate itself
    pipeline.py            holds one analyzer and calls update() per frame
    dashboard              shows temperatures and drift flags on the Live page

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from tetralux.constants import DRIFT_THRESHOLD_C_PER_MIN, ROLLING_WINDOW_SIZE
from tetralux.validation.metrics import temp_drift_rate

# Canonical sensor ordering, the same idea as FACE_NAMES in constants.py: the
# firmware sends six bare temperatures with no labels, and this list is what
# turns position 3 in that list back into "T4".
SENSOR_IDS = ["T1", "T2", "T3", "T4", "T5", "T6"]

# Each DS18B20 is mounted on a cube-face frame. The firmware reads each one by
# its fixed ROM address and sends them in FACE_NAMES order, so position i is
# always face i; the brackets give the physical face number and wire colour
# confirmed by touch-testing.
#
# The mapping is kept separate from SENSOR_IDS because it is documentation for a
# human reading the dashboard, not something the maths uses. "T3 is drifting"
# means nothing on its own; "the +y frame is drifting" points at a physical part
# of the hardware to go and inspect.
SENSOR_FACE = {
    "T1": "+x frame (Face 4, black)", "T2": "-x frame (Face 6, blue)",
    "T3": "+y frame (Face 1, purple)", "T4": "-y frame (Face 2, green)",
    "T5": "+z frame (Face 3, yellow)", "T6": "-z frame (Face 5, orange)",
}


@dataclass
class ThermalStatus:
    """Per-update thermal report (all dicts keyed by sensor id)."""

    # One complete thermal snapshot, produced fresh by each update() call.
    # Every dict is keyed by sensor id, so all six always appear even when a
    # sensor failed; the failure is represented by None or NaN in place, never
    # by an absent key. A caller can therefore loop over all six without
    # checking whether each exists.
    temperatures: dict     # T1..T6 -> degC or None
    drift_rates: dict      # degC/min (nan if unknown)
    rolling_means: dict    # degC (nan if empty)
    drift_flags: dict      # bool, |drift| > threshold
    missing: list          # sensor ids reporting None
    any_drift: bool        # any drift flag set
    #
    # missing and any_drift are both summaries derivable from the dicts above.
    # They exist so the dashboard and the fault logic can ask one cheap question
    # instead of scanning six entries, and so the intent is stated once here
    # rather than reimplemented at each call site.


class TemperatureAnalyzer:
    """Stateful analyzer keeping a rolling window of readings per sensor."""

    # PARAMETERS
    #   window          - how many past readings to keep per sensor, for the
    #                     rolling mean. Defaults to the project-wide 60.
    #   drift_threshold - degrees per minute above which drift is flagged.
    #                     Defaults to the project-wide 0.5.
    # RETURNS
    #   None; a constructor sets the object up.
    def __init__(self, window: int = ROLLING_WINDOW_SIZE,
                 drift_threshold: float = DRIFT_THRESHOLD_C_PER_MIN) -> None:
        self._window = window
        self._threshold = drift_threshold
        # A dict comprehension building SIX SEPARATE deques, one per sensor.
        #
        # Writing `{sid: deque(maxlen=window) for sid in SENSOR_IDS}` calls
        # deque() fresh on each pass, so each sensor gets its own independent
        # history. Creating one deque and reusing it would give all six sensors
        # the same object, and every reading would land in a single shared pile.
        # This is the same aliasing trap as the mutable default in
        # calibration.Calibration, in a different disguise.
        #
        # maxlen makes each self-limiting: at 60 readings, adding a 61st drops
        # the oldest automatically (see validation/rolling.py).
        self._history = {sid: deque(maxlen=window) for sid in SENSOR_IDS}
        # The previous reading per sensor, stored as a (temperature, timestamp)
        # tuple, or None before any reading has arrived. Drift is a comparison
        # between two moments, so the earlier one must be kept.
        self._last: dict = {sid: None for sid in SENSOR_IDS}  # (temp, timestamp_ms)

    # Called once per incoming frame.
    #
    # PARAMETERS
    #   temperatures - the six raw values from SensorFrame.temperatures, in
    #                  SENSOR_IDS order. Entries may be None if a sensor failed
    #                  to respond.
    #   timestamp_ms - the satellite's clock for this frame, milliseconds since
    #                  boot. Needed because drift is a rate: degrees PER MINUTE
    #                  requires knowing how much time passed.
    # RETURNS
    #   one ThermalStatus describing all six sensors.
    def update(self, temperatures: list, timestamp_ms: int) -> ThermalStatus:
        """Ingest one reading per sensor and return the current status."""
        # Five accumulators created on one line by unpacking. Four dicts to fill
        # per sensor, one list for the ones that failed.
        temps, drifts, means, flags, missing = {}, {}, {}, {}, []

        for i, sid in enumerate(SENSOR_IDS):
            # A conditional expression guarding against a short list. If the
            # firmware sent only four temperatures, positions 4 and 5 would
            # raise IndexError; this treats them as missing instead, which is
            # what a truncated packet actually means.
            t = temperatures[i] if i < len(temperatures) else None
            # Two ways a reading can be unusable: an explicit None from a sensor
            # that did not answer, or a NaN. `t != t` is the NaN test again (see
            # spectral/cie.py): NaN is unequal to itself.
            if t is None or (isinstance(t, float) and t != t):
                # Record the failure in every dict, keeping all six keys
                # present. Note means[sid] still calls self._mean: the rolling
                # average of PAST readings is still valid and worth reporting
                # even though this particular reading is missing.
                temps[sid] = None
                drifts[sid] = float("nan")
                means[sid] = self._mean(sid)
                flags[sid] = False
                missing.append(sid)
                # `continue` skips the rest of this pass and moves to the next
                # sensor. Crucially, self._last[sid] is NOT updated, so the last
                # GOOD reading is preserved and drift can still be computed
                # correctly once the sensor recovers.
                continue

            t = float(t)
            temps[sid] = t

            # Start with "unknown". Drift needs a previous reading, and on the
            # very first frame there is none.
            drift = float("nan")
            prev = self._last[sid]
            if prev is not None:
                # Unpacking the stored tuple into two names.
                prev_t, prev_ts = prev
                # Convert milliseconds to minutes: 60 seconds x 1000 ms.
                # THE UNIT CHOICE HERE SETS THE UNIT OF THE RESULT, because
                # temp_drift_rate just divides by whatever dt it is given.
                # Minutes are used so the answer can be compared directly
                # against DRIFT_THRESHOLD_C_PER_MIN.
                dt_min = (timestamp_ms - prev_ts) / 60000.0
                # Guard against a zero or negative interval, which happens with
                # a duplicated packet or a clock reset. Dividing by it would
                # produce infinity, so drift is left as NaN: unknown, not zero.
                if dt_min > 1e-9:
                    drift = temp_drift_rate(t, prev_t, dt_min)
            drifts[sid] = drift
            # `drift == drift` excludes NaN before comparing. Without it, any
            # comparison with NaN is False anyway, so this is belt and braces,
            # but it states the intent: an unknown drift is not a flagged drift.
            # abs() catches rapid COOLING as well as heating, since either
            # direction invalidates a calibration measured at a fixed
            # temperature.
            flags[sid] = drift == drift and abs(drift) > self._threshold

            # Record this reading in the rolling history and update the mean.
            self._history[sid].append(t)
            means[sid] = self._mean(sid)
            # Remember this reading as the baseline for the next frame's drift.
            # Reached only on the success path, which is what makes the
            # `continue` above correct.
            self._last[sid] = (t, timestamp_ms)

        return ThermalStatus(
            temperatures=temps, drift_rates=drifts, rolling_means=means,
            drift_flags=flags, missing=missing,
            # any() is True if at least one item in the sequence is True. One
            # drifting sensor is enough to warrant attention.
            any_drift=any(flags.values()),
        )

    # Internal helper (primer 12).
    #
    # PARAMETER
    #   sid - which sensor, e.g. "T3".
    # RETURNS
    #   the mean of that sensor's stored history, or NaN if it has none yet.
    #
    # WHY A ROLLING MEAN. A single DS18B20 reading carries noise of a few
    # hundredths of a degree. Averaging the last 60 suppresses that, so a slow
    # genuine temperature trend is visible instead of being buried in jitter.
    #
    # `if hist else` guards the empty case: np.mean of an empty deque warns and
    # returns NaN, so returning NaN explicitly is clearer and quieter.
    def _mean(self, sid: str) -> float:
        hist = self._history[sid]
        return float(np.mean(hist)) if hist else float("nan")

    # Discard all history and all previous readings.
    #
    # Used when starting a new recording session, so temperatures from an
    # earlier run cannot leak into this one's rolling means or produce a
    # nonsensical drift across the gap between sessions.
    def reset(self) -> None:
        for sid in SENSOR_IDS:
            self._history[sid].clear()
            self._last[sid] = None
