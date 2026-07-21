"""Tests for the Phase 2 estimator (formulas 1-5) using the brief's worked
examples for instant regression coverage."""

import numpy as np
import pytest

from tetralux.constants import FACE_NAMES, FACE_NORMALS
from tetralux.estimation.estimator import (
    LowSignalError,
    corrected_reading,
    cosine_proxy,
    direction_vector,
    face_weight,
    sun_vector,
)


def test_corrected_reading_worked_example():
    # Formula 1: (720 - 20) * 1.05 = 735
    assert corrected_reading(720, 20, 1.05) == pytest.approx(735.0)


def test_face_weight_worked_example():
    # Formula 2: 735 / 2940 = 0.25
    all_R = [735.0, 735.0, 735.0, 735.0]  # sum = 2940
    assert face_weight(735.0, all_R) == pytest.approx(0.25)


def test_face_weight_low_signal_raises():
    with pytest.raises(LowSignalError):
        face_weight(0.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])


def test_direction_vector_worked_example():
    # Formula 3: +x weight 0.50, +y weight 0.25 -> d = (0.50, 0.25, 0.00)
    weights = [0.50, 0.0, 0.25, 0.0, 0.0, 0.0]  # aligned with FACE_NAMES
    normals = [FACE_NORMALS[f] for f in FACE_NAMES]
    d = direction_vector(weights, normals)
    assert np.allclose(d, [0.50, 0.25, 0.00])


def test_sun_vector_worked_example():
    # Formula 4: d = (0.50, 0.25, 0) -> |d| ~ 0.559 -> s_hat ~ (0.894, 0.447, 0)
    s = sun_vector(np.array([0.50, 0.25, 0.00]))
    assert np.allclose(s, [0.8944, 0.4472, 0.0], atol=1e-4)
    assert np.linalg.norm(s) == pytest.approx(1.0)


def test_sun_vector_low_signal_raises():
    with pytest.raises(LowSignalError):
        sun_vector(np.array([0.0, 0.0, 0.0]))


def test_cosine_proxy_worked_example():
    # Formula 5: 735 / 1000 = 0.735
    assert cosine_proxy(735.0, 1000.0) == pytest.approx(0.735)
