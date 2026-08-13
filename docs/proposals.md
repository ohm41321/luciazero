# RFC decision record: Agentic skills and feature extensions

Current decisions come first. The original proposal remains below them for
design history, not as usage documentation.

## Decision record — 2026-08-12

This RFC is preserved as the input proposal. The table below is authoritative where the original sketches differ from the implementation.

| Proposal | Decision | Implemented contract |
|---|---|---|
| `/plan` | Accepted with revision | Observable pass/fail evidence; approval only for ambiguity, high stakes, destructive action, public-contract choice, or scope change |
| `/bisect` | Accepted with safety redesign | Detached temporary worktree, repeated endpoints, exit-125 skip, missing-command distinction, trap cleanup; reports first bad commit, then routes to `/debug` |
| `/security-audit` | Merged, no standalone skill | The existing reviewer receives a `security` focus; blocker/major must be fixed or explicitly waived, rather than forcing every warning to be fixed |
| Specialized reviewers | Accepted as focus routing | One portable `reviewer` with `security`, `contract`, and `general` modes; separate focused passes when both risks apply |
| `/discipline-report` | Accepted | `npx luciazero discipline`, schema-v2 privacy-preserving JSONL, legacy reader, `--days`, `--project`, and `--json` |
| Smart target verification | Accepted as repo-owned policy | A monorepo owns `verify-changed` via its native task graph and conservative full fallback; the global hook does not guess path mappings |
| `/handoff` naming/transfer | Superseded by implementation request | `/lucia-relay`: recipient-first routing; full paths on the same machine, pushed repo-relative or inline knowledge across machines; portable JSON + generated Markdown, fingerprint, evidence, drift inspection, and explicit consume |

Component inventory is now centralized in `skills/catalog.txt` and `claude/agents/catalog.txt`; install, status, uninstall, and tests consume those catalogs.

Current source files: [`/plan`](../skills/plan/SKILL.md),
[`/bisect`](../skills/bisect/SKILL.md),
[`/discipline-report`](../skills/discipline-report/SKILL.md),
[`/lucia-relay`](../skills/lucia-relay/SKILL.md), the
[`reviewer`](../claude/agents/reviewer.md), and the
[smart-verification policy](../skills/luciazero-bootstrap/references/smart-verification.md).

---

## Archived proposal text

> The remainder of this file is the original design input, preserved for
> rationale and traceability. Names, paths, severity labels, and code sketches
> below are not the current interface. Use the decision table above and the
> shipped `skills/*/SKILL.md` files as the implementation contract.

### Part 1: Proposed new skills

#### 1. `/plan` — Pre-Implementation & Verification Protocol

##### Role & Purpose
Before making non-trivial code changes or implementing new features, `/plan` prevents vague implementations, scope creep, and unverified assumptions by requiring a structured design and a **falsifiable verification plan** before touching implementation code.

##### SKILL.md Specification (`skills/plan/SKILL.md`)
```markdown
---
name: plan
description: Pre-implementation design protocol requiring a verification-first plan before writing code for new features or major refactors.
---

# /plan Protocol

Run `/plan` before implementing new features, major refactors, or multi-step tasks.

## Protocol Steps

1. **Requirements & Scope Boundaries**
   - State explicit goals and non-goals.
   - List affected modules, public interfaces, and configuration keys.

2. **Verification Plan (Falsifiable First)**
   - For every requirement, define the exact command and decisive output line that will prove completion.
   - If a required test or check does not exist yet, design the test case first.

3. **Smallest Reversible Steps**
   - Break implementation into incremental, independently verifiable steps.
   - Identify potential footguns, backwards-compatibility risks, and rollbacks.

4. **User Alignment Gate**
   - Ask clarifying questions for any high-stakes or ambiguous requirements.
   - Obtain user approval on the plan before editing implementation files.
```

---

#### 2. `/bisect` — Automated Regression Pinpointing

##### Role & Purpose
When a previously passing test or feature breaks (a regression), `/bisect` automates `git bisect` using the repository's verify command to locate the exact offending commit without manual intervention.

##### SKILL.md Specification (`skills/bisect/SKILL.md`)
```markdown
---
name: bisect
description: Automates git bisect using the repo's verify command to pinpoint the commit that introduced a regression.
---

# /bisect Protocol

Use `/bisect` when a feature or test worked in a known good revision but is now failing in `HEAD`.

## Protocol Steps

1. **Identify Revisions & Criteria**
   - Confirm current `HEAD` is failing (bad revision).
   - Identify or locate a known passing commit/tag (good revision).
   - Confirm the exact verify command that reproduces the failure.

2. **Automated Execution**
   - Run `git bisect start <bad> <good>`.
   - Execute `git bisect run <verify_command>`.

3. **Hand-Off to Debug**
   - Report the offending commit hash, author, summary, and diff.
   - Feed the root-cause finding directly into `/debug` to construct a hypothesis and regression test.
   - Run `git bisect reset`.
```

---

#### 3. `/security-audit` — Pre-Done Threat & Vulnerability Audit

##### Role & Purpose
An exit code 0 from functional unit tests does not guarantee security. `/security-audit` conducts an independent security pass over the session's diff to detect secret leaks, unsanitized inputs, permission bypasses, and insecure defaults before calling `/done`.

##### SKILL.md Specification (`skills/security-audit/SKILL.md`)
```markdown
---
name: security-audit
description: Security & threat-modeling review over changes before closeout (secrets, inputs, auth, permissions).
---

# /security-audit Protocol

Run `/security-audit` prior to `/done` whenever changes touch authentication, input parsing, environment variables, or public API endpoints.

## Inspection Checklist

1. **Secrets & Credentials Leakage**
   - Check diff for hardcoded tokens, private keys, API keys, or raw connection strings.
   - Ensure new config variables use `.env` / environment variables.

2. **Input Sanitization & Boundary Validation**
   - Verify all external inputs (HTTP params, CLI arguments, file paths) are sanitized and validated.
   - Check for path traversal (`../`), command injection, SQL injection, or unescaped HTML/CSV.

3. **Authentication & Authorization**
   - Ensure protected endpoints enforce permission/role checks.
   - Confirm error responses fail closed without leaking internal stack traces or database structures.

4. **Verdict**
   - Report findings clearly as `CRITICAL`, `WARNING`, or `PASS`.
   - Fix any `CRITICAL` or `WARNING` finding before declaring `/done`.
```

---

### Part 2: Proposed feature extensions

#### 1. Specialized Reviewer Subagents

##### Concept
Extend the single `reviewer` agent into a specialized panel of subagents invoked by `/done` based on diff risk:

- `claude/agents/security-reviewer.md`: Specializes in vulnerability detection, secret exposure, and input sanitization.
- `claude/agents/contract-reviewer.md`: Specializes in detecting breaking public API changes, schema mutations, and backwards-incompatible interfaces.

##### Agent Definition Example (`claude/agents/security-reviewer.md`)
```markdown
---
name: security-reviewer
description: Adversarial security auditor subagent instructed to refute code changes on security grounds.
tools: read_file, grep_search, list_dir
model: inherit
---

# Role
You are an adversarial security auditor. Your sole task is to find security vulnerabilities, secret leaks, or unsanitized inputs in the provided git diff.

Instructions:
1. Examine only the changed lines and immediately surrounding context.
2. Search for: hardcoded secrets, injection flaws, path traversals, broken access controls.
3. If no genuine vulnerabilities exist, output exactly: `No security findings.`
```

---

#### 2. `/discipline-report` — Local Stats Analytics

##### Concept
The enforcement pack logs stop outcomes (`stop-clean`, `nudge`, `strict-block`) to `luciazero-stats.log`. `/discipline-report` analyzes this log to provide actionable discipline insights.

##### Command & Script Spec
- Script: `claude/hooks/luciazero-discipline-report.py`
- Invocation: `npx luciazero discipline` or `/retro` integration.

##### Expected Output Example
```
=== Luciazero Discipline Report ===
Period: Last 30 days (142 session stops)

Stop Outcomes:
  ✅ Clean stops:         110 (77.5%)
  ⚠️ Nudge warnings:        28 (19.7%)
  ❌ Strict blocks:          4 (2.8%)

Top Nudged Repositories:
  1. my-org/backend-service  (12 nudges — missing LUCIAZERO_VERIFY_CMD)
  2. my-org/frontend-app      (9 nudges — fast tier test execution > 60s)

Actionable Recommendation:
  - Add LUCIAZERO_VERIFY_CMD to .claude/settings.local.json in backend-service to avoid regex false positives.
```

---

#### 3. Smart Target Verification (Monorepo Optimization)

##### Concept
In large monorepos, running the full project test suite on every intermediate edit is too slow. `LUCIAZERO_SMART_VERIFY` inspects git diffs to run targeted test suites during intermediate iterations while reserving full verification for `/done`.

##### Implementation Mechanism (`claude/hooks/luciazero-verify.sh`)
```bash
# Optional environment flag: LUCIAZERO_SMART_VERIFY=1
# When set, map modified paths to sub-package test suites:
#   packages/ui/*      -> npm run test:ui
#   packages/api/*     -> npm run test:api
#   *                  -> LUCIAZERO_VERIFY_CMD (full suite)
```

---

### Original integration summary (superseded)

| Piece | Type | Location | Integration Point |
|---|---|---|---|
| `/plan` | Skill | `skills/plan/SKILL.md` | Pre-implementation workflow |
| `/bisect` | Skill | `skills/bisect/SKILL.md` | Regression debugging workflow |
| `/security-audit` | Skill | `skills/security-audit/SKILL.md` | Pre-closeout audit workflow |
| `security-reviewer` | Subagent | `claude/agents/security-reviewer.md` | `/done` skeptic pass |
| `contract-reviewer` | Subagent | `claude/agents/contract-reviewer.md` | `/done` skeptic pass |
| `/discipline-report` | Feature | `claude/hooks/luciazero-discipline-report.py` | Analytics & `/retro` |
| `LUCIAZERO_SMART_VERIFY` | Feature | `claude/hooks/luciazero-verify.sh` | Monorepo fast-path hook |
