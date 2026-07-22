"""Tetralux-1 ground-station dashboard v2 (Phase 9).

A multi-page Plotly Dash app with a Virtual/Real mode toggle:

- **Virtual** — az/el sliders drive an *instantaneous* recompute of every value.
- **Real** — a background stream (HTTP/serial ingest, or the built-in simulated
  device) feeds a rolling buffer; az/el are read-only; connection status shows.

Pages: Live · 3D Vector · Light in 3D · Time-series · History/Logs · About.
Every value is rendered through the units registry (no bare numbers). Requires
the ``dashboard`` extra (dash, plotly).
"""

from __future__ import annotations

import tempfile
from typing import Optional

from dash import Dash, Input, Output, State, callback_context, dcc, html

from tetralux.constants import FACE_NAMES
from tetralux.dashboard import units as U
from tetralux.dashboard.figures import face_readings_figure
from tetralux.dashboard.figures_v2 import (
    cube_figure,
    light_space_figure,
    timeseries_figure,
    weights_figure,
)
from tetralux.dashboard.state import AppState
from tetralux.estimation.estimator import angles_to_vector
from tetralux.store import query
from tetralux.thermal.analysis import SENSOR_FACE, SENSOR_IDS

_ACCENT = "#14213d"
_CARD = {"background": "#f6f8fb", "borderRadius": "8px", "padding": "14px",
         "flex": "1 1 320px"}

ABOUT_MD = """
### Tetralux-1 — Math & Pipeline

**Estimation (locked, formulas 1–4)**
- 1 Corrected reading: `R_i = (V_i − D_i)·G_i`
- 2 Face weight: `w_i = R_i / Σ R_j`
- 3 Direction vector: `d = Σ w_i · n̂_i`
- 4 Sun vector: `ŝ = d / |d|`  (LowSignalError if `Σ R_j < 1e-9` or `|d| < 1e-9`)
- 5 Cosine proxy: `cos θ_i = R_i / V_max,i`

**Solar radiation pressure (formulas 6–10)**
- 6 `F_i = (I_i·A/c)(1+ρ)` · 7 `F_net = Σ F_i·n̂_i` · 8 `|F_net|`
- 9 `θ_SRP = atan2(F_y,F_x)` · 10 `φ_SRP = asin(F_z/|F_net|)`

**Validation (formulas 11–14)**
- 11 Angular error: `θ = arccos(clamp(ŝ·ŝ_ref, −1, 1))`
- 12 Repeatability: `σ = std(θ)` · 13 Bias: `mean(θ)` · 14 Drift: `ΔT/Δt`

**Colour (formulas 15–16 + CCT gate)**
- 15 Chromaticity: `x = X/(X+Y+Z)`, `y = Y/(X+Y+Z)`
- 16 McCamy n: `n = (x−0.3320)/(y−0.1858)`
- CCT (signed McCamy): `−449n³ + 3525n² − 6823.3n + 5520.33`;
  trust = PASS when `|CCT − 5500 K| ≤ 500 K`

**Pipeline:** SensorFrame → calibrate → estimate (+az/el) → validate → faults →
thermal → OPT trust → GroundStationRecord. Real telemetry is newline-JSON with an
8-bit XOR checksum; the online log is Firebase RTDB (per packet) plus a local
JSONL mirror.
"""


# ----------------------------------------------------------------------------
# render helpers
# ----------------------------------------------------------------------------
def _row(label, value):
    return html.Tr([
        html.Td(label, style={"color": "#6b7a9a", "paddingRight": "14px",
                              "whiteSpace": "nowrap"}),
        html.Td(value, style={"fontWeight": 600}),
    ])


def _table(rows):
    return html.Table(rows, style={"width": "100%", "fontSize": "14px"})


def _card(title, rows):
    return html.Div([html.H4(title, style={"margin": "0 0 8px"}), _table(rows)],
                    style=_CARD)


def _face_table(rec):
    header = html.Tr([html.Th("Quantity")] + [html.Th(f) for f in FACE_NAMES])
    specs = [
        ("Photodiode (ADC counts)", rec.photodiodes, 0),
        ("Lux (lx)", rec.lux, 1),
        ("Corrected Rᵢ (ADC counts)", rec.corrected, 1),
        ("Cosine proxy (dimensionless)", rec.cosine_proxy, 3),
        ("Irradiance (W/m²)", rec.irradiance, 2),
        ("Weight wᵢ (dimensionless)", rec.weights, 4),
    ]
    body = []
    for label, data, nd in specs:
        cells = [html.Td(U.fmt(data.get(f), None, nd))
                 for f in FACE_NAMES]
        body.append(html.Tr([html.Td(label, style={"color": "#6b7a9a"})] + cells))
    return html.Table([header] + body,
                      style={"width": "100%", "fontSize": "13px",
                             "borderCollapse": "collapse"})


def _live_panel(rec, mode):
    if rec is None:
        return html.Div(
            "No telemetry yet. In Real mode, start the simulated device (top bar) "
            "or POST JSON frames to the ingest server.",
            style={"padding": "24px", "color": "#6b7a9a"})

    sv = rec.sun_vector
    est = _card("Sun estimate", [
        _row("Sun vector x", U.q(sv[0] if sv else None, "sun_component")),
        _row("Sun vector y", U.q(sv[1] if sv else None, "sun_component")),
        _row("Sun vector z", U.q(sv[2] if sv else None, "sun_component")),
        _row("Azimuth", U.q(rec.azimuth_deg, "angle", 2)),
        _row("Elevation", U.q(rec.elevation_deg, "angle", 2)),
        _row("Confidence", U.q(rec.confidence, "confidence")),
    ])
    val = _card("Validation", [
        _row("Angular error", U.q(rec.angular_error_deg, "angle", 3)),
        _row("Bias", U.q(rec.bias_deg, "angle", 3)),
        _row("Repeatability", U.q(rec.repeatability_deg, "angle", 3)),
    ])
    integ = _card("Integrity & faults", [
        _row("Checksum", U.fmt(rec.checksum, "(8-bit)", 0)),
        _row("Checksum valid", U.fmt(rec.checksum_ok)),
        _row("Saturation flag", U.fmt(rec.saturation_flag)),
        _row("Saturated faces", ", ".join(rec.saturated_faces) or "none"),
        _row("Faults", ", ".join(rec.faults) or "none"),
        _row("Opposition ratio", U.q(rec.opposition_ratio, "opposition")),
    ])

    if rec.stream:
        s = rec.stream
        stream = _card("Telemetry stream", [
            _row("Connected", U.fmt(s["connected"])),
            _row("Rate", U.q(s["rate_hz"], "rate", 1)),
            _row("Received", U.fmt(s["total_received"], "(count)", 0)),
            _row("Dropped", U.fmt(s["dropped"], "(count)", 0)),
            _row("Corrupt (checksum)", U.fmt(s["corrupt"], "(count)", 0)),
            _row("Seq gaps", U.fmt(s["seq_gaps"], "(count)", 0)),
        ])
    else:
        stream = _card("Telemetry stream", [
            _row("Mode", "Virtual — instantaneous, no packet stream")])

    opt = rec.opt
    optc = _card("OPT4048 colour trust", [
        _row("Trust gate", opt["gate"]),
        _row("Trust this estimate?", U.fmt(opt["trusted"])),
        _row("CCT (average)", U.q(opt["cct_average"], "cct", 0)),
        _row("Reference / tol", f'{U.q(opt["reference"], "cct", 0)} ± {opt["tolerance"]:.0f} K'),
        _row("Light source", opt["light_source"]),
    ])

    if rec.thermal:
        temps = rec.thermal["temperatures"]
        drift = rec.thermal["drift_rates"]
        flags = rec.thermal["drift_flags"]
        trows = [_row(
            f"{sid} · {SENSOR_FACE[sid]}",
            f'{U.q(temps.get(sid), "temperature", 2)} · drift '
            f'{U.q(drift.get(sid), "drift", 2)}{" ⚠" if flags.get(sid) else ""}')
            for sid in SENSOR_IDS]
        trows.append(_row("Any drift", U.fmt(rec.thermal["any_drift"])))
    else:
        trows = [_row("Thermal", "N/A")]
    m = rec.magnetometer
    sysc = _card("Thermal & system status", trows + [
        _row("Magnetometer", f'x={m["x"]}, y={m["y"]}, z={m["z"]} (raw)'),
        _row("Source", rec.source),
        _row("Processing time", U.fmt(rec.processing_time_ms, "ms", 2)),
    ])

    cards = html.Div([est, val, integ, stream, optc, sysc],
                     style={"display": "flex", "flexWrap": "wrap", "gap": "12px"})
    faces = html.Div([html.H4("Per-face sensors & calibration"), _face_table(rec)],
                     style={"marginTop": "14px"})
    return html.Div([cards, faces])


def _empty_ts(note):
    fig = timeseries_figure([], {}, note, "value")
    return fig


def _timeseries_figs(history):
    if not history:
        return (_empty_ts("Sun vector — (Real mode / streaming only)"),
                _empty_ts("Validation metrics — (Real mode / streaming only)"))
    times = [r.timestamp_ms / 1000.0 for r in history]
    xs = [r.sun_vector[0] if r.sun_vector else None for r in history]
    ys = [r.sun_vector[1] if r.sun_vector else None for r in history]
    zs = [r.sun_vector[2] if r.sun_vector else None for r in history]
    vec = timeseries_figure(times, {"x": xs, "y": ys, "z": zs},
                            "Sun vector components", "dimensionless")
    met = timeseries_figure(
        times,
        {"angular error": [r.angular_error_deg for r in history],
         "bias": [r.bias_deg for r in history],
         "repeatability": [r.repeatability_deg for r in history]},
        "Validation metrics", "degrees")
    return vec, met


def _conn_badge(state):
    if state.mode == "virtual":
        return html.Span("Virtual mode — instantaneous",
                         style={"color": _ACCENT, "fontWeight": 600})
    s = state.connection()
    if s["connected"]:
        return html.Span(f'🟢 Connected · {s["rate_hz"]:.0f} Hz',
                         style={"color": "#2a9d8f", "fontWeight": 700})
    return html.Span("🔴 Disconnected — waiting for telemetry",
                     style={"color": "#e63946", "fontWeight": 700})


# ----------------------------------------------------------------------------
# app
# ----------------------------------------------------------------------------
def create_app(state: Optional[AppState] = None) -> Dash:
    """Build (but do not run) the ground-station dashboard."""
    state = state or AppState()
    app = Dash(__name__, title="Tetralux-1 Ground Station",
               suppress_callback_exceptions=True)

    def nav_link(label, href):
        return dcc.Link(label, href=href, style={
            "marginRight": "14px", "textDecoration": "none",
            "color": _ACCENT, "fontWeight": 600})

    slider_row = html.Div([
        html.Div([html.Label("Azimuth (°)"),
                  dcc.Slider(id="az", min=-180, max=180, step=1, value=0,
                             marks=None, tooltip={"placement": "bottom"})],
                 style={"flex": 1}),
        html.Div([html.Label("Elevation (°)"),
                  dcc.Slider(id="el", min=-90, max=90, step=1, value=30,
                             marks=None, tooltip={"placement": "bottom"})],
                 style={"flex": 1}),
    ], style={"display": "flex", "gap": "20px", "marginTop": "6px"})

    controls = html.Div([
        html.Div([
            html.Label("Mode", style={"marginRight": "8px", "fontWeight": 600}),
            dcc.RadioItems(id="mode", value="virtual", inline=True,
                           options=[{"label": " Virtual", "value": "virtual"},
                                    {"label": " Real-time", "value": "real"}]),
            dcc.Checklist(id="sim", options=[{"label": " Simulated device feed",
                                              "value": "on"}], value=[],
                          style={"display": "inline-block", "marginLeft": "18px"}),
            html.Button("● Start session", id="session-btn", n_clicks=0,
                        style={"marginLeft": "18px", "padding": "5px 12px"}),
            html.Span(id="session-status", style={"marginLeft": "12px",
                                                  "color": "#6b7a9a"}),
            html.Span(id="conn-badge", style={"marginLeft": "18px", "float": "right"}),
        ]),
        slider_row,
    ], style={"padding": "10px 0", "borderBottom": "1px solid #e5e5e5"})

    def page(cid, children):
        return html.Div(children, id=cid, style={"display": "none",
                                                 "paddingTop": "12px"})

    live_page = page("page-live", [
        html.Div(id="live-panel"),
        html.Div([dcc.Graph(id="fig-faces", style={"flex": "1 1 420px"}),
                  dcc.Graph(id="fig-weights", style={"flex": "1 1 420px"})],
                 style={"display": "flex", "flexWrap": "wrap", "gap": "12px",
                        "marginTop": "12px"}),
    ])
    vector_page = page("page-vector", [dcc.Graph(id="fig-cube")])
    light_page = page("page-light", [dcc.Graph(id="fig-light")])
    ts_page = page("page-timeseries", [dcc.Graph(id="fig-ts-vector"),
                                       dcc.Graph(id="fig-ts-metrics")])
    history_page = page("page-history", [
        html.Div([
            html.Button("Refresh sessions", id="refresh-sessions", n_clicks=0,
                        style={"padding": "5px 12px"}),
            dcc.Dropdown(id="session-dd", placeholder="Select a session",
                         style={"width": "320px", "display": "inline-block",
                                "marginLeft": "12px", "verticalAlign": "middle"}),
            dcc.Input(id="range-start", type="number", placeholder="start ts (ms)",
                      style={"marginLeft": "12px"}),
            dcc.Input(id="range-end", type="number", placeholder="end ts (ms)",
                      style={"marginLeft": "6px"}),
            html.Button("Load", id="load-session", n_clicks=0,
                        style={"marginLeft": "12px", "padding": "5px 12px"}),
            html.Button("Export CSV", id="export-csv", n_clicks=0,
                        style={"marginLeft": "8px", "padding": "5px 12px"}),
            dcc.Download(id="download-csv"),
        ]),
        html.H4("Sessions"), html.Div(id="sessions-table"),
        html.H4("Records (selected range)"), html.Div(id="history-table"),
    ])
    about_page = page("page-about", [dcc.Markdown(ABOUT_MD)])

    app.layout = html.Div(
        style={"maxWidth": "1180px", "margin": "0 auto",
               "fontFamily": "system-ui, sans-serif", "padding": "14px"},
        children=[
            dcc.Location(id="url"),
            html.H2("Tetralux-1 — CubeSat Sun-Direction Ground Station"),
            html.Div([
                nav_link("Live", "/"), nav_link("3D Vector", "/vector"),
                nav_link("Light in 3D", "/light"), nav_link("Time-series", "/timeseries"),
                nav_link("History / Logs", "/history"), nav_link("About", "/about"),
            ], style={"padding": "6px 0"}),
            controls,
            live_page, vector_page, light_page, ts_page, history_page, about_page,
            dcc.Interval(id="tick", interval=700, n_intervals=0),
        ],
    )

    _register_callbacks(app, state)
    return app


def _register_callbacks(app, state):
    PAGES = ["page-live", "page-vector", "page-light", "page-timeseries",
             "page-history", "page-about"]
    ROUTE = {"/": "page-live", "/vector": "page-vector", "/light": "page-light",
             "/timeseries": "page-timeseries", "/history": "page-history",
             "/about": "page-about"}

    @app.callback([Output(p, "style") for p in PAGES], Input("url", "pathname"))
    def _route(pathname):
        active = ROUTE.get(pathname or "/", "page-live")
        return [{"display": "block" if p == active else "none",
                 "paddingTop": "12px"} for p in PAGES]

    @app.callback(
        Output("az", "disabled"), Output("el", "disabled"),
        Input("mode", "value"))
    def _mode(mode):
        state.mode = mode
        if mode == "real":
            state.start_real()
        return (mode == "real"), (mode == "real")

    @app.callback(Output("sim", "value"), Input("sim", "value"))
    def _sim(value):
        if "on" in (value or []):
            state.start_sim_device()
        else:
            state.stop_sim_device()
        return value

    @app.callback(
        Output("session-status", "children"), Output("session-btn", "children"),
        Input("session-btn", "n_clicks"))
    def _session(n):
        if not n:
            return "Logging off (session not started).", "● Start session"
        if state.session.active:
            info = state.session.stop()
            return (f"Stopped {info.session_id}: {info.packet_count} packets, "
                    f"{U.human_bytes(info.local_bytes)} local, "
                    f"~{U.human_bytes(info.rtdb_bytes_est)} RTDB.",
                    "● Start session")
        info = state.session.start()
        return f"Recording {info.session_id}…", "■ Stop session"

    @app.callback(
        Output("live-panel", "children"), Output("fig-faces", "figure"),
        Output("fig-weights", "figure"), Output("fig-cube", "figure"),
        Output("fig-light", "figure"), Output("fig-ts-vector", "figure"),
        Output("fig-ts-metrics", "figure"), Output("conn-badge", "children"),
        Input("tick", "n_intervals"), Input("mode", "value"),
        Input("az", "value"), Input("el", "value"))
    def _refresh(_n, mode, az, el):
        state.mode = mode
        history = []
        if mode == "virtual":
            rec = state.compute_virtual(float(az or 0), float(el or 0))
            reference = angles_to_vector(float(az or 0), float(el or 0))
            light_dir = reference
        else:
            rec = state.latest()
            reference = state.stream_ctx.reference_vector if state.stream_ctx else None
            light_dir = rec.sun_vector if rec else None
            history = state.history(400)

        if rec is None:
            empty = weights_figure({})
            return (_live_panel(None, mode), face_readings_figure({}),
                    empty, cube_figure(), light_space_figure(),
                    _empty_ts("Sun vector"), _empty_ts("Validation"),
                    _conn_badge(state))

        saturated = {f: f in rec.saturated_faces for f in FACE_NAMES}
        faces_fig = face_readings_figure(rec.photodiodes, saturated)
        wfig = weights_figure(rec.weights)
        cube = cube_figure(rec.sun_vector, reference)
        light = light_space_figure(light_dir)
        ts_vec, ts_met = _timeseries_figs(history)
        return (_live_panel(rec, mode), faces_fig, wfig, cube, light,
                ts_vec, ts_met, _conn_badge(state))

    # ---- history page ----
    @app.callback(
        Output("sessions-table", "children"), Output("session-dd", "options"),
        Input("refresh-sessions", "n_clicks"), Input("url", "pathname"))
    def _sessions(_n, pathname):
        sessions = query.list_sessions(state.session.base_dir)
        if not sessions:
            return html.Div("No sessions recorded yet.",
                            style={"color": "#6b7a9a"}), []
        header = html.Tr([html.Th(h) for h in
                          ["Session", "Started", "Packets", "Size", "RTDB ~",
                           "First ts (ms)", "Last ts (ms)"]])
        rows = [header]
        for s in sessions:
            rows.append(html.Tr([
                html.Td(s.session_id), html.Td(s.started_at or "—"),
                html.Td(U.fmt(s.packet_count, "(count)", 0)),
                html.Td(s.size_human()), html.Td(U.human_bytes(s.rtdb_bytes_est)),
                html.Td(U.fmt(s.first_ts_ms, "ms", 0)),
                html.Td(U.fmt(s.last_ts_ms, "ms", 0)),
            ]))
        table = html.Table(rows, style={"width": "100%", "fontSize": "13px"})
        options = [{"label": s.session_id, "value": s.session_id} for s in sessions]
        return table, options

    @app.callback(
        Output("history-table", "children"),
        Input("load-session", "n_clicks"),
        State("session-dd", "value"), State("range-start", "value"),
        State("range-end", "value"))
    def _load(_n, session_id, start_ms, end_ms):
        if not session_id:
            return html.Div("Select a session and click Load.",
                            style={"color": "#6b7a9a"})
        recs = query.read_range(session_id,
                                int(start_ms) if start_ms is not None else None,
                                int(end_ms) if end_ms is not None else None,
                                base_dir=state.session.base_dir)
        if not recs:
            return html.Div("No records in range.", style={"color": "#6b7a9a"})
        header = html.Tr([html.Th(h) for h in
                          ["seq", "ts (ms)", "az (°)", "el (°)",
                           "ang.err (°)", "faults", "checksum"]])
        rows = [header]
        for r in recs[:500]:
            rows.append(html.Tr([
                html.Td(r.get("seq")), html.Td(r.get("timestamp_ms")),
                html.Td(U.fmt(r.get("azimuth_deg"), None, 2)),
                html.Td(U.fmt(r.get("elevation_deg"), None, 2)),
                html.Td(U.fmt(r.get("angular_error_deg"), None, 3)),
                html.Td(", ".join(r.get("faults") or []) or "none"),
                html.Td(r.get("checksum")),
            ]))
        note = "" if len(recs) <= 500 else f" (showing first 500 of {len(recs)})"
        return html.Div([html.Div(f"{len(recs)} records{note}",
                                  style={"color": "#6b7a9a", "marginBottom": "6px"}),
                         html.Table(rows, style={"width": "100%", "fontSize": "13px"})])

    @app.callback(
        Output("download-csv", "data"),
        Input("export-csv", "n_clicks"),
        State("session-dd", "value"), State("range-start", "value"),
        State("range-end", "value"), prevent_initial_call=True)
    def _export(_n, session_id, start_ms, end_ms):
        if not session_id:
            return None
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.close()
        query.export_session_csv(
            session_id, tmp.name,
            int(start_ms) if start_ms is not None else None,
            int(end_ms) if end_ms is not None else None,
            base_dir=state.session.base_dir)
        return dcc.send_file(tmp.name, filename=f"{session_id}.csv")


def main(port: int = 8050, debug: bool = False) -> None:
    """Launch the ground-station dashboard (Virtual mode by default).

    Enables Firebase RTDB online logging automatically if the credentials env
    vars are set; otherwise logs locally only (still full fidelity).
    """
    from tetralux.store import make_online_store

    create_app(AppState(online_store=make_online_store())).run(port=port, debug=debug)


if __name__ == "__main__":
    main()
