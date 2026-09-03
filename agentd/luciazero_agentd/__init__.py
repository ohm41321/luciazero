"""Luciazero Agent Bus daemon package (companion to ``luciazero``).

M1 scope: the durable SQLite store and its state machine. See
``docs/agent-bus-roadmap.md`` and ``docs/adr/0002-agent-bus-packaging-and-language.md``.
"""

from __future__ import annotations

import sys

MIN_PYTHON = (3, 10)
if sys.version_info < MIN_PYTHON:  # pragma: no cover - exercised only on old interpreters
    raise SystemExit(
        f"luciazero-agentd needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+; "
        f"found {sys.version.split()[0]}"
    )

from .store import (  # noqa: E402 - version guard must run first
    ConflictError,
    IdempotencyConflict,
    NotFound,
    Store,
    StoreError,
    ValidationError,
)

__all__ = [
    "ConflictError",
    "IdempotencyConflict",
    "NotFound",
    "Store",
    "StoreError",
    "ValidationError",
]
__version__ = "0.1.0a0"
