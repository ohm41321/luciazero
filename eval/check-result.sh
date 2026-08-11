#!/usr/bin/env bash
# Decides whether a finished `claude -p` invocation produced a genuinely
# completed agent run. Usage: check-result.sh <claude.log>
# Exit 0 = looks like a real run; exit 1 = INVALID, reason on stderr.
#
# Why this exists: the CLI can exit 0 AND report subtype "success" while the
# payload is an error — observed 2026-08-11 as {"subtype": "success",
# "result": "Not logged in · Please run /login", "is_error": true}. A naive
# exit-code-plus-subtype check books that as a valid arm and poisons the
# pass rates. run.sh calls this after every zero-exit invocation; test.sh
# proves each rejection and acceptance path against fixture logs.
set -euo pipefail
LOG="${1:?usage: check-result.sh <claude.log>}"
python3 - "${LOG}" <<'PY'
import json, sys
try:
    raw = open(sys.argv[1]).read()
except OSError as e:
    sys.exit(f"INVALID: cannot read result log ({e})")
try:
    d = json.loads(raw)
except ValueError:
    # plain-text output (an EVAL_CLAUDE_ARGS override without
    # --output-format json): no structured signal to refute the run
    sys.exit(0)
if not isinstance(d, dict):
    sys.exit("INVALID: result log is JSON but not an object")
def clip(v):
    return str(v)[:120]
if d.get("is_error") is True:
    sys.exit(f"INVALID: is_error=true in result: {clip(d.get('result'))}")
if d.get("terminal_reason") == "api_error":
    sys.exit(f"INVALID: terminal_reason=api_error: {clip(d.get('result'))}")
res = d.get("result")
if isinstance(res, str) and "Not logged in" in res:
    sys.exit(f"INVALID: {clip(res)}")
sys.exit(0)
PY
