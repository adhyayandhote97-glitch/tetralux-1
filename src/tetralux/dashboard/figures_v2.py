"""Additional Plotly figures for the v2 dashboard (Phase 9).

Adds the 3D cube + sun vector, the "light in 3D space" view, the weights bar,
and generic time-series. Kept pure (build and return ``go.Figure``) so they are
unit-testable without a server. Needs the ``dashboard`` extra (plotly).
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import plotly.graph_objects as go

from tetralux.constants import FACE_NAMES, FACE_NORMALS

_ESTIMATE = "#fca311"
_REFERENCE = "#2a9d8f"
_CUBE = "#4361ee"
_LIGHT = "#ffd166"
_MARGIN = dict(l=0, r=0, t=36, b=0)

# 8 corners of a 1U cube centered at the origin (half-size 0.5).
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
    xs, ys, zs = zip(*_VERTS)
    i, j, k = zip(*_TRIS)
    return go.Mesh3d(
        x=xs, y=ys, z=zs, i=i, j=j, k=k,
        color=_CUBE, opacity=0.18, flatshading=True,
        name="1U cube", hoverinfo="skip", showscale=False,
    )


def _scene(rng: float = 2.0) -> dict:
    axis = dict(range=[-rng, rng], backgroundcolor="rgba(0,0,0,0)")
    return dict(
        xaxis=dict(title="x", **axis), yaxis=dict(title="y", **axis),
        zaxis=dict(title="z", **axis), aspectmode="cube",
    )


def cube_figure(sun_vector: Optional[Sequence[float]] = None,
                reference: Optional[Sequence[float]] = None,
                title: str = "Body frame + sun vector") -> go.Figure:
    """Translucent 1U cube with face labels and the estimated sun vector."""
    fig = go.Figure()
    fig.add_trace(_cube_mesh())

    # Face-normal markers.
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


def light_space_figure(light_dir: Optional[Sequence[float]] = None,
                       distance: float = 2.0,
                       title: str = "Light source in 3D space") -> go.Figure:
    """Show where the light source sits relative to the cube."""
    fig = go.Figure()
    fig.add_trace(_cube_mesh())

    if light_dir is not None:
        d = np.asarray(light_dir, dtype=float)
        d = d / (np.linalg.norm(d) or 1.0)
        pos = d * distance
        # ray from cube to source
        fig.add_trace(go.Scatter3d(
            x=[0, pos[0]], y=[0, pos[1]], z=[0, pos[2]], mode="lines",
            line=dict(color=_LIGHT, width=5, dash="dot"), name="light ray",
        ))
        # the source itself
        fig.add_trace(go.Scatter3d(
            x=[pos[0]], y=[pos[1]], z=[pos[2]], mode="markers+text",
            text=["light source"], textposition="top center",
            marker=dict(size=10, color=_LIGHT, symbol="circle"), name="source",
        ))

    fig.update_layout(title=title, scene=_scene(distance + 0.4), margin=_MARGIN, height=460)
    return fig


def weights_figure(weights: dict, title: str = "Face weights wᵢ (Σ = 1)") -> go.Figure:
    """Bar chart of the six normalized face weights."""
    fig = go.Figure(go.Bar(
        x=FACE_NAMES, y=[weights.get(f, 0.0) for f in FACE_NAMES],
        marker_color=_CUBE,
    ))
    fig.update_layout(title=title, xaxis_title="face",
                      yaxis_title="weight (dimensionless)",
                      margin=dict(l=10, r=10, t=36, b=10), height=280)
    return fig


def timeseries_figure(times: Sequence[float], series: dict, title: str,
                      y_title: str) -> go.Figure:
    """Multi-line time-series. ``series`` maps label -> y-values (None -> gap)."""
    fig = go.Figure()
    for label, ys in series.items():
        clean = [np.nan if (v is None) else v for v in ys]
        fig.add_trace(go.Scatter(x=list(times), y=clean, mode="lines", name=label))
    fig.update_layout(title=title, xaxis_title="time (s)", yaxis_title=y_title,
                      margin=dict(l=10, r=10, t=36, b=10), height=320)
    return fig
