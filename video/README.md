# Luciazero intro video

A 168-second, 1920×1080, 30 fps intro built from code only, with two cuts of
it: a 178-second launch film with chapter cards and a 106.5-second teaser.
Three.js and GSAP draw each frame in a browser page, Playwright screenshots it, and ffmpeg
encodes the frames. The score is synthesized in Python from oscillators and
seeded noise. No image, video, or music generation model is used.

```text
timeline.json ──► music.py ──► out/music.wav ─┐
      │                                       ├─► ffmpeg ─► out/luciazero-intro.mp4 ─► verify.py
      └─────────► index.html + main.js ─► render.mjs (seek t, screenshot, pipe) ─┘
```

`timeline.json` is the only source of cue times. The shatter, the drop, verify
RED and GREEN, each CAUGHT stamp and each of Lucia's speech bubbles land on the
same frame in the picture and the same sample in the audio, because both sides
read these times from that one file.

The look is a light, minimal anime style matched to Lucia: a pale sky-blue
page with drifting polka dots, white cards with ink outlines and cat-ear
corners, toon-shaded 3D objects with ink outlines, and her cyan as the accent.
The score is anime-flavoured electro-pop in C major at 120 BPM: four-on-the-floor
drums, a sidechained sub bass, pumping supersaw chords, plucks, marimba and a
music box. Its hook is the opening lullaby (E G C G F A) set to a dance rhythm
over the IV–V–iii–vi progression, on a gliding saw lead doubled by a vowel-shaped
"vocal chop". The music box plays it plainly under the false green; it returns
as the hook at the drop, under `/lucia-relay` (lead) and the Agent Bus
(plucks), and in the last chorus under the skills and the install card. Its
first four notes are a sonic logo on verify GREEN and on every chapter card,
and the lullaby returns in tune over the final chord. An FM bell sounds at only
five moments: her reveal, verify GREEN, the relay seal, the evidence result and
the final chord.

## Lucia

Lucia is the live VRM model from the Lucia-AI-Waifu-Project checkout, posed
by motion clips and rendered into a texture every frame. From 36 s to 80 s and
in "Safe to try" she stands at the right edge and presents the scenes, with a
speech bubble, a gesture and a face for each line (`timeline.json` › `lucia`).

`render.mjs` looks for the model in `LUCIA_VRM_DIR`, by default
`Lucia-AI-Waifu-Project/vrm_model` two levels above the repository root
(`../../../Lucia-AI-Waifu-Project/vrm_model` from `video/`). Without it the video falls back to
the flat `site/lucia-3d.png`.

- **Licences.** The model's licence forbids redistributing `Lucia.vrm`, so the
  model, its textures and anything that can be extracted from them stay out of
  this repository; only the rendered video may be published. The motion clips
  under `vrm_motion/hanami_overte/` are Apache-2.0: ship their `LICENSE` and
  `NOTICE.md` with any copy of the clips.

## Run

```bash
cd video
npm install                                  # three, three-vrm, gsap, playwright, fonts
python3 -m venv .venv && .venv/bin/pip install numpy
npm run render                               # music + 5040 frames, about 10 min on an Apple M5 (8.4 fps)
npm run verify                               # CHECKS_FULL checks; exits non-zero if any fails
npm run render:launch                        # the launch film -> out/luciazero-launch.mp4
npm run verify:launch                        # CHECKS_LAUNCH checks: the cues the cut keeps, and its chapter cards
npm run render:teaser                        # the teaser -> out/luciazero-teaser.mp4
npm run verify:teaser                        # CHECKS_TEASER checks
./web.sh                                     # web copies for the website and the READMEs
```

Faster loops while editing:

```bash
node render.mjs --stills 6,45,97             # single frames -> out/stills/t-SS.SS.png
node render.mjs --from 36 --to 48 --fps 15   # a draft of one range, no audio
node render.mjs --serve                      # live preview with sound in a browser
node render.mjs --cut launch --stills 16,38  # frames of a cut, at its own times -> out/stills/launch-t-SS.SS.png
```

## Cuts

`timeline.json` › `cuts` holds shorter edits of the same film. A cut is a list
of shots: a range of the timeline (`src`), played at the timeline's own times
so every cue inside it still holds, or a full-frame chapter card (`card`, the
id of a `.card` in `index.html`) held for `dur` seconds over a `chord`.

`launch` (178 s) is the launch film: every scene of the timeline, with an
Apple-keynote-style chapter card before each part (Verify, Debug, Relay, Agent
Bus).

| Time | Shot |
|---|---|
| 0–24 s | False green, failures, the drop and Lucia (0–24) |
| 24–26.5 s | Card: **Verify.** Proof before "done". |
| 26.5–82.5 s | The loop and failures 01–05 (24–80) |
| 82.5–85 s | Card: **Debug.** Find the commit that broke it. |
| 85–97 s | `/bisect` (80–92) |
| 97–99.5 s | Card: **Relay.** New session. New agent. New machine. |
| 99.5–113.5 s | `/lucia-relay` (92–106) |
| 113.5–116 s | Card: **Agent Bus** (beta). Tasks out. Results back. |
| 116–178 s | Agent Bus, bus safety, evidence, "Safe to try", the skills and the install card (106–168) |

`teaser` (106.5 s) keeps the hook, the loop, failure 01, the relay, the Agent
Bus round trip, the evidence, two "Safe to try" items, the skills and the
install card.

| Time | Shot |
|---|---|
| 0–7 s | False green (0–7) |
| 7–15 s | The drop and Lucia (16–24) |
| 15–17.5 s | Card: **Verify.** |
| 17.5–41.5 s | The loop and failure 01 (24–48) |
| 41.5–44 s | Card: **Relay.** |
| 44–58 s | `/lucia-relay` (92–106) |
| 58–60.5 s | Card: **Agent Bus** (beta) |
| 60.5–72.5 s | Agent Bus (106–118) |
| 72.5–94.5 s | Evidence, "Safe to try" and the skills (128–150) |
| 94.5–106.5 s | Install (156–168) |

- **Picture.** `main.js` maps each output time to its shot and seeks the
  timeline there. On a card it seeks the next shot's first moment and covers
  it; the card then pushes through and fades over the first half second of
  that shot. Leftovers of a scene the cut drops are hidden by name
  (`sceneKept`), for example Lucia's loop-scene pose and the verify ring.
- **Music.** `music.py --cut` places each sound at its shot's time and drops
  the sounds whose onset falls in a range left out; tails ring on across the
  cut. A whoosh may start up to 0.6 s before a range, so it leads out of the
  card before it. Each card stops the groove for half a beat, then lands one
  hit and holds its chord. Every shot starts on a bar line, so the beat never
  skips.
- **Checks.** `verify.py --cut` checks the audio hits the cut keeps at their
  shot times plus a hit on each card, one sample per kept scene and per card,
  and the picture cues (flash, check break, RED/GREEN, relay card) only where
  one shot keeps the frames around them.

## Web copies

`web.sh` makes these from the master and runs `verify.py` on the 720p copy:

| File | Use | Limit |
|---|---|---|
| `site/intro.mp4` | the video on the website; also the file to upload into a README on github.com | under 10 MB, GitHub's upload limit for video on a free plan |
| `site/intro-poster.jpg` | its poster, frame 23.6 s | |
| `docs/assets/intro-cover.jpg` | the README image that links to the video, drawn by `cover.html` | |
| `docs/assets/intro-false-green.gif` | 1.2–6.4 s, the false green and the shatter | under 5 MB |

The web copy takes its audio from `out/music.wav` 1.5 dB lower, because the
score peaks at -1.0 dBFS and AAC at 128 kbit/s overshoots that to +0.2 dBFS.

`web.sh` still has the 60-second cut's poster time and GIF range, and the
website and READMEs still show that cut. Moving them to this version is a
separate, deliberate step: the copy has to fit the 10 MB limit.

## Scenes

| Time | Scene | Beat |
|---|---|---|
| 0–8 s | False green | An agent claims "All tests pass". A 3D check rises, wobbles, and shatters into confetti. |
| 8–16 s | Failures | Three failure modes land on the bar lines. The pieces spin into a vortex. |
| 16–24 s | Lucia | On the drop, the pieces fly into Lucia's pixels and a dissolve reveals her. |
| 24–36 s | The loop | plan → change → verify (RED, exit 1) → fix → verify (GREEN, exit 0), then doctrine rule 1. |
| 36–48 s | Failure 01 | "Done" without a check: the Stop hook nudges once, the check runs, and it is red. |
| 48–54 s | Failure 02 | Scope, quietly dropped: the `/done` report names what was left out. |
| 54–62 s | Failure 03 | The same dead end twice: the ledger in `docs/lessons.md`; `/debug` turns a match into H1. |
| 62–70 s | Failure 04 | `cat test.sh` counted as a test: a broad pattern, an exact `LUCIAZERO_VERIFY_CMD`, and a hostile repo that cannot configure Luciazero. |
| 70–80 s | Failure 05 | New tests that pass without the fix: revert-probe runs them against the old code. |
| 80–92 s | `/bisect` | Twelve commits; three probes in a temporary worktree find the first bad one. |
| 92–106 s | `/lucia-relay` | Cross-machine: session A (Claude Code) on a laptop pushes, seals a relay card (next step, knowledge, evidence, dead ends, the repository) and writes the trusted envelope; session B (Codex CLI) on a desktop clones, inspects the card against the envelope, re-runs its evidence and consumes it. Three chips name what changed: new session, new agent, new machine. |
| 106–118 s | Agent Bus | `lucia codex --as architect` and `lucia claude --as reviewer` in two windows, `lucia watch` in a third. Four numbered steps stay on screen: Codex asks for a review, Claude finds a bug (red), Codex fixes it (a third agent, `codex-implementer`), Claude re-checks it (green). The watch lines follow the real `agent_bus_e2e.py` run. Beta, set up from a checkout. |
| 118–128 s | Bus safety | The daemon restarts and the queue survives; the bus refuses three requests it should refuse. |
| 128–136 s | Evidence | Claude Sonnet, classic pack without hooks: all-criteria pass rate with and without it, with its caveat and the GPT/Codex ceiling. |
| 136–142 s | Safe to try | No npm install scripts, uninstall removes only what it installed, hooks fail open, nothing changes in the background, the core runs offline. |
| 142–156 s | Skills | 13 skill chips, each with a line on what it does, flip in on marimba notes and hold for about eight seconds. The camera dives through them. |
| 156–168 s | Install | Lucia; the Claude Code plugin and Codex CLI installs; the first step (`/luciazero:ready`, `$ready`); where the statusline and Agent Bus come from; the repository URL. The score resolves on C major and the opening's lullaby returns in tune. |

## Gotchas

- **Determinism.** Every value is a function of `t`. Randomness uses a seeded
  `mulberry32`, and nothing may read the clock. Glitch flicker is hashed from
  the frame number.
- **GSAP.** Every tween is `fromTo` with `immediateRender: false` on one
  paused timeline. Otherwise a later tween's "from" state is applied at build
  time, and random-access seeks (`--stills`) show the wrong state. Text that
  changes (typing, statusline, relay terminals) is set in `update(t)`, not
  with callbacks, so a random-access seek shows the same text as a
  frame-by-frame render. A `fromTo` with `immediateRender: false` also renders
  nothing before its start, so `enter()` adds a `set` to hidden at time 0.
  Without it, a line inside a layer that appeared earlier shows at full
  opacity until its own entrance.
- **Relay card.** Its path is written in screen pixels and unprojected every
  frame, so it stays lined up with the DOM terminals while the camera drifts.
  Its material needs `forceSinglePass: true`: three.js draws a transparent
  `DoubleSide` material in two passes and flips the winding for the back
  pass, where `gl_FrontFacing` reads true, so the text showed mirrored on the
  card's back.
- **GPU in headless Chromium on macOS.** `--use-angle=metal` gives the
  Metal renderer. `render.mjs` prints the WebGL renderer string so a silent
  fall back to software rendering is visible.
- **Colors.** Chromium screenshots are full-range sRGB. `render.mjs` converts
  them with an explicit bt709 matrix and tags the stream. Without this, ffmpeg
  uses bt601 and the teal shifts.
- **Checking sync.** Decoding audio samples with ffmpeg ignores a stream's
  start offset. A file with audio muxed 200 ms late still passed every
  per-sample check, so `verify.py` also compares the audio and video
  `start_time`. It is known to fail on both kinds of desync: a container
  offset (`-itsoffset`) and a delay inside the samples (`adelay`).
- **Checking the picture.** On a light page, brightness says nothing, so
  `verify.py` measures content (luma spread), change (the flash on the
  shatter frame against the two before it), ink (the check's outline, gone on
  the shatter frame once the flash is divided out) and color (the share of
  strongly red or green pixels). Scenes are sampled one beat past their midpoint: cards swap on bar
  lines, and the midpoint of 8–16 s lands on the one empty frame between two
  failure cards. The checks were tested against sabotaged copies: audio 100 ms
  late fails all 16 audio hits, the picture one frame early fails the flash
  check, and the check left whole under an on-time flash fails the break
  check. Audio 80 ms early or 80 ms late inside the samples fails all 16 hits
  too (2026-11-10). Early audio once passed 15 of them: the check then looked
  for the loudest moment only in a window too narrow to fail, and the hit's
  tail still filled it, so it now measures where each hit starts within
  100 ms of its cue, which on the renders of 2026-09-30 is 37 ms early at
  most (a chapter card, whose whoosh rises first) against a 50 ms
  tolerance. The launch cut was tested the same way: audio 100 ms late fails all
  13 of its audio hits, the picture one frame early fails the flash and break
  checks, and a chapter card painted over with the page color fails its
  content check.
- **ffmpeg 9** removed `-vsync`. Use `-fps_mode passthrough`.
- **Sleep.** A render takes about ten minutes a cut. On battery, closing the
  lid puts the Mac to sleep even under `caffeinate -i`; the render then fails
  with `page.screenshot: Timeout 30000ms exceeded`, and a still can take the
  whole sleep interval. `pmset -g log` shows the `Clamshell Sleep`. Keep the lid
  open, or run on power with `caffeinate -s`.
- **Light theme.** Everything uses normal blending and there is no bloom:
  additive glow washes out to white on a light page. Glow is drawn as toon
  shading, ink outlines and white emissive pulses instead.
- **Lucia's symbols.** Her `frag_*` expressions (?, !, ♪) are meshes above her
  head, so her render target is framed 0.62 m above the head bone
  (`LUCIA_SPEC.frame`); a tighter frame cuts them off.
