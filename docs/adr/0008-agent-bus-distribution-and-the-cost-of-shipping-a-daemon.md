# ADR 0008: Agent Bus distribution: an opt-in checkout beta, and what would change it

Status: accepted by the maintainer on 2026-09-07. Closes item 4 of the release
gate in `docs/publishing.md` §5, which asked for packaging to be taken as its
own decision rather than settled by a `files` entry.

## Context

ADR 0002 decided that the daemon would ship as a companion npm package,
`luciazero-agentd`, living in `agentd/` and excluded from the core package's
`files`. Its amendment of 2026-09-04 changed how the launcher reaches users:
`npx luciazero` never had a daemon to run, so a bin shim in the npm payload
would have been a command with no package behind it, and `install.sh` writes
`bin/luciazero-agentd` from a checkout instead.

The companion package was never created. That is the actual state today, and
it is worth stating plainly rather than leaving as an unfinished intention:

- `package.json` `files` lists `bin agents claude skills migrations` and the
  four installer scripts. `agentd/` is not there, and the string `agentd` does
  not appear in `package.json` at all.
- The launcher step in `install.sh` is gated on
  `agentd/luciazero_agentd/__init__.py`, which no npm payload carries, so an
  npm install skips it entirely and leaves no command behind that cannot run.
- What the core package does carry is the `/lucia-bus` and `/lucia-chat`
  skills and the `luciazero bus` status client. Each of them degrades to a
  sentence when there is no daemon: the skill says to stop and start nothing,
  and `bin/bus.js` exits 2 with `no running daemon recorded in <dir>`.

So a version bump publishes the skills and the installers as always and moves
the bus not at all. The question this ADR answers is whether that should
change now, on the strength of ff35542 making `lucia claude` and `lucia codex`
the whole of the ordinary path.

## Options considered

1. **Ship the companion package now.** `agentd/package.json` as a second
   manifest, a second publish job on the `v*` tag, and `npm i -g
   luciazero-agentd` as the install. This is what ADR 0002 decided, and the
   work is not large.
2. **Keep it a checkout-only, opt-in beta.** Clone the repository, run
   `./install.sh`, put `~/.claude/bin` on PATH. The core package keeps the two
   skills and the status client, which continue to say so when the daemon is
   absent.
3. **Move `agentd/` to its own repository.** Considered and rejected in ADR
   0002 while the contract was still moving, and the contract is still moving:
   the terminal-binding rule changed in 02ea1a2 and the public command changed
   in ff35542, both within the last week.

## Decision

Option 2. The Agent Bus is an opt-in, checkout-only beta. `agentd/` enters no
installer or npm payload, and no release note, README line, or skill
description may imply that an ordinary install reaches it. The one channel
that does carry `agentd/` is the GitHub release ZIP, and that is the checkout
itself rather than an exception to this decision; the paragraph on channels
under Consequences says exactly what each one holds.

The reason is not that option 1 is hard. It is that the two options are not
equally reversible, and the asymmetry runs the wrong way for the thing being
shipped.

A user who runs `npx luciazero` is asking for a set of skills, a doctrine
block, and some hooks: text files, all of them inert until a session reads
them, all of them removed by `./uninstall.sh`. Option 1 would put three things
of a different kind on that same machine, on the same consent:

- **A long-running local daemon** that owns a SQLite database, listens on
  loopback HTTP, and holds a bearer token on disk.
- **A pty proxy.** `run` sits between the user's keyboard and the provider for
  the life of the session. Every password, every prompt, every pasted secret
  passes through it. It is written not to record keystroke bytes and it does
  not, but the correctness of that is now load-bearing for anyone who installs
  it, and it was load-bearing for a much smaller population an hour before.
- **A service installer.** `service install` writes a launchd plist or a
  systemd unit, which is the one artifact here that outlives both the terminal
  and the user's memory of having agreed to it.

Undoing a bad `files` entry means publishing a patch. It does not mean
un-writing the launchd unit on a machine whose owner has stopped reading the
release notes. The population that has cloned a repository and put a directory
on PATH is a population that chose this; the population that typed `npx
luciazero` chose skills.

## What would change this decision

Option 1 is reopened when all five hold, and not before. These are conditions,
not a schedule.

1. The five items of the release gate in `docs/publishing.md` §5 are closed on
   their own terms, item 3 included: three of three workflows and two of two
   retros in the decision log, with the retros written by the user, since the
   criterion asks what a person attributed and nobody else can supply that.
2. A written security review of the pty proxy exists as its own document,
   covering at least: what the proxy can see, what it records and where, the
   bytes the nudge path types into a live session and the last gate that stops
   a peer's payload from reaching a keyboard, the token file's mode and
   lifetime, and what a compromised daemon can reach on the host.
3. The service installer is reviewed as a public contract, with proof that
   uninstalling removes the unit on both platforms, and an answer for the unit
   that survives an upgrade that changes its arguments.
4. There is an answer for machines without Python 3.10 or newer. The core
   package's floor is Node 18; installing `luciazero` must not begin failing,
   warning, or half-succeeding on a machine that was fine yesterday.
5. Someone owns the second package's release cadence. Two packages that must
   agree about a protocol are two chances to publish a pair that does not.

## Consequences

- The bus's population stays small and self-selected. This is the point, and
  it has a cost worth naming: the decision log's second criterion needs a
  retro from somebody who felt the friction, and a small population produces
  those slowly. The gate is not made easier by this ADR; it is made honest.
- Every user-facing sentence about the bus has to carry the qualifier. The
  README already does at line 302 and the older changelog entry does at line
  38; the entry for `lucia` does not yet, and neither does the hint in
  `bin/bus.js`, which still tells the user to run `python3 -m luciazero_agentd
  serve` — the invocation the launcher exists to replace. Both are corrected
  alongside this ADR.
- The three channels hold three different things, and the decision above is
  about the first two only.

  **npm.** `bin/luciazero-agentd` is in the payload, because `files` lists
  `bin`. `bin/lucia` is not, and not by design: it is a symlink in the
  repository and npm leaves symlinks out of a tarball. `npm pack --dry-run
  --json` lists 44 files, `bin/luciazero-agentd` among them and no
  `bin/lucia`. The shim that does ship is inert — it exits 127 with a message
  naming the checkout it needs — so nothing follows from the asymmetry today.
  Two things would change that and are worth rechecking then: a payload that
  grows a way to run the shim, and `bin/lucia` ceasing to be a symlink, which
  would put a second inert command in the tarball without anyone deciding to.

  **The GitHub release ZIP.** `release.yml` builds it with `git archive
  --format=zip ... HEAD`, and there is no `.gitattributes`, so the asset is
  the whole repository at the tag: 42 entries under `agentd/`, and `bin/lucia`
  present as a symlink entry where npm dropped it. That is deliberate now that
  it has been looked at. A source archive of a tag that omitted the source
  would be the stranger artifact, and unpacking a ZIP costs the same acts as a
  clone — unpack, run `./install.sh`, put a directory on PATH — so it reaches
  nobody who did not go looking. The consent asymmetry this ADR turns on is
  specific to npm: `npx luciazero` is a command people run for skills, and
  that is the channel `agentd/` stays out of. Stripping `agentd/` from the
  archive with an `export-ignore` was considered and rejected for that reason;
  it would also take the beta's only download away from anyone without git.

  **A checkout.** Everything, which is the point.
- ADR 0002's packaging decision is superseded on distribution only. Its
  language decision — Python 3.10+, standard library only, no pip
  dependencies — stands unchanged, as does its rule that an ordinary
  `npx luciazero` install never starts a daemon or writes bus state.

## Rollback

This ADR decides not to ship something. Reversing it costs nothing that has
already been spent: `agentd/` is a directory in this repository either way, and
the five conditions above are the work that would have to happen before option
1 regardless of when it is chosen.
