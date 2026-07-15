"""Research report rendering -- STUB (fills in Sprint 2.6).

Renders an experiment (metrics + benchmark comparison + walk-forward IS/OOS)
into a research report, reusing the presentation helpers from the 1.8/1.14
report layer rather than re-implementing rendering. 2.0 only reserves the module.
"""

from __future__ import annotations

from research.experiment import ExperimentResult


def render_experiment_report(result: ExperimentResult) -> str:
    raise NotImplementedError("research report rendering lands in Sprint 2.6")
