# tests/gates/install.sh — sandboxed Claude install/uninstall cycles, data safety, enforcement pack wiring, Agent Bus launcher.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 5. sandbox install cycle — never touches the real ~/.claude
SB="$(mktemp -d)"
CX="$(mktemp -d)"
trap 'rm -rf "${CLAUDE_CONFIG_DIR}" "${SB}" "${CX}"' EXIT
printf '@RTK.md\n\n# pre-existing user content\n' > "${SB}/CLAUDE.md"
mkdir -p "${SB}/skills/handoff"
cp "${ROOT}/migrations/handoff-v1.5.0.SKILL.md" "${SB}/skills/handoff/SKILL.md"
# A v2.2 install may still have the untouched compatibility alias. The v2.3
# installer must remove it, while preserving a customized copy.
mkdir -p "${SB}/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SB}/skills/luciazero-bootstrap/SKILL.md"
mkdir -p "${SB}/.luciazero-managed/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SB}/.luciazero-managed/skills/luciazero-bootstrap/SKILL.md"
# Generic names may already belong to the user or another plugin. The install
# must preserve the collision outside the discoverable skills directory.
mkdir -p "${SB}/skills/plan"
printf '%s\n' '---' 'name: plan' '---' '# pre-existing plan owner' > "${SB}/skills/plan/SKILL.md"

CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null
[ -f "${SB}/luciazero.md" ] || fail "doctrine not installed"
while IFS= read -r NS; do
  [ -f "${SB}/skills/${NS}/SKILL.md" ] || fail "${NS} skill not installed"
done < <(skill_inventory)
[ -x "${SB}/skills/ready/scripts/detect.sh" ] || fail "detect.sh not installed or not executable"
[ ! -e "${SB}/skills/luciazero-bootstrap" ] \
  || fail "classic install did not migrate the retired compatibility alias"
[ -x "${SB}/skills/done/scripts/revert-probe.sh" ] || fail "revert-probe.sh not installed or not executable"
[ -x "${SB}/skills/bisect/scripts/safe-bisect.sh" ] || fail "safe-bisect.sh not installed or not executable"
[ -x "${SB}/skills/lucia-relay/scripts/relay.py" ] || fail "relay.py not installed or not executable"
[ -f "${SB}/.luciazero-version" ] || fail "version sidecar not written"
[ ! -d "${SB}/skills/handoff" ] || fail "managed legacy handoff was not migrated"
[ -f "${SB}/agents/reviewer.md" ] || fail "reviewer agent not installed"
[ ! -d "${SB}/hooks" ] || fail "hooks installed without --with-hooks"
[ "$(grep -cxF '@luciazero.md' "${SB}/CLAUDE.md")" = 1 ] || fail "import line not added"
grep -q 'pre-existing plan owner' "${SB}/.luciazero-backups"/skills/plan.bak.*/SKILL.md \
  || fail "classic install did not back up a colliding generic skill"

mkdir -p "${SB}/skills/handoff"
printf '%s\n' '---' 'name: handoff' '---' '# user customization' > "${SB}/skills/handoff/SKILL.md"
# Customizing a managed copy before an update must also be backed up, then the
# update may safely restore the shipped version.
echo '# customized managed plan' >> "${SB}/skills/plan/SKILL.md"
mkdir -p "${SB}/skills/luciazero-bootstrap"
printf '%s\n' '---' 'name: luciazero-bootstrap' '---' '# user-owned alias' \
  > "${SB}/skills/luciazero-bootstrap/SKILL.md"
CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null
[ "$(grep -cxF '@luciazero.md' "${SB}/CLAUDE.md")" = 1 ] || fail "install is not idempotent"
grep -q 'user customization' "${SB}/skills/handoff/SKILL.md" || fail "install deleted a customized legacy handoff"
! grep -q 'customized managed plan' "${SB}/skills/plan/SKILL.md" \
  || fail "classic reinstall did not restore the shipped plan skill"
grep -q 'customized managed plan' "${SB}/.luciazero-backups"/skills/plan.bak.*/SKILL.md \
  || fail "classic reinstall did not back up a customized managed skill"
grep -q 'user-owned alias' "${SB}/skills/luciazero-bootstrap/SKILL.md" \
  || fail "classic migration deleted a customized retired alias"
rm -rf "${SB}/skills/handoff"
echo "ok  install + idempotent reinstall"

# --status: green on a complete install, red (and specific) once a piece is gone
CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" --status >/dev/null \
  || fail "--status red on a complete install"
rm -rf "${SB}/skills/debug"
RC=0; SOUT="$(CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" --status 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || fail "--status green with a skill missing"
echo "${SOUT}" | grep -q 'MISS.*debug' || fail "--status did not name the missing skill: ${SOUT}"
CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null   # restore for the uninstall checks
echo "ok  --status green/red"

# Uninstall removes only byte-for-byte managed components; edits made after
# install are user data and must survive.
echo '# keep customized bisect' >> "${SB}/skills/bisect/SKILL.md"
echo '# keep customized reviewer' >> "${SB}/agents/reviewer.md"
echo '# keep customized doctrine' >> "${SB}/luciazero.md"
UOUT="$(CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/uninstall.sh" 2>&1)"
grep -q 'keep customized doctrine' "${SB}/luciazero.md" \
  || fail "classic uninstall deleted a customized doctrine"
while IFS= read -r NS; do
  if [ "${NS}" = bisect ]; then
    grep -q 'keep customized bisect' "${SB}/skills/bisect/SKILL.md" \
      || fail "classic uninstall deleted a customized managed skill"
  else
    [ ! -d "${SB}/skills/${NS}" ] || fail "${NS} skill left behind"
  fi
done < <(skill_inventory)
grep -q 'user-owned alias' "${SB}/skills/luciazero-bootstrap/SKILL.md" \
  || fail "classic uninstall deleted a customized retired alias"
grep -q 'keep customized reviewer' "${SB}/agents/reviewer.md" \
  || fail "classic uninstall deleted a customized managed agent"
echo "${UOUT}" | grep -q 'not the exact Luciazero-managed copy; left untouched' \
  || fail "classic uninstall did not explain preserved customizations"
[ ! -f "${SB}/.luciazero-version" ] || fail "version sidecar left behind"
grep -qxF '@RTK.md' "${SB}/CLAUDE.md" || fail "pre-existing CLAUDE.md content damaged"
grep -qxF '# pre-existing user content' "${SB}/CLAUDE.md" || fail "pre-existing CLAUDE.md content damaged"
! grep -qxF '@luciazero.md' "${SB}/CLAUDE.md" || fail "import line left behind"
echo "ok  uninstall restores CLAUDE.md"

# 5b. fresh-user cycle: no pre-existing CLAUDE.md at all — uninstall must not
# abort on the import-line-only file (regression: grep no-match + set -e)
SB2="$(mktemp -d)"
CLAUDE_CONFIG_DIR="${SB2}" "${ROOT}/install.sh" >/dev/null
CLAUDE_CONFIG_DIR="${SB2}" "${ROOT}/uninstall.sh" >/dev/null \
  || { rm -rf "${SB2}"; fail "uninstall failed on a fresh install (import-line-only CLAUDE.md)"; }
[ ! -f "${SB2}/CLAUDE.md.tmp" ] || { rm -rf "${SB2}"; fail "uninstall left CLAUDE.md.tmp behind"; }
if [ -f "${SB2}/CLAUDE.md" ]; then
  ! grep -qxF '@luciazero.md' "${SB2}/CLAUDE.md" \
    || { rm -rf "${SB2}"; fail "dangling import line after fresh-user uninstall"; }
fi
rm -rf "${SB2}"
echo "ok  fresh-user install + uninstall"

# 5b2. Three data-safety rules that the steps above do not reach, each one a
# way for an installer to destroy something nobody asked it to touch.
SB3="$(mktemp -d)"
SB3_FAIL() { rm -rf "${SB3}" "${SB3}-target" "${SB3}-scratch"; fail "$1"; }

# (i) `.luciazero-import` is a symlink somebody else put there. `printf >` on
# a symlink truncates the far end, so the installer must neither follow it nor
# replace it, and the uninstaller must leave it where it is.
printf 'someone elses data\n' > "${SB3}-target"
ln -s "${SB3}-target" "${SB3}/.luciazero-import"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" >/dev/null 2>&1   || SB3_FAIL "install.sh failed when .luciazero-import was a symlink"
[ -L "${SB3}/.luciazero-import" ] || SB3_FAIL "install.sh replaced a symlink it did not own"
grep -qxF 'someone elses data' "${SB3}-target"   || SB3_FAIL "install.sh followed the symlink and truncated its target"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/uninstall.sh" >/dev/null 2>&1   || SB3_FAIL "uninstall.sh failed when .luciazero-import was a symlink"
[ -L "${SB3}/.luciazero-import" ] || SB3_FAIL "uninstall.sh deleted a symlink it did not own"
grep -qxF 'someone elses data' "${SB3}-target"   || SB3_FAIL "uninstall.sh destroyed the symlink's target"
rm -rf "${SB3}" "${SB3}-target"

# (ii) The user rearranges their CLAUDE.md after installing. The record of the
# separator is only usable while the file is still as the installer left it;
# once it is not, every byte the user added has to survive the uninstall.
SB3="$(mktemp -d)"
printf '# mine\n\nkeep\n' > "${SB3}/CLAUDE.md"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" >/dev/null
printf '# mine\n\nkeep\n\nmy new note\n\n@luciazero.md\n' > "${SB3}/CLAUDE.md"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/uninstall.sh" >/dev/null   || SB3_FAIL "uninstall.sh failed on a CLAUDE.md the user had rearranged"
printf '# mine\n\nkeep\n\nmy new note\n\n' | cmp -s - "${SB3}/CLAUDE.md"   || SB3_FAIL "uninstall.sh did not leave the rearranged CLAUDE.md byte for byte:
$(cat -A "${SB3}/CLAUDE.md")"
rm -rf "${SB3}"

# (iii) The gate script is handed a directory that already exists. It deletes
# its scratch root whole, so it must refuse every path it did not make -- and
# a file named like a marker, or a symlink wearing that name, must buy nothing.
SB3="$(mktemp -d)"
printf 'precious\n' > "${SB3}/sentinel"
printf 'created by scripts/gate-linux-container.sh\n' > "${SB3}/.luciazero-gate5-scratch"
LUCIAZERO_GATE_HOME="${SB3}" "${ROOT}/scripts/gate-linux-container.sh" --inner >/dev/null 2>&1   && SB3_FAIL "the gate script accepted a directory it did not create"
grep -qxF 'precious' "${SB3}/sentinel"   || SB3_FAIL "the gate script deleted a directory it was handed"
rm -rf "${SB3}"

# (iv) `.luciazero-import` is an ordinary file somebody else keeps notes in.
# Being a regular file is not ownership; only the marker in the first line is.
SB3="$(mktemp -d)"
printf 'my own notes\n' > "${SB3}/.luciazero-import"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" >/dev/null 2>&1 \
  || SB3_FAIL "install.sh failed on a foreign .luciazero-import"
printf 'my own notes\n' | cmp -s - "${SB3}/.luciazero-import" \
  || SB3_FAIL "install.sh overwrote a .luciazero-import it did not own"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/uninstall.sh" >/dev/null 2>&1 \
  || SB3_FAIL "uninstall.sh failed on a foreign .luciazero-import"
printf 'my own notes\n' | cmp -s - "${SB3}/.luciazero-import" \
  || SB3_FAIL "uninstall.sh deleted a .luciazero-import it did not own"
rm -rf "${SB3}"

# (v) No predictable temporary path. A symlink waiting at a guessable name
# must never be written through, and no temporary file may survive the run.
SB3="$(mktemp -d)"
printf 'someone elses data\n' > "${SB3}-target"
for GUESS in ".luciazero-import.tmp" ".luciazero-import.tmp.1" ".luciazero-import.tmp.99999"; do
  ln -s "${SB3}-target" "${SB3}/${GUESS}"
done
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" >/dev/null 2>&1 \
  || SB3_FAIL "install.sh failed with decoy temp symlinks present"
grep -qxF 'someone elses data' "${SB3}-target" \
  || SB3_FAIL "install.sh wrote through a symlink at a predictable temp path"
LEFT="$(find "${SB3}" -maxdepth 1 -name '.luciazero-import.*' -type f | wc -l | tr -d ' ')"
[ "${LEFT}" = 0 ] || SB3_FAIL "install.sh left ${LEFT} temporary provenance files behind"
provenance_ok=0
head -n 1 "${SB3}/.luciazero-import" 2>/dev/null | grep -qxF 'luciazero-managed: import-provenance' \
  && provenance_ok=1
[ "${provenance_ok}" = 1 ] || SB3_FAIL "install.sh did not write its own provenance record"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
grep -qxF 'someone elses data' "${SB3}-target" || SB3_FAIL "uninstall.sh destroyed a decoy symlink's target"
rm -rf "${SB3}" "${SB3}-target"

# (vi) The codex side has no ownership record, so it must remove its block and
# nothing else, even when the user has moved that block since installing.
SB3="$(mktemp -d)"
printf '# mine\n\nkeep\n' > "${SB3}/AGENTS.md"
CODEX_HOME="${SB3}" "${ROOT}/install-codex.sh" >/dev/null 2>&1 \
  || SB3_FAIL "install-codex.sh failed on a seeded AGENTS.md"
{ printf '# mine\n\nkeep\n\nmy new note\n\n'
  sed -n '/<!-- luciazero:start -->/,/<!-- luciazero:end -->/p' "${SB3}/AGENTS.md"
  printf '\ntrailing note of mine\n'; } > "${SB3}/AGENTS.md.rearranged"
mv "${SB3}/AGENTS.md.rearranged" "${SB3}/AGENTS.md"
CODEX_HOME="${SB3}" "${ROOT}/uninstall-codex.sh" >/dev/null 2>&1 \
  || SB3_FAIL "uninstall-codex.sh failed on a rearranged AGENTS.md"
for USER_LINE in '# mine' 'keep' 'my new note' 'trailing note of mine'; do
  grep -qxF "${USER_LINE}" "${SB3}/AGENTS.md" \
    || SB3_FAIL "uninstall-codex.sh dropped the user's line: ${USER_LINE}"
done
! grep -qF 'luciazero:start' "${SB3}/AGENTS.md" || SB3_FAIL "uninstall-codex.sh left its block behind"
rm -rf "${SB3}"

# (vii) The gate script proves a footprint, so its own environment is part of
# what it proves. install.sh and uninstall.sh read CLAUDE_CONFIG_DIR,
# CODEX_HOME, LUCIAZERO_BIN_DIR and LUCIAZERO_SERVICE_ROOT before they fall
# back to $HOME, and the gate only sets HOME, which loses to every one of them.
# Carried in from the caller's shell they redirect the gate's installs into the
# operator's real configuration, and the run still reports that it wrote
# nothing outside its own root.
SB3="$(mktemp -d)"
LEAK="${SB3}/leak"
SB3_GATE_OUT="$(CLAUDE_CONFIG_DIR="${LEAK}/claude" CODEX_HOME="${LEAK}/codex" \
  LUCIAZERO_BIN_DIR="${LEAK}/bin" LUCIAZERO_SERVICE_ROOT="${LEAK}/service" \
  LUCIAZERO_GATE_HOME="${SB3}/root" \
  "${ROOT}/scripts/gate-linux-container.sh" --inner 2>&1)" \
  || SB3_FAIL "the gate script did not run green with config env vars set in the caller's shell:
${SB3_GATE_OUT}"
[ ! -e "${LEAK}" ] \
  || SB3_FAIL "the gate script installed outside its own root: $(find "${LEAK}" -maxdepth 2 | head -5)"
rm -rf "${SB3}"
echo "ok  installers refuse foreign provenance paths and keep rearranged user content"

# 5b3. The instruments release gate item 5 is measured with. The gate proves
# its own footprint; these two answer the other half of the item -- that the
# operator's real configuration came out unchanged -- and they are here because
# the prose version of them shipped blind spots. A third of the rows on the
# machine that ran it carried a space in the path, which a left split reads as
# four fields. A symlink pointed somewhere new kept its row. And the first two
# attempts at deciding what counts both worked by naming the harness's own
# directories, a list that was incomplete twice over; what counts is named from
# the installers instead, which is where the claim comes from.
GM="$(mktemp -d)"
GM_FAIL() { rm -rf "${GM}"; fail "$1"; }
MANIFEST="${ROOT}/scripts/gate-config-manifest.py"
COMPARE="${ROOT}/scripts/gate-config-compare.py"
mkdir -p "${GM}/home/.claude/skills/dir with space" "${GM}/home/.claude/projects" \
  "${GM}/home/.claude/backups" "${GM}/home/.claude/sessions" "${GM}/home/.codex"
printf 'doctrine\n' > "${GM}/home/.claude/CLAUDE.md"
printf 'skill\n' > "${GM}/home/.claude/skills/dir with space/SKILL.md"
printf 'turn one\n' > "${GM}/home/.claude/projects/session.jsonl"
printf 'state\n' > "${GM}/home/.claude/sessions/1403674.json"
printf 'backup\n' > "${GM}/home/.claude/backups/.claude.json.backup.1788967498969"
printf 'agents\n' > "${GM}/home/.codex/AGENTS.md"
printf 'first\n' > "${GM}/target-one"
printf 'second\n' > "${GM}/target-two"
ln -s "${GM}/target-one" "${GM}/home/.claude/settings.json"
python3 "${MANIFEST}" "${GM}/home" > "${GM}/before" || GM_FAIL "the manifest failed on a home with a space in a path"
grep -qF 'skills/dir with space/SKILL.md' "${GM}/before" \
  || GM_FAIL "the manifest did not record the path with a space in it"

GM_MUST_FAIL() {
  RC=0; python3 "${COMPARE}" "${GM}/before" "${GM}/after" > "${GM}/out" || RC=$?
  [ "${RC}" = 1 ] || GM_FAIL "$1"
  grep -qE "FAIL +$2 +$3" "${GM}/out" || GM_FAIL "$4: $(cat "${GM}/out")"
}

# (i) the harness rewriting its own state is not a footprint, and the shapes
# below are the ones a real run produced: a transcript appended to, a session
# file rewritten, and a rotated backup that arrives as one added path and one
# removed path at once
printf 'turn two\n' >> "${GM}/home/.claude/projects/session.jsonl"
printf 'newer state\n' > "${GM}/home/.claude/sessions/1403674.json"
rm -f "${GM}/home/.claude/backups/.claude.json.backup.1788967498969"
printf 'backup\n' > "${GM}/home/.claude/backups/.claude.json.backup.1788967866406"
python3 "${MANIFEST}" "${GM}/home" > "${GM}/after"
python3 "${COMPARE}" "${GM}/before" "${GM}/after" > "${GM}/out" \
  || GM_FAIL "the harness rewriting its own state was reported as a footprint: $(cat "${GM}/out")"
grep -q 'installer-owned=0' "${GM}/out" \
  || GM_FAIL "the comparison did not judge the harness rows as noise: $(cat "${GM}/out")"
rm -f "${GM}/home/.claude/backups/.claude.json.backup.1788967866406"
printf 'backup\n' > "${GM}/home/.claude/backups/.claude.json.backup.1788967498969"
printf 'state\n' > "${GM}/home/.claude/sessions/1403674.json"

# (ii) a file the installers own, appearing in a directory they never write --
# the reason a name rule sits beside the location rules
printf 'not ours\n' > "${GM}/home/.claude/projects/luciazero-verify.sh"
python3 "${MANIFEST}" "${GM}/home" > "${GM}/after"
GM_MUST_FAIL "a luciazero-named file appearing outside the owned locations was waved through" \
  added '\.claude/projects/luciazero-verify\.sh' \
  "the comparison did not name the added luciazero file"
rm -f "${GM}/home/.claude/projects/luciazero-verify.sh"

# (iii) a changed file whose path contains a space -- the case a left split
# turns into four fields and then either mis-parses or silently drops
printf 'tampered\n' > "${GM}/home/.claude/skills/dir with space/SKILL.md"
python3 "${MANIFEST}" "${GM}/home" > "${GM}/after"
GM_MUST_FAIL "a changed file with a space in its path did not fail the comparison" \
  changed '\.claude/skills/dir with space/SKILL\.md' \
  "the comparison did not name the changed path"
printf 'skill\n' > "${GM}/home/.claude/skills/dir with space/SKILL.md"

# (iv) a symlink pointed somewhere else keeps its path and its mode, so the
# target is the only thing that can carry the change
rm -f "${GM}/home/.claude/settings.json"
ln -s "${GM}/target-two" "${GM}/home/.claude/settings.json"
python3 "${MANIFEST}" "${GM}/home" > "${GM}/after"
GM_MUST_FAIL "a retargeted symlink did not fail the comparison" \
  changed '\.claude/settings\.json' \
  "the comparison did not name the retargeted symlink"
rm -f "${GM}/home/.claude/settings.json"
ln -s "${GM}/target-one" "${GM}/home/.claude/settings.json"

# (v) a path the installers own that disappears, and (vi) one that appears
rm -f "${GM}/home/.claude/CLAUDE.md"
python3 "${MANIFEST}" "${GM}/home" > "${GM}/after"
GM_MUST_FAIL "a removed config file did not fail the comparison" \
  removed '\.claude/CLAUDE\.md' "the comparison did not name the removed path"
printf 'doctrine\n' > "${GM}/home/.claude/CLAUDE.md"
printf 'left behind\n' > "${GM}/home/.claude/.luciazero-version"
python3 "${MANIFEST}" "${GM}/home" > "${GM}/after"
GM_MUST_FAIL "a file left behind did not fail the comparison" \
  added '\.claude/\.luciazero-version' "the comparison did not name the added path"
rm -f "${GM}/home/.claude/.luciazero-version"

# (vii) the codex side is owned by the same rules
printf 'tampered\n' > "${GM}/home/.codex/AGENTS.md"
python3 "${MANIFEST}" "${GM}/home" > "${GM}/after"
GM_MUST_FAIL "a changed AGENTS.md did not fail the comparison" \
  changed '\.codex/AGENTS\.md' "the comparison did not name the changed AGENTS.md"
printf 'agents\n' > "${GM}/home/.codex/AGENTS.md"

# (viii) a row is a line, so a path carrying a newline is refused rather than
# recorded as two paths
NLNAME="$(printf 'two\nlines')"
: > "${GM}/home/.claude/${NLNAME}"
RC=0; python3 "${MANIFEST}" "${GM}/home" > "${GM}/after" 2>"${GM}/err" || RC=$?
[ "${RC}" != 0 ] || GM_FAIL "the manifest recorded a path containing a newline"
grep -q 'newline' "${GM}/err" || GM_FAIL "the manifest did not say why it refused: $(cat "${GM}/err")"
rm -f "${GM}/home/.claude/${NLNAME}"
rm -rf "${GM}"
echo "ok  gate 5 config manifest and comparison"

# 5c. enforcement pack: --with-hooks wiring is additive, idempotent, and
# fully removed by uninstall while user settings survive
SB3="$(mktemp -d)"
# fixture includes sentinel unknown keys (must round-trip untouched) and a
# user hook whose path merely LOOKS like ours (must never be removed)
cat > "${SB3}/settings.json" <<'JSON'
{
  "permissions": {"allow": ["Bash(ls:*)"]},
  "statusLine": {"type": "command", "command": "/my/custom.sh"},
  "env": {"SENTINEL": "1"},
  "model": "opusplan",
  "feedbackSurveyState": {"x": 1},
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "/Users/someone/dotfiles/hooks/luciazero-verify.sh precheck"}]}
    ]
  }
}
JSON
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --with-hooks >/dev/null
[ -x "${SB3}/hooks/luciazero-verify.sh" ] || { rm -rf "${SB3}"; fail "verify hook not installed by --with-hooks"; }
[ -x "${SB3}/hooks/luciazero-statusline.sh" ] || { rm -rf "${SB3}"; fail "statusline script not installed by --with-hooks"; }
python3 - "${SB3}/settings.json" <<'PY' || { rm -rf "${SB3}"; fail "settings.json wiring wrong after --with-hooks"; }
import json, sys
s = json.load(open(sys.argv[1]))
assert s["permissions"]["allow"] == ["Bash(ls:*)"], "user permissions lost"
assert s["statusLine"]["command"] == "/my/custom.sh", "custom statusLine clobbered"
assert s["env"] == {"SENTINEL": "1"} and s["model"] == "opusplan", "sentinel keys lost"
assert s["feedbackSurveyState"] == {"x": 1}, "nested unknown key lost"
assert len(s["hooks"]["PostToolUse"]) == 3 and len(s["hooks"]["Stop"]) == 1
assert len(s["hooks"]["PostToolUseFailure"]) == 1, "failed Bash hook not wired"
assert len(s["hooks"]["SessionStart"]) == 1, "session hook not wired"
assert len(s["hooks"]["UserPromptSubmit"]) == 1, "prompt timing hook not wired"
assert len(s["hooks"]["UserPromptExpansion"]) == 1, "slash-skill hook not wired"
assert len(s["hooks"]["PreToolUse"]) == 2, "bash timing hook or user's hook missing"
PY
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --status >/dev/null \
  || { rm -rf "${SB3}"; fail "--status red on a complete --with-hooks install"; }
# the hooks pass hashlib's usedforsecurity= (python 3.9+); installing them
# against an older or broken python3 must fail loudly, not leave hooks that
# fail open silently
OLDPY="$(mktemp -d)"; mkdir -p "${OLDPY}/bin" "${OLDPY}/cfg"
printf '#!/bin/sh\nexit 1\n' > "${OLDPY}/bin/python3"; chmod +x "${OLDPY}/bin/python3"
RC=0; OUT_OLDPY="$(PATH="${OLDPY}/bin:${PATH}" CLAUDE_CONFIG_DIR="${OLDPY}/cfg" \
  "${ROOT}/install.sh" --with-hooks 2>&1)" || RC=$?
[ "${RC}" != 0 ] \
  || { rm -rf "${SB3}" "${OLDPY}"; fail "--with-hooks installed against a python3 that cannot run the hooks"; }
printf '%s' "${OUT_OLDPY}" | grep -q 'python3 >= 3.9' \
  || { rm -rf "${SB3}" "${OLDPY}"; fail "--with-hooks did not name the python3 requirement: ${OUT_OLDPY}"; }
[ ! -e "${OLDPY}/cfg/hooks/luciazero-verify.sh" ] \
  || { rm -rf "${SB3}" "${OLDPY}"; fail "--with-hooks left hook files behind after refusing to install"; }
rm -rf "${OLDPY}"
cp "${SB3}/settings.json" "${SB3}/settings.snap"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --with-hooks >/dev/null
cmp -s "${SB3}/settings.json" "${SB3}/settings.snap" \
  || { rm -rf "${SB3}"; fail "--with-hooks reinstall changed settings.json (not idempotent)"; }
# --status must catch a stale hook file (the `git pull && ./install.sh`
# without --with-hooks failure mode: sidecar fresh, hook file old)
echo '# stale marker' >> "${SB3}/hooks/luciazero-verify.sh"
RC=0; SOUT="$(CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --status 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${SB3}"; fail "--status green with a stale hook file"; }
echo "${SOUT}" | grep -q 'differs from this checkout' \
  || { rm -rf "${SB3}"; fail "--status did not name the stale hook: ${SOUT}"; }
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --with-hooks >/dev/null   # restore
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ ! -f "${SB3}/hooks/luciazero-verify.sh" ] || { rm -rf "${SB3}"; fail "hook file left behind"; }
python3 - "${SB3}/settings.json" "${SB3}" <<'PY' || { rm -rf "${SB3}"; fail "settings.json not cleaned correctly by uninstall"; }
import json, sys
s = json.load(open(sys.argv[1]))
ours = sys.argv[2] + "/hooks/luciazero-"
assert ours not in json.dumps(s), "our entries left behind"
assert s["permissions"]["allow"] == ["Bash(ls:*)"], "user permissions lost on uninstall"
assert s["statusLine"]["command"] == "/my/custom.sh", "custom statusLine removed"
assert s["env"] == {"SENTINEL": "1"} and s["model"] == "opusplan", "sentinel keys lost on uninstall"
pre = [h["command"] for e in s["hooks"]["PreToolUse"] for h in e["hooks"]]
assert pre == ["/Users/someone/dotfiles/hooks/luciazero-verify.sh precheck"], \
    "user's lookalike hook was deleted: " + json.dumps(s["hooks"])
PY
rm -rf "${SB3}"
echo "ok  enforcement pack install + idempotent + clean uninstall"

# 5c2. Three config directories whose names no shell survives unquoted: one
# with a space, one with an apostrophe, one carrying a literal `$(...)`. Every
# hook command the installer writes is a shell string, so an unquoted path
# ends at the space -- the stored command runs a prefix of the path, the shell
# answers 127, and the hook silently does nothing on a machine where the
# install reported success. Running the stored command is the assertion; a
# grep for a quote character would pass on a string no shell can run.
#
# The apostrophe is the case that also judges the uninstaller: quoting a path
# that contains one splices the quote in from outside, so the directory name
# stops being a substring of the stored command at all -- and an uninstall
# that decided by grepping for that path answered "nothing of ours here",
# skipped the cleanup, and deleted the hook files anyway, leaving every entry
# in settings.json pointing at a file that no longer exists.
FXR="$(mktemp -d)"
SENTINEL="${FXR}/pwned"
FX_FAIL() { rm -rf "${FXR}"; fail "$1"; }
for FXNAME in "config with space" "config with ' quote" "meta \$(touch ${SENTINEL}) dir"; do
  FX="${FXR}/${FXNAME}"
  mkdir -p "${FX}"
  CLAUDE_CONFIG_DIR="${FX}" "${ROOT}/install.sh" --with-hooks >/dev/null \
    || FX_FAIL "--with-hooks failed in a config directory named: ${FXNAME}"
  FXCMD="$(python3 - "${FX}/settings.json" <<'FXPY'
import json, sys
settings = json.load(open(sys.argv[1]))
for entries in settings["hooks"].values():
    for entry in entries:
        for hook in entry["hooks"]:
            if hook["command"].endswith(" edit"):
                print(hook["command"])
                raise SystemExit(0)
raise SystemExit("no edit hook wired")
FXPY
)" || FX_FAIL "no edit hook wired in: ${FXNAME}"
  RC=0; printf '{}' | sh -c "${FXCMD}" >/dev/null 2>&1 || RC=$?
  [ "${RC}" != 127 ] || FX_FAIL "the stored hook command does not survive the shell: ${FXCMD}"
  [ "${RC}" = 0 ] || FX_FAIL "the stored hook command failed (rc=${RC}): ${FXCMD}"
  [ ! -e "${SENTINEL}" ] || FX_FAIL "the stored hook command executed text from its own path: ${FXCMD}"
  CLAUDE_CONFIG_DIR="${FX}" "${ROOT}/install.sh" --status >/dev/null \
    || FX_FAIL "--status could not see the hooks it had just wired: ${FXNAME}"
  cp "${FX}/settings.json" "${FXR}/settings.snap"
  CLAUDE_CONFIG_DIR="${FX}" "${ROOT}/install.sh" --with-hooks >/dev/null
  cmp -s "${FX}/settings.json" "${FXR}/settings.snap" \
    || FX_FAIL "reinstall changed settings.json in: ${FXNAME}"
  rm -f "${FXR}/settings.snap"
  CLAUDE_CONFIG_DIR="${FX}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
  python3 - "${FX}/settings.json" <<'FXPY' || FX_FAIL "uninstall left hook entries behind in: ${FXNAME}"
import os, sys
path = sys.argv[1]
if not os.path.exists(path):
    raise SystemExit(0)
raise SystemExit(1 if "luciazero-" in open(path).read() else 0)
FXPY
  [ ! -f "${FX}/hooks/luciazero-verify.sh" ] \
    || FX_FAIL "uninstall cleaned settings.json but kept the hook file: ${FXNAME}"
done
rm -rf "${FXR}"

# 5c3. The same directory, upgraded from an install that wrote the path bare.
# Those entries are ours and are broken; the installer has to rewrite them in
# place rather than add a second, quoted copy beside them, and the uninstaller
# has to recognise the bare spelling it no longer writes.
SPL="$(mktemp -d)/legacy with space"
mkdir -p "${SPL}"
SPL_FAIL() { rm -rf "$(dirname "${SPL}")"; fail "$1"; }
python3 - "${SPL}" <<'PY'
import json, os, sys
home = sys.argv[1]
verify = os.path.join(home, "hooks", "luciazero-verify.sh")
status = os.path.join(home, "hooks", "luciazero-statusline.sh")
settings = {
    "hooks": {"PostToolUse": [{"matcher": "Edit|Write|NotebookEdit",
                               "hooks": [{"type": "command", "command": verify + " edit"}]}]},
    "statusLine": {"type": "command", "command": status},
}
json.dump(settings, open(os.path.join(home, "settings.json"), "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="${SPL}" "${ROOT}/install.sh" --with-hooks >/dev/null   || SPL_FAIL "--with-hooks failed over an older unquoted install"
python3 - "${SPL}/settings.json" <<'PY' || { rm -rf "$(dirname "${SPL}")"; fail "unquoted entries were not migrated"; }
import json, shlex, sys
settings = json.load(open(sys.argv[1]))
commands = [h["command"] for entries in settings["hooks"].values()
            for entry in entries for h in entry["hooks"]]
edits = [c for c in commands if c.endswith(" edit")]
assert len(edits) == 1, "the unquoted entry was left beside a new one: " + repr(edits)
assert shlex.split(edits[0])[0].endswith("/hooks/luciazero-verify.sh"),     "migrated command does not parse back to the hook: " + repr(edits[0])
PY
CLAUDE_CONFIG_DIR="${SPL}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
if [ -f "${SPL}/settings.json" ]; then
  grep -qF 'luciazero-' "${SPL}/settings.json"     && SPL_FAIL "uninstall left entries behind after the migration"
fi
rm -rf "$(dirname "${SPL}")"
echo "ok  hook commands survive a config path with a space, old spelling included"

# 5c4. A dangling symlink planted at the name the backup is about to take.
# `os.path.exists` follows the name and answers False when the target is
# missing, so such a name read as free -- and the copy that followed wrote the
# user's settings through the symlink, outside the config directory and under
# a name the planter chose, while the config directory was left with no backup
# at all. Reserving the name with an exclusive create is the only check a
# symlink cannot pass, and the assertions below are all three halves of it:
# nothing outside was written, no decoy was written or removed, and the backup
# that did get made is the real file under the next free name.
BLK="$(mktemp -d)"
BLK_CFG="${BLK}/cfg"; BLK_OUT="${BLK}/outside"
mkdir -p "${BLK_CFG}" "${BLK_OUT}"
BLK_FAIL() { rm -rf "${BLK}"; fail "$1"; }
CLAUDE_CONFIG_DIR="${BLK_CFG}" "${ROOT}/install.sh" --with-hooks >/dev/null
chmod 640 "${BLK_CFG}/settings.json"
cp -p "${BLK_CFG}/settings.json" "${BLK}/settings.before"
# One decoy per second for the next minute, so whichever second the uninstall
# reaches its backup in, the name it computes first is already a symlink. The
# names are written down as they are planted: checking them afterwards against
# whatever is still in the directory would let a run that deleted them pass.
python3 - "${BLK_CFG}/settings.json" "${BLK_OUT}/escaped" "${BLK}/decoys" <<'BLKPY'
import os, sys, time
base = time.time()
with open(sys.argv[3], "w") as planted:
    for i in range(60):
        decoy = sys.argv[1] + ".bak." + time.strftime("%Y%m%d%H%M%S",
                                                      time.localtime(base + i))
        os.symlink(sys.argv[2] + "-" + str(i), decoy)
        planted.write(decoy + "\n")
BLKPY
CLAUDE_CONFIG_DIR="${BLK_CFG}" "${ROOT}/uninstall.sh" >/dev/null 2>&1 || true
[ -z "$(ls -A "${BLK_OUT}")" ] \
  || BLK_FAIL "uninstall wrote through a planted symlink, outside the config directory: $(ls -A "${BLK_OUT}")"
python3 - "${BLK_CFG}/settings.json" "${BLK}/settings.before" "${BLK}/decoys" <<'BLKPY' || BLK_FAIL "backup did not survive a planted symlink (see above)"
import os, re, sys
settings, before, planted = sys.argv[1], sys.argv[2], sys.argv[3]
decoys = [line.rstrip("\n") for line in open(planted) if line.strip()]
if len(decoys) != 60:
    raise SystemExit("the planter recorded " + str(len(decoys)) + " decoys, not 60")
for p in decoys:
    name = os.path.basename(p)
    if not os.path.lexists(p):
        raise SystemExit("a planted decoy was removed: " + name)
    if not os.path.islink(p):
        raise SystemExit("a planted decoy was replaced by a real file: " + name)
    if os.path.exists(p):
        raise SystemExit("a planted decoy was given a target: " + name)
d, base = os.path.dirname(settings), os.path.basename(settings) + ".bak."
real = [n for n in os.listdir(d)
        if n.startswith(base) and not os.path.islink(os.path.join(d, n))]
if len(real) != 1:
    raise SystemExit("expected exactly one real backup, found: " + repr(real))
p = os.path.join(d, real[0])
if not re.search(r"\.bak\.\d{14}\.\d+$", real[0]):
    raise SystemExit("backup did not move on to the next free name: " + real[0])
if open(p, "rb").read() != open(before, "rb").read():
    raise SystemExit("backup is not the file that was replaced: " + real[0])
mode = os.stat(p).st_mode & 0o777
if mode != 0o640:
    raise SystemExit("backup did not keep the original mode: " + oct(mode))
BLKPY
grep -qF 'luciazero-' "${BLK_CFG}/settings.json" \
  && BLK_FAIL "settings.json was not cleaned once the backup took the next name"
[ ! -f "${BLK_CFG}/hooks/luciazero-verify.sh" ] \
  || BLK_FAIL "hook file kept although settings.json was cleaned"
rm -rf "${BLK}"
echo "ok  the settings backup refuses a symlinked name and keeps the bytes"

# 5c5. The same planted name, on the install side. `install.sh` copies an
# existing settings.json aside before it wires the hooks, and `bakpath` picked
# that name with `[ -e ]`, which follows it: a dangling symlink read as free
# and `cp` wrote the user's settings through it. The shell cannot reserve a
# name the way the uninstaller's Python now does -- the window between the
# test and the `cp` stays open, tracked as roadmap R24 -- but it can refuse a
# name any symlink already holds, which is the whole of the planted case.
BLI="$(mktemp -d)"
BLI_CFG="${BLI}/cfg"; BLI_OUT="${BLI}/outside"
mkdir -p "${BLI_CFG}" "${BLI_OUT}"
BLI_FAIL() { rm -rf "${BLI}"; fail "$1"; }
CLAUDE_CONFIG_DIR="${BLI_CFG}" "${ROOT}/install.sh" --with-hooks >/dev/null
cp -p "${BLI_CFG}/settings.json" "${BLI}/settings.before"
python3 - "${BLI_CFG}/settings.json" "${BLI_OUT}/escaped" "${BLI}/decoys" <<'BLIPY'
import os, sys, time
base = time.time()
with open(sys.argv[3], "w") as planted:
    for i in range(60):
        decoy = sys.argv[1] + ".bak." + time.strftime("%Y%m%d%H%M%S",
                                                      time.localtime(base + i))
        os.symlink(sys.argv[2] + "-" + str(i), decoy)
        planted.write(decoy + "\n")
BLIPY
CLAUDE_CONFIG_DIR="${BLI_CFG}" "${ROOT}/install.sh" --with-hooks >/dev/null \
  || BLI_FAIL "reinstall failed with symlinks planted at the backup names"
[ -z "$(ls -A "${BLI_OUT}")" ] \
  || BLI_FAIL "install wrote through a planted symlink, outside the config directory: $(ls -A "${BLI_OUT}")"
python3 - "${BLI_CFG}/settings.json" "${BLI}/settings.before" "${BLI}/decoys" <<'BLIPY' || BLI_FAIL "install backup did not survive a planted symlink (see above)"
import os, re, sys
settings, before, planted = sys.argv[1], sys.argv[2], sys.argv[3]
decoys = [line.rstrip("\n") for line in open(planted) if line.strip()]
if len(decoys) != 60:
    raise SystemExit("the planter recorded " + str(len(decoys)) + " decoys, not 60")
for p in decoys:
    name = os.path.basename(p)
    if not os.path.lexists(p):
        raise SystemExit("a planted decoy was removed: " + name)
    if not os.path.islink(p):
        raise SystemExit("a planted decoy was replaced by a real file: " + name)
    if os.path.exists(p):
        raise SystemExit("a planted decoy was given a target: " + name)
d, base = os.path.dirname(settings), os.path.basename(settings) + ".bak."
real = [n for n in os.listdir(d)
        if n.startswith(base) and not os.path.islink(os.path.join(d, n))]
if len(real) != 1:
    raise SystemExit("expected exactly one real backup, found: " + repr(real))
if not re.search(r"\.bak\.\d{14}\.\d+$", real[0]):
    raise SystemExit("backup did not move on to the next free name: " + real[0])
if open(os.path.join(d, real[0]), "rb").read() != open(before, "rb").read():
    raise SystemExit("backup is not the file that was replaced: " + real[0])
BLIPY
rm -rf "${BLI}"
echo "ok  the install backup refuses a symlinked name too"

# 5d. failed settings cleanup must NOT delete the hook files (no dangling refs)
SB4="$(mktemp -d)"
CLAUDE_CONFIG_DIR="${SB4}" "${ROOT}/install.sh" --with-hooks >/dev/null
# corrupt the JSON while KEEPING a reference to our hook — the dangerous case:
# cleanup cannot run, so deleting the files would leave dangling references
printf '{broken json "%s/hooks/luciazero-verify.sh stop"\n' "${SB4}" > "${SB4}/settings.json"
CLAUDE_CONFIG_DIR="${SB4}" "${ROOT}/uninstall.sh" >/dev/null 2>&1 || true
[ -f "${SB4}/hooks/luciazero-verify.sh" ] \
  || { rm -rf "${SB4}"; fail "hook files deleted although settings cleanup failed (dangling references)"; }
rm -rf "${SB4}"
echo "ok  uninstall keeps hook files when settings cleanup fails"

# 5e. --status flags dangling hook references (files deleted by hand while
# settings.json still wires them — worse than not installed, never "ok")
SB5="$(mktemp -d)"
CLAUDE_CONFIG_DIR="${SB5}" "${ROOT}/install.sh" --with-hooks >/dev/null
rm -rf "${SB5}/hooks"
RC=0; SOUT="$(CLAUDE_CONFIG_DIR="${SB5}" "${ROOT}/install.sh" --status 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${SB5}"; fail "--status green with dangling hook references"; }
echo "${SOUT}" | grep -q 'dangling' || { rm -rf "${SB5}"; fail "--status did not name the dangling references: ${SOUT}"; }
rm -rf "${SB5}"
echo "ok  --status flags dangling hook references"

# 5f. non-ASCII config path: settings.json must store the hook paths raw
# (ensure_ascii=False) or --status's byte-level greps can never match them
SB6R="$(mktemp -d)"
SB6="${SB6R}/claudé"
mkdir -p "${SB6}"
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/install.sh" --with-hooks >/dev/null
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/install.sh" --status >/dev/null \
  || { rm -rf "${SB6R}"; fail "--status red on a healthy non-ASCII config dir"; }
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ ! -f "${SB6}/hooks/luciazero-verify.sh" ] || { rm -rf "${SB6R}"; fail "non-ASCII-path uninstall left hook files"; }
rm -rf "${SB6R}"
echo "ok  non-ASCII config dir install + status + uninstall"

# 5g. Agent Bus launcher: the public `luciazero-agentd` command. Everything
# here runs in a temporary home whose paths contain a space, from outside the
# repository, because that is where the two ways a shim breaks live: an
# unquoted expansion, and a package found relative to the caller's cwd.
if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  LB_ROOT="$(mktemp -d)"
  LB_HOME="${LB_ROOT}/home dir"
  LB_BIN="${LB_ROOT}/path bin"
  LB_STATE="${LB_ROOT}/bus state"
  mkdir -p "${LB_HOME}" "${LB_STATE}"
  lb_fail() { rm -rf "${LB_ROOT}"; fail "$1"; }

  CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
    "${ROOT}/install.sh" >/dev/null || lb_fail "install.sh failed with LUCIAZERO_BIN_DIR"
  for LB_NAME in luciazero-agentd lucia; do
    [ -x "${LB_BIN}/${LB_NAME}" ] || lb_fail "${LB_NAME} not installed as an executable"
    grep -qF 'luciazero-managed: agentd-launcher' "${LB_BIN}/${LB_NAME}" \
      || lb_fail "installed ${LB_NAME} carries no ownership marker"
  done
  [ "$(cat "${LB_HOME}/.claude/.luciazero-agentd-home")" = "${ROOT}/agentd" ] \
    || lb_fail "the launcher was not told where the agentd package is"

  # The store is created here rather than by a daemon: this section is about
  # the shim, and a live daemon would make it about ports and timing.
  PYTHONPATH="${ROOT}/agentd" python3 -c '
import sys
from luciazero_agentd.store import Store
with Store.open(sys.argv[1] + "/bus.sqlite3") as store:
    store.migrate()
' "${LB_STATE}" || lb_fail "could not create a temporary bus database"

  # From / with nothing but PATH: no cwd, no repository, no PYTHONPATH.
  ( cd / && PATH="${LB_BIN}:${PATH}" CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" \
      luciazero-agentd roster add lb-architect codex architect --state-dir "${LB_STATE}" >/dev/null ) \
    || lb_fail "the installed launcher cannot run from outside the checkout"

  # The short name is a second name for the same program, so it answers to
  # every subcommand, and it says its own name back: a message that told a
  # `lucia` user to type `luciazero-agentd` would be a translation step.
  ( cd / && PATH="${LB_BIN}:${PATH}" CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" \
    lucia sessions --state-dir "${LB_STATE}" >/dev/null ) \
    || lb_fail "the short name cannot run from outside the checkout"
  LB_USAGE="$( cd / && PATH="${LB_BIN}:${PATH}" CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" \
    lucia claude --help )" || lb_fail "lucia claude --help failed"
  printf '%s' "${LB_USAGE}" | grep -q '^usage: lucia claude' \
    || lb_fail "lucia printed the long name back at the user: ${LB_USAGE}"

  # `next` renders the short command when the launcher is on PATH...
  LB_NEXT="$( cd / && PATH="${LB_BIN}:${PATH}" CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" \
    luciazero-agentd next --state-dir "${LB_STATE}" )" \
    || lb_fail "next failed through the installed launcher"
  printf '%s' "${LB_NEXT}" | grep -q '^    luciazero-agentd ' \
    || lb_fail "next did not render the short command with the launcher installed: ${LB_NEXT}"
  # ...and falls back to the module form when it is not, so a user who has not
  # installed it is never handed a command that is not on their PATH.
  # A PATH with a python3 on it and provably no launcher anywhere: the
  # directory holding the real python3 may itself be ~/.local/bin, which is
  # exactly where install.sh's help tells people to put the launcher.
  LB_PYBIN="${LB_ROOT}/python only"
  mkdir -p "${LB_PYBIN}"
  ln -s "$(command -v python3)" "${LB_PYBIN}/python3"
  LB_NEXT_BARE="$( cd / && PATH="${LB_PYBIN}" PYTHONPATH="${ROOT}/agentd" \
    CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" \
    python3 -m luciazero_agentd next --state-dir "${LB_STATE}" )" \
    || lb_fail "next failed without the launcher"
  printf '%s' "${LB_NEXT_BARE}" | grep -q 'python3 -m luciazero_agentd' \
    || lb_fail "next did not fall back to the python form: ${LB_NEXT_BARE}"

  # A directory of the caller's must never be able to supply the package.
  # `python -m pkg` puts the working directory first on sys.path, ahead of
  # PYTHONPATH, so a decoy next to the caller would shadow the real daemon.
  mkdir -p "${LB_ROOT}/decoy/luciazero_agentd"
  printf 'print("HIJACKED")\n' > "${LB_ROOT}/decoy/luciazero_agentd/__main__.py"
  # A regular package (one with __init__.py) beats a namespace portion found
  # earlier on sys.path, so the decoy needs one to be a real threat.
  : > "${LB_ROOT}/decoy/luciazero_agentd/__init__.py"
  LB_DECOY="$( cd "${LB_ROOT}/decoy" && PATH="${LB_BIN}:${PATH}" \
    CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" luciazero-agentd sessions --state-dir "${LB_STATE}" )" \
    || lb_fail "the launcher failed next to a decoy package"
  printf '%s' "${LB_DECOY}" | grep -q HIJACKED \
    && lb_fail "the caller's working directory supplied the package"

  # A ':' in the package path must not split it into two PYTHONPATH entries,
  # the tail of which resolves against the caller's directory.
  mkdir -p "${LB_ROOT}/co:lon" "${LB_ROOT}/split/lon/agentd/luciazero_agentd"
  ln -s "${ROOT}/agentd" "${LB_ROOT}/co:lon/agentd"
  printf 'print("HIJACKED")\n' > "${LB_ROOT}/split/lon/agentd/luciazero_agentd/__main__.py"
  : > "${LB_ROOT}/split/lon/agentd/luciazero_agentd/__init__.py"
  LB_COLON="$( cd "${LB_ROOT}/split" && LUCIAZERO_AGENTD_HOME="${LB_ROOT}/co:lon/agentd" \
    "${LB_BIN}/luciazero-agentd" sessions --state-dir "${LB_STATE}" )" \
    || lb_fail "the launcher failed with a ':' in the package path"
  printf '%s' "${LB_COLON}" | grep -q HIJACKED \
    && lb_fail "a ':' in the package path let the caller's directory supply the package"

  # An executable somebody else put there is never replaced, and never
  # removed. `lucia` is the shorter and likelier name to collide, so the rule
  # is asserted for each name in turn: a foreign copy of one must not stop the
  # other being installed.
  for LB_NAME in luciazero-agentd lucia; do
    if [ "${LB_NAME}" = luciazero-agentd ]; then LB_OTHER=lucia; else LB_OTHER=luciazero-agentd; fi
    rm -f "${LB_BIN}/luciazero-agentd" "${LB_BIN}/lucia"
    printf '#!/bin/sh\nexit 3\n' > "${LB_BIN}/${LB_NAME}"
    LB_OUT="$(CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
      "${ROOT}/install.sh" 2>&1)" || lb_fail "install.sh must not fail on a foreign ${LB_NAME}"
    printf '%s' "${LB_OUT}" | grep -q 'not the Luciazero launcher' \
      || lb_fail "install.sh replaced or ignored a foreign ${LB_NAME} silently"
    grep -qF 'exit 3' "${LB_BIN}/${LB_NAME}" || lb_fail "install.sh overwrote a foreign ${LB_NAME}"
    [ -x "${LB_BIN}/${LB_OTHER}" ] \
      || lb_fail "a foreign ${LB_NAME} stopped ${LB_OTHER} from being installed"
    [ -f "${LB_HOME}/.claude/.luciazero-agentd-home" ] \
      || lb_fail "a foreign ${LB_NAME} stopped the package pointer being written"
    CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
      "${ROOT}/uninstall.sh" >/dev/null 2>&1
    grep -qF 'exit 3' "${LB_BIN}/${LB_NAME}" || lb_fail "uninstall.sh deleted a foreign ${LB_NAME}"
  done

  # Ours are removed, both names, together with the record of where the
  # package was.
  rm -f "${LB_BIN}/luciazero-agentd" "${LB_BIN}/lucia"
  CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
    "${ROOT}/install.sh" >/dev/null
  CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
    "${ROOT}/uninstall.sh" >/dev/null
  [ ! -e "${LB_BIN}/luciazero-agentd" ] || lb_fail "uninstall.sh left its own launcher behind"
  [ ! -e "${LB_BIN}/lucia" ] || lb_fail "uninstall.sh left the short name behind"
  [ ! -e "${LB_HOME}/.claude/.luciazero-agentd-home" ] || lb_fail "uninstall.sh left the package pointer behind"

  # The service subcommand must be inspectable without installing anything:
  # this suite may never leave a launchd or systemd unit on the machine.
  LB_SVC="$( cd / && PYTHONPATH="${ROOT}/agentd" python3 -m luciazero_agentd service install \
    --dry-run --root "${LB_ROOT}/svc root" --state-dir "${LB_STATE}" )" \
    || lb_fail "service install --dry-run failed"
  printf '%s' "${LB_SVC}" | grep -q 'dry run' || lb_fail "service dry run did not say so"
  if printf '%s' "${LB_SVC}" | grep -q -- '--allow-unattributed'; then
    lb_fail "a service must never be planned with --allow-unattributed"
  fi
  [ -z "$(find "${LB_ROOT}/svc root" -type f 2>/dev/null)" ] \
    || lb_fail "service install --dry-run wrote a file"

  rm -rf "${LB_ROOT}"
  echo "ok  luciazero-agentd and lucia install, run from anywhere, and stay ownership-safe"
else
  echo "skip  luciazero-agentd launcher (python3 is older than 3.10)"
fi
