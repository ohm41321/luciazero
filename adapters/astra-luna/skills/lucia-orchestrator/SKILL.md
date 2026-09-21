---
name: lucia-orchestrator
description: Coordinate bounded project work through Luciazero's existing proof and closeout skills when project-scoped delegation is explicitly available.
---

# Luciazero project orchestrator

This is an optional, project-scoped adapter. It is model-neutral and does not
install itself, change global or project configuration, or change model
routing; it does not create a second policy system. Keep
it outside `skills/catalog.txt`; ordinary Luciazero installs must not enable
this skill implicitly.

## Contract boundary

Luciazero remains the source of truth for safety, verification, closeout, and
the Agent Bus. Use the existing `/ready`, `/debug`, `/done`, and `/retro`
skills by reference. Do not copy their doctrine, verification rules, or
closeout wording into this adapter. The root remains responsible for
classification, decomposition, integration, and the user-facing result.

## Delegation gate

Delegate only when all three conditions are true:

1. There is independently bounded work: the objective, owned paths, context,
   constraints, deliverable, and acceptance check are explicit.
2. There is measurable benefit from another context, parallelism, research, or
   an independent review.
3. There is runtime and user authority to spawn the requested role.

These are a conjunction: all three are required. File count alone is not a
reason to spawn. If any condition is false, continue root-only and report
that no delegation occurred. A trivial or localized task should remain
root-only even when a role is available.

## Role selection and ownership

The only selectable roles are `lucia-explorer`, `lucia-researcher`,
`lucia-worker`, `lucia-tester`, and `lucia-reviewer`. Select by responsibility,
not by a hidden provider or product tier:

- `lucia-explorer` maps files, symbols, flows, dependencies, and tests without
  editing.
- `lucia-researcher` verifies current external or version-specific facts
  without editing application code.
- `lucia-worker` implements one bounded change in its assigned workspace.
- `lucia-tester` reproduces and verifies the delegated behavior; it edits tests
  only when explicitly authorized.
- `lucia-reviewer` attempts to refute correctness and reports material risk
  without editing.

Give every write role an explicit ownership boundary. The worker never expands
ownership. If the requested change crosses that boundary, stop and report the
scope expansion to the root instead of touching new paths. A tester's report
does not authorize a worker to broaden its task.

## Canary spawn boundary

For the Slice 3 canary, do not use provider-native subagent tools. Native
Codex `multi_agent` and `multi_agent_v2` collaboration are disabled for every
Codex process in the canary, so a root cannot create an unmetered child. Start
roots only with the checked-in budget wrapper's `root` command and its explicit
`codex --disable multi_agent --disable multi_agent_v2` prefix. Do not add
uninspected `--config` or native-feature `-c` overrides. Start each adapter
role as a separate wrapper-owned
`spawn --role <selected-role> --role-file <matching-role.toml>` invocation. A
role-less `spawn`, a direct provider
call, an indirect Codex executable (such as `env codex`), or a native
collaboration request is an invalid canary event; stop and
report it rather than counting it as a role start. The wrapper's ledger and
`ROOT_NATIVE_MULTI_AGENT=disabled` plus
`ROOT_NATIVE_MULTI_AGENT_V2=disabled` lines are the runtime start evidence.
Every role invocation must also pass the matching
`--role-file <cell>/.codex/agents/<selected-role>.toml`. The wrapper checks that
the file is a regular UTF-8 `.toml` role profile with non-empty `name`,
`description`, `sandbox_mode`, and `developer_instructions` fields whose
declared `name` and basename match the selected role, records its SHA-256, and
exports the binding to the provider. After reading the file, the provider must independently calculate
the same digest and invoke:

```text
python3 "$LUCIAZERO_ROLE_ACK_TOOL" --ack-file "$LUCIAZERO_ROLE_ACK_FILE" \
  --content-sha256 <digest>
```

The nonce- and provider-PID-bound acknowledgement is the evidence that this
process received and attested the exact role bytes. A missing, stale, changed,
or mismatched acknowledgement increments `failed_binding`; a clean provider
exit ends as `failed_binding`, while a provider that also exits non-zero ends
as `failed_exit` with the binding failure retained. Neither is `completed`. A
role label without this binding is never evidence that the role instructions
were used. This is an explicit harness-attestation milestone, not named-role
runtime proof: the Slice 3 exit gate remains open until the provider/runtime
also emits independent evidence that it selected the named role and applied
its instructions. A generic provider ack, wrapper ledger row, or role label
cannot close that gate. This is not a claim that Claude automatically loads
Codex TOML files.
Before provider approval, retain a read-only `codex features list` result with
both `features.multi_agent=false` and `features.multi_agent_v2=false`; if the
effective runtime state is not disabled, do not launch the canary.

## Work protocol

The root writes a bounded task brief before any spawn: objective, scope,
context, constraints, deliverable, acceptance check, and reporting format.
The root may perform a small task itself. For delegated work, record the role,
owned paths, task state, verification command, and returned artifact or report.
Do not silently replace failed work with an unreported second attempt.

Use the existing Luciazero skills for their existing jobs: `/ready` establishes
verification, `/debug` requires a hypothesis and reproduction, `/done` owns
closeout, and `/retro` records durable lessons. This adapter only decides
whether bounded project delegation is worthwhile; it does not restate those
rules.

## Failure and review visibility

Expose failed, cancelled, or incomplete work in the root report with its last
known state, evidence, and remaining risk. A failed verification blocks
completion; never turn a non-zero result into a success by omission. Material
reviewer findings must be surfaced, assigned a disposition, and resolved or
explicitly left as a release blocker. A clean reviewer result is evidence of
review, not evidence that the work was unnecessary.

## Proof and truthful handoff

The root performs final repository verification after all delegated work,
using the repository's actual command and quoting its decisive result. A role
report is not root verification. The adapter never claims a role started, a task ran, or an
artifact exists without runtime start evidence such as a start event, role,
task identifier, timestamp, and returned outcome. Without that evidence say
that the role was not started and continue root-only or ask for authority.

Every handoff names what was attempted, what changed, what command ran, what
failed or was cancelled, and what remains. The root owns the final decision and
the final user-facing answer.
