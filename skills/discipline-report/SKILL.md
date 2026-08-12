---
name: discipline-report
description: Analyze Luciazero's local stop-outcome log for evidence-backed verification habits. Use when the user asks for discipline stats, recurring nudge or strict-block patterns, a local behavior report, or runs `npx luciazero discipline`; supports time/project filters and machine-readable JSON.
---

# Discipline report — turn local outcomes into evidence

Run:

```bash
npx luciazero discipline [--days N] [--project PATH_OR_ID] [--json]
```

The report reads `luciazero-stats.log` from the Claude config directory by default. It accepts current schema-versioned JSON lines and legacy space-delimited records, ignores malformed lines without failing, and never sends data over the network.

Treat recorded outcomes as observations, not causes. A `nudge` proves an edit lacked a recognized later verify run; it does not prove why. A `strict-block` proves the configured strict command was red. Recommendations derived from patterns must say `likely` unless the log directly records the cause.

Use `--project .` to filter by the current repository's privacy-preserving project hash, or `--project <display-name-or-id>` for another entry. Use `--json` when feeding a dashboard or `/retro`.
