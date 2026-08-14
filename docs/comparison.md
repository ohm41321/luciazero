# How this compares

Honest positioning against the alternatives a visitor will find in one
search. Every claim below was checked against the named project's public
README/source on **2026-08-12**; these projects move fast, so treat the date
as part of each claim. Corrections welcome — an unfair line here would break
this repo's own first rule.

**What this repo is:** a minimal, self-verifying *discipline layer* — a text
install (doctrine + procedures + opt-in enforcement) for Claude Code and
Codex CLI. It runs nothing by itself. That framing decides most of the
trade-offs below.

## The short version

| | They have, we don't | We have, they don't (verified) |
|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers) (~270k★) | 14 skills across 10+ harness integrations, a multi-plugin community marketplace + official-directory listing, huge community, a real eval lab | A CI-enforced size ceiling on the always-loaded text; evals whose graders run (and are themselves red/green/anti-cheat tested) in public CI; bootstrap falsification; dual-harness install/uninstall cycles proven in CI |
| [SuperClaude](https://github.com/SuperClaude-Org/SuperClaude_Framework) (~24k★) | Commands, personas, MCP integrations, distribution | A context budget at all (their own issue #286 reports ~8k always-loaded tokens; our doctrine is CI-capped at 420 words), behavioral evals, enforcement hooks, a Codex path from one source tree |
| [proof-loop](https://github.com/LeoStehlik/proof-loop) (6★, stale) | A **hard** mechanical done-gate with frozen acceptance criteria — stronger "done" enforcement than ours | The doctrine, the lifecycle procedures, evals, installers, statusline; our opt-in strict gate (below) closes most — not all — of this gap |
| [exiw/proofloop](https://github.com/exiw-ai/proofloop) (37★, frozen), [loopx](https://github.com/huangruiteng/loopx) (3.8k★, active) | A *runtime*: durable state, long-running/overnight orchestration | Nothing comparable — different layer by design. This repo can be installed alongside them |
| [claude-code-templates](https://github.com/davila7/claude-code-templates) (~30k★) | A huge catalog of components | A coherent, tested methodology rather than parts; measured behavior |
| Claude Code built-ins | Agent Stop hooks that can run tests and *hard-refuse* a stop; `/code-review`; auto memory | A CI-enforced doctrine budget (the built-in guidance on notes-file size is advisory); bootstrap falsification; an A/B eval harness; export to Codex |
| Codex CLI built-ins | Native skills, `/review` | Codex *truncates* an oversized AGENTS.md at 32KiB — silent loss, the opposite failure mode of a red test. Our installers keep the block small and byte-stable |

## The five claims we defend

1. **The always-loaded text has a CI-enforced ceiling.** `test.sh` fails if
   the doctrine exceeds 420 words — "cut a word to add a word". Nobody else
   in the table enforces their always-loaded footprint with a test.
2. **The evals prove themselves.** Every task grader must pass its
   `reference/`, fail its unfixed `project/`, and reject a checked-in
   `gamed/` cheat tree — offline, on every CI push. superpowers' eval lab is
   real but (per its own README) cannot run in public CI.
3. **Readiness ends in falsification.** `/ready` finishes by
   breaking a covered line to prove verify goes red, and running it twice to
   catch flakes. A verify command that cannot fail is not a verify command.
4. **Enforcement is instrumented, not prose.** The opt-in pack tracks
   edits-vs-verify per project, shows it in the statusline, nudges once at
   stop — and, in opt-in strict mode, actually runs your verify command and
   blocks a red stop with the failing output attached. Honest limit: the
   blocked stop's continuation is never re-blocked, so strict mode is a
   speed bump with evidence, not proof-loop's wall.
5. **Both harnesses, one source, proven cycles.** Install → reinstall →
   uninstall for Claude Code *and* Codex runs in CI sandboxes on every push,
   including the no-dangling-references guarantee when settings cleanup
   fails.

## When to choose something else

- You want breadth, community, and a plugin ecosystem → **superpowers**
  (our own marketplace is single-plugin by design).
- You want an unattended runtime that survives restarts → **loopx** (and
  nothing in this repo conflicts with running both).
- You want "done" to be machine-unfakeable, frozen criteria and all, and
  will accept an abandoned repo → **proof-loop**'s gate design is still the
  strongest version of that one idea.
- You want one specific hook or command, not a methodology →
  **claude-code-templates**.

## Known weaknesses (ours)

- The published campaigns cover six small Python tasks. Haiku has n=10 per arm;
  Sonnet is preliminary at n=4–5 because eight invalid rows could not be
  replaced from auditable raw data. Three harder coding candidates and one
  transfer-protocol task now pass offline grader validation but have no model
  results yet. Larger, multi-language campaigns and independent replications
  are still needed.
- No runtime, no orchestration, no durable state — by design, but it means
  this repo alone does not give you overnight autonomy.
- Ecosystem listing: published on npm (`luciazero`) and the Claude
  Code plugin marketplace (`ohm41321/luciazero`), but not yet listed in
  [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code).
