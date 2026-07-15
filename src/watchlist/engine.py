"""WatchlistEngine - persist and track the daily ranking of watched stocks.

Sprint 1.9 builds on top of RankingEngine (Sprint 1.7) and the shared database
layer (Sprint 1.1). Each day we snapshot the full cross-sectional rank of every
watched instrument (including those that fall out of the Top-N) into the
``ranking_points`` table, then derive day-over-day deltas: new entries, drops,
rank/score moves. ``deltas`` is a pure read of stored history -- no network, no
look-ahead.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.config import RankingConfig
from core.database import Base, get_engine, get_sessionmaker
from ranking.engine import SCORE_PREFIX, RankingEngine
from watchlist.models import RankingPoint, WatchlistItem

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "new": "新进",
    "dropped": "掉出",
    "up": "上升",
    "down": "下降",
    "steady": "持平",
    "no_data": "无数据",
}


@dataclass
class WatchlistMember:
    """One watched instrument's current standing vs the previous snapshot."""

    code: str
    rank: int | None
    prev_rank: int | None
    rank_change: int | None
    composite_score: float | None
    prev_score: float | None
    score_change: float | None
    status: str  # new | dropped | up | down | steady | no_data
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WatchlistDigest:
    """The watchlist tracking report (metadata + per-member deltas)."""

    as_of: str
    prev_as_of: str | None
    generated_at: str
    members: list[WatchlistMember] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "prev_as_of": self.prev_as_of,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "members": [m.to_dict() for m in self.members],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self, alert_rank_jump: int = 5) -> str:
        lines: list[str] = []
        lines.append("# AROS 自选股追踪日报")
        lines.append("")
        lines.append(f"- 截面日期: {self.as_of}")
        cmp = self.prev_as_of if self.prev_as_of else "-"
        lines.append(f"- 对比截面: {cmp}")
        s = self.summary
        lines.append(
            f"- 汇总: 新进 {s.get('new', 0)} / 掉出 {s.get('dropped', 0)} / "
            f"上升 {s.get('up', 0)} / 下降 {s.get('down', 0)} / "
            f"持平 {s.get('steady', 0)} / 无数据 {s.get('no_data', 0)}"
        )
        lines.append("")
        if not self.members:
            lines.append("> 关注池为空或无快照。")
            return "\n".join(lines)

        lines.append("## 变动明细")
        lines.append("")
        header = ["代码", "当前排名", "排名变化", "综合分", "分数变化", "状态"]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for m in self.members:
            rank = str(m.rank) if m.rank is not None else "-"
            if m.rank_change is None:
                rc = "-"
            elif m.rank_change > 0:
                rc = f"▲{m.rank_change}"
            elif m.rank_change < 0:
                rc = f"▼{-m.rank_change}"
            else:
                rc = "—"
            score = f"{m.composite_score:.4f}" if m.composite_score is not None else "-"
            if m.score_change is None:
                sc = "-"
            else:
                sc = f"{m.score_change:+.4f}"
            label = STATUS_LABELS.get(m.status, m.status)
            if (
                m.status in ("up", "down")
                and m.rank_change is not None
                and abs(m.rank_change) >= alert_rank_jump
            ):
                label += " (显著)"
            lines.append(f"| {m.code} | {rank} | {rc} | {score} | {sc} | {label} |")
        return "\n".join(lines)


def _classify(
    cur: RankingPoint | None, prev: RankingPoint | None
) -> tuple[str, int | None, float | None]:
    """Return (status, rank_change, score_change) for one member."""
    if cur is None:
        return "dropped", None, None
    if prev is None:
        return "new", None, None
    rank_change: int | None = None
    if cur.rank is not None and prev.rank is not None:
        rank_change = prev.rank - cur.rank  # +ve => moved up
    elif cur.rank is not None and prev.rank is None:
        return "new", None, None
    if cur.rank is None:
        return "no_data", None, None
    if rank_change is None:
        return "no_data", None, None
    if rank_change > 0:
        status = "up"
    elif rank_change < 0:
        status = "down"
    else:
        status = "steady"
    score_change: float | None = None
    if cur.composite_score is not None and prev.composite_score is not None:
        score_change = cur.composite_score - prev.composite_score
    return status, rank_change, score_change


class WatchlistEngine:
    """Persist and track the daily ranking of a watchlist of instruments."""

    def __init__(
        self,
        ranking_engine: RankingEngine,
        config: Any,
        session: Session | None = None,
    ) -> None:
        self.ranking_engine = ranking_engine
        self.config = config
        if session is None:
            engine = get_engine()
            Base.metadata.create_all(engine)
            self.session = get_sessionmaker(engine)()
        else:
            self.session = session

    # ------------------------------------------------------------------ #
    # Membership
    # ------------------------------------------------------------------ #
    def add(self, code: str, note: str | None = None) -> WatchlistItem:
        item = self.session.get(WatchlistItem, code)
        if item is None:
            item = WatchlistItem(code=code, note=note)
            self.session.add(item)
        else:
            item.removed_at = None
            item.added_at = datetime.now()
            if note is not None:
                item.note = note
        self.session.commit()
        return item

    def remove(self, code: str) -> WatchlistItem | None:
        item = self.session.get(WatchlistItem, code)
        if item is None:
            return None
        item.removed_at = datetime.now()
        self.session.commit()
        return item

    def list_active(self) -> list[str]:
        rows = (
            self.session.query(WatchlistItem)
            .filter(WatchlistItem.removed_at.is_(None))
            .order_by(WatchlistItem.code)
            .all()
        )
        return [r.code for r in rows]

    def is_member(self, code: str) -> bool:
        item = self.session.get(WatchlistItem, code)
        return item is not None and item.removed_at is None

    # ------------------------------------------------------------------ #
    # Snapshot (rank + persist)
    # ------------------------------------------------------------------ #
    def _upsert_point(
        self,
        as_of: date,
        code: str,
        rank: int | None,
        composite_score: float | None,
        scores: dict[str, float] | None,
    ) -> None:
        existing = (
            self.session.query(RankingPoint)
            .filter(RankingPoint.as_of == as_of, RankingPoint.code == code)
            .one_or_none()
        )
        if existing is not None:
            existing.rank = rank
            existing.composite_score = composite_score
            existing.scores_json = scores
        else:
            self.session.add(
                RankingPoint(
                    as_of=as_of,
                    code=code,
                    rank=rank,
                    composite_score=composite_score,
                    scores_json=scores,
                )
            )

    def snapshot(
        self,
        as_of: str | None = None,
        codes: list[str] | None = None,
        data_manager: Any = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> WatchlistDigest:
        codes = list(codes) if codes is not None else self.list_active()
        if not codes:
            logger.warning("watchlist: snapshot called with empty universe")
            return WatchlistDigest(
                as_of=as_of or "-",
                prev_as_of=None,
                generated_at=datetime.now().isoformat(timespec="seconds"),
                members=[],
                summary={},
            )
        if data_manager is None:
            raise ValueError("snapshot requires a data_manager to compute ranks")

        rc = self.ranking_engine.config
        self.ranking_engine.config = RankingConfig(
            top_n=rc.top_n,
            as_of=as_of or rc.as_of,
            dimensions=rc.dimensions,
        )
        _ranking, scored = self.ranking_engine.rank_universe(
            list(codes), data_manager, start_date, end_date
        )

        if as_of:
            as_of_date = pd.Timestamp(as_of).date()
        elif not scored.empty and "date" in scored.columns:
            as_of_date = pd.to_datetime(scored["date"]).max().date()
        else:
            logger.warning("watchlist: cannot determine as_of; snapshot skipped")
            return WatchlistDigest(
                as_of=as_of or "-",
                prev_as_of=None,
                generated_at=datetime.now().isoformat(timespec="seconds"),
                members=[],
                summary={},
            )

        if scored.empty:
            full = pd.DataFrame(columns=["code", "composite_score"])
        else:
            full = scored.copy()
            full["rank"] = full["composite_score"].rank(ascending=False, method="first").astype(int)
        by_code: dict[str, tuple[int, float | None, dict[str, float]]] = {}
        for _, row in full.iterrows():
            code = str(row["code"])
            scores = {
                n: float(row[SCORE_PREFIX + n])
                for n in self.ranking_engine.names
                if SCORE_PREFIX + n in row and pd.notna(row[SCORE_PREFIX + n])
            }
            comp = float(row["composite_score"]) if pd.notna(row["composite_score"]) else None
            by_code[code] = (int(row["rank"]), comp, scores)

        for code in codes:
            if code in by_code:
                r, c, s = by_code[code]
                self._upsert_point(as_of_date, code, r, c, s)
            # Codes with no data at as_of are intentionally left without a
            # point, so a later deltas() reports them as "dropped" vs the
            # previous snapshot (rather than a null "no_data" row).
        self.session.commit()
        return self.deltas(as_of=str(as_of_date))

    # ------------------------------------------------------------------ #
    # History & deltas (read-only)
    # ------------------------------------------------------------------ #
    def history(self, code: str, limit: int = 20) -> list[RankingPoint]:
        return (
            self.session.query(RankingPoint)
            .filter(RankingPoint.code == code)
            .order_by(RankingPoint.as_of.desc())
            .limit(limit)
            .all()
        )

    def deltas(self, as_of: str | None = None) -> WatchlistDigest:
        dates = [
            d[0]
            for d in self.session.query(RankingPoint.as_of)
            .distinct()
            .order_by(RankingPoint.as_of)
            .all()
        ]
        if not dates:
            return WatchlistDigest(
                as_of=str(as_of) if as_of else "-",
                prev_as_of=None,
                generated_at=datetime.now().isoformat(timespec="seconds"),
                members=[],
                summary={},
            )
        str_dates = [str(d) for d in dates]
        if as_of and as_of in str_dates:
            current = dates[str_dates.index(as_of)]
        else:
            current = dates[-1]
        idx = dates.index(current)
        prev = dates[idx - 1] if idx > 0 else None

        cur_pts = {
            p.code: p
            for p in self.session.query(RankingPoint).filter(RankingPoint.as_of == current).all()
        }
        prev_pts = (
            {
                p.code: p
                for p in self.session.query(RankingPoint).filter(RankingPoint.as_of == prev).all()
            }
            if prev is not None
            else {}
        )
        note_by_code = {it.code: it.note for it in self.session.query(WatchlistItem).all()}

        members: list[WatchlistMember] = []
        for code in self.list_active():
            cur = cur_pts.get(code)
            prv = prev_pts.get(code)
            status, rank_change, score_change = _classify(cur, prv)
            members.append(
                WatchlistMember(
                    code=code,
                    rank=cur.rank if cur else None,
                    prev_rank=prv.rank if prv else None,
                    rank_change=rank_change,
                    composite_score=cur.composite_score if cur else None,
                    prev_score=prv.composite_score if prv else None,
                    score_change=score_change,
                    status=status,
                    note=note_by_code.get(code),
                )
            )
        # Order: active ranks first (None last), then by code.
        members.sort(
            key=lambda m: (
                m.rank is None,
                m.rank if m.rank is not None else 10**9,
                m.code,
            )
        )

        summary = {k: 0 for k in STATUS_LABELS}
        for m in members:
            summary[m.status] = summary.get(m.status, 0) + 1

        return WatchlistDigest(
            as_of=str(current),
            prev_as_of=str(prev) if prev is not None else None,
            generated_at=datetime.now().isoformat(timespec="seconds"),
            members=members,
            summary=summary,
        )
