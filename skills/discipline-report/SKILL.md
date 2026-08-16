---
name: discipline-report
description: Analyze Luciazero stop-outcome logs for evidence-backed verification habits. Use for discipline stats, recurring nudge or strict-block patterns, local behavior reports, or machine-readable JSON.
---

# Discipline report — turn local outcomes into evidence

Resolve the first available local CLI:

```bash
luciazero discipline [--days N] [--project PATH_OR_ID] [--json]
node <this-skill-dir>/../../bin/luciazero.js discipline [--days N] [--project PATH_OR_ID] [--json]
```

Use the first command only when `luciazero` is on PATH; use the second from a source checkout or npm package. If neither local form exists, report that the discipline report is unavailable offline instead of silently invoking `npx`. Use `npx` only when package resolution is explicitly allowed.

The report reads `luciazero-stats.log` from the Claude config directory by default. It accepts current schema-versioned JSON lines and legacy space-delimited records, ignores malformed lines without failing, and never sends data over the network. New enforcement-pack installs also summarize measured turn/Bash wall-clock milliseconds and Bash, verify, and model/user skill invocation counts. Parallel Bash intervals are merged before subtraction. These are aggregates: raw commands and skill names are never persisted.

Treat recorded outcomes as observations, not causes. A `nudge` proves an edit lacked a recognized later verify run; it does not prove why. A `strict-block` proves the configured strict command was red. Recommendations derived from patterns must say `likely` unless the log directly records the cause.

Latency telemetry separates observed Bash time from the rest of the measured turn. The non-Bash remainder can include model reasoning, non-Bash tools, hook overhead, and harness scheduling, so do not label it as model latency without another measurement.

Use `--project .` to filter by the current repository's privacy-preserving project hash, or `--project <display-name-or-id>` for another entry. Use `--json` when feeding a dashboard or `/retro`.
