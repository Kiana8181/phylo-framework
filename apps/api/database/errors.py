"""Telling "the database is away" from "this query is wrong".

The worker needs the difference. A query that fails is a fault in the run's
handling and ends the run with an error. A database that is restarting,
unreachable or dropping connections says nothing about the run at all: the
method job it is following keeps computing, and the right reaction is to wait
and carry on.
"""
from __future__ import annotations

import socket
import traceback
from typing import Optional

import asyncpg
from sqlalchemy import exc as sa_exc

# asyncpg errors that mean the server is not accepting or keeping connections.
_SERVER_AWAY = (
    asyncpg.exceptions.PostgresConnectionError,       # connection failure, does not exist, rejected, ...
    asyncpg.exceptions.CannotConnectNowError,         # "the database system is starting up / shutting down"
    asyncpg.exceptions.AdminShutdownError,
    asyncpg.exceptions.CrashShutdownError,
    asyncpg.exceptions.TooManyConnectionsError,
    asyncpg.exceptions.InterfaceError,                # "connection is closed"
)
# Plain network errors count only when they were raised inside the database
# driver: the same exception types also come from other things a worker talks to.
_NETWORK = (ConnectionError, socket.gaierror, TimeoutError)
_DRIVER_PATH_MARKERS = ("/asyncpg/", "/sqlalchemy/")
_MAX_CHAIN = 12


def _raised_in_driver(exc: BaseException) -> bool:
    return any(
        any(marker in frame.f_code.co_filename.replace("\\", "/") for marker in _DRIVER_PATH_MARKERS)
        for frame, _ in traceback.walk_tb(exc.__traceback__)
    )


def database_unavailable(exc: Optional[BaseException]) -> bool:
    """True when ``exc``, or what it was raised from, says the database could
    not be reached or dropped the connection."""
    seen = 0
    while exc is not None and seen < _MAX_CHAIN:
        if isinstance(exc, sa_exc.DBAPIError) and exc.connection_invalidated:
            return True
        if isinstance(exc, (sa_exc.InterfaceError, sa_exc.OperationalError)):
            return True
        if isinstance(exc, _SERVER_AWAY):
            return True
        if isinstance(exc, _NETWORK) and _raised_in_driver(exc):
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False
