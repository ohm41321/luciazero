"""Luciazero Agent Bus daemon package (companion to ``luciazero``).

The durable SQLite store and state machine (M1), the Streamable HTTP MCP
control plane (M2), and the worktree-isolation, approval-provenance and
redaction rules (M3). See ``docs/agent-bus-roadmap.md`` and the ADRs under
``docs/adr/``.
"""

from __future__ import annotations

import sys

MIN_PYTHON = (3, 10)
if sys.version_info < MIN_PYTHON:  # pragma: no cover - exercised only on old interpreters
    raise SystemExit(
        f"luciazero-agentd needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+; "
        f"found {sys.version.split()[0]}"
    )

from .redact import Redactor  # noqa: E402 - version guard must run first
from .store import (  # noqa: E402
    SENSITIVE_OPERATIONS,
    ApprovalRefused,
    ConflictError,
    IdempotencyConflict,
    NotFound,
    Store,
    StoreError,
    UnsafeReference,
    ValidationError,
    WorktreeMismatch,
)

__all__ = [
    "SENSITIVE_OPERATIONS",
    "ApprovalRefused",
    "ConflictError",
    "IdempotencyConflict",
    "NotFound",
    "Redactor",
    "Store",
    "StoreError",
    "UnsafeReference",
    "ValidationError",
    "WorktreeMismatch",
]
__version__ = "0.1.0a0"
