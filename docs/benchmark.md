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

## Current results — Claude only

Snapshot: 2026-08-11. The number shown is the all-criteria pass rate.

| Model | Luciazero | Bare | Difference | Valid runs per task |
|---|---:|---:|---:|---:|
| Claude Haiku | 36/60 (60%) | 27/60 (45%) | +15pp | 10 |
| Claude Sonnet | 25/27 (93%) | 16/26 (62%) | +31pp | 4–5 |

> **Preliminary Sonnet result:** several arms have only four valid runs. This is
> below the harness's minimum publication threshold, so treat every Sonnet
> delta as noise until replacement runs bring every arm to at least five.

### Claude Sonnet

| Task | Luciazero | Bare | Difference | Lessons arm |
|---|---:|---:|---:|---:|
| slugify | 4/4 | 0/4 | +100pp | — |
| merge-conflict | 3/5 | 0/4 | +60pp | — |
| pipeline | 4/4 | 3/4 | +25pp | 4/4 |
| false-green | 5/5 | 4/5 | +20pp | 5/5 |
| flaky-report | 5/5 | 5/5 | 0pp | — |
| red-suite | 4/4 | 4/4 | 0pp | — |

### Claude Haiku

| Task | Luciazero | Bare | Difference | Lessons arm |
|---|---:|---:|---:|---:|
| slugify | 3/10 | 0/10 | +30pp | — |
| merge-conflict | 1/10 | 0/10 | +10pp | — |
| pipeline | 4/10 | 0/10 | +40pp | 1/10 |
| false-green | 8/10 | 7/10 | +10pp | 7/10 |
| flaky-report | 10/10 | 10/10 | 0pp | — |
| red-suite | 10/10 | 10/10 | 0pp | — |

These samples are small. Compare rates, never a single run, and do not treat a
provider difference as a Luciazero effect. The denominators above come directly
from `eval/report.sh`, which excludes invalid runs.

## GPT/Codex evaluation plan

GPT results are needed before claiming that the measured uplift generalizes to
Codex. The test should extend the harness with a provider adapter, not create a
second set of easier tasks.

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

Until these runs exist, the honest result is: **GPT/Codex not yet measured.**
