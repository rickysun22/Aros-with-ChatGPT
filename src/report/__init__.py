"""Report Engine for AROS (Sprint 1.8).

Public surface:
* ReportEngine - generate the daily A-share research report.
* DailyReport - structured report model (markdown / json renderable).
* ReportRow - one ranked candidate with its latest price snapshot.
"""

from .engine import DailyReport, ReportEngine, ReportRow

__all__ = [
    "ReportEngine",
    "DailyReport",
    "ReportRow",
]
