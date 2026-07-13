"""Alternative data providers for AROS.

Each module here implements the :class:`data.provider.DataProvider` protocol so
it can be selected at runtime via ``config.data.source`` (e.g. ``akshare`` or
``astockdata``). Providers talk to external services directly and contain no
business logic -- all normalization lives here too.
"""
