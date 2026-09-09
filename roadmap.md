# Luciazero improvement roadmap

Review date: 2026-09-09. Baseline: `d5d2798`.

This is a repository-wide review and proposed work queue, not an implementation
or release approval. Existing local commits belong to their owners. Release
decisions remain in [publishing](docs/publishing.md), distribution in
[ADR 0008](docs/adr/0008-agent-bus-distribution-and-the-cost-of-shipping-a-daemon.md),
and Bus milestones in [the Bus roadmap](docs/agent-bus-roadmap.md).

## How to read this review

- **Confirmed** means the described behavior is visible in the cited source;
  it does not imply that an exploit or end-to-end reproduction was run.
- **Proposal** means a product or workflow improvement, not a verified defect.
- **Investigate** means a hypothesis needing a focused reproduction.
- P1 affects evidence correctness, user data, or an advertised contract; P2
  reduces friction or improves coverage; P3 is optional polish.
- Every item below is open unless explicitly marked otherwise. Do not infer
  completion from its presence here or from an unrelated green suite.

## Scope and strengths to preserve

Reviewed all 13 cataloged skills, the reviewer agent, shared doctrine,
verification helpers, evaluation design, and selected installation, release,
and Bus boundaries. This is not an exhaustive proof over every execution path.

Keep the existing evidence-first loop, conservative ownership handling,
read-only reviewer, isolated worktrees, untrusted peer-message boundary,
explicit persona opt-in, and separation of synthetic evals from real runs.
The reviewer source and Claude copy currently agree. Codex installs that
reviewer as a skill; this alone does not guarantee an independent reviewer
execution context.

## Current gates and milestone status

The declared critical path to the checkout-only v2.5.0 beta has one unmet
piece: install/upgrade/uninstall proof on a second machine. The gate script has
passed on one Darwin arm64 machine only. The decision log now stands at 7 of 3
workflows and 2 of 2 qualifying retros; that gate closed on 2026-09-09.

M7's six managed-dispatch live tasks remain behind the same M4 decision gate;
they are not part of v2.5.0. Do not run them merely to manufacture the missing
retro. M8 currently has five of eight work areas evidenced: full suite;
configuration-preserving install/uninstall on the first machine; opt-in CLI
with no ordinary-install daemon start; documented limitations/storage/cleanup;
and the ADR 0008 distribution decision. Still missing are separate security
and public-contract review artifacts, idle/latency/duplicate-delivery metrics,
and the final feature name after those decisions. Under ADR 0008 these affect
reconsidering npm distribution rather than the checkout-only v2.5.0 beta.

The Global acceptance checklist in `docs/agent-bus-roadmap.md` is now linked
to existing evidence: 14 of 15 items are checked. A provider-free full run was
recorded on 2026-09-08. The one open item is behavioral/enforced proof that a
claimed task cannot pass `/done` without a published result or blocked outcome.

The repository-wide review below also found new P1 defects. They are not
silently inserted into the historical five-item release gate. On 2026-09-08 the
owner decided they are fixed rather than accepted, because R10, R11 and R12a
touch the user's own files and R15 disables a credential that is still valid.
The delivery sequence at the end of this document carries that order.

## Skill re-review snapshot — 2026-09-09

All 13 cataloged skill definitions were read again from the tree at `d5d2798`.
The supporting-script inventory and install mapping were rechecked against the
earlier script audit; the scripts were not exhaustively re-audited in this
pass. `python3 scripts/check-skill-prompts.py` is green; that proves prompt
structure and budgets, not that a model follows the prompts. This table is the
current queue, not a claim that every proposal is a defect.

| Skill | Current finding or improvement | Status |
| --- | --- | --- |
| `ready` | Replace the numeric 3–6 smoke-test target with risk-based selection; keep offline and service-dependent verification distinct | Proposal, R09 coverage |
| `show` | Make its five-part response contract proportional so a one-fact request does not require a ceremonial report | Proposal |
| `imouto-mode` | Its name suggests persistence but its contract is one invocation; `focus` permits no visible voice, invocation UX hides the arguments, and coexistence with persistent style plugins is undefined | Contract half is pre-release; plugin interaction waits for A/B, R23 |
| `plan` | Reuse authority already granted and pause only for a decision that changes the result | Proposal, R05 |
| `debug` | Permit evidence-led hypotheses where production or intermittent failures cannot safely be reproduced; revert only the agent-owned edit | Proposal |
| `bisect` | Explain per-revision dependency setup and that endpoint retries do not make flaky midpoints reliable | Proposal |
| `done` | R01 is closed; still avoid rerunning an unchanged full suite and distinguish a reviewer prompt from an independent execution context | R04/R06 open |
| `lucia-relay` | Resolve all five bare `relay.py` commands relative to the installed skill before release; keep publication/tag creation explicit | R03 pre-release; R07 open |
| `experiment` | Treat three samples as a minimum heuristic, model warmup/noise, and retain correctness or secondary benefits in keep/revert decisions | Proposal |
| `discipline-report` | Give installed/standalone layouts a real command-resolution contract and state malformed/partial-data limits in reports | R03 open |
| `lucia-bus` | Reuse verified identity before redundant registration, bound display of untrusted/private payloads, and expose queued-without-proxy state | R05/R20 open |
| `lucia-chat` | Two-window flow, optional watcher, nudge/pull split, and three latency names now match the shipped CLI | R02 closed; no new finding |
| `retro` | Preserve user testimony as testimony, route private evidence out of Git, deduplicate corrections, and keep nonqualifying outcomes visible | R08 open |

Pre-release skill order is now R03 first, then the source-confirmed contract
half of R23. After that come R04/R06, then R05/R20, R08, and the remaining
proposals. R03 moved ahead because an installed Relay user reaches a command
that does not resolve, not because portable discovery would merely be nicer.
R23 is deliberately not called a Caveman defect: the installed Caveman state
conflicts with Imouto's voice, but no controlled A/B result exists yet.

## P1: proof and runtime contract correctness

### R01 — Revert-probe accepts unrelated failures as regression proof [Confirmed]

Source: `skills/done/scripts/revert-probe.sh:84-93`.
Any nonzero verification exit becomes `PASS: regression tests bite`. Missing
executables, import failures, sandbox denial, and genuine target assertions
are not distinguished. `/done` relies on this output.

Proposed work: verify the current implementation first; report infrastructure
failures as unassessable; retain the failing test identity and expected failure
evidence. A nonzero old-code run alone is insufficient to claim causality.
Explain the base revision: the helper defaults to HEAD for uncommitted fixes,
but a committed fix needs an explicit pre-fix base.

Running the current tree green and the parent tree red is not enough on its
own. A dependency or import failure that exists only in the parent tree still
produces a red parent and a green current tree, so the probe would still print
regression proof for a change that proves nothing. The fix therefore needs two
further properties: the verification command must be targeted at the tests the
change adds or repairs rather than the whole suite, and the probe must compare
the parent run's failure fingerprint — the failing test identities and the
failure kind — against what the regression is expected to look like. A parent
run that fails for a different reason than the regression is unassessable, not
proof.

Acceptance: a real target regression passes the probe; missing command,
missing dependency, denied execution, and unrelated failing tests never count
as regression proof; a parent run whose failure fingerprint does not match the
expected regression is reported as unassessable rather than as proof;
current-code failure cannot yield success. Tests preserve the caller's
dirty/untracked files and cleanup the isolated worktree.

Closed 2026-09-08 by `5de14a8`. The probe now requires a current-tree green,
attributes the parent failure to the changed tests, rejects infrastructure
fingerprints, and reports mismatched failure evidence as unassessable.

### R02 — Chat skill describes pre-nudge behavior and misattributes wait [Confirmed]

Sources: `skills/lucia-chat/SKILL.md:61-101`,
`agentd/luciazero_agentd/__main__.py` (`cmd_run`, `_run_with_nudge`).
The skill requires three terminals and says delivery acknowledgement waits for
a human-started turn, even though its recommended `run` can use a nudge proxy.
It equates send-to-acknowledgement with human waiting cost.

Proposed work: teach `lucia claude` / `lucia codex` after one-time setup;
make the watcher optional; separate nudge, pull-only `--no-nudge`, and managed
dispatch. Name delivery latency, review completion latency, and user-attributed
blocking cost separately. Use existing supported inspection for bus identity;
do not promise a startup banner before that feature exists.

Acceptance: examples resolve with actual CLI help/parsing; a two-session nudge
flow and a pull flow have distinct explanations; no prose infers human wait
from send/ack timestamps. Real-provider evidence remains distinct from mocks.

Closed 2026-09-08. The skill now opens one window per agent with `lucia claude`
and `lucia codex`, keeps the watcher as the optional third, and explains the
knock and `--no-nudge` as two different flows. The send-to-acknowledgement gap
is named delivery latency and kept apart from completion latency and from
user-attributed blocking cost, which the skill says only the user can supply.
`chat` printed the same two false sentences and prints the corrected ones now,
and `conversation_plan` labels the watcher optional rather than "terminal 1".
The claims are held by `agentd/tests/test_docs.py`: every command the skill
quotes is parsed by the real CLI parser (extracted as `build_parser`), every
flag it names has to exist, and the cooldown and cap it quotes come from the
constants in `nudge`.

### R03 — Installed Relay commands do not resolve their bundled script [Confirmed, pre-release]

Sources: `skills/discipline-report/SKILL.md:12`,
`skills/lucia-relay/SKILL.md`, `install-codex.sh:121-153`.
Discipline's fallback resolves `../../bin/luciazero.js` relative to the skill.
That matches checkout/package layout but is not guaranteed for individually
copied skills and remains an investigation. Relay is already confirmed:
`skills/lucia-relay/SKILL.md` invokes bare `relay.py` five times, while the
installer puts the executable at
`<this-skill-dir>/scripts/relay.py` and never adds it to `PATH`. Ready, Bisect,
and Done already use the resolvable `<this-skill-dir>/scripts/...` convention.
A user or agent following Relay literally therefore fails on its first command
after a normal install. This is part of the v2.5.0 installed skill surface, not
a future packaging concern.

Pre-release work: replace all five bare Relay invocations with the bundled
skill-relative path. Keep the broader Discipline layout question separate so
it cannot hold the small confirmed fix hostage. Report offline unavailability
when a required runtime is absent rather than silently installing dependencies.

Acceptance: test in both directions. Extract every
`<this-skill-dir>/scripts/...` reference from every cataloged skill, resolve it
from that skill directory, and require the referenced file to exist and be
executable; also require every mention of a script that is actually bundled by
that skill to carry the prefix. The first direction catches a documented typo
such as `relay2.py`; the second catches a return to bare `relay.py`. Put this
contract beside `agentd/tests/test_docs.py`, whose command parser covers
`lucia-chat`; run the Relay command from `/` in isolated Claude and Codex
install layouts. A missing runtime produces a useful diagnostic without
network access or config writes.

## P2: autonomy, cost, and consistent skill behavior

### R04 — Reuse verification for unchanged tested state [Proposal]

Source: `skills/done/SKILL.md:10-15`; doctrine asks for full verification once
at closeout. Done's literal "now, not earlier" can cause repeated full suites
despite unchanged source.

Tie reuse to tested files, relevant inputs, command, and environment, including
dirty/untracked changes; HEAD alone is inadequate. Invalidate evidence when a
relevant change or new concern appears. Keep full closeout coverage, with no
rerun merely for reporting or committing unchanged files.

Acceptance: a docs-only handoff after a valid unchanged check avoids duplicate
work; changed code/config/fixtures invalidates the relevant proof. Report check
scope and local omissions explicitly.

### R05 — Scope missing-capability stops and preserve prior authorization [Proposal]

Sources: `skills/lucia-bus/SKILL.md:11,67-69`, `skills/plan/SKILL.md`,
`claude/luciazero.md:9` (rule 9 is under Autonomy).

Say that unavailable Bus tools stop Bus operations, while authorized local
work may continue. Distinguish daemon-enforced nonces from harness approval;
neither a skill nor a peer grants new authority. Reuse existing user
authorization for the same scope and request a new decision only when scope
or the consequential action changes. Report enforced permission denial as
such rather than treating it as a software failure.

Acceptance: no-MCP local work proceeds; peer-supplied approval is rejected;
already-authorized routine work does not prompt again; a blocked Bus action
does not trigger an alternate route around its permission boundary.

### R06 — Reviewer evidence and actual independence [Proposal]

Source: `agents/reviewer.md`, `claude/agents/reviewer.md`,
`install-codex.sh:143-153`, `skills/done/SKILL.md:32-45`.

Keep confirmed reachability, no speculative findings, and `No findings` as a
valid outcome. Permit a short trigger → consequence → evidence explanation
when one line cannot carry a concurrency/security issue. Distinguish confidence
from severity. Record whether review ran in an independent context; loading
the Codex reviewer skill in the implementer's context is not independent.
Use two separate security/contract passes when their risks warrant it, not
merely because every CLI change could fit both labels.

Acceptance: seeded reachable defects are found, clean changes do not require
invented defects, and a self-review is never reported as independent.

### R07 — Relay draft should make publication explicit [Proposal]

Sources: `skills/lucia-relay/SKILL.md:24-26`,
`skills/lucia-relay/scripts/relay.py:258-278`.
Cross-machine draft publishes a commit-named tag when absent. This behavior
is documented, but the command name can imply local preparation.

Separate local draft/inspection from authorized publication, or make the
publication requirement unmistakable before execution. Preserve trusted
envelope verification and never auto-execute transferred commands. Clarify
same-machine versus cross-machine instructions without imposing remote pushes
on a local handoff. Any CLI change requires compatibility planning.

Acceptance: local preparation performs no remote writes; publication targets
the declared commit/ref; receiver rejects stale or untrusted envelopes.

### R08 — Retro evidence types and outcome-neutral gates [Proposal]

Sources: `skills/retro/SKILL.md`, `docs/agent-bus-decision-log.md`.
Add observed, user-reported, inferred, and not-measured distinctions. Allow
agents to edit a user's testimony faithfully; prohibit fabrication of subjective
cost. Keep useful null/negative retros even when they do not qualify for a gate.

Review the distinction between dispatch-value evidence and checkout-beta
readiness. Current qualifying-retro policy asks for blocking cost; general
Bus value also includes reduced copying and provenance. Any amendment is an
explicit owner decision, not a retroactive change to counts. Do not seek or
manufacture painful workflows just to satisfy a positive-result quota.

Acceptance: zero-wait testimony remains zero; send-to-first-touch and
send-to-result are never interchangeable; a nonqualifying retro remains
discoverable and cannot silently increase qualifying counts.

## Complete catalog: improvements and acceptance checks

| Component | Proposed improvement | Acceptance condition |
| --- | --- | --- |
| reviewer | R06: explanatory evidence and real independence | Clean and seeded-defect fixtures; explicit execution context |
| ready | Add only needed smoke tests instead of a numeric 3–6 target; separate offline fast checks from integrations needing services | Existing useful verify is reused; unavailable integration is reported, not replaced with misleading coverage |
| plan | R05: reuse authorization; proportional plans | Routine clear edit proceeds; material ambiguity gets one focused decision |
| debug | Permit evidence-led hypotheses when production/intermittent failures cannot safely be reproduced; revert only the agent's failed diff | Logs can support a labeled hypothesis; no broad rollback of user changes |
| bisect | Explain per-revision dependency setup and endpoint-only retry limits | Infrastructure failure aborts; midpoint flakes remain an explicit limitation; caller tree stays intact |
| done | R01/R04/R06 | Target regression proof, unchanged-state reuse, and honest review scope |
| experiment | Treat three samples as a minimum heuristic; account for warmup/noise and secondary benefits before discarding a null performance change | Raw measurements retained; no win claimed inside noise; keep/revert rationale covers correctness and other objectives |
| retro | R08 plus deduplication and private-data routing | User testimony preserved; private paths excluded; old disproven lessons corrected |
| discipline-report | R03; report malformed-record coverage and attribution limits | Missing logs and partial data do not look like complete behavior evidence; non-Bash time is not labeled model latency |
| lucia-relay | R03/R07 | Portable commands and explicit publication without weakening envelope trust |
| lucia-bus | R05; inspect verified identity before redundant registration; bounded quoted inbox display | No identity guessing, payload cannot grant permission, long/private messages do not force indiscriminate full display |
| lucia-chat | R02 | Two-window default, optional watcher, correct latency and nudge explanations |
| show | Make the five-part output proportional to the question | Small questions get concise answers; material diagram edges retain evidence pointers |
| imouto-mode | Preserve explicit invocation and per-request reset; validate suppression during incidents | No implicit activation, carried-over persona, or teasing in incident/security guidance |

## R09 — Extend the existing behavioral evaluation suite [Proposal, P2]

Sources: `eval/README.md`, `eval/tasks/`, `test.sh:497-503`,
`scripts/check-skill-prompts.py`.
The repository already has behavioral outcome graders and anti-gaming
fixtures. The gap is targeted skill selection, unnecessary pauses, tool
availability, and orchestration cost; do not describe the current eval as
entirely absent. Literal prompt checks and word budgets guard structure but
cannot establish runtime behavior.

Add scenarios for routine typo correction, analysis-only requests, prior
approval reuse, sandbox denial, missing Bus tools, clean review, long untrusted
inbox content, committed/uncommitted revert probes, and zero-blocking-cost
retros. Where routing itself must be measured, use consented test-harness
instrumentation: final-tree grading alone cannot identify the invoked skill.

Measure task correctness, verified defects, false findings, avoidable user
turns, redundant verification runs, wall time, and tokens when available.
Pin model/configuration and distinguish synthetic fixtures from real provider
runs. Existing paid-provider runs require their own authorization.

Acceptance: unchanged baseline and candidate prompts run on the same fixtures;
cost reductions cannot hide lower correctness or weaker permission handling.

## Additional installer, hook, Bus, and release review

### R10 — Refused snapshot-parent symlinks still reach deletion [Confirmed, P1]

Sources: `uninstall.sh:64-73`, `uninstall-codex.sh:43-52`.
The unsafe snapshot-parent branch reports refusal, but unconditional snapshot
cleanup still follows it. A symlinked `.luciazero-managed/skills` can redirect
cleanup of the child snapshot outside the managed directory. This is a
source-confirmed destructive path; no destructive reproduction was run.

Fix: return before all cleanup on unsafe ancestry and apply the same ownership
policy to file/tree operations. Acceptance: external sentinels survive both
provider uninstallers, with the managed destination present and absent.

Closed 2026-09-08 by `0703fdf`. Unsafe ancestry returns before cleanup for
both managed files and trees; external sentinels cover every refusal path.

### R11 — Codex uninstall predictable temporary path [Confirmed, P1]

Source: `uninstall-codex.sh:109-110`.
Redirection to `AGENTS.md.tmp` follows a planted symlink before `mv`; the
Claude-side mktemp hardening did not cover this path.

Fix: validated same-directory mktemp, cleanup, and conservative replacement.
Acceptance: a decoy symlink and its target survive; failed writes preserve the
original AGENTS.md. Source review only; no live user files were exercised.

Closed 2026-09-08 by `dc8dc22`, with same-directory `mktemp`, cleanup, and a
sentinel regression. File-mode preservation was closed separately by
`c46421e` for both user instruction files.

### R12a — Malformed Codex markers rewrite the file anyway [Confirmed, P1]

Sources: `install-codex.sh:100-115`, `uninstall-codex.sh:95-110`.
An opening marker without a closing marker suppresses trailing text through
EOF. Nested or duplicated markers have no defined meaning either, and the
rewrite proceeds regardless. Backups aid recovery but do not make the rewrite
correct: the user's `AGENTS.md` is their own file, and losing the tail of it is
data loss.

Fix: validate marker structure before any mutation, and refuse on anything that
is not exactly one well-formed block — malformed, nested, or missing a closing
marker. A refusal must leave the file byte-identical, not merely recoverable
from a backup, and must say which marker structure it found.
Acceptance: for each of malformed, nested, and incomplete-marker inputs, the
command exits nonzero and the file's bytes are unchanged (compare hashes, not
just content read back through the same rewriter); the well-formed case still
installs and uninstalls as before.

Closed 2026-09-08 by `e5c06dc`. Install and uninstall refuse malformed,
nested, and incomplete markers before rewriting the user's file.

### R12b — Trailing whitespace round-trip and separator provenance [Confirmed, P2]

Source: `install-codex.sh:100-115`.
First install trims trailing blank lines even when no managed block existed, so
an install/uninstall cycle does not return the file to its original bytes.

Fix: preserve zero, one, and multiple trailing blank lines across a full cycle,
and introduce explicit separator provenance if exact round-trip is promised
rather than inferred.
Acceptance: install then uninstall restores the original bytes for zero, one,
and multiple trailing blank lines, and for user content rearranged around the
managed block.

Closed 2026-09-09 by `994d4a2` and `0fa38c9`, merged as `b86f2f0`. The block
owns its separator inside its markers, records a final newline it had to add,
and round-trips LF/CRLF files whose last line has no newline.

### R13 — Generated hook commands need shell quoting [Confirmed, pre-release]

Sources: `install.sh:457-458,481-493`.
Executable paths enter shell command strings unquoted. Spaces break the
command and shell metacharacters can alter execution. This review does not
establish a remote attack path; the configured directory is the input.

Reproduced 2026-09-09 with `CLAUDE_CONFIG_DIR` containing a space. The
installer completed and stored
`<config with space>/hooks/luciazero-verify.sh edit` without quoting; executing
that exact hook command through the shell exited 127 at the first space. This
is the same installed-user surface that promoted R03 and therefore belongs
before v2.5.0, even without a remote injection path.

Fix command construction, status detection, and uninstall matching together.
Acceptance: generated hooks actually run from paths with spaces/apostrophes;
metacharacter fixtures cannot execute an unintended sentinel command.

Closed 2026-09-09 by `ff199fb` and `610b0c3`. Hook and status-line
commands are quoted at the write site, legacy bare entries are normalized
in place, and status/uninstall parse both spellings. Space, apostrophe and
shell-metacharacter fixtures execute the stored command, preserve idempotency,
remove every owned entry, and never execute path text.

### R14 — Settings updates need failure-safe publication [Proposal, P2]

Sources: `install.sh:439-453,502-507`, `uninstall.sh:237-240`.
Settings JSON is written directly; hook files may be copied before settings
validation. Use preflight parsing, validated temporary output, atomic replace,
and conflict handling. Acceptance: serialization/write failures and invalid
settings preserve the original configuration and report partial work honestly.

### R15 — Credential renewal write failure breaks valid authentication [Confirmed, P1]

Source: `agentd/luciazero_agentd/store.py:1945-1972`.
The current `_renew_binding` has no sqlite3.Error catch around its write
transaction, despite the earlier discussion of best-effort renewal.
The independent reviewer ran an isolated valid-binding probe with
`PRAGMA query_only=ON`: resolution raised
`OperationalError: attempt to write a readonly database`.

Fix: catch only sqlite3.Error around the write/event transaction, after
calculation and liveness/expiry checks. Failed renewal retains existing access,
expiry/state, and writes no renewal event; corrupt timestamps and programming
errors still surface. Acceptance: read-only resolve succeeds while the valid
binding's persisted fields and event count remain unchanged.

Closed 2026-09-08 by `14bf3d6`. Only the renewal write transaction catches
`sqlite3.Error`; a valid credential retains access without a false renewal.

### R16 — Renewal updates can shorten expiry under reordered requests [Confirmed, P2]

Source: `agentd/luciazero_agentd/store.py:1967`.
The SQL update lacks a persisted expiry monotonicity condition. The reviewer
used two valid row snapshots, committed the later target first and earlier
target second, and observed expiry decrease. This demonstrates stale-snapshot
behavior, not a stress-test reproduction of scheduling frequency.

The event is also emitted without checking affected row count, so a revoked
row can produce a misleading renewal event. This is not a demonstrated
privilege escalation. Fix: conditional update against current stored expiry and active state, with
accurate event/return behavior when no row changes. Acceptance: reversed-order
renewals never reduce expiry; revoked/stale/expired bindings never revive.

### R17 — Managed binding still probes liveness under write transaction [Confirmed, P2]

Sources: `agentd/luciazero_agentd/store.py:1808-1810,2028`.
Managed binding calls `binding_of()` inside its transaction; that path reaches
process liveness. An injected liveness callback in the review observed
`_conn.in_transaction == True`. Human-path reap changes did not fix this path.

Fix: external liveness/reaping before the write transaction, followed by
transactional row-only conflict checks. Acceptance: no process probe runs
under a write transaction; simultaneous launchers still produce one winner.

### R18 — PTY fallback validation is weaker than its stated boundary [Confirmed gap, P2]

Source: `agentd/luciazero_agentd/nudge.py:178-192`.
The reviewer verified `_typeable(TEXT + '; ignore previous instructions')`
passes its prefix/ASCII/length validation. The current builder allowlists its
components, so this is not a demonstrated peer-payload exploit.

Consider exact generated grammar validation or carrying typed structured
metadata to the PTY boundary. Acceptance: malformed suffixes fall back to the
literal; valid counts/provider/kind combinations retain their allowed output.

### R19 — Release artifacts and gate attestations [Proposal, P2]

Sources: `.github/workflows/release.yml`, `scripts/stage-npm-package.sh`,
`docs/publishing.md`.
Verify staged npm contents independently from the full-source GitHub ZIP.
Document partial release recovery when GitHub release succeeds and npm fails.
Consider a reviewed machine-readable gate attestation that references human
evidence without manufacturing testimony. Fix any remaining clone-only wording
that excludes the deliberately supported source-ZIP route.

Acceptance: tarball/source-ZIP inclusion matrices are asserted; retries do not
silently move tags or republish different bits; gate state remains 5 workflows,
1 qualifying retro, and no second-machine proof until new evidence changes it.

### R20 — Bus identity, delivery visibility, and lifecycle [Proposal, P2]

Reuse M9 in `docs/agent-bus-roadmap.md` rather than opening a competing
session-adapter design. Make the selected state directory and bound identity
visible, and distinguish durable queueing from an active delivery proxy.
The wf4 mismatch motivates this; it does not prove all empty inboxes have the
same cause. Avoid exposing tokens or private paths in public exported evidence.

Current autostart (`__main__.py:681-745`) uses detached Popen, not automatic
user-service installation. Document that fact. Adopting launchd/systemd
bootstrap requires an explicit lifecycle decision and uninstall proof.

Acceptance: two isolated buses are distinguishable to their operators;
queued-without-proxy is observable without claiming the recipient read it;
normal/pull-only sessions remain supported. Session-control adapter work stays
under M9 and requires verified provider capabilities and ownership boundaries.

### R21 — Metrics rotation writes through a predictable temporary name [Confirmed, P2]

Source: `claude/hooks/luciazero-verify.sh:326`.
The metrics log rotation writes `path + ".tmp"` and then `os.replace`s it over
the log. It is the same class as R11, one directory further in: anyone able to
create that name in the state directory receives the rotated content and hands
back whatever they point at. The exposure is smaller — the state directory is
the user's own and the content is telemetry, not their config file — so this is
P2, but the fix is the same `mkstemp` in the same directory.
Acceptance: a symlink pre-created at the rotation name is not followed, and the
sentinel it points at is unchanged.

### R22 — A test pins CPython's old JSON recursion behavior [Confirmed, P1]

Source: `agentd/tests/test_mcp.py:203-205`.
`test_pathological_json_is_a_parse_error_not_a_dropped_connection` feeds 20000
nested brackets and asserts `-32700` (parse error). Until CPython 3.14.7 that
input raised inside `json.loads`; 3.14.7 parses it, so the daemon correctly
answers `-32600` (invalid request) — valid JSON that is not a JSON-RPC request
— and the assertion fails. The behavior under test is the daemon's, but the
input's classification belongs to the interpreter, so the test pinned something
it does not own. Confirmed on 2026-09-08 after homebrew relinked python3 to
3.14.7 at 16:25; the same suite was green earlier the same afternoon.

This is P1 for a different reason than the rest: while `./test.sh` is red,
nothing below it can be proven by the full suite.

Closed 2026-09-08. The test now asserts what the daemon owns and nothing else:
valid JSON whose root is not a request object is an invalid request (`-32600`)
at a depth every supported interpreter parses, malformed syntax is a parse
error (`-32700`) whichever exception the parser reaches for, and the daemon is
still serving afterwards. The 20000-level input stays, as malformed syntax,
where its classification no longer depends on the interpreter. Verified on
3.14.7 and 3.10.20.

### R23 — Imouto is presented as a mode but is a one-invocation voice [Confirmed contract gaps, Investigate interaction, P2]

Sources: `skills/imouto-mode/SKILL.md`,
`skills/imouto-mode/agents/openai.yaml`, and the installed Caveman plugin's
`plugin.json`, `caveman-activate.js`, and `caveman-mode-tracker.js`. The OpenAI
YAML is interface metadata and is not evidence of Claude Code behavior.

Three source-visible gaps are separate:

1. The skill says the next request is off, while its name and “mode” vocabulary
   can reasonably lead a user to expect session persistence. A prompt cannot
   truthfully promise persistence without state and a lifecycle hook.
2. `focus` requires a warm touch only in a greeting, transition, or handoff. A
   normal coding answer may contain none of those and remain compliant, so the
   activation can be invisible.
3. Model invocation is disabled intentionally, but the skill exposes neither
   an argument hint nor an activation acknowledgement. Natural-language “turn
   Imouto on” is therefore not a supported activation, and an empty invocation
   shows choices without enabling one.

There is also a plausible conflict, not yet a confirmed cause: the installed
Caveman plugin persists `full` in `.caveman-active`, injects its complete style
at `SessionStart`, and reinforces it at every `UserPromptSubmit`. Imouto has no
precedence or suspend/restore protocol. The presence of two conflicting prompts
does not prove which one caused a particular silent answer.

Split the work before implementation. The source-confirmed contract half does
not need the A/B result: state conspicuously that the voice is one invocation,
make `focus` require one observable brief touch per response, add
`argument-hint: [focus|on|off]`, and add an activation acknowledgement that
does not pad or delay the work. `imouto-mode` is already at 316/319 words, so
this change must deliberately revise its prompt budget in
`scripts/check-skill-prompts.py` rather than silently deleting safety clauses
to squeeze under three remaining words.

The separate product decision remains: retain that explicit one-shot voice or
make it a real session mode. The persistent design needs its own symlink-safe
state, `SessionStart` re-assertion after
startup/resume/clear/compaction, `UserPromptSubmit` handling, and a defined
suspend/restore contract with other persistent style plugins. Merely writing
“Imouto wins” in the skill is not a state machine.

Acceptance begins with a controlled A/B using the same prompt: invoke Imouto
while Caveman is `full`, stop Caveman and verify its flag is absent, invoke
Imouto again, then send one request without invoking it. Record the literal
prompts and responses. Only an A-silent/B-voiced result attributes suppression
to Caveman; B-silent routes to invocation/installation debugging; a voiced
third request disproves the current one-shot contract or shows unbounded style
carry-over. If one-shot is retained, `focus` has an observable per-response
minimum and frontmatter advertises `[focus|on|off]`. If persistence is chosen,
tests cover start, resume, clear, compaction, off, crash/corrupt state, and
suspend/restore without modifying the other plugin's source.

### R24 — The shell backup name is checked, not reserved [Confirmed, P2]

Sources: `install.sh`, `uninstall.sh`, `install-codex.sh`,
`uninstall-codex.sh` — the `bakpath()` each of them defines.
The helper picks `<file>.bak.<timestamp>[.n]` by testing the name and then
returns it; the caller copies to it afterwards. 550a656 closed the planted
case — `[ -e ]` alone follows the name and calls a dangling symlink free, so
`install.sh` copied a real settings.json through one and out of the config
directory (reproduced: `escaped-0` outside a scratch config dir) — by refusing
any name a symlink holds. What it does not close is the window between that
test and the `cp`: anything able to create files in the config directory can
plant the symlink after the test, and `cp` will still follow it. POSIX `sh`
has no `O_CREAT | O_EXCL`, which is what the uninstaller's settings backup
uses now that the same logic is Python.
The exposure is the user's own config directory, and winning the race needs
write access to it plus timing, so this is P2 rather than a release blocker.
The claim in the code and in any note about it is "a free name", never
"collision-proof" or "atomic".
Acceptance: the backup is created by a call that fails when the name exists,
so a symlink planted between choosing the name and writing it cannot be
followed — in practice by moving each `bakpath` caller onto `mktemp` in the
same directory, or onto the same Python reservation, and a test that plants
the symlink after the name is chosen rather than before.

## Delivery sequence

The owner reviewed this order on 2026-09-08 and rejected accepting the P1
findings as known risks: R10, R11 and R12a touch the user's own files directly,
and R15 makes a still-valid credential unusable. They are fixed, not accepted.
The proof tool is repaired first, because every fix below is supposed to be
proven with it.

0. R22, done first on 2026-09-08 at the owner's direction: the full suite is
   the proof for everything below it, and it was red.
1. R01 (closed `5de14a8`): repair the proof tool. The fix must go past "current tree green, parent
   tree red" — targeted verification plus a failure-fingerprint check, or a
   parent-only dependency failure still reads as regression proof.
2. R10 (closed `0703fdf`): the refusal must return before snapshot cleanup, in every path.
3. R11 (closed `dc8dc22`): same-directory `mktemp` for the Codex uninstall rewrite. R10 and R11
   are separate commits; they are separate defects in separate scripts.
4. R12a (closed `e5c06dc`): malformed, nested, and incomplete markers refuse, leaving the file
   byte-identical.
5. R15 (closed `14bf3d6`): reproduce the read-only failure in a focused test first, then narrow
   the handling to the SQLite write alone.
6. R03 before v2.5.0: make all five Relay commands resolve the bundled script
   and bind cataloged skill script references to real files in a test. R02 and
   R12b are already closed.
7. R13 before v2.5.0: quote generated hook/status commands, then keep install,
   status detection, and uninstall matching on the same canonical contract.
8. R23 contract half before v2.5.0: observable `focus`, explicit one-shot UX,
   argument hint, and a deliberate prompt-budget revision. Caveman
   suspend/restore remains behind the controlled A/B.
9. R04/R06 next: unchanged-state verification reuse and actual review
   independence.
10. R05/R20, R08, R14, R16–R19, R21, R24, R09 and remaining proposals after
   that, ordered by reproduced impact rather than catalog order.

Implementation proposals here do not authorize bumping versions, tagging,
publishing, changing existing release gates, or deploying to production.

## Review evidence and limits

- Read all 13 cataloged skill definitions and reviewer source/copy.
- Inspected shared doctrine, helper scripts, skill installation mapping,
  prompt checks, and existing evaluation design.
- Prior analysis ran `python3 scripts/check-skill-prompts.py` successfully and
  compared reviewer copies successfully. Those are structural checks, not
  proof of runtime skill quality.
- No real model benchmark, production action, or release was run for this
  audit. Independent reviewers inspected installer/hook/release and Bus
  boundaries; Bus probes used isolated state. No cross-platform installer run
  or exhaustive hook-state-machine/network-client audit was performed.
