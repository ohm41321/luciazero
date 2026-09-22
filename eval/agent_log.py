#!/usr/bin/env python3
"""Read the provider log of one eval invocation.

The Claude CLI writes its result object in two shapes: `--output-format json`
prints the object alone, `--output-format stream-json` prints one event per
line (system init, assistant and user messages, then the result object as the
last event, `"type": "result"`). check-result.sh and run.sh both need that
object, so the shape detection lives here once.
"""

from __future__ import annotations

import json
from typing import Any


def read_events(text: str) -> list[dict[str, Any]] | None:
    """Parse a JSONL log into its event objects; None when the text is not
    a stream.

    A stream is any text with at least one line that is a JSON object with a
    `type`. Other lines — a warning the CLI printed on the same descriptor, a
    partial last line from a run killed mid-write — are skipped, not fatal:
    a check that turned "text" on one stray line would let an error result
    through as unrefuted plain output.
    """
    events = []
    typed = False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
            typed = typed or "type" in event
    return events if typed else None


def load_claude_log(text: str) -> tuple[str, Any]:
    """Classify a Claude log: ("object", result), ("stream", events) or
    ("text", None). A JSON object alone is the legacy single-result shape."""
    try:
        whole = json.loads(text)
    except ValueError:
        events = read_events(text)
        if events is None:
            return "text", None
        return "stream", events
    if isinstance(whole, dict) and whole.get("type") not in (None, "result"):
        # a one-line stream: the run died after its first event
        return "stream", [whole]
    return "object", whole


def stream_result(events: list[Any]) -> dict[str, Any] | None:
    """The final result object of a stream, or None when the run never
    reached one."""
    for event in reversed(events):
        if isinstance(event, dict) and event.get("type") == "result":
            return event
    return None
