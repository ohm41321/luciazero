# Project verification notes

- Reuse `./test.sh --fast` for the normal code loop and `./test.sh` for full
  closeout/CI. For hook/report/prompt-only edits, `./test.sh --discipline` is
  the narrower loop; for `agentd/` and the Agent Bus scripts, `./test.sh --bus`
  (`--fast` no longer runs the daemon suite). Coverage and prerequisites:
  `CONTRIBUTING.md`.
- CI pins ShellCheck (0.9.0 on Linux, 0.10.0 on the macOS job, the first
  arm64 build) and fails on any finding, style included; locally
  `tests/gates/core.sh` skips ShellCheck when it is not installed. A newer
  local ShellCheck can pass what the older CI one flags (0.11.0 accepts
  `A && [ "$(cmd)" = x ] || C`, 0.9.0 reports SC2015): write multi-command
  assertions as if/then, and set `LZ_REQUIRE_LINT=1` locally.
- Site changes also need `python3 scripts/check-site.py` in the loop: only
  the full tier runs it (packaging gate), and the Pages workflow runs it
  again before it deploys.
- Video changes need `(cd video && npm run verify)` against a fresh render;
  the root suite does not verify the MP4. Verification needs local ffmpeg,
  ffprobe and the video's Python environment, but no GPU or model quota.
  Rendering has separate browser/model requirements; see `video/README.md`.
  The intro master rendered 2026-09-30 fails `audio not clipping` (peak
  +0.13 dBFS; launch and teaser cuts pass), measured 2026-11-10 with no
  source change since that render: a red there predates later work.
- Video checks sample content and timing, not text overlap, readable dwell
  time, continuous motion or musical quality. Inspect the final distribution
  encode and listen before release. Thresholds in `video/verify.py` were
  calibrated on the light renders of 2026-09-29 and 2026-09-30 (152 to
  164 seconds; the intro master is now 168), as the comment above them
  records: after a recut, prove checks still reject broken output (audio
  moved in the samples, a frame shifted) rather than merely lowering
  thresholds until green.
- Video terminal scenes reconstruct implementation output; some lines are
  shortened or illustrative. `timeline.json` documents provenance. Do not
  label every scene an unedited recording or every value a measured result.
- The video uplift result is Claude Sonnet-specific, using the classic pack
  without hooks. Codex has an exploratory ceiling-effect pilot, so neither
  "Codex not measured" nor a claim of demonstrated Codex uplift is accurate.
  Keep caveats with evidence; see `README.md` and `docs/benchmark.md`.
- Preserve the test suite's environment sanitation and service-root guard:
  uninstall fixtures must never resolve services under the real home directory.
- Bash 3.2 can return zero on a syntax error in a sourced gate. Keep the
  dispatcher's pre-source syntax check; `tests/gates/tiers.sh` covers this.
- Bash 3.2 also exits 0 on a fatal *runtime* error (unset var under `set -u`,
  `${x:?}`, bad substitution) whenever an EXIT trap is armed: the trap's last
  status wins and `$?` inside it reads 0. `bash -n` passes all three. The
  dispatcher's `RUN_ENDED` sentinel turns that red; set it on any new intended
  exit-0 path, and never give a gate its own EXIT trap (use `mktmp`).
  `tests/dispatcher-fatal-exit.sh` guards it; CI runs it in `bash:3.2`
  because the bug was seen on 3.2 and the runner's Bash 5 may not show it
  (not run locally: no Bash 5 on this Mac, 2026-11-03).
  A `"$(printf '...$(cat <<...')"` with a quote inside dies this way; use
  `printf -v`.
- Eval graders have the same 3.2 exit-0 hazard, but it cannot fake a score:
  `eval/run.sh` books a grader with no `SCORE` line as INVALID, and the eval
  gate requires `SCORE` from the reference run. Probed 2026-11-03 with an
  unbound variable after red-suite's trap: grader rc=0, row `INVALID — grader
  crashed (no SCORE line, rc=0)`. No grader change needed.
- `agentd/tests/test_nudge.py` `test_a_knock_waits_for_a_provider_that_is_mid_turn`
  flakes under heavy host load (load average above ~5): it failed 1 run in 6
  on unmodified HEAD and 1 in 6 on a working tree, interleaved (2026-10-06).
  A red full run on that test alone is not evidence of a regression; rerun it
  against HEAD before blaming a change. 53441d9 (2026-10-08) fixed a race
  that matched it; keep this rule until CI history shows it gone.
- `agentd/tests/test_adapters.py`
  `test_the_config_is_gone_however_the_turn_ends` gave its fake provider a
  1-second timeout; at load average ~26 the `print('done')` case failed once
  (`False != True`) and passed 6 of 6 in isolation with agentd unchanged from
  HEAD (2026-10-07). Since 53441d9 the turns that end get 30 seconds and only
  the timeout case keeps 1, but why the host took that long is unknown. Same
  rule as the nudge test: rerun before blaming.
- Claude Code silently drops an agent whose `name:` contains a colon
  (`lucia:reviewer` never loads; checked against the `claude -p` init event's
  agent list, 2.1.317). `x:y` only comes from plugin namespacing.
- Reviewer cost A/B: run `claude -p --system-prompt-file <agent body>
  --setting-sources project --strict-mcp-config` in a fresh clone; that keeps
  the user's CLAUDE.md and hooks out. A small fixture hits a floor (4-5 steps
  for any prompt). The caller's brief drives step count more than the prompt,
  so A/B with a realistic long brief. Results: `docs/experiments.md`
  2026-11-03.
