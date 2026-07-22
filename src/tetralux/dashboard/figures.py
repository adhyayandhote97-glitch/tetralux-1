"""Phase 5 — Plotly figure builders (pure functions returning go.Figure).

Kept separate from the Dash app so each figure can be built and unit tested
without a running server. Requires the ``dashboard`` extra (plotly).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Optional

import numpy as np
import plotly.graph_objects as go

from tetralux.constants import FACE_NAMES, FACE_NORMALS

_ESTIMATE_COLOR = "#fca311"
_REFERENCE_COLOR = "#2a9d8f"
_SATURATED_COLOR = "#e63946"
_BAR_COLOR = "#457b9d"

_MARGIN = dict(l=10, r=10, t=40, b=10)


def sun_vector_figure(
    sun_vector: Optional[np.ndarray] = None,
    reference: Optional[np.ndarray] = None,
    title: str = "Estimated sun vector",
) -> go.Figure:
    """3D view of the body frame with the estimated (and optional true) vector."""
    fig = go.Figure()

    # Faint body-frame axes through the origin.
    for a, b in (([-1, 0, 0], [1, 0, 0]), ([0, -1, 0], [0, 1, 0]), ([0, 0, -1], [0, 0, 1])):
        fig.add_trace(
            go.Scatter3d(
                x=[a[0], b[0]], y=[a[1], b[1]], z=[a[2], b[2]],
                mode="lines", line=dict(color="lightgray", width=2),
                showlegend=False, hoverinfo="skip",
            )
        )

    # Face-normal markers, labelled with face names.
    fig.add_trace(
        go.Scatter3d(
            x=[FACE_NORMALS[f][0] for f in FACE_NAMES],
            y=[FACE_NORMALS[f][1] for f in FACE_NAMES],
            z=[FACE_NORMALS[f][2] for f in FACE_NAMES],
            mode="markers+text", text=FACE_NAMES, textposition="top center",
            marker=dict(size=3, color="gray"), showlegend=False, hoverinfo="text",
        )
    )

    if reference is not None:
        r = np.asarray(reference, dtype=float)
        fig.add_trace(
            go.Scatter3d(
                x=[0, r[0]], y=[0, r[1]], z=[0, r[2]], mode="lines",
                line=dict(color=_REFERENCE_COLOR, width=6, dash="dash"), name="true",
            )
        )

    if sun_vector is not None:
        s = np.asarray(sun_vector, dtype=float)
        fig.add_trace(
            go.Scatter3d(
                x=[0, s[0]], y=[0, s[1]], z=[0, s[2]], mode="lines+markers",
                line=dict(color=_ESTIMATE_COLOR, width=8),
                marker=dict(size=4, color=_ESTIMATE_COLOR), name="estimate",
            )
        )

    axis = dict(range=[-1.1, 1.1], backgroundcolor="rgba(0,0,0,0)")
    fig.update_layout(
        title=title,
        scene=dict(
            xaxis=dict(title="x", **axis), yaxis=dict(title="y", **axis),
            zaxis=dict(title="z", **axis), aspectmode="cube",
        ),
        margin=_MARGIN, height=460,
    )
    return fig


def face_readings_figure(
    readings: Mapping[str, float],
    saturated: Optional[Mapping[str, bool]] = None,
    title: str = "Face readings (ADC counts)",
) -> go.Figure:
    """Bar chart of the six face readings; saturated faces highlighted red."""
    saturated = saturated or {}
    colors = [_SATURATED_COLOR if saturated.get(f) else _BAR_COLOR for f in FACE_NAMES]
    fig = go.Figure(
        go.Bar(
            x=FACE_NAMES, y=[readings.get(f, 0) for f in FACE_NAMES],
            marker_color=colors,
        )
    )
    fig.update_layout(
        title=title, xaxis_title="face", yaxis_title="counts",
        margin=_MARGIN, height=300,
    )
    return fig


def angular_error_figure(
    times: Sequence[float],
    errors: Sequence[Optional[float]],
    current_index: Optional[int] = None,
    title: str = "Angular error vs ground truth",
) -> go.Figure:
    """Line of angular error (deg) over time, with the current frame marked."""
    ys = [np.nan if e is None else e for e in errors]
    fig = go.Figure(
        go.Scatter(x=list(times), y=ys, mode="lines+markers", name="error",
                   line=dict(color=_BAR_COLOR))
    )
    if current_index is not None and 0 <= current_index < len(times):
        fig.add_trace(
            go.Scatter(
                x=[times[current_index]], y=[ys[current_index]], mode="markers",
                marker=dict(size=12, color=_ESTIMATE_COLOR), name="current",
            )
        )
    fig.update_layout(
        title=title, xaxis_title="time (s)", yaxis_title="degrees",
        margin=_MARGIN, height=300,
    )
    return fig
