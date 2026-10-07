# Windows field test

Native Windows support (installer, hooks, skill helpers, Agent Bus, no WSL)
has passed CI on `windows-latest`. That covers Node 18 and 22 for the
installer, settings wiring, hooks, global install and skill helpers, and
Python 3.10 and 3.13 for the Agent Bus suite and Lucia Relay. Nobody has
run it on a real Windows machine yet. This checklist covers what CI cannot
show. Written 2026-10-07 against `windows-native` at 993f1d0.

## What CI does not cover

- **The account.** The runner is an administrator account on an English
  image, with no one at the desktop. Nothing has run as a standard user, in
  another display language, with a user profile path containing spaces or
  non-ASCII characters, or with OneDrive-redirected folders.
- **The dialog.** No dialog was clicked. The approval `MessageBox` and its
  timeout are untested by hand.
- **The scheduled task.** No Task Scheduler task was registered and run at
  logon as a standard user.
- **Skipped tests.** 18 Agent Bus tests skip on Windows. Most drive a POSIX
  pty: the nudge proxy, typing passthrough, exit-code passthrough, and the
  knock that waits for a provider that is mid-turn. `test_windows` drives the
  pseudo console separately, but no one has typed into a `lucia run` session
  in Windows Terminal or conhost. The `claim approve` process-table deny
  tests also skip ("Windows has no ps to deny"). `safe-bisect`'s `#!` test is
  POSIX only.
- **Unverified cmd.exe behaviour.** The strict hook keeps a red (fails
  closed) for these forms. CI shows that the gate blocked them; it does not
  show what cmd.exe ran:
  - `;lz-red` and `lz-red,x`: which program, if any, cmd.exe started;
  - `:label && x` under `cmd /d /s /c`: whether the part after `&&` runs.
- **Other languages.** cmd.exe's "is not recognized" line is matched in
  English only. In another language, revert-probe and the strict hook rely
  on file-system checks instead. That is tested by injecting a French line,
  never on a localized Windows.

## Machines

Run the whole list on at least one machine. Use the second for the rows
marked (2).

| | Machine 1 | Machine 2 |
|---|---|---|
| Windows | 11, current | 10 22H2 |
| Account | standard user, no admin | administrator |
| Display language | Thai | English |
| Profile path | contains a space and Thai characters | plain |
| Shells | PowerShell 5.1, cmd.exe | PowerShell 7, Windows Terminal |
| Python | Microsoft Store alias left on, plus python.org 3.12 | `py` launcher only |
| Node | 22 LTS | 18 |
| Git for Windows | `core.autocrlf=true` | `core.autocrlf=input` |

Before starting, record the output of `ver`, `chcp`, `Get-Culture`,
`$PSVersionTable.PSVersion`, `node -v`, `python -V`, `py -0p`, `git --version`
and `Get-ExecutionPolicy -List`.

## 1. Core install (npx)

- [ ] `npx luciazero` in PowerShell with the default execution policy, then
      in cmd.exe. If PowerShell refuses to run `npx.ps1`, record the exact
      message: the README must say what to do about it.
- [ ] `npx luciazero --status` lists every component as installed.
- [ ] Running `npx luciazero` a second time changes nothing (compare
      `%USERPROFILE%\.claude` before and after).
- [ ] With your own status line and hooks already in `settings.json`
      (including one saved with a BOM and CRLF), install keeps them and backs
      up anything it replaces.
- [ ] With a skill directory that is a junction (`mklink /J`), as a standard
      user without Developer Mode, install backs it up (as a junction) and
      goes on; it must not stop with EPERM.
- [ ] `npx luciazero uninstall` removes only what install added, and your
      own settings are back exactly as they were.
- [ ] `npx luciazero codex` and `npx luciazero uninstall-codex` behave the
      same way for `%USERPROFILE%\.codex`.

## 2. Global install

- [ ] `npx luciazero global-install`: the files land under npm's global
      prefix (`%APPDATA%\npm` unless moved), and no startup file or user Path
      entry is edited.
- [ ] In a new shell, `luciazero --status` works, and so do
      `npx luciazero global-status` and `global-uninstall`.

## 3. Hooks in Claude Code

- [ ] With the hooks on, edit a file and end the turn: one nudge appears.
      Run the repo's verify command (as a Bash tool call and as a PowerShell
      tool call): the nudge is cleared.
- [ ] The status line shows the model, the branch and the verify state in a
      repo whose path contains Thai characters and a space.
- [ ] A `git.exe` copied into the project is never the one the status line
      runs. Repeat with `node.exe`.
- [ ] A hook does not slow down an ordinary tool call noticeably. Record the
      time with and without the hooks.
- [ ] Run the verify command as a background Bash call (`run_in_background`):
      the nudge is not cleared until a foreground run finishes green.
- [ ] `cd` into a subdirectory in one Bash call, edit a file, end the turn:
      the nudge still appears, and the status line keeps the project's verify
      state.
- [ ] A committed `.claude/settings.json` whose `env` sets
      `luciazero_strict_verify_cmd` in lowercase: named at `SessionStart` as
      refused, and never run at stop.

## 4. Strict verify gate (Thai display language)

Set `LUCIAZERO_STRICT_VERIFY_CMD` in your personal settings and end a turn
after an edit, once for each command below.

- [ ] A command that does not exist (`luciazero-no-such-cmd`): ordinary
      nudge, no "Strict verify gate", no strict-block row in
      `luciazero-stats.log`.
- [ ] A test that fails: blocks, writes a strict-block row, and sets
      `last_verify` to fail.
- [ ] A runner `.cmd` that deletes itself and exits 1: blocks.
- [ ] `;lz-red`, `lz-red,x`, `:label && lz-red` (with `lz-red.cmd` on PATH
      exiting 1): record what cmd.exe printed, the exit status, and whether
      `lz-red` ran.
- [ ] A command slower than `LUCIAZERO_STRICT_TIMEOUT`: nudge, not block.
- [ ] A `.cmd` slower than the timeout that starts a child
      (`ping -n 600 127.0.0.1`): record whether `ping.exe` still runs after
      the nudge. On POSIX the timeout kills the whole process group; on
      Windows only `cmd.exe` is known to be stopped.

## 5. Skill helpers

In a repo with a space and Thai characters in its path, under both autocrlf
settings:

- [ ] `/ready`'s detect lists the test commands and CI run lines.
- [ ] `revert-probe` reports PASS for a test that bites, FAIL for a vacuous
      one, and UNASSESSABLE in two cases: when the change adds the runner
      (`run-tests.cmd`), and when the verify command names a program that
      is not installed (in Thai, cmd.exe's line is not the English one).
- [ ] `safe-bisect` finds the first bad commit and leaves the worktree clean.
- [ ] A repo nested deeper than 260 characters: each helper either works or
      says plainly why not.

## 6. Lucia Relay

- [ ] `py -3 <skill-dir>\scripts\relay.py` and `python ...relay.py` both
      work, and so does `npx luciazero relay validate` with only the py
      launcher on PATH; with only the Store alias present, the error says no
      Python 3.9+ was found.

## 7. Agent Bus (from a checkout)

- [ ] `node bin\luciazero.js` puts `luciazero-agentd.cmd` and `lucia.cmd` in
      `%USERPROFILE%\.claude\bin`, and names that directory when it is not on
      the user Path.
- [ ] The launchers pick the first Python 3.10+ among `python3`, `python`
      and `py -3`, skip the Store alias, and leave the working directory
      unchanged. Try them from PowerShell and from cmd.exe.
- [ ] `lucia claude` in one window and `lucia codex` in another, in both
      Windows Terminal and conhost. Check that:
  - [ ] typing and Ctrl+C reach the provider;
  - [ ] the window resizes cleanly;
  - [ ] the provider's exit code becomes the command's exit code;
  - [ ] a message delivered to an idle session knocks once;
  - [ ] a message to a session that is mid-turn waits.
- [ ] Approval dialog:
  - [ ] Allow and Deny each decide;
  - [ ] closing the dialog or letting it time out decides nothing;
  - [ ] `--approve-with console` and `LUCIAZERO_AGENT_BUS_NO_DIALOG=1`
        print the code instead.
- [ ] Service, as a standard user:
  - [ ] `luciazero-agentd service install --dry-run` shows the task XML and
        the commands;
  - [ ] `service install` registers `\Luciazero\agentd` without asking for
        admin;
  - [ ] the daemon starts at the next logon under `pythonw.exe` with no
        console window;
  - [ ] `service status` reports it;
  - [ ] `daemon.log` is in the state directory, and that directory is
        readable by you alone (check with `icacls`);
  - [ ] with the service running, bind a worktree and cancel a managed
        turn: no console window flashes for `git` or `taskkill`. Note
        whether each managed turn's provider opens a console window of its
        own; nothing suppresses that yet.
- [ ] After sleep and resume, and after a logoff and logon, the daemon is
      serving again.
- [ ] `service uninstall` removes the task and only the files carrying the
      ownership marker. A task XML you wrote yourself at that path is left
      alone.
- [ ] The full uninstall stops the service before removing the launcher.

## 8. Lookup on PATH only

- [ ] Put a copy of `node.exe` in the project under the names `git.exe`,
      `node.exe`, `npm.cmd`, `python.exe`, `schtasks.exe` and
      `powershell.exe`, then run the hooks, the installer and the bus
      commands there. None of the copies run.

## Reporting

For each failed box, record:
- the exact command;
- its full output;
- the facts from the "Machines" section;
- whether it reproduces in a fresh shell.

Fix with a regression test where CI can hold one, and record anything
non-obvious in [lessons.md](lessons.md). Tick a box only after watching it
pass on the machine, never from CI or a macOS run.
