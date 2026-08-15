# Experiment log

## 2026-08-15 — a core fast tier cuts intermediate verification latency

change: added `./test.sh --fast`, stopping after doctrine, hook/report,
Relay, bisect, learning-layer, and benchmark-integrity checks; the default and
`--full` continue through eval, packaging, and install-cycle coverage.

baseline: pre-change full 29.02s, 26.97s, 27.12s (mean 27.70s) | result:
final fast 13.02s, 12.83s, 13.04s (mean 12.96s).

verdict: WIN 53.2% — the improvement exceeds the predeclared 50% threshold
and the measured ranges do not overlap.

cost note: 10 instrumented Bash pre/post hook pairs took 2.00s on the same
machine (~200ms per Bash call). Telemetry is therefore opt-in and its own hook
time remains part of the report's non-Bash remainder.

decision: kept — use fast or a narrower relevant check during iteration and
reserve full verification for CI and closeout.

## 2026-08-12 — harder tasks may discriminate capable coding agents

change: added `archive-security`, `schema-migration`, and `paginated-sync`, each
with offline reference/project/anti-gamed proofs; no model inference was run.

baseline: on five valid paired legacy tasks, Terra/medium passed 5/5 in both
arms (28/28 criteria each; observed 0pp).

result: not measured yet; the three candidates pass grader validation but have
no behavioral samples.

verdict: PENDING — do not claim improved discrimination before the six-run
Terra screen (one run per arm per new task).

decision: kept as candidate fixtures because their graders falsify unfixed and
test-free solutions offline; return to task design if the screen again reaches
the ceiling.

## 2026-08-13 — Relay transfer has a falsifiable offline contract

change: added `relay-transfer`, a six-criterion protocol task with deterministic
Git setup, canonical JSON plus generated Markdown, and generic-prose and
stale-fingerprint cheat overlays.

baseline: no transfer task; Relay's command lifecycle had unit coverage but no
eval-shaped artifact grader. | result: reference 6/6, untouched project 1/6,
generic Markdown 1/6, stale fingerprint 5/6.

verdict: WIN — the grader separates a complete current relay from missing and
stale transfers without model inference.

decision: kept as a candidate behavioral task. These offline scores validate
the harness only; do not quote them as model uplift.
