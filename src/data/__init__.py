"""Data layer for AROS.

This package centralizes everything related to market data:

* ``models``     - SQLAlchemy ORM models (stocks, daily bars, sync state)
* ``provider``   - external data providers (AKShare) and column normalization
* ``manager``    - :class:`DataManager`, the *single* entry point for reading
                   and writing market data (project principle: DataManager 为
                   唯一数据入口)

All access to market data must go through :class:`DataManager`; nothing else
in the codebase should talk to AKShare or the database directly.
"""
