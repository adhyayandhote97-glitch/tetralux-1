"""Phase 5: dashboard — live sun vector, fault health, and telemetry replay.

Only the pure replay layer is exported here so importing ``tetralux.dashboard``
never requires Dash/Plotly. The interactive app lives in
:mod:`tetralux.dashboard.app` (needs the ``dashboard`` extra) and the figure
builders in :mod:`tetralux.dashboard.figures`.
"""

from tetralux.dashboard.replay import ReplayFrame, build_replay

__all__ = ["ReplayFrame", "build_replay"]
