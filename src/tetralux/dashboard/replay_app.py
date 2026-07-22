"""Phase 5 — Plotly Dash dashboard: live sun vector, health, and replay.

Builds an interactive dashboard over a list of :class:`ReplayFrame` records. A
slider (with play/pause) scrubs through the telemetry; each frame updates the 3D
vector view, the face-reading bars, the angular-error timeline, and a fault
health panel.

Requires the ``dashboard`` extra (``pip install -e ".[dashboard]"``).
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
from dash import Dash, Input, Output, State, dcc, html

from tetralux.dashboard.figures import (
    angular_error_figure,
    face_readings_figure,
    sun_vector_figure,
)
from tetralux.dashboard.replay import ReplayFrame, build_replay
from tetralux.faults.detector import FaultCode
from tetralux.telemetry.generator import generate_telemetry, pack_stream

_FAULT_COLOR = {
    FaultCode.LOW_SIGNAL: "#e63946",
    FaultCode.SATURATION: "#e9c46a",
    FaultCode.MULTI_SOURCE: "#e76f51",
}


def _health_panel(frame: ReplayFrame) -> list:
    """Render a frame's fault health as a list of Dash HTML components."""
    health = frame.health
    if health.ok:
        badges = [html.Span("HEALTHY", style={
            "background": "#2a9d8f", "color": "white", "padding": "2px 10px",
            "borderRadius": "10px", "fontWeight": "bold"})]
    else:
        badges = [
            html.Span(code.value.replace("_", " ").upper(), style={
                "background": _FAULT_COLOR.get(code, "#888"), "color": "white",
                "padding": "2px 10px", "borderRadius": "10px", "marginRight": "6px",
                "fontWeight": "bold"})
            for code in health.faults
        ]

    err = "—" if frame.angular_error_deg is None else f"{frame.angular_error_deg:.3f}°"
    rows = [
        ("Sequence", str(frame.seq)),
        ("Time", f"{frame.time_s:.2f} s"),
        ("Dominant face", str(health.dominant_face)),
        ("Angular error", err),
        ("Opposition ratio", f"{health.opposition_ratio:.3f}"),
        ("Saturated faces", ", ".join(health.saturated_faces) or "none"),
        ("Total signal", f"{health.total_signal:.0f}"),
    ]
    return [
        html.Div(badges, style={"marginBottom": "12px"}),
        html.Table(
            [html.Tr([html.Td(k, style={"color": "#6b7a9a", "paddingRight": "16px"}),
                      html.Td(v, style={"fontWeight": "600"})]) for k, v in rows],
            style={"width": "100%"},
        ),
    ]


def create_app(
    frames: Sequence[ReplayFrame],
    tick_ms: int = 400,
    title: str = "Tetralux-1 — Sun-Direction Telemetry",
) -> Dash:
    """Create (but do not run) the Dash app over the given replay frames.

    Args:
        frames: The decoded/estimated replay frames to visualize.
        tick_ms: Auto-advance interval, in milliseconds, while playing.
        title: Page/header title.

    Returns:
        A configured :class:`dash.Dash` instance (call ``.run(...)`` to serve).
    """
    frames = list(frames)
    if not frames:
        raise ValueError("create_app requires at least one ReplayFrame")

    times = [f.time_s for f in frames]
    errors = [f.angular_error_deg for f in frames]
    n = len(frames)

    app = Dash(__name__, title=title)
    app.layout = html.Div(
        style={"maxWidth": "1100px", "margin": "0 auto",
               "fontFamily": "system-ui, sans-serif", "padding": "16px"},
        children=[
            html.H2(title),
            html.Div(
                [
                    html.Button("▶ Play", id="play-btn", n_clicks=0,
                                style={"marginRight": "12px", "padding": "6px 14px"}),
                    html.Span("Frame", style={"marginRight": "8px"}),
                    html.Div(
                        dcc.Slider(id="frame-slider", min=0, max=n - 1, step=1, value=0,
                                   marks=None, tooltip={"placement": "bottom"}),
                        style={"flex": "1"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "8px",
                       "marginBottom": "16px"},
            ),
            dcc.Interval(id="tick", interval=tick_ms, disabled=True),
            html.Div(
                [
                    dcc.Graph(id="vec3d", style={"flex": "1 1 460px"}),
                    html.Div(id="health", style={
                        "flex": "1 1 300px", "padding": "16px",
                        "background": "#f6f8fb", "borderRadius": "8px"}),
                ],
                style={"display": "flex", "flexWrap": "wrap", "gap": "16px"},
            ),
            dcc.Graph(id="bars"),
            dcc.Graph(id="err"),
        ],
    )

    @app.callback(
        Output("vec3d", "figure"),
        Output("bars", "figure"),
        Output("err", "figure"),
        Output("health", "children"),
        Input("frame-slider", "value"),
    )
    def _update(idx):
        idx = int(idx or 0)
        frame = frames[idx]
        return (
            sun_vector_figure(frame.sun_vector, frame.reference),
            face_readings_figure(frame.readings, frame.saturated),
            angular_error_figure(times, errors, current_index=idx),
            _health_panel(frame),
        )

    @app.callback(
        Output("tick", "disabled"),
        Output("play-btn", "children"),
        Input("play-btn", "n_clicks"),
        State("tick", "disabled"),
        prevent_initial_call=True,
    )
    def _toggle_play(_clicks, disabled):
        now_playing = disabled  # was disabled -> start playing
        return (not disabled), ("⏸ Pause" if now_playing else "▶ Play")

    @app.callback(
        Output("frame-slider", "value"),
        Input("tick", "n_intervals"),
        State("frame-slider", "value"),
        prevent_initial_call=True,
    )
    def _advance(_n, value):
        return (int(value or 0) + 1) % n

    return app


def _demo_trajectory(n: int = 72, elevation_deg: float = 35.0) -> list[np.ndarray]:
    """A light source sweeping azimuth 0 -> 180 deg at fixed elevation."""
    el = np.radians(elevation_deg)
    dirs = []
    for i in range(n):
        az = np.radians(i * (180.0 / n))
        dirs.append(np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)]))
    return dirs


def build_demo_frames(seed: int = 0) -> list[ReplayFrame]:
    """Generate a noisy demo telemetry stream and decode it into replay frames."""
    dirs = _demo_trajectory()
    stream_pairs = generate_telemetry(
        dirs, rate_hz=10.0, intensity=60000.0, noise_std=200.0,
        rng=np.random.default_rng(seed),
    )
    raw = pack_stream(pkt for _, pkt in stream_pairs)
    return build_replay(raw, references=dirs, rate_hz=10.0)


def main(port: int = 8050, debug: bool = False) -> None:
    """Launch the dashboard on a demo telemetry stream."""
    app = create_app(build_demo_frames())
    app.run(port=port, debug=debug)


if __name__ == "__main__":
    main()
