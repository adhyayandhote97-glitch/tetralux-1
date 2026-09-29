"""Dashboard package.

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `dashboard/` as a package. That is all it does, and the emptiness is
deliberate.

WHY THIS ONE RE-EXPORTS NOTHING, unlike most others in this project. Importing
app.py pulls in Dash and Plotly, which are optional dependencies installed only
with the `dashboard` extra. If this file imported them eagerly, then merely
touching `tetralux.dashboard` would fail on a machine without them, and worse,
`from tetralux.dashboard import units` would break even though units.py itself
needs nothing beyond the standard library.

Leaving it empty means each module is imported only when actually wanted. That
is why test_dashboard_v2.py can test units.py with no Dash installed, and why
the figure tests skip themselves cleanly when Plotly is absent.

WHAT IS IN HERE
    units.py    the units registry; every displayed value carries its unit
    figures.py  the Plotly chart builders
    state.py    everything the dashboard remembers between refreshes
    app.py      the page layout and the Dash callbacks
    __main__.py the entry point for `python -m tetralux.dashboard`

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
"""
