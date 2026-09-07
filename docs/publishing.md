# Publishing checklist

How luciazero reaches each distribution channel, in dependency order. Facts
below were verified 2026-08-13; re-check anything marked (†) before relying
on it, since third-party processes change.

## 0. Prerequisites (everything depends on this)

- [x] `git init` + first commit — done 2026-08-10
- [x] Create the GitHub repo `luciazero` and push — github.com/ohm41321/luciazero
- [x] Cut `v2.0.0` per CONTRIBUTING — changelog and both manifests agree;
      GitHub Release and npm publish completed 2026-08-13
- [x] `repository`/`homepage` fields added to `package.json` and
      `.claude-plugin/plugin.json` — done 2026-08-10
- [x] `./test.sh` green; `claude plugin validate .` passes — verified locally
      and in GitHub Actions for `v2.0.0`

Version sync rule: a release bumps `CHANGELOG.md`, `.claude-plugin/plugin.json`,
and `package.json` together — `test.sh` fails on any mismatch.

**Release-state rule:** the source manifest, Git tag, GitHub Release, and npm
registry must agree before a version is described as public. Check the registry
with `npm view luciazero version` and inspect `dist.attestations`; a prepared
manifest or pushed tag alone is not a completed release.

## 1. Claude Code plugin (live the moment the repo is public)

Users need no setup from us beyond the push:

```
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

Third-party marketplace auto-update is off by default. Users can enable it for
`luciazero` in `/plugin` → Marketplaces, or update explicitly with
`claude plugin update luciazero@luciazero` and `/reload-plugins`. Because
`plugin.json` supplies an explicit version, every plugin release must bump it;
new commits at the same version are not delivered as updates.

To get listed in Anthropic's catalogs (†):

- Community/official directory submission form: <https://platform.claude.com/plugins/submit>
  (Team/Enterprise admins have their own path via claude.ai admin settings).
  Approved plugins land pinned-to-SHA in
  [anthropics/claude-plugins-community](https://github.com/anthropics/claude-plugins-community);
  sync is nightly, allow ~24h. The official tier (`claude-plugins-official`)
  is curated by Anthropic at their discretion — superpowers lives there; that
  is the long-term target.
- Review criteria they state: valid manifest, no file access outside the
  plugin dir, clear skill instructions, adequate README. Note for the
  submission: our hooks keep verify-state under a user-owned
  `$TMPDIR/luciazero-verify-state-<uid>` directory (never the repo), and the
  strict gate only runs a command the *user* set via
  `LUCIAZERO_STRICT_VERIFY_CMD`.

## 2. `npx skills add ohm41321/luciazero` (live the moment the repo is public)

[vercel-labs/skills](https://github.com/vercel-labs/skills) scans public GitHub
repos for `skills/<name>/SKILL.md` with `name` + `description` frontmatter —
that is exactly our root `skills/` layout, so there is nothing to register.
The [skills.sh](https://skills.sh) leaderboard populates itself from install
telemetry; the only lever is people actually running the command. (†)

## 3. npm — `npx luciazero`

One-time setup, in this order:

- [x] npm account with 2FA-on-publish — done 2026-08-10
- [x] First publish of `luciazero` — 1.5.0 live 2026-08-10 (browser 2FA flow)
- [x] Configure **trusted publishing** (OIDC) — registered 2026-08-10:
      npmjs.com/package/luciazero → Settings → Trusted Publisher → GitHub
      Actions → user `ohm41321`, repo `luciazero`, workflow `release.yml`,
      environment blank. Exercised by `v2.0.0` on 2026-08-13;
      `npm view luciazero dist.attestations` reports SLSA provenance. npm
      generated it under OIDC without a `--provenance` flag.
- [x] Publish from a GitHub Actions workflow with `permissions: id-token: write`, done 2026-08-10 — `release.yml` job `npm-publish` runs on every `v*` tag (skips versions already live),
      npm CLI ≥ 11.5.1
- [ ] Never add lifecycle scripts (`postinstall` etc.): npm v12 blocks them by
      default and scanners flag packages that carry them. `test.sh` enforces
      this; keep it that way.
- [x] npmjs.com does not resolve relative image paths in READMEs — README image
      tags use immutable-revision `cdn.jsdelivr.net` URLs shared with GitHub,
      avoiding mutable branch paths and raw GitHub rate limits.
- [x] npm treats every root README variant as mandatory and npm 11 selected
      `README.th.md` for 2.3.0. The release job now publishes from a disposable
      staged package containing only `README.md`; the repository keeps the Thai
      README at its existing public path. The stage also omits `CHANGELOG.md`,
      which is release documentation rather than installer/runtime payload.

Users check and apply classic/Codex updates explicitly with
`npx luciazero@latest check-update` and `npx luciazero@latest update`.
`check-update` is the only installer-path command that contacts the npm
registry; `update` preserves the detected classic hook mode and runs the
already-downloaded installers. No lifecycle or background updater is allowed.

## 4. Directories, once live

- [ ] awesome-claude-code: submissions ONLY via their web issue form
      ("Recommend a new resource"); eligibility is repo ≥ 14 days old and
      actively developed, or ≥ 100 stars; human PRs are rejected (†)
- [ ] Codex side: "Awesome Codex CLI" pinned discussion on openai/codex;
      OpenAI's curated set is [openai/skills](https://github.com/openai/skills)
      (curated-acceptance process unconfirmed) (†)

## 5. Agent Bus — checkout only, and deliberately so

No installer channel ships it. `package.json` `files` does not list `agentd/`,
and the launcher step in `install.sh` is gated on
`agentd/luciazero_agentd/__init__.py`, which the npm payload does not carry:
"the npm payload ships this shim but not the package it runs". So a version
bump publishes the skills and hooks as always and moves the bus not at all.
Nothing about the bus reaches a user who has not cloned the repo and run
`./install.sh` from the checkout, which is the intended state for now.

Decided 2026-09-06. Five things close before that changes, in this order:

1. The wt-docs items 1-5 are green and merged.
2. A clean install is driven through `lucia claude` and `lucia codex` — the
   public command, not `run --agent ... --provider ...`.
3. The decision log reaches 3 of 3 workflows and 2 of 2 retros. It stands at
   2 of 3 and 0 of 2.
4. Packaging `agentd/` is taken as its own decision, reviewed as a public
   contract and as a security question. It is not a `files` entry: it puts a
   Python daemon, a pty proxy and a launchd or systemd service onto machines
   whose owners asked for a set of skills.
5. Install, upgrade and uninstall are proved on a machine that is not this
   one, and proved to leave the user's own configuration alone.

Item 2 was closed on 2026-09-06. A clean clone was installed and driven
through `lucia claude` in one window and `lucia codex` in the other, both
typed by the user rather than by a script, and the run's state directory was
kept. Its records are exported now rather than described from memory:
`docs/assets/evidence/msg_571db8b6423c46e69872e5241ad4ec09.json` and
`docs/assets/evidence/handshake-hi-what-20260906.json`. Between them: two
conversations, four messages, every delivery acknowledged and then completed,
and the two agent ids the short form assigns without being asked, `claude` and
`codex`. Neither conversation has a dispatcher run behind it, so the exporter
calls both `user-started`; three of the four waits were ended by a bus knock
and the fourth leaves 79 seconds or less unattributed.

Two things that run does not prove, said plainly rather than left for a reader
to assume:

- **No quota figure was captured, and none can be reconstructed.** The
  exchange carried no task, so nothing called `task_record_usage`, and the
  turns were the user's own session turns rather than dispatched ones, so no
  provider-side usage was measured either. What the record proves is that both
  real CLIs ran, bound, and answered each other through the public command.
  What it costs to do that is not in this evidence and must not be claimed
  from it.
- **It is not the third workflow.** The exchange was a handshake with no work
  attached, and the roadmap excludes demonstrations from the ledger by name —
  the same reason M7b's live chat is not a row. The decision log stands at 2
  of 3 workflows and 0 of 2 retros.

Item 4 was closed on 2026-09-07 by ADR 0008: the bus stays an opt-in,
checkout-only beta, and `agentd/` enters no installer or npm payload. One
channel does carry it, and the first draft of that ADR was wrong to say
otherwise: `release.yml` builds the GitHub release asset with `git archive
--format=zip ... HEAD` against a repository with no `.gitattributes`, so the
ZIP holds all 42 entries under `agentd/`, and `bin/lucia` as a symlink entry
besides. ADR 0008 now records that as the checkout channel rather than an
exception — the ZIP asks the same acts of a user as `git clone` does — and
says why an `export-ignore` was rejected. The other four items are open, and
item 5 has a partial answer worth writing down rather than leaving as a blank.

`scripts/gate-linux-container.sh` refuses any scratch root that already
exists, rather than deleting a path it was handed on the strength of a marker
file: a marker proves only that something once wrote a marker. Cleaning up an
old run is the caller's, and visible. It is otherwise the check item 5 asks
for: clone,
install, read-only invocations, a second install, uninstall, and a path-for-path
comparison of a home directory before and after. It runs in a Debian container,
or with `--inner` against a home you name, which is what a real second machine
should use. Two honest limits on what it has proved so far:

- **No second machine yet, and no container either.** The development machine
  has no docker, podman, colima or lima, so only the `--inner` path has run,
  and only on macOS. Linux and a second machine are both still unproved.
- **It found a real footprint on its first run, since fixed.** A home that
  started empty did not come back empty: `./uninstall.sh` left
  `.claude/CLAUDE.md.bak.<timestamp>` — whose entire content was the
  `@luciazero.md` line the installer itself wrote, on a machine that never had
  a `CLAUDE.md` — together with empty `.claude/agents` and `.claude/skills`
  directories. One install and one uninstall were enough; it was not an
  artefact of reinstalling, and `./test.sh` stayed green throughout because
  its `fresh-user install + uninstall` step does not count a leftover backup
  or an empty directory as a footprint. `uninstall.sh` now removes that one
  backup, under a deliberately narrow rule: only the path this invocation just
  created, only when its content is exactly the import line and nothing else,
  never by glob and never an older backup whose identical content is still
  somebody's decision to keep. Empty directories are removed leaf to root by
  name, and `rmdir` leaves any directory that still holds anything.
- **Phase 2 then found a second one, also since fixed.** After a real upgrade
  and an uninstall, a `CLAUDE.md` the user wrote came back one byte longer:
  `install.sh` appends the import line to an existing file as `printf
  '\n%s\n'` — a blank separator and then the line — and `uninstall.sh` removed
  only the line, so every install-and-uninstall cycle left one more blank line
  in a file nobody else had touched. It now drops that separator, but only
  where it can prove it put it there: `install.sh` records `appended` or
  `created` in `.luciazero-import` in the branch that actually writes, and
  `uninstall.sh` removes a blank line above the import line only on the first
  of those, and only while the file still hashes to what the installer left --
  the record carries that hash, so it is about this file rather than about the
  installer's habits, and a user who moves the import line or adds a blank of
  their own turns the swallow off. The record is owned by a marker in its first
  line, not by being a regular file, so a `.luciazero-import` that is a
  symlink, a directory, or somebody's own notes is neither followed, written,
  nor removed; it is created through `mktemp` in the directory it belongs to,
  so no symlink can be waiting at a predictable temporary path. The rewrite
  reads the backup snapshot rather than the live file, and the live file is
  compared against that snapshot again before the result is moved into place,
  so a decision and a transform cannot see two different files. That narrows
  the window against a concurrent editor; it does not close it, and no test
  covers a true race — what is tested is the stale-record path, which is the
  same guard reached deterministically.
- **The codex side does not do any of this, deliberately.**
  `uninstall-codex.sh` removes its marker block and leaves the blank separator
  `install-codex.sh` wrote, so a cycle still costs one blank line in
  `AGENTS.md`. Removing it would mean guessing, since there is no record on
  that side, and a user who moves the block after installing would lose a
  blank line of their own — the worse failure of the two. Giving the codex
  side the same ownership proof is what would make it safe, and that is its
  own piece of work. The distinction is not academic — a CLAUDE.md that already carries
  the import line makes `install.sh` leave the file alone entirely, so the
  blank line above it is the user's, and an uninstaller that assumed otherwise
  would delete it while printing "Other CLAUDE.md content was left untouched."
  Any other value, including none, which is every install older than this one,
  takes the old conservative path. Two full cycles now leave a seeded file
  byte-identical, and a file whose owner wrote the import line themselves
  keeps its blank line. `AGENTS.md` had the same defect from the same cause —
  `install-codex.sh` writes a blank separator before its marker block — and
  took the same fix in `uninstall-codex.sh`, where the block's own markers
  make the provenance unambiguous without a sidecar.
- **One asymmetry is left in place deliberately.** `uninstall.sh` now removes
  the `CLAUDE.md` backup it just made when that backup holds nothing but the
  import line. `uninstall-codex.sh` does not do the equivalent for a backup
  holding nothing but the doctrine block: that backup is a different shape and
  a wider rule, and phase 1 does not exercise the codex installers, so nothing
  here has tested it. A user who installs the codex side on a machine with no
  `AGENTS.md` and then uninstalls still keeps one backup file. Decide it on its
  own evidence rather than by analogy.
- **Upgrading from a release older than the record leaves one blank line.**
  `v2.4.3`'s `install.sh` appended the separator without recording that it
  had, so this uninstaller cannot prove the blank is its own and does not
  touch it. The check asserts what is actually true rather than pretending
  otherwise: every line the user wrote survives unchanged, and the residue is
  at most one trailing blank line. `AGENTS.md` has no such residue even on
  that path, because its marker block makes the separator's provenance plain
  without a sidecar. Phase 3 covers the case where the record does exist —
  this revision installing and uninstalling a seeded home — and there the bar
  is byte-identical, on both files.
- **What phase 1 compares is paths, not bytes.** It catches a file or a
  directory left behind; it says nothing about the contents of a path that
  appears in both listings. Phase 2 is what compares bytes, and it compares
  two files: a `CLAUDE.md` and an `AGENTS.md` that a user wrote, across a real
  upgrade from the previous released tag to this revision and out the other
  side of both uninstallers.

Item 5 is still not met, for one reason only: nothing has run anywhere but
this machine. Linux and a second machine are both unproved, and "clean
uninstall" should carry that qualifier until one of them has run.

Until then the bus is described as checkout-only wherever it is described at
all, and a release note that implies otherwise is wrong.

## Channel honesty

The classic `./install.sh` remains the reference channel — it is the only one
that carries the statusline and the CLAUDE.md import. The plugin substitutes a
`SessionStart` doctrine hook (same capped text, silent when a classic install
exists); `npx skills` carries the 13 skills — no doctrine, no reviewer agent,
no hooks. Do not describe the channels as equivalent.
