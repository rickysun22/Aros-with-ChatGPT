"""SQLite schema migration: reconcile model-defined columns with the live DB.

SQLite's ``CREATE TABLE IF NOT EXISTS`` (used by ``Base.metadata.create_all``)
never *alters* an already-existing table, so columns added to ORM models after
the table was first created silently drift from the DB. This script closes that
gap: for every model table it compares the ORM column set against the actual
table and issues ``ALTER TABLE ... ADD COLUMN`` for anything missing.

It is intentionally conservative:
- Never drops or renames columns (data-preserving).
- Skips new tables (those are handled by ``create_all``); only fills missing
  columns on existing tables.
- Compiles types with the live SQLite dialect.

Usage:
    PYTHONPATH=src python scripts/migrate_schema.py [--db data/aros.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import importlib

from sqlalchemy import create_engine, inspect, text


def _load_base() -> object:
    """Import every model module so all tables register on ``Base.metadata``."""
    # Explicit, deterministic lookup first.
    try:
        from core.database import Base  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            from research.models import Base  # type: ignore
        except Exception:  # noqa: BLE001
            Base = None
    # Side-effect imports: registering every model on Base.metadata.
    for mod in [
        "research.models",
        "research.kb",
        "research.calibration",
        "research.papertrade",
        "research.entry",
        "research.exit",
        "research.feedback",
        "research.consensus",
        "research.experiment",
        "research.market_regime",
        "research.validation",
    ]:
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001 - best-effort import
            continue
    if Base is None or not hasattr(Base, "metadata"):
        raise RuntimeError("Could not locate SQLAlchemy Base")
    return Base


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/aros.db", help="path to the sqlite DB")
    ap.add_argument("--dry-run", action="store_true", help="only report, don't alter")
    args = ap.parse_args()

    base = _load_base()
    eng = create_engine(f"sqlite:///{args.db}")
    insp = inspect(eng)
    md = base.metadata

    applied = 0
    with eng.begin() as conn:
        for tname, table in sorted(md.tables.items()):
            if tname.startswith("sqlite_"):
                continue
            if not insp.has_table(tname):
                print(f"[skip] new table {tname} (let create_all handle it)")
                continue
            db_cols = {c["name"] for c in insp.get_columns(tname)}
            for col in table.columns:
                if col.name in db_cols:
                    continue
                ddl_type = col.type.compile(dialect=eng.dialect)
                parts = [f'ALTER TABLE "{tname}" ADD COLUMN "{col.name}" {ddl_type}']
                if not col.nullable:
                    parts.append("NOT NULL")
                    if col.default is not None:
                        parts.append(f"DEFAULT {col.default}")
                stmt = " ".join(parts)
                print(f"[migrate] {tname}.{col.name}: {stmt}")
                if not args.dry_run:
                    conn.execute(text(stmt))
                applied += 1

    print(f"Done. columns added: {applied}" + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
