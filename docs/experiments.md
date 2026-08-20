# Experiment log

## 2026-08-20 — cross-machine Relay schema 3

change: replaced artifact-declared trust with a sender/receiver protocol. The
sender now commits and pushes before drafting, live-checks the upstream branch,
publishes a commit-named transfer tag, and records sanitized repository locator,
head/base OIDs, and committed task files. The receiver supplies route, HEAD,
repository URL, and manifest digest from a trusted envelope. Relay never runs
artifact commands; the receiver reruns approved argv-safe evidence in its own
harness before explicitly asserting verification and consuming.

baseline: a clean branch clone inspected successfully, but the same commit in a
detached clone failed on `branch`; an empty cross-machine knowledge and
verification payload returned `([], [])`. Draft-before-push also made the
captured fingerprint stale after the required commit.

result: `./test.sh --fast` now drives sender → bare remote → fresh detached
clone → trusted inspect → receiver-harness verification → trusted consume. It also rejects
stale or deleted remote refs, URL rewrite poisoning, unrelated clone remotes,
route downgrade, artifact tampering, forged receipt shortcuts, empty
evidence/knowledge, unsafe paths, secret-shaped payloads, and excessive nesting.

verdict: WIN — the new fixture returns `PASS  fast checks green`; the old CLI
fails its first schema-3 `--base` acceptance step.

decision: kept schema 3 for cross-machine transfer. Schema 1/2 remains readable
for same-machine use; cross-machine receivers fail closed on legacy artifacts.

## 2026-08-20 — compact the remaining cataloged skills

change: compressed each remaining skill as a separate one-variable experiment.
Before each edit, `scripts/check-skill-prompts.py` fixed its frontmatter,
section-scoped behavioral clauses, code templates, and a 30% word-reduction
budget. Each baseline and result was measured three times with identical output.

| Skill | Baseline words / bytes | Result words / bytes | Verdict |
|---|---:|---:|---:|
| show | 788 / 5,043 | 457 / 3,000 | WIN 42.0% |
| imouto-mode | 457 / 3,052 | 316 / 2,209 | WIN 30.9% |
| plan | 264 / 1,737 | 182 / 1,256 | WIN 31.1% |
| debug | 655 / 4,206 | 340 / 2,267 | WIN 48.1% |
| bisect | 249 / 1,632 | 172 / 1,149 | WIN 30.9% |
| done | 655 / 4,130 | 386 / 2,679 | WIN 41.1% |
| lucia-relay | 622 / 4,413 | 384 / 2,835 | WIN 38.3% |
| experiment | 421 / 2,542 | 267 / 1,740 | WIN 36.6% |
| discipline-report | 285 / 2,086 | 198 / 1,481 | WIN 30.5% |
| retro | 934 / 5,907 | 465 / 3,137 | WIN 50.2% |

verdict: WIN 40.6% fewer words overall (5,330 → 3,167), with every skill above
the predeclared 30% threshold. Word and byte counts are deterministic prompt
footprint proxies; an exact model tokenizer was not installed locally.

decision: kept all ten — the contract checker passed after every individual
edit, preserving trigger, safety, evidence, routing, and output requirements.
Substring-only trigger checks were rejected after a contradictory suffix still
passed; exact descriptions plus a preserving-clause adversarial mutation close
that gap.

## 2026-08-20 — route-focused reviewer prompt

change: compressed both installed copies of the reviewer agent around a
risk-first search order, direct caller/consumer evidence, severe-finding
priority, and a three-minor output cap. Added deterministic contract and word
budgets to `test.sh` so compression cannot silently remove focus routes,
no-edit behavior, revert honesty, severities, or the empty-result contract.

baseline: 598 words / 3,872 bytes in all three runs | result: 361 words /
2,559 bytes in all three runs. Word and byte counts are deterministic prompt
footprint proxies; an exact model tokenizer was not installed locally.

verdict: WIN 39.6% fewer words — above the predeclared 30% threshold; reviewer
contract checks and `./test.sh --fast` passed.

decision: kept — less checklist narration is loaded and emitted while every
blocker/major remains reportable and investigation starts at the riskiest
reachable boundary.

## 2026-08-20 — compact agent-readiness procedure

change: compressed `skills/ready/SKILL.md`, merging repeated rationale while
retaining CI-first detection, offline/unattended verification, fast/full and
monorepo routing, hook consent, smoke-test safety, project notes, flake checks,
and an exact-restoration red check. Added those contracts to the prompt budget
test before compression.

baseline: 1,466 words / 9,607 bytes in all three runs | result: 709 words /
4,933 bytes in all three runs. Word and byte counts are deterministic prompt
footprint proxies; an exact model tokenizer was not installed locally.

verdict: WIN 51.6% fewer words — above the predeclared 30% threshold; ready
contract checks, detect fixtures, and `./test.sh --fast` passed.

decision: kept — the skill now reaches the verify decision faster without
dropping destructive-action consent or proof requirements.

## 2026-08-20 — npm staging removes non-runtime release documentation

change: removed `CHANGELOG.md` from the runtime allowlist and publish from a
disposable package stage that keeps `README.md` but omits the alternate Thai
README. The repository still carries both documents at their existing paths;
the staged payload retains every installer, hook, skill, agent, and CLI file.

baseline: npm tarball 86,666 bytes, 265,531 unpacked, 41 entries in all three
runs | result: 65,925 bytes, 205,167 unpacked, 39 entries in all three runs.

verdict: WIN 23.9% packed-size reduction — above the predeclared 10% threshold
with deterministic results. The staged payload has exactly one README
(`README.md`) and passes the runtime-file contract.

decision: kept — npm gets the intended English README and no release-only
changelog/translation payload, while GitHub keeps the complete documentation.

## 2026-08-20 — shell ownership checks remove one Python startup per hook

change: replaced the Python `lstat`/owner/permission check for the predictable
hook state directory with Bash directory, symlink, owner, and mode checks. The
existing hostile-symlink regression and full hook state machine remain the
correctness guard.

baseline: 10 instrumented Bash pre/post pairs plus one prompt took 1.00s,
1.00s, 1.05s (mean 1.017s) | result: 0.83s, 0.84s, 0.83s (mean 0.833s).

verdict: WIN 18.0% — above the predeclared 10% threshold and outside the
baseline range; `./test.sh --fast` stayed green.

decision: kept — every hook call avoids one interpreter startup without
changing the state path, telemetry schema, or fail-open behavior.

## 2026-08-20 — a targeted sanitation probe avoids a recursive fast-suite run

change: replaced the poisoned child process that re-ran all of
`./test.sh --fast` with a child that exits immediately after proving every
ambient `LUCIAZERO_*` variable was removed. The main process still runs the
complete hook state-machine coverage once.

baseline: recursive fast 36.960s, 36.495s, 34.749s (mean 36.068s) | result:
targeted probe 18.83s, 17.24s, 17.28s (mean 17.783s).

verdict: WIN 50.7% — above the predeclared 25% threshold; the measured ranges
do not overlap and every run ended with `PASS fast checks green`.

decision: kept — the regression now tests the sanitation boundary directly
instead of paying to repeat unrelated Relay, bisect, and evidence checks.

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
