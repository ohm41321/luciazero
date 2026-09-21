# Astra/Luna adapter — Slice 0 evidence

Status: source pinned and discovery probes captured. No adapter file was
installed into a real user or project configuration.

## Ownership and source

Luciazero is the canonical owner of this adapter. The upstream Astra/Luna
repository is input only:

- repository: `https://github.com/donvito/codex-astra-luna-orchestrator.git`
- pinned source commit: `9c2a98435ca9ed2b85ac6b0e942b5ded75a4d194`
- pinned source inventory: `docs/assets/astra-luna-adapter-baseline.json`

The source checkout was clean with respect to tracked files when the commit
was recorded. Its untracked roadmap is not part of the pinned adapter input.

## Runtime observed

The supported local Codex build reported `codex-cli 0.154.0` on macOS
arm64. The disposable-project probe used the app-server JSON-RPC surface, so
it did not start a provider turn or spend provider quota.

### Project skill discovery

The disposable project contained one probe skill at
`.agents/skills/probe/SKILL.md`. Calling `skills/list` with the project as its
working directory returned that entry with `scope: repo`, `enabled: true`, and
the expected project-relative location. This is direct discovery evidence, not
an inference from the directory listing.

### Agent-role directory scan and validation

The same project contained a valid `.codex/agents/probe.toml` with the required
`name`, `description`, and `developer_instructions` fields. A trusted project
started a root thread successfully with that file present. Replacing the file
with an unterminated TOML string produced the observed
`Ignoring malformed agent role definition` parse error before any provider
turn. This is positive evidence that the supported build scans the role
directory and validates malformed TOML. The app-server response does not
enumerate a named role, so this slice deliberately does **not** claim that a
valid role was available to a spawned subagent. A live model turn was not used.

Project-local `.codex` config must be trusted before Codex applies project
config, hooks, and exec policies. The app-server warning explicitly said that
skills still load while those project-local surfaces remain disabled. The
probe therefore records trust as a prerequisite rather than silently treating
an untrusted project as a successful adapter installation.

### Instruction precedence

With both files present in the same disposable directory, `thread/start`
reported `AGENTS.override.md` as the selected instruction source instead of
`AGENTS.md`. With only `AGENTS.md` present, it reported that file. This is the
measured same-directory precedence used by the canary design:

`AGENTS.override.md` > `AGENTS.md`.

The probe does not claim a broader inheritance order than the runtime actually
reported. In particular, no Astra/Luna `AGENTS.md` is copied into Luciazero or
into a user's project by this slice.

### Root-only baseline

Before any adapter file was installed, the probe created an ephemeral root
thread in the disposable project and left it idle. No provider was started,
no global Luciazero file was changed, and no project adapter file was
installed. A live task remains part of the later manual canary, where its
inputs and outputs can be measured without conflating discovery with model
behavior.

## Reproduction contract

The evidence was produced with these bounded operations in a disposable
project and disposable `CODEX_HOME`:

1. create one valid and one intentionally malformed project agent definition
2. create one repo-scoped skill and two instruction-file precedence fixtures
3. trust only the disposable project
4. start `codex app-server --stdio`
5. call `initialize`, `thread/start`, and `skills/list`
6. record only counts, scopes, selected filenames, versions, and hashes

The structural baseline contains no prompt text, credentials, rollout payloads,
or machine-local paths. The probe is read-only with respect to Luciazero and
the real global Codex/Luciazero configuration. To roll back Slice 0, remove
the two evidence files added by this slice; no runtime state needs migration.

## Slice 1 source fixtures

Slice 1 is closed at the source-fixture boundary. Luciazero now owns five
model-neutral role profiles under `adapters/astra-luna/agents/`, renamed with
the `lucia-` prefix. Explorer, researcher, and reviewer are read-only;
worker and tester are workspace-write. Every role carries a bounded report
contract and no model or product-tier choice.

The three files under `adapters/astra-luna/presets/` are adapter-owned
fragments for a future project materializer, not files to copy into global
Codex state or pass to Codex as a complete configuration. `model-neutral.toml`
only enables the bounded agent concurrency setting. `pro.toml` and
`plus.toml` record root, default-subagent, and named-role routing separately;
they do not contain MCP, hooks, approval, sandbox, or global-home settings.

`scripts/check-astra-luna-adapter-slice1.py` is the contract guard. It rejects
role permission drift, model IDs in canonical roles, preset safety-key leaks,
missing roles or presets, upstream `AGENTS.md`, and source-pin drift. Its
mutation fixtures run from temporary copies, so this slice has not installed
anything into a real project or changed global configuration.

## Slice 2 orchestration skill

The project-scoped `lucia-orchestrator` skill is now present under the adapter
tree but is deliberately absent from `skills/catalog.txt`. It references the
existing `/ready`, `/debug`, `/done`, and `/retro` skills instead of copying
their doctrine. Its delegation decision is a three-way conjunction: bounded
work, measurable benefit, and runtime plus user authority. If any term is
false, the root continues and reports no delegation.

The skill names only the five `lucia-*` roles, keeps worker ownership bounded,
requires visibility for failed/cancelled work and material reviewer findings,
and reserves final repository verification for the root. It never claims a
role ran without runtime start evidence. `docs/assets/astra-luna-slice2-behavior.json`
holds the six offline behavior fixtures; the checker and mutation cases run
from temporary copies. No project or global configuration, model routing,
provider session, or canary was used.

These results are static contract/fixture validation only, not runtime
behavior evidence. Provider-backed role selection and runtime behavior remain
acceptance work for Slice 3. The role-file protocol described below is a
separate harness-attestation milestone: its hash/nonce/PID ack proves which
bytes were presented to a provider process, but does not prove that a provider
selected a named role or applied its `developer_instructions`.

## Slice 3 canary plan (review draft)

This is a plan, not evidence that a canary has run. It authorizes no provider
session and no quota spend. Review must approve `${CANARY_ROOT}` and a numeric
quota ceiling before any adapter file is copied.

### Target and files

The review target is the non-production `shrinkly-review` checkout of Shrinkly,
branch `codex/review-audio-share-2`, at commit
`5a9faf0a535353e5f6ebf8ee8626dfe941812d21`. Its target verification command is
`npm run verify` (`npm run typecheck && npm test`). Re-check that exact commit,
clean status, and script immediately before launch. Its observed origin is
`https://github.com/ohm41321/shrinkly-compress.git`; cells must be cloned from
a source checkout containing that SHA rather than silently substituting
`origin/main`.

Create eight fresh disposable cells from that SHA (`C1-root`, `C1-adapter`,
through `C4-root` and `C4-adapter`). Assert the SHA, empty `git status`, and
matching starting manifests for `AGENTS*`, `.codex/`, and `.agents/` before
each cell. Record the global Slice 0 manifest once. No cell is reused, and no
task output is carried into another cell.

Copy only these adapter-owned files, with `model-neutral.toml`:

```text
.codex/agents/lucia-{explorer,researcher,worker,tester,reviewer}.toml
.agents/skills/lucia-orchestrator/SKILL.md
```

If a project `.codex/config.toml` agent block is required, snapshot it and
merge only that block. Do not copy upstream `AGENTS.md` or change global
Luciazero/Codex doctrine, model, approval, sandbox, MCP, hooks, or Agent Bus
state. `pro.toml` and `plus.toml` are not part of Slice 3.

### Frozen corpus and positive role proof

Freeze these exact prompts before launch; every cell uses `npm run verify`:

```text
C1: In README.md, change the English title phrase "Smarter quality" to
"Smarter output". Do not modify any other file. Run npm run verify and report
the result.

C2: Add a pure formatBytes(bytes) helper in lib/compress.ts, use it wherever
result sizes are displayed in components/Compressor.tsx, and add unit coverage
for 0 bytes, 1024 bytes, and 1 MiB in scripts/video-plan.test.ts. Preserve the
existing binary-unit behavior. Run npm run verify and report the result.

C3: Reproduce and fix a queue-state regression in the browser flow: after one
queued item fails, adding a second item must leave the failed item visible,
allow the new item to run, and keep the batch summary accurate. Add a failing
test or deterministic reproduction before the fix, update the smallest set of
components/lib code needed, and run npm run verify. Report the red and green
results. If the pinned baseline does not produce a deterministic red result,
stop this cell as unassessable; do not invent a failure or spend a retry.

C4: Using only the repository README, app/, components/, lib/, and package
metadata, write docs/canary-research.md comparing the current on-device
processing flow with the project's documented privacy boundary. Cite each
claim by path and line or symbol, state one unresolved risk, and add no
runtime dependency. Run npm run verify and report the result.
```

Run each prompt once root-only and once with the adapter. C1 must remain
root-only. C2 maps with explorer, gives one worker the edit, and uses tester;
C3 requires explorer/worker/tester and reviewer; C4 uses researcher and
reviewer. The adapter runs must produce both of the following for all five
`lucia-*` roles:

1. Harness evidence: a wrapper-owned start and a verified role-file
   attestation with the exact profile digest.
2. Runtime evidence: an independent provider/runtime event showing that the
   named role was selected and its instructions were applied, carrying a role
   identifier and applied-profile digest (or an equivalent reviewed proof).

A parse result, absence of a warning, role prose, generic provider ack, or
wrapper `--role` label is not named-role runtime proof. If the selected runtime
cannot expose this evidence, stop and leave Slice 3 open; request a separately
approved runtime adapter or smoke task instead of treating harness
attestation as role discovery.

### Quota boundary and rollback

Preparation, guards, rollback, and `./test.sh` spend no provider quota. The
planned budget is fixed before launch:

| Cell | Root starts | Role starts |
| --- | ---: | ---: |
| C1-root | 1 | 0 |
| C1-adapter | 1 | 0 |
| C2-root | 1 | 0 |
| C2-adapter | 1 | 3 (explorer, worker, tester) |
| C3-root | 1 | 0 |
| C3-adapter | 1 | 4 (explorer, worker, tester, reviewer) |
| C4-root | 1 | 0 |
| C4-adapter | 1 | 2 (researcher, reviewer) |
| **Total** | **8** | **9** |

The hard ceiling is **17 provider session starts**. It is not a token or cost
ceiling: approval must name a provider-specific token/cost ceiling as a second
mandatory hard boundary. The runtime quota meter is telemetry only; it cannot
authorize a spawn, extend the ceiling, or replace the approved provider limit.
If that meter cannot be observed for the selected runtime, do not start the
canary.

Use the checked-in `scripts/astra_luna_canary_budget.py` wrapper for every
provider command. Root and role starts deliberately have different entry
points:

```text
python3 scripts/astra_luna_canary_budget.py init --ledger <ledger>
python3 scripts/astra_luna_canary_budget.py root --ledger <ledger> \
  --cell C1-root -- codex --disable multi_agent --disable multi_agent_v2 <root-args>
python3 scripts/astra_luna_canary_budget.py spawn --ledger <ledger> \
  --cell C2-adapter --role lucia-worker \
  --role-file <cell>/.codex/agents/lucia-worker.toml -- <provider> <args>
```

The `root` subcommand rejects a command unless it is Codex with explicit
`--disable multi_agent --disable multi_agent_v2` flags at the executable
boundary, rejects conflicting enable flags and uninspected `--config`/`-c`
native-feature overrides before reservation or `Popen`. It prints
`ROOT_NATIVE_MULTI_AGENT=disabled` and `ROOT_NATIVE_MULTI_AGENT_V2=disabled` as
pre-start evidence. The generic `spawn`
subcommand rejects a role-less request; every adapter role must therefore use
`spawn --role <lucia-role> --role-file <matching-lucia-role.toml>`. The wrapper
requires a regular UTF-8 `.toml` role profile containing non-empty `name`,
`description`, `sandbox_mode`, and `developer_instructions` fields; its basename
and declared `name` must match the role. It records the SHA-256 and refuses the
reservation when that binding is missing or malformed. A role command whose executable is Codex is held
to the same native-spawn barrier. This is the harness boundary chosen for
Slice 3: the root and any Codex role process cannot create native subagents
because that feature is disabled, and all nine planned role sessions (covering
five role types) are separate, direct, wrapper-owned starts counted in the
ledger. The wrapper passes the exact role file, digest, nonce, and a private
acknowledgement path in the provider environment. The provider must read the
file, independently calculate that digest, and invoke the checked-in
`scripts/astra_luna_role_ack.py` helper through `LUCIAZERO_ROLE_ACK_TOOL`.
The helper writes a nonce- and provider-PID-bound record; only a verified ack
can end in `completed`. A missing, stale, changed, or mismatched ack always
increments `failed_binding` and returns a non-zero status. If the provider also
exits non-zero, the terminal reservation state is `failed_exit` while the
binding failure remains recorded; a clean provider exit becomes
`failed_binding`. Thus a generic provider process with only a `--role` label
cannot count as that role. This attests the exact
bytes supplied to the process; it does not claim that Claude or Codex
automatically loads a foreign provider's role-file format. They are not claims
that Codex native subagent events were observed.

Before requesting provider approval, verify the selected Codex runtime's
effective feature state without starting a conversation and retain the two
`false` rows as preflight evidence:

```text
codex features list -c features.multi_agent=false \
  -c features.multi_agent_v2=false
```

If either native-collaboration feature is not reported disabled, stop the
canary; the wrapper flags alone are not permission to proceed.

The wrapper's single-writer reservation ledger rejects duplicate `(cell, role)`
keys, roles not listed for that cell, a second root reservation, and totals
above 17 before invoking the provider. It records `refused_quota` without
starting a process; a reserved but failed start consumes its slot and is never
retried. A direct provider call, a native collaboration attempt, or an
unguarded role-less spawn outside this seam invalidates the canary. If
reserve-before-spawn or the native-spawn barrier cannot be enforced, do not
start the canary.

Keep `planned_budget` separate from `observed_usage` (started, failed,
binding failures, refused, completed) collected from runtime events. No extra
turns, automatic
retries, Pro/Plus preset, or managed dispatch are allowed. Non-authoritative
fields remain `unknown`, never an estimate, when unavailable; the required
provider token/cost meter being unavailable is a preflight failure. The offline proof
`python3 scripts/test_astra_luna_canary_budget.py` covers duplicate and
concurrent reservations, failed starts, role-file/name/hash binding and
provider acknowledgement failures, roles outside the matrix, an
eighteenth-slot attempt against the 17-start plan, all nine explicit role
sessions across five role types, and the native-spawn barrier (including the
unlabelled and indirect Codex bypass paths).

Before copying in each cell, snapshot exact bytes/modes/symlinks and the global
manifest. Stop on any global change, unbounded process, hidden failure,
permission drift, or non-idempotent rewrite. Terminate only processes started
by that cell. First remove byte-identical adapter files and restore the project
config fragment. Then record the task patch/untracked-artifact manifest and
discard that disposable cell; no task artifact crosses into another cell. If
ownership is uncertain or a user edit is detected, leave it untouched and
report the conflict. Never invoke the global uninstaller.

### Exit evidence

Keep raw provider records outside the public repository; publish only a
redacted structural summary and hashes. Slice 3 passes only when C1 stays
root-only, delegated writes have one bounded owner, all nine role sessions
across five role types have verified role-file attestations **and** independent
named-role runtime proof that the provider selected each role and applied its
instructions, read-only roles do not write, failures block completion, root
performs final verification, global manifests are unchanged, and rollback
restores prior bytes. The harness attestation is a milestone, not a substitute
for named-role runtime acceptance; a generic ack or role label cannot close the
gate. Run `./test.sh --fast` during preparation and `./test.sh` at canary
closeout. This section remains unexecuted until review approves the target and
quota ceiling.
