# Roadmap: Project-scoped Astra/Luna Adapter for Luciazero

## Summary

Use the orchestration capabilities of this repository as an optional,
project-scoped adapter for an existing Luciazero installation. Do not merge a
second orchestration core into Luciazero. Luciazero remains the global policy,
safety, verification, closeout, skills, and Agent Bus layer. Astra/Luna adds
project-local agent definitions, model routing, and delegation guidance.

```text
Luciazero global policy (AGENTS.md)
  -> safety / verification / closeout / Agent Bus
  -> root orchestrator
      -> explorer / researcher (read-only)
      -> worker (bounded writes)
      -> tester (verification)
  -> reviewer (read-only, adversarial)
  -> root integration, full verification, /done
  -> /retro for durable findings
```

The adapter must not install the Astra/Luna `AGENTS.md` into the target
project until its instruction precedence has been explicitly reviewed.

## Goals

- Add optional, repeatable multi-agent orchestration to Luciazero projects.
- Preserve Luciazero's `plan -> change -> fastest relevant check -> fix` loop.
- Keep small, localized work root-only.
- Delegate complex or parallel work using bounded ownership.
- Require command-backed verification before completion.
- Measure token usage, rate-limit impact, wall time, and agent participation.
- Make project-scoped installation and rollback safe for repositories with
  existing Luciazero config.
- Keep Luciazero's global installer, doctrine, MCP, hooks, and Agent Bus as the
  source of truth for those concerns.

## Non-goals

- Replacing Luciazero's safety, production, or destructive-action rules.
- Installing the Astra/Luna `AGENTS.md` without a separate review.
- Changing `~/.codex/config.toml`, global model defaults, MCP, or hooks in the
  first integration milestone.
- Requiring the Astra/Luna model IDs when the target runtime does not support
  them.
- Building a second agent runtime, model provider, backend, or user interface.
- Automatically deploying or changing production systems.

## Facts and assumptions

### Confirmed in the Astra/Luna repository

- Pro routes root orchestration to Astra and execution roles to Luna.
- Plus routes root orchestration and execution roles to Luna while retaining an
  Astra reviewer.
- Five roles exist: explorer, worker, tester, reviewer, and researcher.
- The shell installer can install `.codex`, `.agents`, and `AGENTS.md` into an
  existing directory, so its default component flow must not be used blindly
  against an existing Luciazero installation.
- `scripts/token_usage.py` reads Codex rollout JSONL files and emits Markdown or
  JSON usage reports.
- The targeted Python test suite contains five passing tests.

### Confirmed in the installed Luciazero environment

- Luciazero's Codex installer writes a managed doctrine block to
  `~/.codex/AGENTS.md` and managed skills under `~/.codex/skills/`.
- Luciazero already provides canonical `ready`, `plan`, `debug`, `done`,
  `reviewer`, `lucia-relay`, `lucia-bus`, `discipline-report`, and `retro`
  skills for Codex.
- The current machine has `~/.codex/.luciazero-managed` and an existing
  `~/.codex/config.toml`.
- The current machine's `~/.codex/config.toml` contains
  `mcp_servers.luciazero-bus`. This is observed machine state, not a contract
  of Luciazero's installer; `install-codex.sh` intentionally does not edit the
  central MCP configuration.

### To confirm before implementation

- The target project's effective project-scoped Codex configuration and model
  availability.
- How the installed Codex runtime discovers `.codex/agents/*.toml` and
  `.agents/skills/*` relative to a project.
- Whether any target project already has agent roles that should be extended
  instead of duplicated.
- The format and location of discipline or stop-outcome logs.
- Whether the first release should support project-only installation or a
  separately reviewed optional installer command.

## Policy precedence

Use this as the intended adapter contract, then verify the actual runtime
precedence in Phase 0:

1. Explicit user instructions.
2. Luciazero global safety, verification, and closeout policy.
3. Existing target-project instructions that have been reviewed.
4. Project-scoped Astra/Luna delegation policy.
5. Role-specific agent instructions.
6. Model and reasoning defaults.

The adapter must not create a second copy of Luciazero's `ready`, `debug`,
`done`, or `retro` rules. It should reference those canonical skills. The root
agent always owns architecture, decomposition, integration, final verification,
and the user-facing result. Subagents provide bounded evidence or
implementation; they do not own overall direction.

## Phase 0: Inventory and baseline

### Work

- Treat the existing Luciazero install as the baseline; do not install Astra/Luna
  components yet.
- Inspect `~/.codex/AGENTS.md`, its Luciazero markers,
  `~/.codex/.luciazero-managed`, `~/.codex/skills/`, and the existing global
  `~/.codex/config.toml`.
- Record `mcp_servers.luciazero-bus` if present, but do not treat its presence
  as an installer guarantee or modify it.
- Inspect the target project's own `AGENTS.md`, `.codex/`, `.agents/`, and
  existing role names before selecting the import surface.
- Read Luciazero project notes before changing any covered area.
- Use Luciazero's existing checks as the baseline: `./test.sh --fast` for the
  intermediate loop and `./test.sh` for full closeout/CI verification.
- Record baseline behavior for one root-only task and one multi-file task.
- Record current token usage and wall time when rollout logs are available.

### Acceptance criteria

- The adapter's import files and owners are listed.
- The target project's fastest relevant check and Luciazero full verification
  command are known.
- Existing model, permission, sandbox, MCP, hook, and skill settings are
  documented.
- The global Luciazero install is unchanged after inventory.
- Any missing target-project verification command is handled through
  Luciazero's `/ready` procedure before implementation continues.

### Rollback point

No global or target-project changes have been made.

## Phase 1: Define the project-scoped adapter contract

### Work

- Define the boundary: Luciazero owns policy and proof; Astra/Luna owns
  project-local delegation and model routing.
- Define the root-only versus delegated task gate.
- Reuse Luciazero's hypothesis-first debugging requirement and existing
  `/ready`, `/debug`, `/done`, and `/retro` workflows.
- Define one-writer-per-file or one-writer-per-subsystem ownership.
- Require every delegated task to specify objective, scope, context,
  constraints, deliverable, and acceptance criteria.
- Require failed, cancelled, or incomplete subagent work to be reported rather
  than silently replaced.
- Require final root verification even when a tester subagent reports success.
- Record the runtime precedence result rather than assuming that a project
  instruction can never override a global instruction.

### Delegation gate

Use root-only execution when the task is small, localized, and gains little
from independent exploration, testing, research, or review.

Treat delegation as a candidate when at least one condition applies:

- The task spans multiple files, modules, services, or components.
- Two or more independent workstreams exist.
- Repository exploration is required before implementation.
- The bug crosses component boundaries.
- Current or version-specific external facts must be verified.
- Independent review materially reduces correctness or safety risk.
- The user explicitly requests agents, delegation, or parallelism.

Delegate only when the work can be bounded independently, the extra agent is
likely to improve evidence or elapsed time, and the active runtime/user policy
authorizes spawning. File count alone is not authority to spawn. If spawning is
unavailable or forbidden, keep the work root-owned and report that no
delegation occurred; do not pretend a subagent ran.

### Acceptance criteria

- Luciazero remains the only source of truth for safety, verification, closeout,
  and Agent Bus behavior.
- A trivial one-file task remains root-only.
- A multi-module task either delegates one independently bounded workstream or
  records why delegation would not help or is not authorized.
- A debugging task records a hypothesis and reproduction before code changes.
- A failed verification command prevents completion.
- The contract contains no duplicate copy of Luciazero's core doctrine.
- No global `AGENTS.md`, MCP, hook, or model configuration is modified.

### Rollback point

Remove the adapter contract; no global or project runtime configuration has
changed.

## Phase 2: Import project-scoped role profiles and routing

### Work

- Use the Astra/Luna repository as input, not as an installed tree. Import its
  project-scoped role surface into Luciazero-owned adapter sources, rename the
  roles `lucia-explorer`, `lucia-researcher`, `lucia-worker`, `lucia-tester`,
  and `lucia-reviewer`, and remove model choices from the canonical role
  contracts.
- Do not import this repository's `AGENTS.md` in this phase. Review it as a
  separate instruction-precedence decision only if there is a clear need.
- Do not copy the Astra/Luna `.codex/config.toml` wholesale. Create or update
  the target project's project-scoped config by merging only the agent-related
  definitions.
- Preserve the target's `approval_policy`, `sandbox_mode`, MCP servers, hooks,
  and global model settings in the first milestone.
- Adapt existing role profiles instead of introducing overlapping roles.
- Keep model selection in project config and role profiles, not in workflow
  instructions. Prefer model-neutral defaults when model availability is
  uncertain.
- Preserve the following permission boundaries:

| Role | Default access | Responsibility |
|---|---|---|
| Explorer | Read-only | Map files, symbols, tests, dependencies, and flows |
| Researcher | Read-only | Verify current external or version-specific facts |
| Worker | Workspace write | Implement one bounded, owned change |
| Tester | Workspace write | Reproduce and verify; edit tests only when authorized |
| Reviewer | Read-only | Attempt to refute correctness and identify residual risk |

- Require concise reports containing conclusions, paths or symbols, commands,
  results, and remaining risks.
- Keep the project-scoped concurrent-agent limit at two to four until canary
  results justify increasing it.

### Acceptance criteria

- Every role loads successfully in the target Codex runtime.
- Read-only roles cannot modify the workspace.
- Worker and tester changes remain within their delegated ownership.
- Changing the plan or project default model does not require editing workflow
  logic.
- The global Luciazero config, global model, MCP servers, hooks, and doctrine
  are unchanged.
- The Astra/Luna `AGENTS.md` is not present in the target unless explicitly
  reviewed and approved.

### Rollback point

Remove only the newly imported role/skill files and restore the previous
project-scoped agent configuration block. Do not touch the global Luciazero
installation.

## Phase 3: Create `lucia-orchestrator`

### Work

- Derive a project-scoped `lucia-orchestrator` from the upstream
  `astra-orchestrator`. Keep it outside `skills/catalog.txt` in the first
  milestone so ordinary global/plugin installs do not enable orchestration.
- Remove model-specific requirements from the delegation logic, while leaving
  model routing in the project-scoped config/role files.
- Make the skill reference Luciazero's canonical `ready`, `debug`, `done`, and
  `retro` skills instead of copying their doctrine.
- Add explicit adapter gates for hypothesis, verification, review, `/done`, and
  `/retro`.
- Use the following default lifecycle:

```text
classify root-only/delegated
  -> establish hypothesis or map the repository
  -> decide architecture and ownership
  -> bounded implementation
  -> fastest relevant check
  -> adversarial review when risk warrants it
  -> fix material findings
  -> full verification
  -> /done
  -> /retro when a dead end or footgun is worth preserving
```

- Do not spawn every role mechanically. Spawn only roles that materially
  improve the task, while requiring at least one real subagent whenever the
  delegation gate is met.
- Treat subagent spawning as runtime behavior to be tested, not as an
  enforcement guarantee supplied by Markdown alone.

### Acceptance scenarios

1. A typo correction completes without spawning a subagent.
2. A multi-file feature uses exploration before bounded implementation.
3. A cross-component bug is red before the fix and green afterward.
4. A test failure prevents `/done` and the final success claim.
5. A material reviewer finding is fixed and reverified.
6. A subagent failure remains visible in the final result.
7. Existing Luciazero `/ready`, `/debug`, `/done`, and `/retro` behavior remains
   canonical and is not duplicated by the adapter.

### Rollback point

Disable or remove the project-scoped `lucia-orchestrator` adapter; existing
Luciazero global behavior remains active.

## Phase 4: Canary the adapter before changing installers

### Work

- Do the first migration manually in one non-production project; do not run
  the Astra/Luna installer with all components enabled against Luciazero.
- Copy only the Luciazero-owned adapter output into the canary:
  `.codex/agents/lucia-*.toml` and
  `.agents/skills/lucia-orchestrator/`.
- Create or update the target project's `.codex/config.toml` with only the
  agent-related definitions needed by the adapter.
- Do not copy the Astra/Luna `AGENTS.md` until its instructions have been
  reviewed against Luciazero's global doctrine and the target project's own
  instructions.
- Do not change `approval_policy`, `sandbox_mode`, MCP servers, hooks, or the
  global model in the first canary.
- Verify that the current Luciazero `mcp_servers.luciazero-bus` remains
  untouched. Its presence is useful runtime context, not a dependency that the
  adapter installer may assume or create.
- After the manual canary proves the integration, design an optional adapter
  installer with dry-run, explicit component selection, conflict detection,
  managed snapshots, and rollback. Keep it separate from Luciazero's global
  `install-codex.sh` path until that contract is reviewed.

### Acceptance criteria

- The manual canary changes only project-scoped role, skill, and agent config
  files.
- Global Luciazero `AGENTS.md`, skills, MCP, hooks, model, and Agent Bus state
  remain unchanged.
- The Astra/Luna `AGENTS.md` is absent unless separately reviewed and approved.
- Re-running the manual migration is idempotent.
- Root-only and delegated workflows both behave as specified.
- A failed check blocks closeout through Luciazero's existing workflow.
- A rollback removes only project-scoped adapter files and settings.

### Rollback point

Delete the project-scoped adapter files and restore the previous project agent
configuration. Do not run the global Luciazero uninstaller and do not alter
`~/.codex`.

## Phase 5: Integrate observability

### Work

- Adopt `scripts/token_usage.py` as a read-only reporting tool.
- Preserve Markdown and JSON output.
- Add Luciazero-specific fields only after the stop-outcome log schema is
  confirmed.
- Establish the Luciazero baseline with `./test.sh --fast` during iteration and
  `./test.sh` at closeout. Do not use a live quota-spending gate as the default
  baseline.
- Compare root-only and delegated runs using:

  - agent count and roles
  - uncached and cached input
  - output and reasoning tokens
  - wall time
  - five-hour and seven-day rate-limit deltas
  - verification result
  - reviewer findings
  - human intervention count

### Acceptance criteria

- Reports group root and subagent threads into the correct session.
- Guardian or automatic-review threads are consistently included or excluded.
- Reports handle both current and supported legacy rollout source shapes.
- Reading reports does not modify session logs.
- Schema mismatches fail clearly instead of silently reporting misleading
  totals.
- Baseline and adapter runs use the same Luciazero verification tier and the
  same recorded prompts.

### Rollback point

Remove the reporting integration; orchestration behavior is unaffected.

## Phase 6: Verification and regression coverage

### Required coverage

- Root-only and delegated task classification.
- Role loading, model inheritance, and explicit model overrides.
- Read-only and workspace-write permission boundaries.
- Existing `AGENTS.md` preservation.
- Fresh install, update, dry-run, idempotence, conflict, and rollback paths.
- Subagent failure, verification failure, and reviewer finding handling.
- Token report grouping, role parsing, guardian exclusion, and JSON output.
- Project-scoped adapter install/update/rollback behavior.
- Preservation of the global Luciazero install, including `AGENTS.md`, managed
  skills, MCP, hooks, model, and Agent Bus state.

### Luciazero verification commands

```bash
./test.sh --fast
./test.sh
git diff --check
```

Use `./test.sh --fast` for the intermediate loop and `./test.sh` (equivalent to
the repository's full closeout tier) for final verification. Do not run live
provider/quota gates unless the user explicitly approves that external cost.

When changing the standalone Astra/Luna source repository, additionally run
its targeted checks:

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
sh -n setup.sh
```

The target project's own CI-equivalent command remains required for the
project-scoped adapter. If it does not have one, use Luciazero's `/ready`
procedure to create the smallest appropriate command before implementation.
The verification entry point must fail when no tests are discovered; a generic
test-discovery command that returns success while running zero tests is not
acceptable evidence.

### Acceptance criteria

- The original reproduction for every fixed defect is retained as a regression
  test.
- Targeted checks pass after each independently reversible step.
- The full CI-equivalent verification passes once at closeout.
- The final diff contains no unintended files or whitespace errors.
- An independent adversarial review reports no unresolved material findings.
- `./test.sh --fast` and `./test.sh` both pass with the adapter files present.

## Phase 7: Canary rollout

### Work

- Enable the project-scoped adapter in one non-production repository first;
  leave the global Luciazero installation unchanged.
- Keep it opt-in and limit concurrency to two to four agents.
- Run the same recorded prompts in root-only and orchestrated modes:

  1. single-file fix
  2. multi-file feature
  3. cross-component bug
  4. research-heavy change

- Repeat each comparison enough times to expose variance.
- Review correctness, rework, latency, usage, and human intervention rather
  than relying on total token count alone.
- Run `./test.sh --fast` during the canary loop and `./test.sh` at canary
  closeout. Record whether any live provider gate was intentionally omitted.

### Exit criteria

- Delegation improves quality or latency for complex work.
- Small tasks remain cheaper and faster in root-only mode.
- No task reports success after a failed required check.
- No existing repository instructions or config are lost.
- The global Luciazero `AGENTS.md`, skills, MCP, hooks, model, and Agent Bus
  remain unchanged.
- Usage remains acceptable for the selected plan.

### Rollback trigger

Disable the feature when it increases regressions, frequently exceeds plan
limits, breaks instruction precedence, or causes unsafe concurrent edits.

## Phase 8: Documentation and release

### Deliverables

- Luciazero orchestration architecture and precedence documentation.
- Role and permission reference.
- Installation, migration, update, and rollback guides.
- Pro, Plus, and model-neutral configuration examples.
- Verification command and troubleshooting guide.
- Token measurement protocol and canary results.
- Known runtime and rollout-schema compatibility limits.

### Release criteria

- All Phase 6 checks pass.
- Canary exit criteria are satisfied.
- No agent remains running when the root completes.
- Material review findings are resolved.
- Project-scoped installation and rollback have been exercised from clean
  temporary targets.
- No release step requires modifying the global Luciazero MCP, hooks, model, or
  doctrine settings.
- The final release diff passes Luciazero's `/done` procedure.

## Canonical implementation plan

Luciazero owns this adapter. The Astra/Luna repository is pinned upstream
input, not the release or installation authority. Complete these slices in
order; each must be independently reversible and green before the next starts.

### Slice 0 — Pin the source and prove runtime discovery

Add `docs/astra-luna-adapter.md` with the upstream repository and commit,
observed Codex version/config schema, and the measured instruction-precedence
result. Add a structural baseline under `docs/assets/` containing hashes and
counts only—no prompt text, credentials, rollout payloads, or machine paths.

On a disposable project, prove that the supported Codex build discovers
`.codex/agents/*.toml` and `.agents/skills/*`. Snapshot the target project's
`AGENTS.md`, `.codex/`, and `.agents/`, plus the global Luciazero surfaces from
Phase 0. Record one root-only thread baseline before installing any adapter
file.

**Pass/fail:** fail if discovery or precedence is inferred instead of observed,
or if inventory changes a global file. Run `./test.sh --fast` for the new
documentation/fixture checks.

**Rollback:** remove the evidence documents; no runtime file has changed.

**Exit scope:** Slice 0 closes on observed project-skill discovery, role
directory scanning, malformed-role rejection, same-directory instruction
precedence, and zero global/config footprint. Named-role spawn discovery and a
live provider task are intentionally not Slice 0 requirements; they require a
provider-backed canary and are acceptance criteria of Slice 3.

**Implementation status (2026-09-10, closed at this scope):** evidence is captured in
`docs/astra-luna-adapter.md` and the redacted structural inventory at
`docs/assets/astra-luna-adapter-baseline.json`. Codex `0.154.0` discovery was
observed through app-server `skills/list` and `thread/start`: the repo skill
was returned as `scope: repo`, the role directory was scanned, malformed TOML
was rejected, and `AGENTS.override.md` won over `AGENTS.md` in the same
directory. The probe does not claim named-role spawn discovery because the
zero-provider response did not expose a role enumeration. No provider turn,
global-file write, or adapter install was used. The remaining live-model proof
is tracked by Slice 3 rather than blocking this discovery slice.

### Slice 1 — Add model-neutral role profiles and separate presets

Use this canonical source layout:

```text
adapters/astra-luna/
  agents/
    lucia-explorer.toml
    lucia-researcher.toml
    lucia-worker.toml
    lucia-tester.toml
    lucia-reviewer.toml
  presets/
    model-neutral.toml
    pro.toml
    plus.toml
```

Role files own responsibilities, permission boundaries, and report contracts;
they contain no product tier or model choice. `model-neutral.toml` enables
agents/concurrency without a model ID. `pro.toml` maps the project root and
reviewer to Astra and execution roles to Luna. `plus.toml` maps the project
root/execution roles to Luna and reviewer to Astra. Presets are project-scoped
fragments and contain no MCP, hooks, `approval_policy`, or `sandbox_mode`.

**RED before implementation:** add a `test.sh` adapter contract that fails while
the files are absent, then proves exactly five unique `lucia-*` roles exist;
explorer/researcher/reviewer are read-only; worker/tester are workspace-write;
canonical roles contain no Astra/Luna model ID; presets contain no forbidden
security/global keys; no adapter tree contains `AGENTS.md`; and upstream source
plus commit are recorded.

**Proof:** the adapter contract's stable `ok` line through `./test.sh --fast`.

**Rollback:** delete `adapters/astra-luna/`; no catalog/global install changed.

**Implementation status (2026-09-10, source-fixture scope):** closed. The five
`lucia-*` role profiles and the three model-routing preset fragments are
checked by `scripts/check-astra-luna-adapter-slice1.py`. The guard also runs
temporary-copy mutations for permission boundaries, preset safety keys, and
the forbidden upstream `AGENTS.md`. No project or global configuration has
been installed; live role selection remains a Slice 3 canary requirement.

### Slice 2 — Add the project-scoped orchestration skill

Create:

```text
adapters/astra-luna/skills/lucia-orchestrator/SKILL.md
```

The skill owns classification, decomposition, role selection, bounded
ownership, integration, and visibility of failed/cancelled work. It references
Luciazero's existing `ready`, `debug`, `done`, and `retro` skills instead of
copying them. It requests `lucia-*` roles and contains no model ID. Keep it out
of `skills/catalog.txt` so ordinary global/plugin installs do not enable it.

Delegation is a conjunction:

```text
independently bounded work
  + measurable benefit from another context, parallelism, or review
  + runtime and user authority to spawn
  = delegate
```

If any term is false, root continues and reports that no delegation occurred.
The skill never claims a model or agent ran without runtime start evidence.

**RED before implementation:** extend prompt-contract tests to reject a skill
that duplicates Luciazero doctrine, treats file count alone as mandatory spawn,
embeds Astra/Luna routing, hides failed work, omits root verification, or enters
the global catalog. Add behavior fixtures for trivial root-only work,
authorized parallel work, spawn unavailable, worker scope expansion, failed
tester verification, and a material reviewer finding.

**Proof:** focused prompt/behavior checks, then `./test.sh --fast`.

**Rollback:** remove the project skill/fixtures; role profiles remain inert.

**Implementation status (2026-09-11, contract/skill scope):** closed for this
slice. `adapters/astra-luna/skills/lucia-orchestrator/SKILL.md` is a
model-neutral, project-scoped policy that references the existing Luciazero
skills and requests only `lucia-*` roles. The six behavior fixtures and the
temporary-copy mutation checks are run by
`scripts/check-astra-luna-slice2.py` through `test.sh`. No catalog, project
configuration, global configuration, or model routing changed. Provider-backed
role selection and the manual canary remain Slice 3 work.

### Slice 3 — Run the manual model-neutral canary

**Status: review draft only.** No provider session, canary project, or quota
spend is authorized by this section. The review must approve the target and
the quota ceiling before any adapter files are copied.

#### Review-ready canary plan

**Target and preflight.** The named target for review is the non-production
`shrinkly-review` checkout of Shrinkly, branch
`codex/review-audio-share-2`, at commit
`5a9faf0a535353e5f6ebf8ee8626dfe941812d21`. Its verification command is
`npm run verify` (`npm run typecheck && npm test` from its `package.json`). The
checkout's observed origin is
`https://github.com/ohm41321/shrinkly-compress.git`; the pinned branch commit
must be available in the source checkout used to make the cells.
The checkout was clean when inspected; re-check that exact commit, clean status,
and command immediately before launch. Cells must be cloned from a source
checkout that contains this SHA; do not silently substitute `origin/main` if
the branch is unavailable. If any fact changes, the canary is blocked pending
review.

Create eight fresh disposable cell checkouts from that same commit under a
dedicated `${CANARY_ROOT}`: `C1-root`, `C1-adapter`, through `C4-root` and
`C4-adapter`. No cell may be reused. Before each copy, assert
`git rev-parse HEAD` equals the pinned SHA, `git status --porcelain` is empty,
and the starting manifests for `AGENTS*`, `.codex/`, and `.agents/` equal the
recorded baseline. Do not use Luciazero itself, a production checkout, or a
project whose existing `.codex/` configuration cannot be inspected.
Record the global Luciazero/Codex manifest used by Slice 0 once before launch;
a missing target verification command or a starting-manifest mismatch is a
preflight failure, not permission to improvise a weaker one.

The manual copy is limited to the adapter-owned files:

```text
.codex/agents/lucia-explorer.toml
.codex/agents/lucia-researcher.toml
.codex/agents/lucia-worker.toml
.codex/agents/lucia-tester.toml
.codex/agents/lucia-reviewer.toml
.agents/skills/lucia-orchestrator/SKILL.md
```

If the runtime requires an agent block in project `.codex/config.toml`, merge
only that reviewed block after taking an exact snapshot. Never copy upstream
`AGENTS.md`, replace the project's model/approval/sandbox/MCP/hooks settings,
or modify any global Luciazero/Codex file. Start with `model-neutral.toml`;
`pro.toml` and `plus.toml` are explicitly out of scope for this slice.

**Recorded task corpus.** Freeze the following prompt text and acceptance
command before the first run. Execute each prompt once in its fresh root cell
and once in its fresh adapter cell; the pair uses the same pinned revision,
input files, and verification command. These are the exact prompts, not
summaries:

| ID | Shape and expected root decision | Required adapter evidence |
| --- | --- | --- |
| C1 | One-file README correction; root-only, no spawn | No role start; `npm run verify` passes |
| C2 | Small multi-file utility feature; delegate only after the three-part gate | Explorer maps first, one worker owns the edit, tester verifies, and root integrates |
| C3 | Cross-component bug with a failing reproduction; red before fix, then green | Explorer/worker/tester/reviewer flow; failed checks block closeout |
| C4 | Research-heavy local-doc decision followed by a bounded note | Researcher cites findings, reviewer challenges material claims, and root verifies |

Frozen prompts (the acceptance command for every cell is `npm run verify`):

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

The adapter run must produce two independent classes of evidence for all five
named roles across the corpus. First, the harness must positively record each
wrapper-owned start and an attested instruction binding. Second, the selected
provider/runtime must positively show that the named role was selected and its
role instructions were applied (for example, a provider role-selection/start
event carrying the role identifier and the applied-profile digest). A parse
result, absence of a warning, a role mentioned in prose, or the harness ack by
itself is not named-role runtime proof. If the provider cannot expose this
evidence, stop and request a separately approved runtime adapter/smoke task
rather than silently relabelling the harness attestation as role discovery.

**Provider and quota boundary.** Preparation, contract checks, rollback, and
the normal Luciazero test suite spend zero provider quota. The canary requires
explicit approval with a numeric ceiling immediately before starting. The
planned start budget is fixed before launch and is not inferred from runtime
events:

| Cell | Root starts | Allowed role starts |
| --- | ---: | --- |
| C1-root | 1 | none |
| C1-adapter | 1 | none |
| C2-root | 1 | none |
| C2-adapter | 1 | explorer, worker, tester (3) |
| C3-root | 1 | none |
| C3-adapter | 1 | explorer, worker, tester, reviewer (4) |
| C4-root | 1 | none |
| C4-adapter | 1 | researcher, reviewer (2) |
| **Total** | **8** | **9** |

The hard ceiling is therefore **17 provider session starts**: 8 roots + 9
roles. It is a start ceiling, not a token or cost ceiling. Approval must name a
provider-specific token/cost ceiling as a second, mandatory hard boundary;
there is no approval path that omits it. The runtime quota meter is telemetry
only: it cannot authorize a spawn, extend a ceiling, or replace the approved
provider limit. If the selected runtime cannot expose the meter needed to
observe that hard boundary, do not start the canary.

Enforce the start ceiling with the checked-in wrapper
`scripts/astra_luna_canary_budget.py` and its single-writer, locked reservation
ledger, created before launch. Root and role launches have separate, mandatory
entry points. A root must use
`root --ledger <path> --cell <cell> -- codex --disable multi_agent
--disable multi_agent_v2 ...`; this rejects missing or conflicting
native-collaboration flags before reservation or `Popen`, rejects uninspected
`--config`/`-c` native-feature overrides, and emits
`ROOT_NATIVE_MULTI_AGENT=disabled` plus
`ROOT_NATIVE_MULTI_AGENT_V2=disabled` as pre-start evidence.
Every adapter role must use
`spawn --ledger <path> --cell <cell> --role <lucia-role> --role-file
<cell>/.codex/agents/<lucia-role>.toml -- ...`; a role-less `spawn` is
rejected. The wrapper requires a regular UTF-8 `.toml` role profile containing
non-empty `name`, `description`, `sandbox_mode`, and `developer_instructions`
fields; its basename and declared `name` must match the role. It records its
SHA-256 and refuses the reservation when that binding is missing or malformed.
This is the approved
harness alternative to integrating a provider-internal hook: native Codex
subagents are disabled for the root and for any Codex role process, so the nine
role starts are separate wrapper-owned provider sessions and each is counted.
They cover five role types. The wrapper passes the exact role file, digest,
nonce, and a private acknowledgement path in the provider environment. The
provider must read the file, independently calculate that digest, and invoke
the checked-in `scripts/astra_luna_role_ack.py` helper through
`LUCIAZERO_ROLE_ACK_TOOL`. The helper writes a nonce- and provider-PID-bound
record; only a verified ack can end in `completed`. A missing, stale, changed,
or mismatched ack always increments `failed_binding` and returns a non-zero
status. If the provider also exits non-zero, the terminal reservation state is
`failed_exit` while the binding failure remains recorded; a clean provider exit
becomes `failed_binding`. A generic provider process with only a `--role` label
cannot count as that role.
This attests the exact bytes supplied to the process; it does not claim that
Claude or Codex automatically loads a foreign provider's role-file format. A
direct provider call, a native collaboration attempt, or an
unguarded/indirect Codex role launch is outside the canary and invalidates the
run.
Before provider approval, run the read-only preflight
`codex features list -c features.multi_agent=false -c
features.multi_agent_v2=false` and retain both `false` rows. If the selected
runtime does not report both features disabled, do not start; command-line
flags are not a substitute for an effective-state check.
`reserve(cell, role)` must reject without invoking the provider when the
`(cell, role)` key already exists, the role is not listed for that cell, the
root cell already has its one reservation, or the total reservations would
exceed 17. A rejected reservation records `refused_quota` and starts no
process. A successful reservation is consumed even if the provider fails to
start; it cannot be retried. If the wrapper cannot make this reserve-before-
spawn refusal, the canary is blocked.

Keep `planned_budget` separate from `observed_usage`: the former is the table
above; the latter is populated only from runtime start/exit events and records
started, failed, binding failures, refused, and completed counts. No automatic
retries, extra turns, Pro/Plus preset, or managed dispatch are allowed.
Non-authoritative
fields remain `unknown`, never an estimate, when unavailable; the required
provider token/cost meter being unavailable is a preflight failure. No
live-provider command is added to CI or to `./test.sh`. The offline
enforcing-wrapper proof is
`python3 scripts/test_astra_luna_canary_budget.py`; it covers duplicate and
concurrent reservations, failed starts, role-file/hash/ack binding and failure
cases, roles outside the matrix, an eighteenth-slot attempt against the
17-start plan, all nine explicit role sessions across five role types, and the
native-spawn barrier including the unlabelled and indirect Codex bypass paths.

**Rollback and stop triggers.** Before the first copy in each fresh cell, save
exact bytes, modes, symlink state, and hashes for every target file that may be
touched, plus the global manifest. Stop immediately on a global hash change,
ambiguous config, role permission drift, an unverified or hidden failure, a
non-idempotent rewrite, a quota/rate-limit boundary, or a provider process
without bounded ownership. Terminate only provider processes started by that
cell.

Rollback has two explicit layers. First remove byte-identical adapter files
and restore the snapshotted project config fragment; if a file changed after
installation or ownership is not provable, leave it in place and report the
conflict. Then capture the task patch/untracked-artifact manifest and discard
the entire disposable cell, which is the only operation allowed to remove the
corpus work. No task artifact, generated note, or worktree change is copied to
the next cell. A fresh clone at the pinned SHA is the restoration target for
the next comparison. Never run the global Luciazero uninstaller or delete a
user's global `.codex` state as part of rollback.

**Evidence and exit gate.** Keep raw provider/session records outside the
public repository and publish only a redacted structural summary plus hashes.
For every corpus cell record the exact mode, role starts, verification result,
reviewer findings, wall time, user-started blocking turns, and available
quota telemetry. Slice 3 passes only when C1 stays root-only; delegated writes
have one bounded owner; all nine role sessions across five role types have
verified role-file attestations **and** independent named-role runtime proof
showing that the provider selected each role and applied its instructions;
read-only roles make no writes; failures remain visible and block completion;
root passes final verification; global manifests are unchanged; and rollback
restores the target's prior bytes. The role-file attestation is a necessary
harness milestone, not a substitute for this runtime acceptance criterion. A
generic provider ack, `--role` label, or wrapper ledger entry cannot close the
named-role gate. Run `./test.sh --fast` during preparation and `./test.sh`
after the canary evidence is captured. This plan does not authorize the
canary itself.

### Slice 4 — Build a deterministic project materializer

Only start this after the manual canary passes. The proposed explicit interface
is:

```text
scripts/astra-luna-adapter.sh plan --target <project> --preset model-neutral
scripts/astra-luna-adapter.sh apply --target <project> --preset model-neutral
scripts/astra-luna-adapter.sh status --target <project>
scripts/astra-luna-adapter.sh remove --target <project>
```

`plan` is read-only. `apply` materializes only project `lucia-*` roles, the
project skill, and one narrowly owned `[agents]` block or included fragment
whose syntax was proven in Slice 0. It refuses ambiguous config, symlinks,
unknown presets, unsupported model IDs, and every path that could touch
`AGENTS.md` or `~/.codex`.

Store exact installed bytes/source version in a project ownership directory.
`remove` deletes only byte-identical owned material; customized content remains
with a warning. Publish through same-directory exclusive temporary files,
preserve existing modes, and leave a recoverable prior state on interruption.

**RED before implementation:** sandbox fixtures cover plan-with-no-writes,
clean apply, idempotence, preset change, foreign collision, malformed config,
symlinks at every write boundary, customized owned files, partial failure,
exact rollback, spaces/non-ASCII paths, and unchanged global hashes.

**Rollback:** run `remove`; when ownership is unprovable, stop and keep data.

### Slice 5 — Evaluate Pro and Plus independently

Run the Slice 3 corpus with `pro.toml` and `plus.toml`, one preset at a time.
Confirm model availability first; unsupported IDs are a clean refusal, never a
silent fallback. Compare correctness and latency before token/rate-limit cost.
Changing a model must not require editing a role or orchestration skill.

Keep, revise, or drop each preset independently. The model-neutral adapter may
ship even if neither named preset earns its cost.

### Slice 6 — Closeout and distribution decision

1. Run `git diff --check` and `./test.sh` from a clean tree.
2. Run separate independent security and contract reviews: input-to-write paths
   for the materializer, and role/skill instruction precedence.
3. Resolve blocker/major findings and rerun their regressions.
4. Exercise apply/status/remove on macOS and Linux or WSL in disposable
   project roots while hashing global Luciazero config before/after.
5. Document the source pin, Codex compatibility, presets, rollback,
   observability limits, and distinction from Agent Bus managed workers.
6. Decide separately whether this stays checkout-only, joins npm as inert
   project assets, or gains an explicit CLI route. Ordinary Luciazero installs
   never enable it implicitly.

**Release proof:** `./test.sh` exits zero, the canary reaches its declared
sample gate, both focused reviews have no unresolved material finding, and the
release artifact contains exactly the files allowed by the distribution
decision.

## Decisions fixed by this plan

- Luciazero is the canonical integration owner; upstream is pinned input.
- Orchestration is a project-scoped `lucia-orchestrator` skill.
- Responsibilities are five model-neutral `lucia-*` agent profiles.
- Astra/Luna are preset mappings, never agent identities or workflow rules.
- The first canary is manual and model-neutral.
- The adapter does not modify `AGENTS.md`, global Codex config, MCP, hooks,
  approval policy, sandbox mode, or Agent Bus state.
- No installer or global catalog change happens before the manual canary and a
  separate public-contract/security decision.
