#!/usr/bin/env bash
# Decides whether a finished agent invocation produced a genuinely completed
# run. Usage: check-result.sh [--provider claude|codex] <agent.log>
# Exit 0 = looks like a real run; exit 1 = INVALID, reason on stderr.
#
# Why this exists: the CLI can exit 0 AND report subtype "success" while the
# payload is an error — observed 2026-08-11 as {"subtype": "success",
# "result": "Not logged in · Please run /login", "is_error": true}. A naive
# exit-code-plus-subtype check books that as a valid arm and poisons the
# pass rates. run.sh calls this after every zero-exit invocation; test.sh
# proves each rejection and acceptance path against fixture logs.
set -euo pipefail
PROVIDER=claude
if [ "${1:-}" = --provider ]; then
  PROVIDER="${2:?--provider needs claude or codex}"
  shift 2
fi
case "${PROVIDER}" in
  claude|codex) ;;
  *) echo "usage: check-result.sh [--provider claude|codex] <agent.log>" >&2; exit 2 ;;
esac
LOG="${1:?usage: check-result.sh [--provider claude|codex] <agent.log>}"
python3 - "${PROVIDER}" "${LOG}" <<'PY'
import json, sys
provider, path = sys.argv[1:3]
try:
    raw = open(path).read()
except OSError as e:
    sys.exit(f"INVALID: cannot read result log ({e})")

def clip(v):
    return str(v)[:120]

if provider == "codex":
    completed = 0
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            sys.exit(f"INVALID: malformed Codex JSONL at line {line_no}")
        if not isinstance(event, dict):
            sys.exit(f"INVALID: Codex event at line {line_no} is not an object")
        kind = event.get("type")
        if kind in ("turn.failed", "error"):
            reason = event.get("error") or event.get("message") or event
            sys.exit(f"INVALID: Codex {kind}: {clip(reason)}")
        if kind == "turn.completed":
            usage = event.get("usage")
            if not isinstance(usage, dict):
                sys.exit("INVALID: Codex turn.completed has no usage object")
            for field in ("input_tokens", "output_tokens"):
                value = usage.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    sys.exit(f"INVALID: Codex usage.{field} is not a non-negative integer")
            for field in ("cached_input_tokens", "reasoning_output_tokens"):
                if field not in usage:
                    continue
                value = usage[field]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    sys.exit(f"INVALID: Codex usage.{field} is not a non-negative integer")
            completed += 1
    if completed == 0:
        sys.exit("INVALID: Codex log has no turn.completed event")
    sys.exit(0)

try:
    d = json.loads(raw)
except ValueError:
    # plain-text output (an EVAL_CLAUDE_ARGS override without
    # --output-format json): no structured signal to refute the run
    sys.exit(0)
if not isinstance(d, dict):
    sys.exit("INVALID: result log is JSON but not an object")
if d.get("is_error") is True:
    sys.exit(f"INVALID: is_error=true in result: {clip(d.get('result'))}")
if d.get("terminal_reason") == "api_error":
    sys.exit(f"INVALID: terminal_reason=api_error: {clip(d.get('result'))}")
res = d.get("result")
if isinstance(res, str) and "Not logged in" in res:
    sys.exit(f"INVALID: {clip(res)}")
sys.exit(0)
PY
