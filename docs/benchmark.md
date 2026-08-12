# Behavioral benchmark

Luciazero measures one question: does installing Luciazero improve the behavior
of the **same model and harness** on the same coding tasks? It does not use the
benchmark to declare one provider or model universally better than another.

## Method

Each task starts from the same planted bug. The `doctrine` arm (its historical
JSON label) receives the classic Luciazero install without hooks: doctrine,
skills, and reviewer. The bare arm receives none of them. Both receive the same
prompt and are graded from the final tree by an offline deterministic grader.
This is a treatment-bundle comparison, not a doctrine-only ablation.

Every grader is tested three ways in CI:

- the solved `reference/` tree passes;
- the unfixed `project/` tree fails; and
- one or more `gamed*/` trees are rejected.

Runs that never produced a valid agent result are marked invalid and excluded.
See [eval/README.md](../eval/README.md) for commands, costs, and the full honesty
box.

<!-- BEGIN GENERATED: benchmark-evidence -->

## Claude campaigns

Snapshot: 2026-08-11. Tables below are generated from digest-verified raw JSONL.

| Model | Luciazero | Bare | Difference | Valid runs per task | Status |
|---|---:|---:|---:|---:|---|
| Claude Haiku | 36/60 (60%) | 27/60 (45%) | +15pp | 10 | published |
| Claude Sonnet | 25/27 (93%) | 16/26 (62%) | +31pp | 4–5 | preliminary |

> **Canonical Sonnet result:** the checked-in campaign contains eight invalid
> rows and leaves several arms at four valid runs. Commit `b24f6a2` described
> replacement runs yielding +37pp, but those raw rows could not be recovered.
> The auditable preliminary campaign below is canonical; do not quote +37pp.

> **Haiku model-provenance limitation:** only 70/140 rows encode model
> identity. Attribution of the other 70 comes from the original campaign
> file/report and cannot be independently verified per row.

### Claude Sonnet

| Task | Luciazero | Bare | Difference | Lessons arm |
|---|---:|---:|---:|---:|
| false-green | 5/5 | 4/5 | +20pp | 5/5 |
| flaky-report | 5/5 | 5/5 | +0pp | — |
| merge-conflict | 3/5 | 0/4 | +60pp | — |
| pipeline | 4/4 | 3/4 | +25pp | 4/4 |
| red-suite | 4/4 | 4/4 | +0pp | — |
| slugify | 4/4 | 0/4 | +100pp | — |

Raw: [`claude-sonnet-preliminary-2026-08-11.jsonl`](../eval/results/claude-sonnet-preliminary-2026-08-11.jsonl) · SHA-256 `fafb7a91b788bb484a66cb6c7259d91e9f32412e167a72385e735e50e2865117`

### Claude Haiku

| Task | Luciazero | Bare | Difference | Lessons arm |
|---|---:|---:|---:|---:|
| false-green | 8/10 | 7/10 | +10pp | 7/10 |
| flaky-report | 10/10 | 10/10 | +0pp | — |
| merge-conflict | 1/10 | 0/10 | +10pp | — |
| pipeline | 4/10 | 0/10 | +40pp | 1/10 |
| red-suite | 10/10 | 10/10 | +0pp | — |
| slugify | 3/10 | 0/10 | +30pp | — |

Raw: [`claude-haiku-2026-08-11.jsonl`](../eval/results/claude-haiku-2026-08-11.jsonl) · SHA-256 `fc1d323966817e0bd3b0f5e0d0184a8b25a6e28100c700c98585cd98dbb31901`

These samples are small. Compare rates, never a single run, and do not treat a
provider difference as a Luciazero effect.

## GPT/Codex pilot — exploratory only

Snapshot: 2026-08-12. Codex CLI 0.147.0, `gpt-5.6-terra`, medium reasoning;
11/12 valid invocations.

| Task | Luciazero | Bare |
|---|---:|---:|
| false-green | 1/1 | 1/1 |
| flaky-report | invalid: capacity | 1/1 |
| merge-conflict | 1/1 | 1/1 |
| pipeline | 1/1 | 1/1 |
| red-suite | 1/1 | 1/1 |
| slugify | 1/1 | 1/1 |

Five tasks have a valid pair. Both arms passed 5/5 runs and 28/28 individual
criteria, an observed 0pp delta. This is a ceiling-effect warning, not evidence
that Luciazero has zero effect. With n=1, one sample can move a task by 100pp.

Raw: [`gpt-5.6-terra-medium-pilot-2026-08-12.jsonl`](../eval/results/gpt-5.6-terra-medium-pilot-2026-08-12.jsonl) · SHA-256 `96c7401c297d915006b49115f96e17e0d7db9e28471ed2078dc7e1a29d1473aa`

<!-- END GENERATED: benchmark-evidence -->

The five valid pairs averaged 99 seconds and 3,386 output tokens with Luciazero,
versus 74 seconds and 2,415 output tokens bare. Those resource differences are
also exploratory: one run per task cannot separate treatment overhead from
normal model variance. The capacity-invalid run lasted 642 seconds and emitted
no completed-turn usage record, so its partial token use is unknown. The
[raw JSONL](../eval/results/gpt-5.6-terra-medium-pilot-2026-08-12.jsonl) preserves
every row, model setting, duration, token count, CLI version, and invalid reason.

The pilot held the fixture, prompt, grader, model, effort, sandbox, and stopping
interface constant within each pair. It used `workspace-write`, ephemeral
sessions, no inherited user config or rules, and only a sandboxed copy of the
operator's login state. The treatment arm installed the same classic pack used
by the Claude benchmark; the bare arm received an empty `CODEX_HOME` apart from
auth.

One historical limitation matters: this first pilot predated the adapter's
explicit core-only shell environment. No credentials or local paths appear in
the checked-in rows, but the run does not prove that caller environment values
were unavailable to agent-launched commands. The adapter now sets a core-only
shell environment and automatic secret-name exclusions, fixture-proven without
inference in `test.sh`. Future runs therefore have a stronger credential
boundary. The remaining automation flags follow the official guidance for
[non-interactive Codex runs](https://learn.chatgpt.com/docs/non-interactive-mode).

## Next GPT/Codex evaluation steps

Do not spend another 48 invocations taking the six legacy tasks directly to
n=5: the pilot says they may not discriminate at this model capability. Three
harder candidates now pass offline red/green/anti-gamed proof:

- `archive-security`: traversal, link, destination-symlink, and partial-write
  failures;
- `schema-migration`: lossless/idempotent migration and interrupted atomic
  persistence; and
- `paginated-sync`: three-page contract propagation and cursor-cycle defense.

The next measured step is deliberately small: one Terra/medium run per arm on
these three candidates (six invocations total), using one clean commit, campaign
ID, and seed. If both arms again pass everything, record the null screen and
return to task design. Only tasks that show headroom advance to n>=5 per arm.

For each selected GPT coding model:

1. Run Luciazero and bare arms through the same Codex or Responses API harness.
2. Hold the task, prompt, tools, sandbox, grader, reasoning effort, and stopping
   limits constant within the pair.
3. Record the exact model ID or snapshot, reasoning settings, tokens, latency,
   cost, exit status, and invalid-run reason.
4. Collect at least five valid runs per arm before publishing a delta; ten is
   preferable for the lower-cost model.
5. Report Luciazero uplift within each model. Keep cross-provider comparisons
   descriptive because the harnesses and tool implementations differ.

The [official OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
recommends testing representative tasks and comparing quality, required
evidence, tokens, latency, and cost. It also recommends testing more than one
reasoning setting instead of assuming the highest setting is the best trade-off.

Until the task set can discriminate Terra and every arm has at least five valid
runs, the honest result is: **GPT/Codex uplift not yet measured.**
