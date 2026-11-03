# Experiment log

## 2026-11-03 — verify detector recall and edits the hook should not count (measurement only)

question: now that the detector counts the program a command runs, which
nudges fire after a real check the default does not know, which fire after
edits that were never project code, and would counting Bash writes as edits
pay for itself?

method: replayed Claude transcripts from 2026-10-24 to 2026-11-03 (10,525
Bash calls, 659 turn ends, one state per project) through the merged
`defaultVerify` from `claude/hooks/luciazero-verify.cjs`. Commands it did not
count were sorted into families by the program they run: test (`node --test`,
`playwright test`), typecheck (`tsc --noEmit`, `npm run typecheck`), lint
(`eslint`, `shellcheck`, `npm run lint`), check-script (`npm run check`,
scripts named `check*`, `validate*`, `smoke*`, `selftest*`), syntax (`node
--check`, `py_compile`, `bash -n`) and build. Each variant below replays the
stop nudge with one change. A nudge episode is an edit left without a counted
verify at a turn end. The person who wrote the classifier also graded the
episodes by hand, so the grading is not independent. Codex transcripts were
not scanned.

result:
- Nudge episodes today: 93.
- Counting test, typecheck, lint and check-script: 73. Adding build changes
  nothing; adding syntax gives 66.
- Of that drop, test, typecheck and lint alone account for 3. The rest are
  project check scripts, mostly from two repositories: `npm run check`, `node
  build/check.mjs`, `check-skill.py`, `check-run.py` and `check-package.mjs`.
- Hand grading of the 26 episodes a test, lint or check-script command
  closed: 21 ran a real check of the edited work. 3 ran a check of something
  else (a skill's `check-skill.py` after editing a video's
  `publish-copy.txt`; one skill's package check after editing another
  skill). 1 was a project check after a `.txt` edit. 1 was `shellcheck
  --version`.
- Precision across the corpus: every test (256) and typecheck (16) match ran
  the tool. Lint was 17 of 20; the other 3 were `shellcheck --version`.
  Check-script was about 222 of 230. The misses were ad hoc `check*.py`
  probes in scratch directories, one `--help` and one `npm ci` that the
  family pattern wrongly took for `ci`.
- Ignoring edits under the temp directory (`/tmp`, `/private/tmp`,
  `/var/folders`) outside the session's project: 77. All 16 removed episodes
  were the agent's own scratchpad tools (measurement scripts, probes, mock
  data builders). No session had its project under a temp directory, so
  exempting the project root changed nothing here.
- Both changes together: 59, 37% fewer than today.
- Ignoring every edit outside the project root instead: 52 with no other
  change. It is too broad, because about 28 of the 41 episodes it drops
  were real edits to a sibling repository, a worktree's main checkout or
  `~/.agents/skills`.
- Counting Bash writes to source-like files as edits: 149 episodes (+56), or
  101 on top of both changes, mostly in media pipelines where a render is the
  check. 19 episodes had a Bash write after the last verify that the hook
  never saw; in 5 of them an uncounted check ran afterwards.

verdict: PASS for ignoring temp-directory edits outside the project: it
removes 17% of nudges, and every one removed was noise. PASS for counting
project check scripts and the generic test, typecheck and lint commands. 81%
of the nudges they close followed a real check. The generic commands are
precise but barely move this corpus. NULL for counting Bash writes as edits:
the nudge count rises by 60% and the extra nudges are mostly noise.

decision: two hook changes, each with tests:
- Ignore Edit and Write targets under the temp directory unless they are
  inside the session's cwd or `CLAUDE_PROJECT_DIR`, or inside a git work
  tree.
- Widen `DEFAULT_VERIFY_RE` to `node --test`, `tsc`, `playwright test`,
  `eslint`, `ruff check`, `shellcheck`, `npm run check|lint|typecheck`, and
  scripts with the word `check` or `validate` in a name that ends in a
  script extension. `bun test`, `deno test`, `mypy`, `pyright`, `cargo
  clippy` and `go vet` were added with them, though none appeared in this
  corpus. These do not count:
  - a program run with nothing but `--version`, `--help` or `-h`;
  - a program's own short version flag (`tsc -v`, `shellcheck -V`);
  - `node --check`.

The corpus was replayed with the first implementation, before review added
the git work tree and `CLAUDE_PROJECT_DIR` exceptions and the short version
flags. Those additions can only add nudges back. The wider detector gave 74
nudge episodes, and 60 with the temporary-directory rule as well.
Of the 423 commands it newly counts, about 8 were ad hoc `check*.py`
probes of a database in a scratch directory. The rest ran tests, type
checkers, linters or a project's check script. It stopped counting 2
commands, both `verify.py --help`.

Bash writes stay uncounted. `.txt` stays a non-document on purpose (see
`DEFAULT_DOC_RE`). The check-script gain is concentrated in one person's two
repositories. A repeat over other users' transcripts or Codex sessions could
change it.

## 2026-11-03 — verify regex precision and repeated greens (measurement only)

question: should the hook tell the agent that a verify already passed with no
edit since, to save repeated runs? Its `redundant_green_count` suggested most
greens were repeats.

method: replayed local transcripts from 2026-10-24 to 2026-11-03 (main
sessions and subagents, 13 projects, 10,417 Bash calls) in time order, one
state per project as the hook keeps it. A command counts as a real verify only
when the program it runs matches the regex: the executable plus its script,
`-m` module or subcommand (`pytest`, `npm test`, `./test.sh`, `node
verify-seek.mjs`). Readers such as `grep`, `sed`, `cat` and `wc`, inline
`python -c` code and heredoc bodies do not count. Bash commands that write
files (`sed -i`, redirects, heredoc scripts that write, `cp`/`mv`, `git
checkout`) count as edits. A hand reading of 50 random regex matches agreed
with the classifier on all 50. The person who wrote the classifier did that
reading, so it is not an independent check.

result:
- Regex precision: 834 commands matched `DEFAULT_VERIFY_RE` and 469 (56%) ran
  a verify. The false positives were mostly reads of files named `verify*` or
  containing `pytest`: `grep` 102, `sed` 89, heredoc bodies 87, `wc` 20 and
  inline `python -c` 17.
- Repeated greens under the hook's own rule: 628 of 807 (78%).
- Repeated greens, real verifies only and Bash writes counted as edits: 35 of
  442 (8%).
- Repeated greens, the same check in the same directory and no edit since: 22
  of 442 (5%). That is 5.1 of 194 minutes of verify wall time and about 4k
  output tokens over ten days. All 22 came within 30 minutes of the earlier
  green.
- Missed nudges: at turn ends, 91 edit episodes were left without a real
  verify after the last Edit/Write. In 21 of them (23%) a false-positive match
  had already marked the edits verified, so the stop nudge stayed silent.
  Examples are a `grep` for `pytest` in a doc, a `python -c` montage that
  writes into a `verify/` folder, and a memory note containing "verify".

verdict: NULL for the hint. Real repeated greens are about 5–8% and cost
minutes, not hours. With today's detection a "verify already green" hint would
be correct about 22 times in 628. It would also invite skipping verification
right after a heredoc or `sed -i` edit, which the hook does not see.
`redundant_green_count` overstates repeats by about 15 times.

decision: no hint. The larger problem is precision: false-positive verifies
silence the stop nudge. A detector based on the executable and its script,
module or subcommand fixes most of the false positives. That needs its own
change with tests. Counting Bash writes as edits is noisy (scratch files, logs)
and would need a project-path filter first.

## 2026-11-03 — reviewer step budget and caller brief

change: the reviewer opens with `git diff -W`, batches independent reads,
reads line ranges once, probes only when reading cannot decide, never installs
dependencies, budgets about twelve steps and reports an `Unchecked:` line.
`/done` and the agent description tell callers to brief it with only the base
ref, focus and changed files.

baseline: 227 local reviewer subagent transcripts. Tool calls per run: p10 21,
median 43, p90 75, at 1.04 calls per step. Median peak context was 194k tokens
and median cache reads 4.2M tokens per run. Half the runs read one file more
than once. Caller briefs had a median of 3.5k characters, and the heavy ones
covered a whole app, listed five focus areas and invited a full verify run.

result: headless `claude -p` runs with the old and the new prompt as the
system prompt (`--setting-sources project`, Opus 5.5, tools Read/Grep/Glob/
Bash). Each run used a fresh clone.
- Seeded fixture (a 95-line change with three planted defects, short brief, 3
  runs per arm): both arms took 4–5 steps. Both found the path traversal and the
  `None` config crash in 3/3. The test that passes on revert: old 1/3, new 2/3.
  Cost: old $0.13–0.14, new $0.08–0.09.
- `8360f8e` (421 lines, 10 files, short brief, 1 run per arm): 7 steps each.
  Cost: old $0.38, new $0.26.
- `8360f8e` with a long caller-style brief (2 runs per arm): steps old 28 and
  15, new 8 and 9. Cache reads old 1.31M and 508k, new 200k and 244k. Cost old
  $1.14 and $0.66, new $0.52 and $0.57. Wall time old 648s and 306s, new 94s and
  128s.
  Of the three real findings that `48e03f9` recorded, old found 2/6 and new
  1/6. Neither arm found the `AGENTS.override.md` one.

verdict: WIN on cost (fewer steps, about 4x fewer cached tokens, about 4x
faster) when the brief invites a wide review. The brief itself is the larger
lever: with a short brief both prompts took 7 steps. Recall is UNRESOLVED.
Real-diff recall dropped from 2/6 to 1/6, and two runs per arm cannot separate
that from noise. Calls per step stayed near 1.0, so the batching clause did not
change behaviour; the savings came from the step budget and the scope.

decision: kept. Caveats: headless runs omit the user-level CLAUDE.md a real
subagent receives, so absolute step counts are lower than the transcripts show.
Re-measure with the transcript scan after real use, and run more real-diff
pairs before claiming recall parity.

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
