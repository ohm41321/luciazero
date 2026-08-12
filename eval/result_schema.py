#!/usr/bin/env python3
"""Strict validation shared by eval reporting and published evidence."""

from __future__ import annotations

import datetime
import math
import re
from typing import Any


SUPPORTED_SCHEMAS = {1, 2}
SUPPORTED_ARMS = {"doctrine", "lessons", "bare"}
SUPPORTED_PROVIDERS = {"claude", "codex"}
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
SCORE = re.compile(r"^(0|[1-9][0-9]*)/(0|[1-9][0-9]*)$")


def _fail(source: str, message: str) -> None:
    raise ValueError(f"{source}: {message}")


def _nonempty_string(row: dict[str, Any], field: str, source: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        _fail(source, f"{field} is not a non-empty string")
    return value


def _optional_string(row: dict[str, Any], field: str, source: str) -> Any:
    value = row.get(field)
    if value is not None and not isinstance(value, str):
        _fail(source, f"{field} is not string or null")
    return value


def _boolean(row: dict[str, Any], field: str, source: str, default: Any = None) -> bool:
    if field not in row:
        if default is not None:
            return default
        _fail(source, f"{field} is missing")
    value = row[field]
    if not isinstance(value, bool):
        _fail(source, f"{field} is not boolean")
    return value


def _nonnegative_number(value: Any, field: str, source: str, *, integer: bool) -> None:
    expected = int if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, expected):
        _fail(source, f"{field} is not a non-negative {'integer' if integer else 'number'} or null")
    if value < 0 or (isinstance(value, float) and not math.isfinite(value)):
        _fail(source, f"{field} is not a non-negative {'integer' if integer else 'number'} or null")


def _timestamp(row: dict[str, Any], field: str, source: str) -> str:
    value = _nonempty_string(row, field, source)
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        _fail(source, f"{field} is not an ISO-8601 timestamp ({exc})")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(source, f"{field} must include a timezone")
    return value


def validate_result_row(raw: Any, *, source: str = "result row") -> dict[str, Any]:
    """Validate a schema-v1/v2 row and return a normalized shallow copy."""
    if not isinstance(raw, dict):
        _fail(source, "row is not an object")
    row = dict(raw)

    schema = row.get("result_schema", 1)
    if isinstance(schema, bool) or not isinstance(schema, int) or schema not in SUPPORTED_SCHEMAS:
        _fail(source, f"unsupported result_schema {schema!r}")
    row["result_schema"] = schema

    task = _nonempty_string(row, "task", source)
    arm = _nonempty_string(row, "arm", source)
    if arm not in SUPPORTED_ARMS:
        _fail(source, f"unsupported arm {arm!r}")
    run = row.get("run")
    if isinstance(run, bool) or not isinstance(run, int) or run < 1:
        _fail(source, "run is not a positive integer")

    invalid = _boolean(row, "invalid", source)
    criteria = row.get("criteria")
    if not isinstance(criteria, dict):
        _fail(source, "criteria is not an object")
    for criterion, value in criteria.items():
        if not isinstance(criterion, str) or not criterion:
            _fail(source, "criteria names must be non-empty strings")
        if not isinstance(value, bool):
            _fail(source, f"criterion {criterion!r} is not boolean")

    score = row.get("score")
    if score is not None:
        if not isinstance(score, str) or not SCORE.fullmatch(score):
            _fail(source, "score is not N/N or null")
        wins, total = (int(value) for value in score.split("/"))
        if total != len(criteria) or wins != sum(criteria.values()):
            _fail(source, "score does not match criteria")
    if invalid:
        if criteria or score is not None:
            _fail(source, "invalid rows must have empty criteria and null score")
    elif not criteria or score is None:
        _fail(source, "valid rows need non-empty criteria and a score")

    if "duration_s" not in row:
        _fail(source, "duration_s is missing")
    _nonnegative_number(row["duration_s"], "duration_s", source, integer=False)
    for field in (
        "tokens_in", "tokens_out", "cached_input_tokens",
        "reasoning_output_tokens", "num_turns",
    ):
        if row.get(field) is not None:
            _nonnegative_number(row[field], field, source, integer=True)
    if row.get("cost_usd") is not None:
        _nonnegative_number(row["cost_usd"], "cost_usd", source, integer=False)

    provider = row.get("provider", "claude")
    if not isinstance(provider, str) or provider not in SUPPORTED_PROVIDERS:
        _fail(source, f"unsupported provider {provider!r}")
    row["provider"] = provider
    for field in (
        "model", "requested_model", "reasoning_effort", "cli_version",
        "campaign_id", "pair_id", "invocation_id", "timestamp",
        "campaign_started_at", "seed", "repository_commit", "task_sha256",
        "prompt_sha256", "system", "architecture", "runner_profile",
        "invalid_reason",
    ):
        _optional_string(row, field, source)
    row["offline"] = _boolean(row, "offline", source, default=False)
    row["repository_dirty"] = _boolean(row, "repository_dirty", source, default=False)

    arm_order = row.get("arm_order")
    if arm_order is not None:
        if (not isinstance(arm_order, list)
                or any(not isinstance(value, str) or not value for value in arm_order)
                or len(arm_order) != len(set(arm_order))):
            _fail(source, "arm_order is not a unique non-empty string list or null")
        if any(value not in SUPPORTED_ARMS for value in arm_order):
            _fail(source, "arm_order contains an unsupported arm")

    if schema == 2:
        campaign_id = _nonempty_string(row, "campaign_id", source)
        pair_id = _nonempty_string(row, "pair_id", source)
        invocation_id = _nonempty_string(row, "invocation_id", source)
        _timestamp(row, "timestamp", source)
        _timestamp(row, "campaign_started_at", source)
        _nonempty_string(row, "seed", source)
        commit = _nonempty_string(row, "repository_commit", source)
        _boolean(row, "repository_dirty", source)
        _boolean(row, "offline", source)
        for field in ("task_sha256", "prompt_sha256"):
            value = _nonempty_string(row, field, source)
            if not HEX_64.fullmatch(value):
                _fail(source, f"{field} is not a lowercase SHA-256 digest")
        for field in ("system", "architecture", "runner_profile"):
            _nonempty_string(row, field, source)
        if not row["offline"]:
            _nonempty_string(row, "cli_version", source)
        if commit == "unknown" and not (row["offline"] or row["repository_dirty"]):
            _fail(source, "clean real rows require a known repository_commit")
        if arm_order is None or arm not in arm_order:
            _fail(source, "arm_order is missing or does not contain arm")
        expected_pair = f"{campaign_id}/{task}/{run}"
        if pair_id != expected_pair:
            _fail(source, f"pair_id does not equal {expected_pair!r}")
        if invocation_id != f"{pair_id}/{arm}":
            _fail(source, "invocation_id does not equal pair_id/arm")
        if provider == "codex":
            model = _nonempty_string(row, "model", source)
            requested_model = _nonempty_string(row, "requested_model", source)
            if model != requested_model:
                _fail(source, "Codex model does not match requested_model")
            _nonempty_string(row, "reasoning_effort", source)

    return row
