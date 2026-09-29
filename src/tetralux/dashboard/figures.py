"""Plotly figure builders for the dashboard.

WHAT THIS FILE CONTRIBUTES
--------------------------
Every chart on the dashboard is built here. Plotly is the graphing library; a
"figure" is one chart object, which Dash then renders in the browser.

Five builders, one per kind of chart:

    cube_figure           the 3D cube with the sun vector drawn on it
    face_readings_figure  raw readings per face, saturated ones in red
    weights_figure        the six normalized weights
    srp_figure            radiation-pressure force per face
    timeseries_figure     any quantity plotted against time

THE ORGANISING RULE: these functions take DATA and return a FIGURE. They hold no
state, know nothing about the application, and never fetch anything. Give
cube_figure a vector and it draws that vector. That is what makes them testable
without a browser, and test_dashboard_v2.py does exactly that, asserting each
returns a real Figure.

EVERY AXIS CARRIES ITS UNIT, matching the rule in dashboard/units.py. "counts",
"weight (dimensionless)", "force (nN)", "time (s)". A bare axis label is the
same failure as a bare number.

WHY THE CUBE IS DRAWN AS TRIANGLES. 3D graphics has no concept of a square face;
everything is triangles. A cube's six square faces therefore need twelve
triangles, two per face, which is what _TRIS below lists.

WHERE IT SITS IN THE FLOW
    dashboard/app.py     calls these and places the results in the page
    record.py            supplies the values plotted
    constants.py         supplies the face names and normals for the 3D view

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

import numpy as np
# The standard Plotly import. `go` holds the chart types: Figure, Bar, Scatter3d.
import plotly.graph_objects as go

from tetralux.constants import FACE_NAMES, FACE_NORMALS

# Colours as hex codes: "#RRGGBB", two hex digits each for red, green and blue.
# Named constants rather than repeated literals, so the palette is consistent
# and changing a colour is one edit.
_ESTIMATE = "#fca311"    # orange, the estimated sun vector
_REFERENCE = "#2a9d8f"   # teal, the known truth, deliberately distinct
_CUBE = "#4361ee"        # blue, the cube body and the weights bars
_BAR = "#457b9d"         # muted blue, normal readings
_SATURATED = "#e63946"   # red, because saturation is a fault worth noticing
# Margins in pixels: left, right, top, bottom. The 3D view uses zero side margin
# so the cube fills the space; flat charts need room for their axis labels.
_MARGIN = dict(l=0, r=0, t=36, b=0)
_FLAT_MARGIN = dict(l=10, r=10, t=36, b=10)

# 8 corners of a 1U cube centred on the origin (half-size 0.5).
#
# Centred on the origin so that FACE_NORMALS, which point outward from the
# origin, line up with the drawing without any offset. Half-size 0.5 makes the
# cube one unit across, matching the unit-length normals.
_C = 0.5
_VERTS = [
    # The first four are the bottom face (z = -0.5), the last four the top.
    (-_C, -_C, -_C), (_C, -_C, -_C), (_C, _C, -_C), (-_C, _C, -_C),
    (-_C, -_C, _C), (_C, -_C, _C), (_C, _C, _C), (-_C, _C, _C),
]
# 12 triangles (two per face).
#
# Each triple is three INDEXES into _VERTS, naming which corners that triangle
# joins. So (0, 1, 2) means "connect vertex 0 to vertex 1 to vertex 2". Storing
# indexes rather than repeating coordinates means each corner is defined once,
# which is how all 3D mesh formats work.
_TRIS = [
    (0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7),
    (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
    (1, 2, 6), (1, 6, 5), (0, 3, 7), (0, 7, 4),
]


# Internal helper (primer 12).
# RETURNS
#   a Plotly 3D mesh representing the cube body.
def _cube_mesh() -> go.Mesh3d:
    """Translucent mesh for the 1U cube body."""
    # zip(*_VERTS) TRANSPOSES the list. The `*` unpacks _VERTS into eight
    # separate arguments, and zip then pairs up their first elements, their
    # second elements, and so on. So a list of (x,y,z) triples becomes three
    # lists: all the xs, all the ys, all the zs, which is the format Plotly
    # wants.
    xs, ys, zs = zip(*_VERTS)
    # The same transpose on the triangles, giving three lists of indexes.
    i, j, k = zip(*_TRIS)
    return go.Mesh3d(
        x=xs, y=ys, z=zs, i=i, j=j, k=k,
        # opacity 0.18 makes the cube nearly transparent, which is essential:
        # the sun vector starts at the centre, so a solid cube would hide half
        # of it.
        color=_CUBE, opacity=0.18, flatshading=True,
        # hoverinfo="skip" stops tooltips appearing over the body, which would
        # otherwise block hovering on the vectors that actually carry data.
        name="1U cube", hoverinfo="skip", showscale=False,
    )


# PARAMETER
#   rng - how far each axis extends from the origin.
# RETURNS
#   a dict of 3D scene settings.
def _scene(rng: float = 2.0) -> dict:
    """Equal-aspect 3D scene with a transparent background."""
    # rgba(0,0,0,0) is fully transparent: the last number is the alpha channel,
    # and 0 means invisible. Lets the page background show through.
    axis = dict(range=[-rng, rng], backgroundcolor="rgba(0,0,0,0)")
    return dict(
        # `**axis` unpacks that dict into keyword arguments, so each axis gets
        # the same range and background without repeating them three times.
        xaxis=dict(title="x", **axis), yaxis=dict(title="y", **axis),
        zaxis=dict(title="z", **axis),
        # aspectmode="cube" forces equal scaling on all three axes. Without it
        # Plotly stretches axes to fill the window, and the cube would render as
        # a box while directions came out visually distorted, which would make
        # the sun vector point somewhere it does not.
        aspectmode="cube",
    )


# --- The 3D view ---
#
# PARAMETERS
#   sun_vector - the estimate to draw, or None to draw no estimate.
#   reference  - the known truth, or None. Drawn dashed for comparison, which is
#                what makes the angular error visible rather than merely
#                numeric.
#   title      - the chart heading.
# RETURNS
#   a Plotly Figure.
#
# Both vectors default to None so the same function draws the empty state, which
# the tests exercise as `cube_figure()`.
def cube_figure(sun_vector: Optional[Sequence[float]] = None,
                reference: Optional[Sequence[float]] = None,
                title: str = "Body frame + sun vector") -> go.Figure:
    """Cube with labelled face normals, the estimated sun vector, and a reference."""
    # A figure is built by adding TRACES, one per thing drawn, layered in order.
    fig = go.Figure()
    fig.add_trace(_cube_mesh())

    # Face labels: a marker at each face normal with its name beside it. Without
    # these the cube is an anonymous box and there is no way to tell which
    # direction is +y.
    fig.add_trace(go.Scatter3d(
        # Three comprehensions pulling the x, y and z of each normal.
        x=[FACE_NORMALS[f][0] for f in FACE_NAMES],
        y=[FACE_NORMALS[f][1] for f in FACE_NAMES],
        z=[FACE_NORMALS[f][2] for f in FACE_NAMES],
        mode="markers+text", text=FACE_NAMES, textposition="top center",
        marker=dict(size=3, color="gray"), showlegend=False, hoverinfo="text",
    ))

    # Reference FIRST, so the estimate draws on top of it where they overlap.
    # That ordering is deliberate: the estimate is the thing being judged, so it
    # should never be hidden behind the truth.
    if reference is not None:
        # Scaled to 1.4 so the arrow extends past the cube's surface at 0.5 and
        # is clearly visible outside the body.
        r = np.asarray(reference, dtype=float) * 1.4
        # A line from the origin [0] to the vector tip: two points.
        fig.add_trace(go.Scatter3d(
            x=[0, r[0]], y=[0, r[1]], z=[0, r[2]], mode="lines",
            # Dashed and thinner, so the solid estimate reads as the primary
            # value even when the two nearly coincide.
            line=dict(color=_REFERENCE, width=6, dash="dash"), name="reference",
        ))
    if sun_vector is not None:
        s = np.asarray(sun_vector, dtype=float) * 1.4
        fig.add_trace(go.Scatter3d(
            x=[0, s[0]], y=[0, s[1]], z=[0, s[2]], mode="lines+markers",
            line=dict(color=_ESTIMATE, width=9),
            marker=dict(size=4, color=_ESTIMATE), name="sun estimate",
        ))

    # 1.6 rather than the default 2.0: a tighter view, since the vectors reach
    # only 1.4 and empty space wastes the panel.
    fig.update_layout(title=title, scene=_scene(1.6), margin=_MARGIN, height=460)
    return fig


# --- Raw readings per face ---
#
# PARAMETERS
#   readings  - face name to ADC count.
#   saturated - face name to bool, or None if unknown.
#   title     - includes the unit, per the units rule.
# RETURNS
#   a bar chart Figure.
def face_readings_figure(readings: Mapping[str, float],
                         saturated: Optional[Mapping[str, bool]] = None,
                         title: str = "Face readings (ADC counts)") -> go.Figure:
    """Bar chart of the six face readings, saturated faces highlighted red."""
    # `or {}` so the .get below works whether or not saturation data was given.
    saturated = saturated or {}
    # COLOUR AS INFORMATION. A saturated bar turns red, so a fault that would
    # otherwise be a line of text becomes visible at a glance. Saturation
    # matters because a clipped reading understates the true light and drags the
    # estimate (see faults/detector.py).
    colors = [_SATURATED if saturated.get(f) else _BAR for f in FACE_NAMES]
    fig = go.Figure(go.Bar(
        # Iterating FACE_NAMES fixes the bar order, so the chart does not
        # reshuffle between frames. .get with a default of 0 tolerates a missing
        # face rather than raising.
        x=FACE_NAMES, y=[readings.get(f, 0) for f in FACE_NAMES],
        marker_color=colors,
    ))
    fig.update_layout(title=title, xaxis_title="face", yaxis_title="counts",
                      margin=_FLAT_MARGIN, height=300)
    return fig


# --- The normalized weights ---
#
# PARAMETERS
#   weights - face name to w_i, from formula 2.
#   title   - contains the mathematical notation: wᵢ with a subscript i, and Σ
#             for "sum", so the chart title states the property that the six
#             weights add to exactly 1.
# RETURNS
#   a bar chart Figure.
#
# This is arguably the most informative chart on the dashboard: it shows the
# actual input to the direction calculation. A single tall bar means the light
# is nearly dead-on to one face; several similar bars mean it is between faces.
def weights_figure(weights: dict, title: str = "Face weights wᵢ (Σ = 1)") -> go.Figure:
    """Bar chart of the six normalised face weights."""
    fig = go.Figure(go.Bar(
        x=FACE_NAMES, y=[weights.get(f, 0.0) for f in FACE_NAMES],
        marker_color=_CUBE,
    ))
    fig.update_layout(title=title, xaxis_title="face",
                      # The axis says "dimensionless" explicitly, exactly as
                      # dashboard/units.py requires.
                      yaxis_title="weight (dimensionless)",
                      margin=_FLAT_MARGIN, height=280)
    return fig


# --- Radiation pressure per face ---
#
# PARAMETERS
#   forces - face name to force in NEWTONS, as stored in the record.
#   title  - states nN, matching the conversion below.
# RETURNS
#   a bar chart Figure.
def srp_figure(forces: dict, title: str = "SRP force per face (nN)") -> go.Figure:
    """Bar chart of per-face solar radiation pressure force, in nanonewtons."""
    fig = go.Figure(go.Bar(
        # THE 1e9 CONVERTS NEWTONS TO NANONEWTONS. SRP forces are around
        # 1e-8 N, so an axis in newtons would read 0.00000001 and every bar
        # would look like zero. Multiplying by a billion gives about 10 nN,
        # which is legible. The unit in the title and axis is what keeps this
        # honest rather than misleading.
        x=FACE_NAMES, y=[forces.get(f, 0.0) * 1e9 for f in FACE_NAMES],
        marker_color=_ESTIMATE,
    ))
    fig.update_layout(title=title, xaxis_title="face", yaxis_title="force (nN)",
                      margin=_FLAT_MARGIN, height=280)
    return fig


# --- Anything plotted against time ---
#
# PARAMETERS
#   times   - the shared x-axis values, in seconds.
#   series  - a dict of label to y-values. Multiple entries draw multiple lines
#             on one chart, which is how angular error, bias and repeatability
#             appear together and can be compared.
#   title   - the chart heading.
#   y_title - the y-axis label, supplied by the caller BECAUSE this function is
#             generic: it does not know whether it is plotting degrees or
#             kelvin, so the unit must come from whoever does.
# RETURNS
#   a line chart Figure.
def timeseries_figure(times: Sequence[float], series: dict, title: str,
                      y_title: str) -> go.Figure:
    """Multi-line time series. Values of None render as gaps."""
    fig = go.Figure()
    for label, ys in series.items():
        # None BECOMES NaN, AND THAT IS THE POINT. Plotly draws nothing at a
        # NaN, leaving a genuine gap in the line, whereas None would break the
        # trace and a 0 would draw a spike down to the axis.
        #
        # This is the display-layer counterpart of the None convention
        # throughout the project: a frame too dark to estimate leaves a hole in
        # the graph, honestly showing that no measurement was made rather than
        # implying an error of zero.
        clean = [np.nan if (v is None) else v for v in ys]
        # name=label puts each series in the legend.
        fig.add_trace(go.Scatter(x=list(times), y=clean, mode="lines", name=label))
    fig.update_layout(title=title, xaxis_title="time (s)", yaxis_title=y_title,
                      margin=_FLAT_MARGIN, height=320)
    return fig
