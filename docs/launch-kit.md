# Luciazero launch kit

This is the source of truth for a public Luciazero launch. Keep the copy
specific, keep the proof reproducible, and update live adoption metrics at the
time of posting.

## Positioning

Primary category: verification and handoff layer for coding agents.

One-liner:

> Make coding agents prove their work before they say “done.”

Short description:

> Luciazero adds a `plan → change → verify → fix` loop to Claude Code, Codex
> CLI, and compatible skill runtimes. It catches false-green verification,
> preserves scope and lessons, and moves unfinished work across sessions with
> evidence.

Primary CTA:

> Install it, start a new agent session, and run `ready` (`$ready` in Codex).

## 30-second demo

The demos use the shipped implementation in throwaway directories. They do not
invoke a model, need an API key, or modify the repository:

```bash
bash docs/assets/statusline-demo.sh
bash docs/assets/relay-demo.sh
```

Use the statusline demo to show the red/green verification loop. Use the Relay
demo to show drift detection, evidence replay, and explicit consumption.

## Proof strip

Safe claims for the README or a release post:

- 11 on-demand skills
- Claude Code, Codex CLI, and compatible skill-runtime install paths
- Relay protocol fixture: reference 6/6; generic Markdown handoff 1/6; stale
  fingerprint 5/6
- Claude snapshot (2026-08-11): Haiku +15pp; Sonnet +31pp preliminary
- Codex pilot (2026-08-12): 5 paired tasks, 0pp observed difference, exploratory

The Relay scores are mechanical protocol checks, not model-uplift results. The
Claude and Codex figures are model/task-specific measurements with the limits
shown in [`docs/benchmark.md`](benchmark.md). Do not remove those caveats from
public copy.

Refresh these live metrics immediately before posting:

```bash
gh api repos/ohm41321/luciazero \
  --jq '{stars:.stargazers_count,forks:.forks_count,pushed:.pushed_at}'
curl -fsSL https://api.npmjs.org/downloads/point/last-week/luciazero
npm view luciazero version
```

## Draft posts

### GitHub release or launch note

> Coding agents can now prove their work before saying “done.”
>
> Luciazero is a verification and handoff layer for Claude Code and Codex CLI:
> it tracks whether the latest check is real, keeps scope visible, routes risky
> reviews, and transfers unfinished work with a verifiable Relay.
>
> Try it in 30 seconds:
>
> ```bash
> npx luciazero codex
> ```
>
> Then start a new session and run `$ready`.

### Short social post

> “Done” is not a feeling. Luciazero gives Claude Code/Codex a
> `plan → change → verify → fix` loop plus evidence-backed handoffs.
> `npx luciazero codex`

### Community reply

> If your coding agent sometimes says “done” without running the right check,
> Luciazero is a small verification layer worth trying. It is local-first,
> supports Claude Code and Codex CLI, and the Relay demo shows exactly what
> crosses a session boundary.

## Benchmark launch gate

Do not publish a new uplift claim until all of these are true:

1. Use one clean commit, fixed task/prompt hashes, one seed, and the exact model
   identity.
2. Collect at least five valid runs per arm; record invalid runs separately.
3. Publish the raw JSONL, SHA-256, model settings, CLI version, duration, and
   token/cost fields when available.
4. Run `eval/report.sh` and regenerate evidence with
   `python3 eval/evidence.py --write`.
5. Run `./test.sh` before publishing.

Candidate Claude screen: one run per arm on `archive-security`,
`schema-migration`, and `paginated-sync`. This is six real model invocations
before scaling to five per arm. It consumes Claude subscription quota or API
credit; obtain explicit budget approval first.

Example after authorization:

```bash
eval/run.sh --runs 1 --seed 20260824 \
  --campaign-id claude-hard-screen-2026-08-24 \
  --use-login --out eval/results/claude-hard-screen-2026-08-24.jsonl \
  archive-security schema-migration paginated-sync
eval/report.sh eval/results/claude-hard-screen-2026-08-24.jsonl
```

The screen is a decision gate, not a publishable headline. If both arms hit
the ceiling again, redesign the tasks before buying more runs.

## Distribution checklist

- Release the README/demo update with a short changelog entry.
- Attach the 30-second demo and one concrete failure mode to every launch post.
- Link the raw benchmark and its limitations, not only the headline delta.
- Ask users for a star after they successfully install and run `ready`; never
  imply that a star is required for support.
- Collect one real user workflow before adding another feature.
- Recheck npm downloads and GitHub stars one week after each launch.
