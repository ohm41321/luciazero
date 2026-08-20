---
name: discipline-report
description: Analyze Luciazero stop-outcome logs for evidence-backed verification habits. Use for discipline stats, recurring nudge or strict-block patterns, local behavior reports, or machine-readable JSON.
---

# Discipline report

Resolve the first available local CLI:

```bash
luciazero discipline [--days N] [--project PATH_OR_ID] [--json]
node <this-skill-dir>/../../bin/luciazero.js discipline [--days N] [--project PATH_OR_ID] [--json]
```

Use the first only when on PATH; use the second from a checkout/package. If
neither local form exists, report unavailable offline. Use `npx` only when
package resolution is explicitly allowed.

The command reads `luciazero-stats.log`, accepts current
schema-versioned JSON lines and legacy space-delimited records, ignores malformed
lines without failing, and never sends data over the network. Telemetry includes
turn/Bash wall time plus Bash, verify, and skill counts; parallel Bash intervals
are merged. Raw commands and skill names are never persisted.

Treat recorded outcomes as observations, not causes. `nudge` means no recognized
later verify; `strict-block` means its strict command was red. Explanations must
say `likely` unless the log records the cause.

Non-Bash remainder includes tools, hooks, scheduling, and reasoning; do not
label it as model latency without another measurement.

Use `--project .` for this repo or another name/id as needed. Use `--json` for
dashboards or `/retro`.
