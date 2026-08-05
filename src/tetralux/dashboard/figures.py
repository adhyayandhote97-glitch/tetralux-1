"""Plotly figure builders for the dashboard."""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

import numpy as np
import plotly.graph_objects as go

from tetralux.constants import FACE_NAMES, FACE_NORMALS

_ESTIMATE = "#fca311"
_REFERENCE = "#2a9d8f"
_CUBE = "#4361ee"
_BAR = "#457b9d"
_SATURATED = "#e63946"
_MARGIN = dict(l=0, r=0, t=36, b=0)
_FLAT_MARGIN = dict(l=10, r=10, t=36, b=10)

# 8 corners of a 1U cube centred on the origin (half-size 0.5).
_C = 0.5
_VERTS = [
    (-_C, -_C, -_C), (_C, -_C, -_C), (_C, _C, -_C), (-_C, _C, -_C),
    (-_C, -_C, _C), (_C, -_C, _C), (_C, _C, _C), (-_C, _C, _C),
]
# 12 triangles (two per face).
_TRIS = [
    (0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7),
    (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
    (1, 2, 6), (1, 6, 5), (0, 3, 7), (0, 7, 4),
]


def _cube_mesh() -> go.Mesh3d:
    """Translucent mesh for the 1U cube body."""
    xs, ys, zs = zip(*_VERTS)
    i, j, k = zip(*_TRIS)
    return go.Mesh3d(
        x=xs, y=ys, z=zs, i=i, j=j, k=k,
        color=_CUBE, opacity=0.18, flatshading=True,
        name="1U cube", hoverinfo="skip", showscale=False,
    )


def _scene(rng: float = 2.0) -> dict:
    """Equal-aspect 3D scene with a transparent background."""
    axis = dict(range=[-rng, rng], backgroundcolor="rgba(0,0,0,0)")
    return dict(
        xaxis=dict(title="x", **axis), yaxis=dict(title="y", **axis),
        zaxis=dict(title="z", **axis), aspectmode="cube",
    )


def cube_figure(sun_vector: Optional[Sequence[float]] = None,
                reference: Optional[Sequence[float]] = None,
                title: str = "Body frame + sun vector") -> go.Figure:
    """Cube with labelled face normals, the estimated sun vector, and a reference."""
    fig = go.Figure()
    fig.add_trace(_cube_mesh())

    fig.add_trace(go.Scatter3d(
        x=[FACE_NORMALS[f][0] for f in FACE_NAMES],
        y=[FACE_NORMALS[f][1] for f in FACE_NAMES],
        z=[FACE_NORMALS[f][2] for f in FACE_NAMES],
        mode="markers+text", text=FACE_NAMES, textposition="top center",
        marker=dict(size=3, color="gray"), showlegend=False, hoverinfo="text",
    ))

    if reference is not None:
        r = np.asarray(reference, dtype=float) * 1.4
        fig.add_trace(go.Scatter3d(
            x=[0, r[0]], y=[0, r[1]], z=[0, r[2]], mode="lines",
            line=dict(color=_REFERENCE, width=6, dash="dash"), name="reference",
        ))
    if sun_vector is not None:
        s = np.asarray(sun_vector, dtype=float) * 1.4
        fig.add_trace(go.Scatter3d(
            x=[0, s[0]], y=[0, s[1]], z=[0, s[2]], mode="lines+markers",
            line=dict(color=_ESTIMATE, width=9),
            marker=dict(size=4, color=_ESTIMATE), name="sun estimate",
        ))

    fig.update_layout(title=title, scene=_scene(1.6), margin=_MARGIN, height=460)
    return fig


def face_readings_figure(readings: Mapping[str, float],
                         saturated: Optional[Mapping[str, bool]] = None,
                         title: str = "Face readings (ADC counts)") -> go.Figure:
    """Bar chart of the six face readings, saturated faces highlighted red."""
    saturated = saturated or {}
    colors = [_SATURATED if saturated.get(f) else _BAR for f in FACE_NAMES]
    fig = go.Figure(go.Bar(
        x=FACE_NAMES, y=[readings.get(f, 0) for f in FACE_NAMES],
        marker_color=colors,
    ))
    fig.update_layout(title=title, xaxis_title="face", yaxis_title="counts",
                      margin=_FLAT_MARGIN, height=300)
    return fig


def weights_figure(weights: dict, title: str = "Face weights wᵢ (Σ = 1)") -> go.Figure:
    """Bar chart of the six normalised face weights."""
    fig = go.Figure(go.Bar(
        x=FACE_NAMES, y=[weights.get(f, 0.0) for f in FACE_NAMES],
        marker_color=_CUBE,
    ))
    fig.update_layout(title=title, xaxis_title="face",
                      yaxis_title="weight (dimensionless)",
                      margin=_FLAT_MARGIN, height=280)
    return fig


def srp_figure(forces: dict, title: str = "SRP force per face (nN)") -> go.Figure:
    """Bar chart of per-face solar radiation pressure force, in nanonewtons."""
    fig = go.Figure(go.Bar(
        x=FACE_NAMES, y=[forces.get(f, 0.0) * 1e9 for f in FACE_NAMES],
        marker_color=_ESTIMATE,
    ))
    fig.update_layout(title=title, xaxis_title="face", yaxis_title="force (nN)",
                      margin=_FLAT_MARGIN, height=280)
    return fig


def timeseries_figure(times: Sequence[float], series: dict, title: str,
                      y_title: str) -> go.Figure:
    """Multi-line time series. Values of None render as gaps."""
    fig = go.Figure()
    for label, ys in series.items():
        clean = [np.nan if (v is None) else v for v in ys]
        fig.add_trace(go.Scatter(x=list(times), y=clean, mode="lines", name=label))
    fig.update_layout(title=title, xaxis_title="time (s)", yaxis_title=y_title,
                      margin=_FLAT_MARGIN, height=320)
    return fig
