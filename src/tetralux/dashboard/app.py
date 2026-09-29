"""Tetralux-1 ground-station dashboard v2 (Phase 9).

WHAT THIS FILE CONTRIBUTES
--------------------------
The user interface: the web page a person actually looks at. It builds the
layout, wires up the buttons and sliders, and refreshes the display several
times a second.

It is the largest file in the project and also the least mathematical. Every
number it shows was computed elsewhere; this file only arranges them.

HOW DASH WORKS, because the structure will look strange otherwise. Dash lets you
build a web page in Python: no HTML file, no JavaScript. You describe the page
as nested Python objects (html.Div, dcc.Graph), and Dash renders them in the
browser and keeps them updated.

The important idea is the CALLBACK. A callback is a function tagged with
`@app.callback` that says which inputs it watches and which outputs it fills.
When a watched input changes, Dash calls the function and puts what it returns
into the named outputs. You never call these functions yourself.

    @app.callback(Output("live-panel", "children"), Input("tick", "n_intervals"))
    def _refresh(n):
        return "whatever should appear in the panel"

Every component has an `id`, and those ids are how callbacks address them. A
typo in an id fails silently, which is the main hazard of this style.

CALLBACKS ARE STATELESS. Each one runs, returns, and forgets everything. That is
why AppState exists in dashboard/state.py: anything that must survive between
refreshes lives there, and the callbacks here read and write it.

THE FIVE PAGES all exist in the browser at once. `_route` shows one and hides the
other four by switching their CSS display property, rather than rebuilding the
page. That keeps navigation instant and avoids losing the state of a page you
click away from.

THE UNITS RULE IS ENFORCED HERE. Every displayed value goes through U.q or
U.fmt, so it carries its unit or is labelled dimensionless. There are no bare
numbers on this page (see dashboard/units.py).

WHERE IT SITS IN THE FLOW
    dashboard/state.py    the state these callbacks read and mutate
    dashboard/figures.py  the charts placed into the page
    dashboard/units.py    the formatting of every value shown
    store/query.py        the session history the History page lists

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# tempfile: creates a temporary file, used for the CSV download.
import tempfile
from typing import Optional

# Dash's building blocks:
#   Dash                the application object
#   Input/Output/State  declare what a callback watches and fills
#   dcc                 "Dash Core Components": sliders, graphs, dropdowns
#   html                Python mirrors of HTML tags: html.Div, html.Table
from dash import Dash, Input, Output, State, dcc, html

from tetralux.constants import FACE_NAMES
from tetralux.dashboard import units as U
from tetralux.dashboard.figures import (
    cube_figure,
    face_readings_figure,
    srp_figure,
    timeseries_figure,
    weights_figure,
)
from tetralux.dashboard.state import AppState
from tetralux.estimation.estimator import angles_to_vector
from tetralux.store import query
from tetralux.thermal.analysis import SENSOR_FACE, SENSOR_IDS

_ACCENT = "#14213d"
# A reusable CSS style dict for the panels on the Live page. Styles in Dash are
# Python dicts using camelCase names ("borderRadius", not "border-radius").
#
# "flex": "1 1 320px" means: grow to fill space, shrink when cramped, but prefer
# to be 320 pixels wide. That is what makes the cards reflow into however many
# columns the window allows, rather than needing a fixed layout.
_CARD = {"background": "#f6f8fb", "borderRadius": "8px", "padding": "14px",
         "flex": "1 1 320px"}

# The About page content, written in Markdown. A triple-quoted string can span
# many lines, and dcc.Markdown renders it as formatted text.
#
# EVERY FORMULA LISTED HERE IS ACTUALLY COMPUTED. That was not always true: the
# SRP formulas were listed while nothing called them, which made this page a
# claim rather than a description. They are now wired into pipeline.py, and this
# text should be checked against the code whenever either changes.
ABOUT_MD = """
### Tetralux-1: math and pipeline

Every formula below is computed on each frame and shown somewhere in this app.

**Sun-vector estimation (formulas 1-5)**
- 1 Corrected reading: `R_i = (V_i - D_i) * G_i`
- 2 Face weight: `w_i = R_i / sum(R_j)`
- 3 Direction vector: `d = sum(w_i * n_i)`
- 4 Sun vector: `s = d / |d|`  (LowSignalError if `sum(R_j) < 1e-9` or `|d| < 1e-9`)
- 5 Cosine proxy: `cos(theta_i) = R_i / V_max,i`

**Solar radiation pressure (formulas 6-10)**
- 6 `F_i = (I_i * A / c) * (1 + rho)`, using the per-face irradiance from step 5
- 7 `F_net = sum(F_i * n_i)`   8 `|F_net| = sqrt(Fx^2 + Fy^2 + Fz^2)`
- 9 `az_SRP = atan2(Fy, Fx)`   10 `el_SRP = asin(Fz / |F_net|)`
- Saturated faces are excluded: a clipped reading understates true irradiance.

**Validation (formulas 11-14)**
- 11 Angular error: `theta = arccos(clamp(s . s_ref, -1, 1))`
- 12 Repeatability: `std(theta)`   13 Bias: `mean(theta)`   14 Drift: `dT/dt`

**Colour trust (formulas 15-18)**
- 15 Chromaticity: `x = X/(X+Y+Z)`, `y = Y/(X+Y+Z)`
- 16 McCamy n: `n = (x - 0.3320) / (y - 0.1858)`
- 17 CCT: `-449n^3 + 3525n^2 - 6823.3n + 5520.33` (signed coefficients)
- 18 Trust gate: PASS when `|CCT - 5500 K| <= 500 K`

**Pipeline:** SensorFrame -> calibrate -> estimate (+ az/el) -> SRP -> validate
-> faults -> thermal -> colour trust -> GroundStationRecord. Telemetry is
newline-delimited JSON with an 8-bit XOR checksum over the bytes preceding the
checksum field.
"""


# ----------------------------------------------------------------------------
# render helpers
# ----------------------------------------------------------------------------
# Small builders that assemble the page's repeating pieces. Each returns a Dash
# component, and they nest: _row builds a table row, _table gathers rows,
# _card wraps a table with a heading.
#
# Their value is consistency. Every label on the page gets the same colour and
# spacing because it went through _row, so restyling all of them is one edit
# here rather than fifty scattered style dicts.
#
# PARAMETERS
#   label - the field name, e.g. "Azimuth".
#   value - the formatted value, already carrying its unit.
# RETURNS
#   one table row: a muted label and a bold value.
#
# whiteSpace "nowrap" stops a label wrapping mid-phrase and misaligning the row.
def _row(label, value):
    return html.Tr([
        html.Td(label, style={"color": "#6b7a9a", "paddingRight": "14px",
                              "whiteSpace": "nowrap"}),
        html.Td(value, style={"fontWeight": 600}),
    ])


def _table(rows):
    return html.Table(rows, style={"width": "100%", "fontSize": "14px"})


# PARAMETERS
#   title - the card heading.
#   rows  - the _row entries inside it.
# RETURNS
#   one styled panel.
#
# The Live page is a row of these: sun estimate, validation, SRP, integrity,
# stream, colour, thermal. Grouping related values into cards is what makes
# forty numbers scannable instead of a wall of text.
def _card(title, rows):
    return html.Div([html.H4(title, style={"margin": "0 0 8px"}), _table(rows)],
                    style=_CARD)


# --- The per-face table ---
#
# PARAMETER
#   rec - the GroundStationRecord to display.
# RETURNS
#   a table with six face columns and one row per quantity.
#
# This is where the calibration chain becomes visible. Reading DOWN a column
# follows one face from its raw ADC count, through the corrected value, the
# cosine, the irradiance, to its final weight. Reading ACROSS a row compares the
# six faces at one stage. That layout is what makes a miscalibrated face
# obvious: its corrected value sits out of line with the others.
def _face_table(rec):
    header = html.Tr([html.Th("Quantity")] + [html.Th(f) for f in FACE_NAMES])
    # Each entry is (label, data, decimal places). Listing them as data rather
    # than writing six near-identical blocks means adding a quantity is one
    # line.
    #
    # THE DECIMAL PLACES ARE CHOSEN PER QUANTITY, matching real precision. ADC
    # counts are whole numbers, so 0. Weights need 4 because six of them sum to
    # 1, so meaningful differences appear in the fourth place. Showing 4
    # decimals on an integer ADC count would imply precision the hardware does
    # not have.
    #
    # Every label carries its unit, or says "dimensionless".
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


# --- The main Live page panel ---
#
# PARAMETERS
#   rec  - the record to display, or None if nothing has arrived yet.
#   mode - "virtual" or "real".
# RETURNS
#   the whole panel: seven cards plus the per-face table.
def _live_panel(rec, mode):
    # THE EMPTY STATE, and it tells the user what to DO rather than just
    # reporting that data is absent. "No telemetry yet" alone would leave
    # someone stuck; naming the two ways to produce data does not.
    if rec is None:
        return html.Div(
            "No telemetry yet. In Real mode, start the simulated device (top bar) "
            "or POST JSON frames to the ingest server.",
            style={"padding": "24px", "color": "#6b7a9a"})

    sv = rec.sun_vector
    est = _card("Sun estimate", [
        # `sv[0] if sv else None` guards the dark case: sun_vector is None when
        # no direction could be resolved, and indexing None would raise. U.q
        # then renders a dash, honestly showing no measurement.
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
    net = rec.srp_net
    srp = _card("Solar radiation pressure", [
        # The 1e9 converts newtons to nanonewtons, as in figures.srp_figure.
        # SRP forces are around 1e-8 N, which would display as 0.000 at three
        # decimal places; in nN it reads as a real number. The unit is stated
        # explicitly, which is what keeps the conversion honest.
        _row("Net force |F|", U.fmt(rec.srp_magnitude_n * 1e9, "nN", 3)),
        _row("F_x", U.fmt(net[0] * 1e9, "nN", 3)),
        _row("F_y", U.fmt(net[1] * 1e9, "nN", 3)),
        _row("F_z", U.fmt(net[2] * 1e9, "nN", 3)),
        _row("SRP azimuth", U.q(rec.srp_azimuth_deg, "angle", 2)),
        _row("SRP elevation", U.q(rec.srp_elevation_deg, "angle", 2)),
    ])
    integ = _card("Integrity & faults", [
        _row("Checksum", U.fmt(rec.checksum, "(8-bit)", 0)),
        _row("Checksum valid", U.fmt(rec.checksum_ok)),
        _row("Saturation flag", U.fmt(rec.saturation_flag)),
        # `", ".join(...) or "none"` renders an empty list as the word "none".
        # An empty join gives "", which is falsy, so `or` supplies the fallback.
        # A blank cell would be ambiguous: no faults, or a rendering failure?
        _row("Saturated faces", ", ".join(rec.saturated_faces) or "none"),
        _row("Faults", ", ".join(rec.faults) or "none"),
        _row("Opposition ratio", U.q(rec.opposition_ratio, "opposition")),
    ])

    # Real mode has a packet stream and link statistics; Virtual mode computes
    # instantaneously and has no stream at all. Saying so explicitly is better
    # than showing a rate of 0 Hz, which would look like a broken connection.
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
            _row("Mode", "Virtual - instantaneous, no packet stream")])

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
        # SENSOR_FACE turns "T3" into "+y frame", so a drifting sensor names a
        # physical part of the hardware to inspect rather than an opaque id.
        # The warning triangle appears only when that sensor's drift flag is
        # set, so a problem is visible without reading every number.
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

    # flexWrap "wrap" lets the seven cards flow onto as many rows as the window
    # needs, so the page works on a laptop and a wide monitor without a separate
    # layout for each.
    cards = html.Div([est, val, srp, integ, stream, optc, sysc],
                     style={"display": "flex", "flexWrap": "wrap", "gap": "12px"})
    faces = html.Div([html.H4("Per-face sensors & calibration"), _face_table(rec)],
                     style={"marginTop": "14px"})
    return html.Div([cards, faces])


# PARAMETER
#   note - the title explaining why the chart is empty.
# RETURNS
#   an empty time-series figure.
#
# Dash requires every Output to receive a value on every callback run, so a
# chart cannot simply be left unfilled. An empty figure with an explanatory
# title is the honest placeholder.
def _empty_ts(note):
    fig = timeseries_figure([], {}, note, "value")
    return fig


# PARAMETER
#   history - recent records, oldest first.
# RETURNS
#   two figures: the sun vector components, and the validation metrics.
def _timeseries_figs(history):
    # Empty in Virtual mode, which has no timeline at all: each slider position
    # is an independent instantaneous calculation, not a moment in a sequence.
    # The titles say so rather than leaving a blank chart.
    if not history:
        return (_empty_ts("Sun vector - (Real mode / streaming only)"),
                _empty_ts("Validation metrics - (Real mode / streaming only)"))
    times = [r.timestamp_ms / 1000.0 for r in history]
    # None for any dark frame. timeseries_figure turns those into NaN, which
    # Plotly draws as a genuine GAP in the line, so a dropout is visible as a
    # hole rather than being papered over with a zero.
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


# PARAMETER
#   state - the AppState, for the mode and the link statistics.
# RETURNS
#   the connection indicator shown in the top bar.
#
# Three distinct states, not two. Virtual mode is not "disconnected", it is a
# mode where no connection is expected, and conflating the two would send
# someone hunting for a wiring fault that does not exist.
def _conn_badge(state):
    if state.mode == "virtual":
        return html.Span("Virtual mode - instantaneous",
                         style={"color": _ACCENT, "fontWeight": 600})
    s = state.connection()
    if s["connected"]:
        return html.Span(f'🟢 Connected · {s["rate_hz"]:.0f} Hz',
                         style={"color": "#2a9d8f", "fontWeight": 700})
    return html.Span("🔴 Disconnected - waiting for telemetry",
                     style={"color": "#e63946", "fontWeight": 700})


# ----------------------------------------------------------------------------
# app
# ----------------------------------------------------------------------------
# --- Build the whole application ---
#
# PARAMETER
#   state - an AppState to use, or None to create one. Injecting it is what lets
#           tests build an app pointed at a temporary directory.
# RETURNS
#   a configured Dash app, NOT running.
#
# Building and running are separate, as in ingest/http_server.py, so
# test_dashboard_v2.py can assert the app constructs and has a layout without
# opening a port or a browser.
def create_app(state: Optional[AppState] = None) -> Dash:
    """Build (but do not run) the ground-station dashboard."""
    state = state or AppState()
    # suppress_callback_exceptions=True is REQUIRED by this page's design.
    # Normally Dash verifies at startup that every id a callback references
    # exists in the layout. All five pages are in the layout here, but Dash
    # cannot always confirm that for components inside hidden divs, so the check
    # is disabled. The cost is that a typo in an id now fails silently at
    # runtime rather than loudly at startup.
    app = Dash(__name__, title="Tetralux-1 Ground Station",
               suppress_callback_exceptions=True)

    def nav_link(label, href):
        return dcc.Link(label, href=href, style={
            "marginRight": "14px", "textDecoration": "none",
            "color": _ACCENT, "fontWeight": 600})

    # THE SLIDERS ARE THE VIRTUAL-MODE INPUT: they define where the sun is, so
    # in Virtual mode they set the ground truth that the estimate is scored
    # against. In Real mode they are disabled (see the _mode callback), because
    # the sun's true position is then whatever the hardware is actually seeing
    # and cannot be dictated from a web page.
    #
    # The ids "az" and "el" are how the callbacks below reach these. Their
    # ranges match the physical meaning: azimuth wraps a full circle from -180
    # to 180, elevation runs from straight down to straight up.
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
            html.Span(id="conn-badge", style={"marginLeft": "18px", "float": "right"}),
        ]),
        html.Div([
            html.Label("Calibration file (Real mode)", style={"marginRight": "8px"}),
            dcc.Input(id="cal-path", type="text", placeholder="calibration.json",
                      style={"width": "260px"}),
            html.Button("Load calibration", id="cal-load-btn", n_clicks=0,
                        style={"marginLeft": "8px", "padding": "4px 10px"}),
            html.Span(id="cal-status", style={"marginLeft": "12px", "color": "#6b7a9a"}),
        ], style={"marginTop": "8px"}),
        slider_row,
    ], style={"padding": "10px 0", "borderBottom": "1px solid #e5e5e5"})

    # PARAMETERS
    #   cid      - the div id the router uses to show or hide this page.
    #   children - the page's contents.
    # RETURNS
    #   a hidden page div.
    #
    # EVERY PAGE STARTS HIDDEN, and _route reveals whichever one the URL names.
    # All five stay in the browser the whole time; navigation only toggles
    # visibility, so switching pages is instant and no page loses its state.
    def page(cid, children):
        return html.Div(children, id=cid, style={"display": "none",
                                                 "paddingTop": "12px"})

    live_page = page("page-live", [
        html.Div(id="live-panel"),
        html.Div([dcc.Graph(id="fig-faces", style={"flex": "1 1 420px"}),
                  dcc.Graph(id="fig-weights", style={"flex": "1 1 420px"}),
                  dcc.Graph(id="fig-srp", style={"flex": "1 1 420px"})],
                 style={"display": "flex", "flexWrap": "wrap", "gap": "12px",
                        "marginTop": "12px"}),
    ])
    vector_page = page("page-vector", [dcc.Graph(id="fig-cube")])
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
            # dcc.Location tracks the browser's URL. It renders nothing; the
            # _route callback watches its pathname to decide which page shows.
            dcc.Location(id="url"),
            html.H2("Tetralux-1 - CubeSat Sun-Direction Ground Station"),
            html.Div([
                nav_link("Live", "/"), nav_link("3D Vector", "/vector"),
                nav_link("Time-series", "/timeseries"),
                nav_link("History / Logs", "/history"), nav_link("About", "/about"),
            ], style={"padding": "6px 0"}),
            controls,
            live_page, vector_page, ts_page, history_page, about_page,
            # THE HEARTBEAT. dcc.Interval fires every 700 milliseconds,
            # incrementing n_intervals. The _refresh callback watches that
            # counter, so the whole display updates roughly 1.4 times a second.
            #
            # This is what makes the page live. Without it nothing would change
            # until a user touched a control, and Real mode would appear frozen
            # while data was arriving perfectly well behind it.
            #
            # 700 ms is a compromise: fast enough to feel live, slow enough that
            # rebuilding every card and chart does not saturate the browser.
            dcc.Interval(id="tick", interval=700, n_intervals=0),
        ],
    )

    _register_callbacks(app, state)
    return app


# --- Wire up every interaction ---
#
# PARAMETERS
#   app   - the Dash app to attach callbacks to.
#   state - the AppState the callbacks read and mutate.
# RETURNS
#   None; it registers functions as a side effect.
#
# Split out from create_app purely for readability: layout above, behaviour
# below. Every function defined here is called by DASH, never by this code.
def _register_callbacks(app, state):
    PAGES = ["page-live", "page-vector", "page-timeseries",
             "page-history", "page-about"]
    ROUTE = {"/": "page-live", "/vector": "page-vector",
             "/timeseries": "page-timeseries", "/history": "page-history",
             "/about": "page-about"}

    # THE ROUTER. Watches the URL, sets the style of all five page divs.
    #
    # Reading the decorator: it lists five Outputs, one per page's "style"
    # property, and one Input, the URL's pathname. So whenever the URL changes,
    # this runs and returns five style dicts, in the same order as the Outputs.
    #
    # PARAMETER
    #   pathname - the current URL path, e.g. "/vector".
    # RETURNS
    #   five style dicts, one per page.
    @app.callback([Output(p, "style") for p in PAGES], Input("url", "pathname"))
    def _route(pathname):
        # `pathname or "/"` handles a None pathname on first load, and .get
        # falls back to the Live page for any unknown URL rather than showing a
        # blank screen.
        active = ROUTE.get(pathname or "/", "page-live")
        return [{"display": "block" if p == active else "none",
                 "paddingTop": "12px"} for p in PAGES]

    @app.callback(
        Output("az", "disabled"), Output("el", "disabled"),
        Input("mode", "value"))
    # MODE SWITCHING.
    #
    # PARAMETER
    #   mode - "virtual" or "real", from the radio buttons.
    # RETURNS
    #   two booleans: whether each slider is disabled.
    def _mode(mode):
        # Writing to the shared state, which is how a stateless callback makes a
        # change that outlives it.
        state.mode = mode
        if mode == "real":
            # Idempotent, so clicking Real twice is harmless.
            state.start_real()
        # THE SLIDERS ARE LOCKED IN REAL MODE, and this is a correctness
        # decision rather than a cosmetic one. In Real mode the sun's true
        # position is whatever the hardware sees; letting a user set it would
        # let them declare a truth that was never measured, and every angular
        # error would then be scored against a fiction.
        return (mode == "real"), (mode == "real")

    # THE SIMULATED DEVICE TOGGLE.
    #
    # NOTE IT WATCHES AND WRITES THE SAME COMPONENT. Dash requires every
    # callback to have an Output, but the real work here is the side effect of
    # starting or stopping the background thread, and the checkbox should keep
    # whatever the user just clicked. So the value is echoed straight back.
    @app.callback(Output("sim", "value"), Input("sim", "value"))
    def _sim(value):
        if "on" in (value or []):
            state.start_sim_device()
        else:
            state.stop_sim_device()
        return value

    @app.callback(
        Output("cal-status", "children"),
        Input("cal-load-btn", "n_clicks"), State("cal-path", "value"),
        prevent_initial_call=True)
    # LOADING A CALIBRATION FILE.
    #
    # INPUT VERSUS STATE, which is the distinction to learn here. An Input
    # TRIGGERS the callback when it changes; a State is only READ when the
    # callback runs for some other reason.
    #
    # So the button is an Input and the text box is a State: this fires when the
    # button is clicked, not on every keystroke as the path is typed.
    #
    # prevent_initial_call=True stops Dash running it once at page load, which
    # would otherwise try to load an empty path immediately.
    #
    # PARAMETERS
    #   _n   - the click count. Underscore-prefixed because the VALUE is
    #          irrelevant; only the fact that it changed matters.
    #   path - the text box contents.
    # RETURNS
    #   a status message.
    def _load_calibration(_n, path):
        if not path:
            return "Enter a calibration.json path first."
        try:
            state.load_calibration(path)
        except (FileNotFoundError, ValueError, OSError) as exc:
            return f"Failed to load {path}: {exc}"
        return f"Loaded {path} - applied to Real-mode processing."

    @app.callback(
        Output("live-panel", "children"), Output("fig-faces", "figure"),
        Output("fig-weights", "figure"), Output("fig-srp", "figure"),
        Output("fig-cube", "figure"), Output("fig-ts-vector", "figure"),
        Output("fig-ts-metrics", "figure"), Output("conn-badge", "children"),
        Input("tick", "n_intervals"), Input("mode", "value"),
        Input("az", "value"), Input("el", "value"))
    # THE MAIN REFRESH. The busiest callback in the project: it fills the entire
    # display, and it runs roughly 1.4 times a second.
    #
    # EIGHT OUTPUTS, FOUR INPUTS. It fires whenever the timer ticks, the mode
    # changes, or either slider moves, and it must return all eight values every
    # time. That is why the empty-state branch below still returns eight things.
    #
    # One callback rather than eight, because everything shown comes from ONE
    # record. Separate callbacks would each compute their own, so the cards and
    # the charts could disagree about which frame they were describing.
    #
    # PARAMETERS
    #   _n     - the tick count, unused; only the fact it changed matters.
    #   mode   - "virtual" or "real".
    #   az, el - the slider positions.
    # RETURNS
    #   eight values, in the same order as the Outputs above.
    def _refresh(_n, mode, az, el):
        state.mode = mode
        history = []
        # THE TWO MODES DIVERGE COMPLETELY HERE.
        if mode == "virtual":
            rec = state.compute_virtual(float(az or 0), float(el or 0))
            reference = angles_to_vector(float(az or 0), float(el or 0))
        else:
            rec = state.latest()
            reference = state.stream_ctx.reference_vector if state.stream_ctx else None
            history = state.history(400)

        # THE EMPTY STATE. Real mode before any telemetry has arrived. Every
        # figure is built empty rather than skipped, because Dash requires all
        # eight Outputs to receive a value on every run.
        if rec is None:
            return (_live_panel(None, mode), face_readings_figure({}),
                    weights_figure({}), srp_figure({}), cube_figure(),
                    _empty_ts("Sun vector"), _empty_ts("Validation"),
                    _conn_badge(state))

        # Convert the list of saturated face names into the face-keyed dict of
        # booleans that face_readings_figure wants for its red bars.
        saturated = {f: f in rec.saturated_faces for f in FACE_NAMES}
        faces_fig = face_readings_figure(rec.photodiodes, saturated)
        wfig = weights_figure(rec.weights)
        sfig = srp_figure(rec.srp_forces)
        cube = cube_figure(rec.sun_vector, reference)
        ts_vec, ts_met = _timeseries_figs(history)
        return (_live_panel(rec, mode), faces_fig, wfig, sfig, cube,
                ts_vec, ts_met, _conn_badge(state))

    # ---- history page ----
    @app.callback(
        Output("sessions-table", "children"), Output("session-dd", "options"),
        Input("refresh-sessions", "n_clicks"), Input("url", "pathname"))
    # LISTING RECORDED SESSIONS.
    #
    # TWO INPUTS, so this fires either when Refresh is clicked or when the user
    # NAVIGATES to a page. The pathname input means arriving at History
    # automatically shows a current list, without the user having to click
    # Refresh first to see anything.
    def _sessions(_n, pathname):
        # Reads the session directories from disk (see store/query.py), which is
        # robust to damaged or interrupted sessions.
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
                html.Td(s.session_id), html.Td(s.started_at or "-"),
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
    # LOADING RECORDS FROM ONE SESSION.
    #
    # One Input (the Load button) and three States (the dropdown and the two
    # range boxes), so nothing is read from disk until the user actually asks.
    # Making the dropdown an Input would reload the file on every selection
    # change, which for a large session would stall the page.
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
        # ONLY THE FIRST 500 ROWS ARE RENDERED. An hour-long session holds tens
        # of thousands of records, and building that many HTML rows would freeze
        # the browser. The count and the note below make the truncation visible,
        # and the CSV export is the path to the complete data.
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
    # THE CSV DOWNLOAD.
    def _export(_n, session_id, start_ms, end_ms):
        if not session_id:
            return None
        # A TEMPORARY FILE, because export_session_csv writes to a path while
        # the browser needs bytes to download. The file is written here, then
        # handed to dcc.send_file.
        #
        # delete=False is REQUIRED: by default Python deletes the file when it
        # is closed, and send_file needs it to still exist afterwards. The
        # operating system cleans up its temp directory later.
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.close()
        query.export_session_csv(
            session_id, tmp.name,
            int(start_ms) if start_ms is not None else None,
            int(end_ms) if end_ms is not None else None,
            base_dir=state.session.base_dir)
        return dcc.send_file(tmp.name, filename=f"{session_id}.csv")


# --- Find this Mac's address on the local network ---
#
# RETURNS
#   the IP the Arduino should send to (e.g. "172.20.10.2" on an iPhone
#   hotspot), or None if it cannot be worked out.
#
# The Arduino cannot use 127.0.0.1: on the Arduino that means "the Arduino
# itself". It needs the Mac's address on the hotspot, and that address can
# change every time the Mac joins, so printing it at startup saves a trip to
# System Settings. Connecting a UDP socket sends no packet; it only asks the OS
# which network interface it would use, and that interface's address is ours.
def _lan_ip() -> Optional[str]:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


# --- Launch the dashboard ---
#
# PARAMETERS
#   argv - command-line arguments; None means "read the real command line".
#          Tests can pass a list instead.
# RETURNS
#   None, and not until the server stops.
#
# This is what `python -m tetralux.dashboard` runs. With no flags it behaves
# exactly as before: Virtual mode, no hardware needed. The flags connect REAL
# hardware straight into this dashboard, so Real mode shows the Arduino's data.
# (groundstation.py is a separate program with its own memory; frames it
# receives never reach this page.)
def main(argv: Optional[list] = None) -> None:
    """Launch the ground-station dashboard (Virtual mode by default)."""
    import argparse
    import logging
    import threading

    from tetralux.store import make_online_store

    ap = argparse.ArgumentParser(description="Tetralux-1 ground-station dashboard")
    ap.add_argument("--port", type=int, default=8050, help="dashboard web page port")
    ap.add_argument("--ingest-port", type=int, default=None,
                    help="also receive the Arduino's WiFi POSTs on this port "
                         "(use SERVER_PORT from secrets.h, normally 8000)")
    ap.add_argument("--serial", default=None,
                    help="also read the Arduino over USB serial, e.g. "
                         "/dev/tty.usbmodem14101 (use this OR --ingest-port)")
    ap.add_argument("--record", action="store_true",
                    help="log every Real-mode frame to data/logs (off by default)")
    args = ap.parse_args(argv)

    # Flask prints one line per request, and the page refreshes every 0.7 s,
    # so the terminal fills with 200s. ERROR keeps real problems visible.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # Make an AppState with a Firebase store if one is configured.
    state = AppState(online_store=make_online_store())

    # HARDWARE LINKS. Both hand each raw JSON line to state.feed_raw, the same
    # inbox the "Simulated device feed" uses, so everything downstream is the
    # code the tests already exercise. start_real() begins processing right
    # away; otherwise frames would pile up in the queue until someone clicked
    # "Real" and then replay minutes of stale data.
    if args.ingest_port is not None or args.serial:
        state.start_real()
    if args.ingest_port is not None:
        from tetralux.ingest.http_server import run_ingest_server

        # Same pattern as calibration_tool.py: the HTTP server blocks forever,
        # so it gets its own daemon thread. It listens on 0.0.0.0 (every
        # network interface) so the Arduino on the hotspot can reach it.
        threading.Thread(
            target=run_ingest_server,
            kwargs={"on_frame": state.feed_raw, "port": args.ingest_port,
                    "monitor": state.monitor},
            daemon=True,
        ).start()
        ip = _lan_ip() or "<run: ipconfig getifaddr en0>"
        print(f"[tetralux] listening for the Arduino on port {args.ingest_port}")
        print(f"[tetralux] secrets.h should say: SERVER_IP \"{ip}\", "
              f"SERVER_PORT {args.ingest_port}")
    if args.serial:
        from tetralux.ingest.serial_reader import SerialReader

        SerialReader(state.feed_raw, args.serial).start()
        print(f"[tetralux] reading the Arduino over serial on {args.serial}")

    if args.record:
        info = state.session.start()
        print(f"[tetralux] recording session {info.session_id}")

    try:
        create_app(state).run(port=args.port)
    finally:
        # Closes the session file cleanly on Ctrl+C. A no-op if not recording.
        state.session.stop()


# The entry-point guard (see groundstation.py). Importing this module must not
# start a web server.
if __name__ == "__main__":
    main()
