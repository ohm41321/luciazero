# tests/gates/install.sh — sandboxed Claude install/uninstall cycles, data safety, enforcement pack wiring, Agent Bus launcher.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# entries_named <dir> <prefix>: the names in <dir> that begin with <prefix>,
# one per line, dot names included. A glob, not `ls | grep`, so a name may
# hold any byte but a newline.
entries_named() {
  local E
  for E in "$1/$2"*; do
    if [ -e "${E}" ] || [ -L "${E}" ]; then printf '%s\n' "${E##*/}"; fi
  done
}

# 5. sandbox install cycle — never touches the real ~/.claude
SB="$(mktemp -d)"
trap 'rm -rf "${SB}"' EXIT
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
for HELPER in ready/scripts/detect.cjs done/scripts/revert-probe.cjs bisect/scripts/safe-bisect.cjs; do
  [ -x "${SB}/skills/${HELPER}" ] || fail "${HELPER} not installed or not executable"
done
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
[ -f "${SB3}/hooks/luciazero-verify.cjs" ] || { rm -rf "${SB3}"; fail "verify hook not installed by --with-hooks"; }
[ -f "${SB3}/hooks/luciazero-statusline.cjs" ] || { rm -rf "${SB3}"; fail "statusline script not installed by --with-hooks"; }
python3 - "${SB3}/settings.json" "${SB3}/hooks/luciazero-verify.cjs" <<'PY' || { rm -rf "${SB3}"; fail "settings.json wiring wrong after --with-hooks"; }
import json, sys
s = json.load(open(sys.argv[1]))
verify = sys.argv[2]
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
# exec form: no shell between Claude Code and the hook, on any platform; the
# shell-command hooks also match PowerShell, the shell tool on Windows
ours = {}
for event, entries in s["hooks"].items():
    for e in entries:
        for h in e["hooks"]:
            if h.get("args", [None])[0] == verify:
                assert h["command"] == "node" and len(h["args"]) == 2, "not exec form: " + repr(h)
                ours[h["args"][1]] = (event, e.get("matcher"))
assert sorted(ours) == sorted("prompt skill-prompt bash-start edit bash bash-failure skill stop session".split()), ours
for sub in ("bash-start", "bash", "bash-failure"):
    assert ours[sub][1] == "Bash|PowerShell", sub + " matcher " + repr(ours[sub][1])
PY
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --status >/dev/null \
  || { rm -rf "${SB3}"; fail "--status red on a complete --with-hooks install"; }
# the hooks, the status line and the wiring all run on Node 18+; installing
# against an older or broken node must fail loudly, before anything is copied
OLDNODE="$(mktemp -d)"; mkdir -p "${OLDNODE}/bin" "${OLDNODE}/cfg"
printf '#!/bin/sh\nexit 1\n' > "${OLDNODE}/bin/node"; chmod +x "${OLDNODE}/bin/node"
RC=0; OUT_OLDNODE="$(PATH="${OLDNODE}/bin:${PATH}" CLAUDE_CONFIG_DIR="${OLDNODE}/cfg" \
  "${ROOT}/install.sh" --with-hooks 2>&1)" || RC=$?
[ "${RC}" != 0 ] \
  || { rm -rf "${SB3}" "${OLDNODE}"; fail "--with-hooks installed against a node that cannot run the hooks"; }
printf '%s' "${OUT_OLDNODE}" | grep -q 'Node 18+' \
  || { rm -rf "${SB3}" "${OLDNODE}"; fail "--with-hooks did not name the Node requirement: ${OUT_OLDNODE}"; }
[ ! -e "${OLDNODE}/cfg/hooks/luciazero-verify.cjs" ] \
  || { rm -rf "${SB3}" "${OLDNODE}"; fail "--with-hooks left hook files behind after refusing to install"; }
rm -rf "${OLDNODE}"
cp "${SB3}/settings.json" "${SB3}/settings.snap"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --with-hooks >/dev/null
cmp -s "${SB3}/settings.json" "${SB3}/settings.snap" \
  || { rm -rf "${SB3}"; fail "--with-hooks reinstall changed settings.json (not idempotent)"; }
# one backup, of the user's own file: a reinstall with nothing to change
# leaves no copy of a file it did not touch
SB3_BAKS="$(find "${SB3}" -maxdepth 1 -name 'settings.json.bak.*' | wc -l | tr -d ' ')"
[ "${SB3_BAKS}" = 1 ] \
  || { rm -rf "${SB3}"; fail "--with-hooks left ${SB3_BAKS} settings.json backups, not 1: a reinstall that changed nothing backed it up"; }
# --status must catch a stale hook file (the `git pull && ./install.sh`
# without --with-hooks failure mode: sidecar fresh, hook file old)
echo '// stale marker' >> "${SB3}/hooks/luciazero-verify.cjs"
RC=0; SOUT="$(CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --status 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${SB3}"; fail "--status green with a stale hook file"; }
echo "${SOUT}" | grep -q 'differs from this checkout' \
  || { rm -rf "${SB3}"; fail "--status did not name the stale hook: ${SOUT}"; }
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --with-hooks >/dev/null   # restore
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ ! -f "${SB3}/hooks/luciazero-verify.cjs" ] || { rm -rf "${SB3}"; fail "hook file left behind"; }
[ ! -f "${SB3}/hooks/luciazero-statusline.cjs" ] || { rm -rf "${SB3}"; fail "statusline file left behind"; }
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

# 5c2. Config directories whose names no shell survives unquoted: a space, an
# apostrophe, a literal `$(...)`, and a backtick pair with Thai text. The
# hooks are exec form -- Claude Code passes the path as one argument, no shell
# -- so the assertion runs each stored hook that way. The status line has no
# exec form: its command goes to sh (or Git Bash, or PowerShell on Windows)
# and names the script only as base64 inside a fixed program, so the command
# holds no character any of them treats specially. Running the stored command
# through sh and bash is the assertion; the sentinel proves no part of the
# path was executed.
#
# The apostrophe also judges the uninstaller: a path is not always a
# substring of what is stored (base64 never is), so only the parser can say
# what is ours -- an uninstall that grepped answered "nothing of ours here"
# and deleted the hook files under entries still pointing at them.
FXR="$(mktemp -d)"
SENTINEL="${FXR}/pwned"
# the hooks keep state under TMPDIR: a private one, never the ambient one
mkdir -p "${FXR}/tmp"; chmod 700 "${FXR}/tmp"
FX_FAIL() { rm -rf "${FXR}"; fail "$1"; }
for FXNAME in "config with space" "config with ' quote" "meta \$(touch ${SENTINEL}) dir" \
  "tick \`touch ${SENTINEL}\` ไทย dir"; do
  FX="${FXR}/${FXNAME}"
  mkdir -p "${FX}"
  CLAUDE_CONFIG_DIR="${FX}" "${ROOT}/install.sh" --with-hooks >/dev/null \
    || FX_FAIL "--with-hooks failed in a config directory named: ${FXNAME}"
  FXRUN="$(TMPDIR="${FXR}/tmp" CLAUDE_CONFIG_DIR="${FX}" python3 - "${FX}/settings.json" "${FX}/proj" <<'FXPY'
import json, subprocess, sys
settings = json.load(open(sys.argv[1]))
payload = json.dumps({"cwd": sys.argv[2]})
ran = 0
for entries in settings["hooks"].values():
    for entry in entries:
        for hook in entry["hooks"]:
            if hook.get("args", [""])[-1] == "edit":
                # what Claude Code does with an exec-form hook: no shell
                p = subprocess.run([hook["command"]] + hook["args"], input=payload.encode())
                if p.returncode != 0:
                    raise SystemExit("the stored edit hook failed (rc=%d): %r" % (p.returncode, hook))
                ran += 1
if ran != 1:
    raise SystemExit("expected one edit hook, ran %d" % ran)
print(settings["statusLine"]["command"])
FXPY
)" || FX_FAIL "the stored hook did not run in: ${FXNAME}: ${FXRUN}"
  mkdir -p "${FX}/proj"
  for FXSH in sh bash; do
    SLOUT="$(printf '{"workspace":{"current_dir":"%s/proj"}}' "${FX}" \
      | TMPDIR="${FXR}/tmp" "${FXSH}" -c "${FXRUN}" 2>&1)" \
      || FX_FAIL "the stored statusLine failed under ${FXSH} in ${FXNAME}: ${SLOUT}"
    # the edit hook above ran for this directory: our status line reports it
    printf '%s' "${SLOUT}" | grep -q 'unverified' \
      || FX_FAIL "the stored statusLine ran something else under ${FXSH} in ${FXNAME}: ${SLOUT}"
  done
  [ ! -e "${SENTINEL}" ] || FX_FAIL "a stored command executed text from its own path: ${FXNAME}"
  CLAUDE_CONFIG_DIR="${FX}" "${ROOT}/install.sh" --status >/dev/null \
    || FX_FAIL "--status could not see the hooks it had just wired: ${FXNAME}"
  cp "${FX}/settings.json" "${FXR}/settings.snap"
  CLAUDE_CONFIG_DIR="${FX}" "${ROOT}/install.sh" --with-hooks >/dev/null
  cmp -s "${FX}/settings.json" "${FXR}/settings.snap" \
    || FX_FAIL "reinstall changed settings.json in: ${FXNAME}"
  rm -f "${FXR}/settings.snap"
  CLAUDE_CONFIG_DIR="${FX}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
  python3 - "${FX}/settings.json" <<'FXPY' || FX_FAIL "uninstall left hook entries behind in: ${FXNAME}"
import json, os, sys
path = sys.argv[1]
if not os.path.exists(path):
    raise SystemExit(0)
text = open(path).read()
s = json.loads(text)
raise SystemExit(1 if "luciazero-" in text or "statusLine" in s or s.get("hooks") else 0)
FXPY
  [ ! -f "${FX}/hooks/luciazero-verify.cjs" ] \
    || FX_FAIL "uninstall cleaned settings.json but kept the hook file: ${FXNAME}"
done
rm -rf "${FXR}"

# 5c3. The same directory, upgraded from a Bash-era install that wrote the
# path bare. Those entries are ours and are broken; the installer has to
# rewrite them in place, in exec form, rather than add a second copy beside
# them, and the uninstaller has to recognise the bare spelling too.
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
python3 - "${SPL}/settings.json" "${SPL}/hooks/luciazero-verify.cjs" <<'PY' || { rm -rf "$(dirname "${SPL}")"; fail "unquoted entries were not migrated"; }
import json, sys
settings = json.load(open(sys.argv[1]))
hooks = [h for entries in settings["hooks"].values() for entry in entries for h in entry["hooks"]]
edits = [h for h in hooks if h.get("args", [""])[-1] == "edit" or h.get("command", "").endswith(" edit")]
assert edits == [{"type": "command", "command": "node", "args": [sys.argv[2], "edit"]}], \
    "the unquoted entry was not migrated in place: " + repr(edits)
assert ".sh" not in json.dumps(settings), "a Bash-era entry survived: " + json.dumps(settings)
assert settings["statusLine"]["command"].startswith("node -e "), "the old status line was not migrated"
PY
CLAUDE_CONFIG_DIR="${SPL}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
if [ -f "${SPL}/settings.json" ]; then
  grep -qF 'luciazero-' "${SPL}/settings.json"     && SPL_FAIL "uninstall left entries behind after the migration"
  grep -qF 'statusLine' "${SPL}/settings.json"     && SPL_FAIL "uninstall left the status line behind after the migration"
fi
rm -rf "$(dirname "${SPL}")"
echo "ok  hook commands survive a config path no shell parses unquoted, old spelling included"

# 5c3b. Upgrading a Bash-era install that wrote quoted commands and still has
# its hook files. Every entry becomes exec form in place -- the Bash matcher
# widened to Bash|PowerShell where the entry is ours alone, and split off where
# a user hook shares it -- and the old files go: as shipped (a released digest
# in claude/hooks/legacy-hooks.sha256) without a backup, edited only after one.
# Uninstalling a Bash-era install that was never upgraded removes its entries
# and the shipped file, and leaves the edited one where it is.
LGY="$(mktemp -d)"
LGY_FAIL() { rm -rf "${LGY}"; fail "$1"; }
legacy_fixture() { # legacy_fixture <config dir>: a Bash-era --with-hooks install
  mkdir -p "$1/hooks"
  cp "${ROOT}/tests/fixtures/legacy-luciazero-statusline.sh" "$1/hooks/luciazero-statusline.sh"
  printf '#!/usr/bin/env bash\n# edited by its owner\nexit 0\n' > "$1/hooks/luciazero-verify.sh"
  chmod +x "$1/hooks/luciazero-statusline.sh" "$1/hooks/luciazero-verify.sh"
  python3 - "$1" <<'PY'
import json, os, shlex, sys
home = sys.argv[1]
verify = shlex.quote(os.path.join(home, "hooks", "luciazero-verify.sh"))
status = shlex.quote(os.path.join(home, "hooks", "luciazero-statusline.sh"))
hook = lambda sub: {"type": "command", "command": verify + " " + sub}
settings = {"hooks": {
    "PostToolUse": [{"matcher": "Edit|Write|NotebookEdit", "hooks": [hook("edit")]},
                    {"matcher": "Bash", "hooks": [hook("bash")]},
                    {"matcher": "Skill", "hooks": [hook("skill")]}],
    "PostToolUseFailure": [{"matcher": "Bash", "hooks": [hook("bash-failure")]}],
    # the user's own hook shares the entry: it keeps the Bash matcher
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/usr/bin/true mine"},
                                                 hook("bash-start")]}],
    "UserPromptSubmit": [{"hooks": [hook("prompt")]}],
    "UserPromptExpansion": [{"hooks": [hook("skill-prompt")]}],
    "Stop": [{"hooks": [dict(hook("stop"), timeout=30)]}],
    "SessionStart": [{"hooks": [hook("session")]}]},
    "statusLine": {"type": "command", "command": status}}
json.dump(settings, open(os.path.join(home, "settings.json"), "w"), indent=2)
PY
}
mkdir -p "${LGY}/up dir"
legacy_fixture "${LGY}/up dir"
CLAUDE_CONFIG_DIR="${LGY}/up dir" "${ROOT}/install.sh" --with-hooks > "${LGY}/up.out" 2>&1 \
  || LGY_FAIL "--with-hooks failed over a Bash-era install: $(cat "${LGY}/up.out")"
python3 - "${LGY}/up dir" <<'PY' || LGY_FAIL "a Bash-era install was not migrated (see above)"
import json, os, sys
home = sys.argv[1]
s = json.load(open(os.path.join(home, "settings.json")))
verify = os.path.join(home, "hooks", "luciazero-verify.cjs")
text = json.dumps(s)
assert ".sh" not in text.replace("/usr/bin/true", ""), "a Bash-era entry survived: " + text
seen = {}
for event, entries in s["hooks"].items():
    for e in entries:
        for h in e["hooks"]:
            if h.get("command") == "node":
                assert h["args"][0] == verify and len(h["args"]) == 2, h
                assert h["args"][1] not in seen, "wired twice: " + h["args"][1]
                seen[h["args"][1]] = (event, e.get("matcher"), h)
assert len(seen) == 9, sorted(seen)
for sub in ("bash", "bash-failure", "bash-start"):
    assert seen[sub][1] == "Bash|PowerShell", sub + ": " + repr(seen[sub][1])
assert seen["stop"][2].get("timeout") == 30, "the user's timeout on our entry was dropped"
mine = [e for e in s["hooks"]["PreToolUse"] if any(h["command"] == "/usr/bin/true mine" for h in e["hooks"])]
assert len(mine) == 1 and mine[0]["matcher"] == "Bash" and len(mine[0]["hooks"]) == 1, \
    "the user's hook lost its entry or matcher: " + repr(s["hooks"]["PreToolUse"])
assert s["statusLine"]["command"].startswith("node -e "), "status line not migrated"
PY
[ ! -e "${LGY}/up dir/hooks/luciazero-statusline.sh" ] \
  || LGY_FAIL "the shipped Bash-era statusline was kept after the migration"
[ ! -e "${LGY}/up dir/hooks/luciazero-verify.sh" ] \
  || LGY_FAIL "the edited Bash-era hook was kept after the migration"
LGY_BAK="$(entries_named "${LGY}/up dir/hooks" luciazero-verify.sh.bak.)"
if [ -z "${LGY_BAK}" ] || ! grep -q 'edited by its owner' "${LGY}/up dir/hooks/${LGY_BAK}"; then
  LGY_FAIL "the edited Bash-era hook was removed without a backup"
fi
[ -z "$(entries_named "${LGY}/up dir/hooks" luciazero-statusline.sh.bak.)" ] \
  || LGY_FAIL "the shipped Bash-era statusline was backed up as if edited"
CLAUDE_CONFIG_DIR="${LGY}/up dir" "${ROOT}/install.sh" --status >/dev/null \
  || LGY_FAIL "--status red right after migrating a Bash-era install"
# never upgraded: uninstall alone
mkdir -p "${LGY}/old dir"
legacy_fixture "${LGY}/old dir"
RC=0; LGY_ST="$(CLAUDE_CONFIG_DIR="${LGY}/old dir" "${ROOT}/install.sh" --status 2>&1)" || RC=$?
if [ "${RC}" = 0 ] || ! printf '%s' "${LGY_ST}" | grep -q 'older Bash version'; then
  LGY_FAIL "--status did not flag a Bash-era hook install: ${LGY_ST}"
fi
CLAUDE_CONFIG_DIR="${LGY}/old dir" "${ROOT}/uninstall.sh" > "${LGY}/un.out" 2>&1 || true
python3 - "${LGY}/old dir/settings.json" <<'PY' || LGY_FAIL "uninstall left Bash-era entries behind"
import json, sys
s = json.load(open(sys.argv[1]))
assert "statusLine" not in s, s
left = [h["command"] for entries in s.get("hooks", {}).values() for e in entries for h in e["hooks"]]
assert left == ["/usr/bin/true mine"], left
PY
[ ! -e "${LGY}/old dir/hooks/luciazero-statusline.sh" ] \
  || LGY_FAIL "uninstall kept the shipped Bash-era statusline"
grep -q 'edited by its owner' "${LGY}/old dir/hooks/luciazero-verify.sh" \
  || LGY_FAIL "uninstall removed an edited Bash-era hook"
grep -q 'luciazero-verify.sh differs from every shipped version' "${LGY}/un.out" \
  || LGY_FAIL "uninstall did not say why it kept the edited hook: $(cat "${LGY}/un.out")"
rm -rf "${LGY}"
echo "ok  a Bash-era install migrates to the Node hooks, and uninstalls clean without migrating"

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
[ ! -f "${BLK_CFG}/hooks/luciazero-verify.cjs" ] \
  || BLK_FAIL "hook file kept although settings.json was cleaned"
rm -rf "${BLK}"
echo "ok  the settings backup refuses a symlinked name and keeps the bytes"

# 5c5. The same planted name, on the install side. `install.sh` copies an
# existing settings.json aside before it wires the hooks, and `bakpath` picked
# that name with `[ -e ]`, which follows it: a dangling symlink read as free
# and `cp` wrote the user's settings through it. `bakcopy` now takes the name
# by creating it, which refuses any name a symlink already holds; 5c6 below
# covers a symlink that arrives after the name was chosen (roadmap R24).
BLI="$(mktemp -d)"
BLI_CFG="${BLI}/cfg"; BLI_OUT="${BLI}/outside"
mkdir -p "${BLI_CFG}" "${BLI_OUT}"
BLI_FAIL() { rm -rf "${BLI}"; fail "$1"; }
CLAUDE_CONFIG_DIR="${BLI_CFG}" "${ROOT}/install.sh" --with-hooks >/dev/null
# settings.json as the user left it, unwired, so the reinstall has a change
# to make and a backup to take
printf '{"model": "opus"}\n' > "${BLI_CFG}/settings.json"
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

# 5c6. A name planted after it was chosen (roadmap R24). The case above plants
# before the installer looks; this one plants in the window between choosing
# a backup name and writing it. A `cp` shim plants a symlink at every nearby
# second's backup name the moment settings.json is handed to `cp`: a name that
# was only tested free is then followed, and a name that is reserved by
# creating it cannot be.
BLR="$(mktemp -d)"
BLR_CFG="${BLR}/cfg"; BLR_OUT="${BLR}/outside"; BLR_BIN="${BLR}/bin"
mkdir -p "${BLR_CFG}" "${BLR_OUT}" "${BLR_BIN}"
BLR_FAIL() { rm -rf "${BLR}"; fail "$1"; }
CLAUDE_CONFIG_DIR="${BLR_CFG}" "${ROOT}/install.sh" --with-hooks >/dev/null
printf '{"model": "opus"}\n' > "${BLR_CFG}/settings.json"
cp -p "${BLR_CFG}/settings.json" "${BLR}/settings.before"
BLR_CP="$(command -v cp)"
cat > "${BLR_BIN}/cp" <<BLRSH
#!/usr/bin/env bash
for a in "\$@"; do
  if [ "\$a" = "${BLR_CFG}/settings.json" ] && [ ! -e "${BLR}/planted" ]; then
    : > "${BLR}/planted"
    python3 - "${BLR_CFG}/settings.json" "${BLR_OUT}/escaped" <<'BLRPY'
import os, sys, time
base = time.time()
for i in range(-2, 60):
    decoy = sys.argv[1] + ".bak." + time.strftime("%Y%m%d%H%M%S", time.localtime(base + i))
    if not os.path.lexists(decoy):
        os.symlink(sys.argv[2] + "-" + str(i), decoy)
BLRPY
  fi
done
exec "${BLR_CP}" "\$@"
BLRSH
chmod +x "${BLR_BIN}/cp"
PATH="${BLR_BIN}:${PATH}" CLAUDE_CONFIG_DIR="${BLR_CFG}" "${ROOT}/install.sh" --with-hooks >/dev/null 2>&1 \
  || BLR_FAIL "reinstall failed when symlinks arrived after the backup name was chosen"
[ -f "${BLR}/planted" ] || BLR_FAIL "the cp shim never saw settings.json copied, so nothing was planted"
[ -z "$(ls -A "${BLR_OUT}")" ] \
  || BLR_FAIL "install wrote through a symlink planted after its backup name was chosen: $(ls -A "${BLR_OUT}")"
python3 - "${BLR_CFG}/settings.json" "${BLR}/settings.before" <<'BLRPY' || BLR_FAIL "install backup did not survive a late-planted symlink (see above)"
import os, sys
settings, before = sys.argv[1], sys.argv[2]
d, base = os.path.dirname(settings), os.path.basename(settings) + ".bak."
real = [n for n in os.listdir(d)
        if n.startswith(base) and not os.path.islink(os.path.join(d, n))]
if len(real) != 1:
    raise SystemExit("expected exactly one real backup, found: " + repr(real))
if open(os.path.join(d, real[0]), "rb").read() != open(before, "rb").read():
    raise SystemExit("backup is not the file that was replaced: " + real[0])
stray = [n for n in os.listdir(d) if n.startswith(".luciazero-bak.")]
if stray:
    raise SystemExit("temporary backup copies left behind: " + repr(stray))
BLRPY
rm -rf "${BLR}"
echo "ok  the install backup reserves its name, so a symlink planted after the choice is not followed"

# 5c7. A real directory at the chosen name (roadmap R24). `ln -n` and `ln -sn`
# refuse a symlink there but take a directory as the place to put the link, so
# the backup landed inside it and the helper reported a name that held no
# backup. With the clock pinned, the first name is the planted directory; each
# kind of backup must move on to `.1` and leave the directory as it was.
BLD="$(mktemp -d)"
BLD_FAIL() { rm -rf "${BLD}"; fail "$1"; }
mkdir -p "${BLD}/bin" "${BLD}/b/d"
printf '#!/bin/sh\necho 20000101000000\n' > "${BLD}/bin/date"
chmod +x "${BLD}/bin/date"
awk '/^(bc_raw|bc_physical|bc_symlink|bc_enter|bakcopy)\(\) \{/,/^\}/' "${ROOT}/install.sh" > "${BLD}/bakcopy.sh"
printf 'user bytes\n' > "${BLD}/b/f"
printf 'tree bytes\n' > "${BLD}/b/d/x"
ln -s "../some where" "${BLD}/b/l"
for BLD_K in f l d; do
  BLD_DST="${BLD}/b/${BLD_K}.bak.20000101000000"
  mkdir "${BLD_DST}"
  BLD_GOT="$(PATH="${BLD}/bin:${PATH}" bash -c '. "$1"; bakcopy -P "$2" "$2"' _ \
    "${BLD}/bakcopy.sh" "${BLD}/b/${BLD_K}")" \
    || BLD_FAIL "backup of ${BLD_K} failed when a directory held its first name"
  [ "${BLD_GOT}" = "${BLD_DST}.1" ] \
    || BLD_FAIL "backup of ${BLD_K} reported ${BLD_GOT#"${BLD}/"}, not the next free name"
  [ -z "$(ls -A "${BLD_DST}")" ] \
    || BLD_FAIL "backup of ${BLD_K} wrote into the directory at its name: $(ls -A "${BLD_DST}")"
done
if ! { [ -f "${BLD}/b/f.bak.20000101000000.1" ] && [ ! -L "${BLD}/b/f.bak.20000101000000.1" ] \
  && cmp -s "${BLD}/b/f" "${BLD}/b/f.bak.20000101000000.1"; }; then
  BLD_FAIL "file backup is not a copy of the file"
fi
if [ ! -L "${BLD}/b/l.bak.20000101000000.1" ] \
  || [ "$(readlink "${BLD}/b/l.bak.20000101000000.1")" != "../some where" ]; then
  BLD_FAIL "symlink backup is not the symlink"
fi
cmp -s "${BLD}/b/d/x" "${BLD}/b/d.bak.20000101000000.1/x" \
  || BLD_FAIL "tree backup is not a copy of the tree"
[ -z "$(entries_named "${BLD}/b" .luciazero-bak.)" ] \
  || BLD_FAIL "temporary backup copies left behind: $(ls -A "${BLD}/b")"
rm -rf "${BLD}"
echo "ok  a directory at the backup name is skipped, not written into"

# 5c8. A name swapped after it was taken (roadmap R24). 5c6 and 5c7 plant
# before the helper writes; these plant in the window after a name is taken
# and before the backup is complete, each through a shim of the tool that
# takes it. A symlink used to take its name as an empty file that `ln -sfn`
# then replaced: a directory swapped in there had a child of the link's name
# deleted. A tree was copied into whatever directory held its name, and a
# file into whatever its temporary name held, so a swapped directory had its
# children overwritten and a swapped symlink sent the user's bytes elsewhere.
# Each swap must leave the planted bytes as they were and the source in place.
BLS="$(mktemp -d)"
BLS_FAIL() { rm -rf "${BLS}"; fail "$1"; }
mkdir -p "${BLS}/bin" "${BLS}/b/d" "${BLS}/out"
printf '#!/bin/sh\necho 20000101000000\n' > "${BLS}/bin/date"
awk '/^(bc_raw|bc_physical|bc_symlink|bc_enter|bakcopy)\(\) \{/,/^\}/' "${ROOT}/install.sh" > "${BLS}/bakcopy.sh"
printf 'user bytes\n' > "${BLS}/b/f"
printf 'tree bytes\n' > "${BLS}/b/d/x"
ln -s "../some where" "${BLS}/b/l"
# Every tool that can make the link, wrapped so that the first call naming
# the first backup name finds a directory there whose child has the link's
# name, as the swap left it.
for BLS_T in ln perl node; do
  BLS_REAL="$(command -v "${BLS_T}" || true)"
  cat > "${BLS}/bin/${BLS_T}" <<BLSSH
#!/usr/bin/env bash
for a in "\$@"; do last="\$a"; done
if [ "\${last##*/}" = l.bak.20000101000000 ] && [ ! -e "${BLS}/planted-l" ]; then
  : > "${BLS}/planted-l"
  rm -f "\${last}"; mkdir "\${last}"
  printf 'planted child\n' > "\${last}/some where"
fi
[ -n "${BLS_REAL}" ] || exit 127
exec "${BLS_REAL}" "\$@"
BLSSH
done
BLS_MKDIR="$(command -v mkdir)"
cat > "${BLS}/bin/mkdir" <<BLSSH
#!/usr/bin/env bash
for a in "\$@"; do last="\$a"; done
"${BLS_MKDIR}" "\$@" || exit
if [ "\${last##*/}" = d.bak.20000101000000 ] && [ ! -e "${BLS}/planted-d" ]; then
  : > "${BLS}/planted-d"
  mv "\${last}" "${BLS}/moved-d"; "${BLS_MKDIR}" "\${last}"
  printf 'planted child\n' > "\${last}/x"
fi
BLSSH
BLS_MKTEMP="$(command -v mktemp)"
cat > "${BLS}/bin/mktemp" <<BLSSH
#!/usr/bin/env bash
p="\$("${BLS_MKTEMP}" "\$@")" || exit
case "\${p##*/}" in
  .luciazero-bak.*)
    if [ "\${BLS_CASE}" = f ] && [ ! -e "${BLS}/planted-f" ]; then
      : > "${BLS}/planted-f"
      rm -rf "\${p}"; ln -s "${BLS}/out" "\${p}"
    fi ;;
esac
printf '%s\n' "\${p}"
BLSSH
chmod +x "${BLS}/bin/"*
BLS_RUN() {
  BLS_CASE="$1" PATH="${BLS}/bin:${PATH}" bash -c 'set -euo pipefail; . "$1"; bakcopy -P "$2" "$2"' _ \
    "${BLS}/bakcopy.sh" "${BLS}/b/$1"
}
BLS_GOT="$(BLS_RUN l)" || BLS_FAIL "symlink backup failed when a directory was swapped in at its first name"
[ -f "${BLS}/planted-l" ] || BLS_FAIL "no symlink tool was ever handed the first backup name, so nothing was swapped"
[ "$(cat "${BLS}/b/l.bak.20000101000000/some where" 2>/dev/null)" = "planted child" ] \
  || BLS_FAIL "symlink backup replaced the child of a directory swapped in at its name"
[ "$(ls -A "${BLS}/b/l.bak.20000101000000")" = "some where" ] \
  || BLS_FAIL "symlink backup wrote into a directory swapped in at its name: $(ls -A "${BLS}/b/l.bak.20000101000000")"
if [ "${BLS_GOT}" != "${BLS}/b/l.bak.20000101000000.1" ] \
  || [ "$(readlink "${BLS_GOT}")" != "../some where" ]; then
  BLS_FAIL "symlink backup is not the symlink at the next free name: ${BLS_GOT#"${BLS}/"}"
fi
[ "$(readlink "${BLS}/b/l")" = "../some where" ] || BLS_FAIL "symlink backup disturbed the symlink it backed up"
if BLS_GOT="$(BLS_RUN d 2>/dev/null)"; then
  BLS_FAIL "tree backup reported ${BLS_GOT#"${BLS}/"} after its directory was swapped for another"
fi
[ -f "${BLS}/planted-d" ] || BLS_FAIL "mkdir never took the first tree backup name, so nothing was swapped"
if [ "$(cat "${BLS}/b/d.bak.20000101000000/x")" != "planted child" ] \
  || [ "$(ls -A "${BLS}/b/d.bak.20000101000000")" != x ]; then
  BLS_FAIL "tree backup wrote into a directory swapped in after mkdir took the name"
fi
[ -z "$(ls -A "${BLS}/moved-d")" ] || BLS_FAIL "tree backup followed its directory after the swap"
cmp -s <(printf 'tree bytes\n') "${BLS}/b/d/x" || BLS_FAIL "tree backup disturbed the tree it backed up"
if BLS_GOT="$(BLS_RUN f 2>/dev/null)"; then
  BLS_FAIL "file backup reported ${BLS_GOT#"${BLS}/"} after its private directory was swapped for a symlink"
fi
[ -f "${BLS}/planted-f" ] || BLS_FAIL "mktemp never made the private backup directory, so nothing was swapped"
[ -z "$(ls -A "${BLS}/out")" ] \
  || BLS_FAIL "file backup wrote through a symlink swapped in for its private directory: $(ls -A "${BLS}/out")"
[ -z "$(entries_named "${BLS}/b" f.bak.)" ] || BLS_FAIL "file backup left a backup name after refusing"
cmp -s <(printf 'user bytes\n') "${BLS}/b/f" || BLS_FAIL "file backup disturbed the file it backed up"
rm -rf "${BLS}"
echo "ok  a backup name swapped after it was taken is neither written into nor replaced"

# 5c9. No tool that makes a symlink at exactly its name. BSD `ln` has no -T,
# and perl and node are optional, so a symlink's backup can be impossible;
# then the install must stop before it removes the symlink, and leave
# nothing behind. With the tools back, the same install backs it up and
# replaces it.
BLN="$(mktemp -d)"
BLN_FAIL() { rm -rf "${BLN}"; fail "$1"; }
mkdir -p "${BLN}/bin" "${BLN}/cfg" "${BLN}/mine/plan"
printf 'my plan skill\n' > "${BLN}/mine/plan/SKILL.md"
BLN_LN="$(command -v ln)"
printf '#!/bin/sh\nexit 127\n' > "${BLN}/bin/perl"
printf '#!/bin/sh\nexit 127\n' > "${BLN}/bin/node"
cat > "${BLN}/bin/ln" <<BLNSH
#!/bin/sh
case "\$1" in -*T*) echo "ln: illegal option -- T" >&2; exit 1 ;; esac
exec "${BLN_LN}" "\$@"
BLNSH
chmod +x "${BLN}/bin/"*
CLAUDE_CONFIG_DIR="${BLN}/cfg" "${ROOT}/install.sh" >/dev/null
rm -rf "${BLN}/cfg/skills/plan"
ln -s "${BLN}/mine/plan" "${BLN}/cfg/skills/plan"
if PATH="${BLN}/bin:${PATH}" CLAUDE_CONFIG_DIR="${BLN}/cfg" "${ROOT}/install.sh" \
  >/dev/null 2>"${BLN}/err"; then
  BLN_FAIL "install succeeded with no way to back up a symlinked skill exactly"
fi
grep -q 'no tool here makes a symlink at exactly a given name' "${BLN}/err" \
  || BLN_FAIL "install did not say why it stopped: $(cat "${BLN}/err")"
[ "$(readlink "${BLN}/cfg/skills/plan")" = "${BLN}/mine/plan" ] \
  || BLN_FAIL "install removed a symlinked skill it could not back up"
if [ "$(cat "${BLN}/mine/plan/SKILL.md")" != "my plan skill" ] || [ "$(ls -A "${BLN}/mine/plan")" != SKILL.md ]; then
  BLN_FAIL "install changed the directory behind a symlinked skill"
fi
[ -z "$(find "${BLN}/cfg" -name '*.bak.*' -o -name '.luciazero-bak.*')" ] \
  || BLN_FAIL "install left backup names behind after refusing: $(find "${BLN}/cfg" -name '*.bak.*' -o -name '.luciazero-bak.*')"
CLAUDE_CONFIG_DIR="${BLN}/cfg" "${ROOT}/install.sh" >/dev/null \
  || BLN_FAIL "install failed to back up a symlinked skill with the system's own tools"
BLN_BAK="$(find "${BLN}/cfg" -name 'plan.bak.*')"
if [ -z "${BLN_BAK}" ] || [ "$(readlink "${BLN_BAK}")" != "${BLN}/mine/plan" ]; then
  BLN_FAIL "the backup of a symlinked skill is not that symlink: ${BLN_BAK:-none}"
fi
if [ ! -d "${BLN}/cfg/skills/plan" ] || [ -L "${BLN}/cfg/skills/plan" ]; then
  BLN_FAIL "install did not replace the symlinked skill after backing it up"
fi
[ "$(cat "${BLN}/mine/plan/SKILL.md")" = "my plan skill" ] \
  || BLN_FAIL "install wrote through a symlinked skill"
rm -rf "${BLN}"
echo "ok  a symlink that cannot be backed up exactly stops the install before it is removed"

# 5c10. Names kept byte for byte (roadmap R24). `$( )` deletes every trailing
# newline, so a link target or a directory name ending in one used to come
# back as a different name: a symlink's backup pointed somewhere else, and a
# backup beside `cfg<newline>/f` was made in a sibling `cfg` and reported at
# a name where nothing was. The same held for a relative source read from a
# directory whose name ends in a newline.
BNL="$(mktemp -d)"
BNL_FAIL() { rm -rf "${BNL}"; fail "$1"; }
BNL_C="${BNL}/cfg"$'\n'
mkdir -p "${BNL}/bin" "${BNL_C}/d" "${BNL}/cfg/d" "${BNL}/b/tgt"$'\n' "${BNL}/b/tgt"$'\n\n' "${BNL}/b/tgt"
printf '#!/bin/sh\necho 20000101000000\n' > "${BNL}/bin/date"
chmod +x "${BNL}/bin/date"
awk '/^(bc_raw|bc_physical|bc_symlink|bc_enter|bakcopy)\(\) \{/,/^\}/' "${ROOT}/install.sh" > "${BNL}/bakcopy.sh"
BNL_RUN() {
  PATH="${BNL}/bin:${PATH}" bash -c 'set -euo pipefail; . "$1"; cd "$2"; bakcopy -P "$3" "$4"' _ \
    "${BNL}/bakcopy.sh" "$@"
}
printf 'one\n' > "${BNL}/b/tgt"$'\n'"/which"
printf 'two\n' > "${BNL}/b/tgt"$'\n\n'"/which"
printf 'none\n' > "${BNL}/b/tgt/which"
ln -s "tgt"$'\n' "${BNL}/b/l1"
ln -s "tgt"$'\n\n' "${BNL}/b/l2"
for BNL_K in 1 2; do
  BNL_GOT="$(BNL_RUN "${BNL}/b" "l${BNL_K}" "${BNL}/b/l${BNL_K}")" \
    || BNL_FAIL "backup of a symlink whose target ends in a newline failed"
  [ "$(readlink "${BNL_GOT}"; printf x)" = "$(readlink "${BNL}/b/l${BNL_K}"; printf x)" ] \
    || BNL_FAIL "symlink backup lost the trailing newlines of its target"
  [ "$(cat "${BNL_GOT}/which")" = "$(cat "${BNL}/b/l${BNL_K}/which")" ] \
    || BNL_FAIL "symlink backup resolves to $(cat "${BNL_GOT}/which" 2>&1), not where its source does"
done
printf 'user bytes\n' > "${BNL_C}/f"
printf 'tree bytes\n' > "${BNL_C}/d/x"
ln -s "../some where" "${BNL_C}/l"
printf 'sibling bytes\n' > "${BNL}/cfg/f"
printf 'sibling tree\n' > "${BNL}/cfg/d/x"
ln -s "../elsewhere" "${BNL}/cfg/l"
for BNL_K in f d l; do
  for BNL_SRC in "${BNL_C}/${BNL_K}" "${BNL_K}"; do
    BNL_GOT="$(BNL_RUN "${BNL_C}" "${BNL_SRC}" "${BNL_C}/${BNL_K}")" \
      || BNL_FAIL "backup of ${BNL_K} in a directory whose name ends in a newline failed"
    if [ "${BNL_GOT%/*}" != "${BNL_C%/}" ] || { [ ! -e "${BNL_GOT}" ] && [ ! -L "${BNL_GOT}" ]; }; then
      BNL_FAIL "backup of ${BNL_K} reported ${BNL_GOT#"${BNL}/"}, where there is no backup"
    fi
    case "${BNL_K}" in
      f) cmp -s "${BNL_C}/f" "${BNL_GOT}" || BNL_FAIL "file backup is not a copy of ${BNL_SRC#"${BNL}/"}" ;;
      d) cmp -s "${BNL_C}/d/x" "${BNL_GOT}/x" || BNL_FAIL "tree backup is not a copy of ${BNL_SRC#"${BNL}/"}" ;;
      l) [ "$(readlink "${BNL_GOT}")" = "../some where" ] || BNL_FAIL "symlink backup is not ${BNL_SRC#"${BNL}/"}" ;;
    esac
    rm -rf "${BNL_GOT}"
  done
done
[ "$(find "${BNL}/cfg" -mindepth 1 -maxdepth 1 | LC_ALL=C sort | tr '\n' ' ')" \
  = "${BNL}/cfg/d ${BNL}/cfg/f ${BNL}/cfg/l " ] \
  || BNL_FAIL "backup wrote into the sibling directory without the newline: $(ls -A "${BNL}/cfg")"
[ -z "$(find "${BNL_C}" -mindepth 1 -maxdepth 1 ! -name d ! -name f ! -name l)" ] \
  || BNL_FAIL "backups left temporary names behind: $(ls -A "${BNL_C}")"
rm -rf "${BNL}"
echo "ok  backup names and link targets keep their trailing newlines"

# 5c11. The private directory is removed only when it still passes the owner
# check. With `[ -O` failing, as for a directory of another user swapped in at
# its name, the backup must fail and the directory must stay where it is.
# And a symlink tool that replaces a regular file at its name is not trusted
# with the backup name, as one that replaces a directory or symlink is not.
BCG="$(mktemp -d)"
BCG_FAIL() { rm -rf "${BCG}"; fail "$1"; }
mkdir -p "${BCG}/bin" "${BCG}/b/mine"
awk '/^(bc_raw|bc_physical|bc_symlink|bc_enter|bakcopy)\(\) \{/,/^\}/' "${ROOT}/install.sh" > "${BCG}/bakcopy.sh"
printf 'user bytes\n' > "${BCG}/b/f"
if bash -c 'set -euo pipefail; . "$1"
  [() { case "$1" in -O) return 1 ;; esac; builtin [ "$@"; }
  bakcopy -P "$2" "$2"' _ "${BCG}/bakcopy.sh" "${BCG}/b/f" >/dev/null 2>&1; then
  BCG_FAIL "file backup succeeded although its private directory failed the owner check"
fi
[ -n "$(find "${BCG}/b" -name '.luciazero-bak.*' -type d)" ] \
  || BCG_FAIL "file backup removed a private directory that failed the owner check"
[ -z "$(entries_named "${BCG}/b" f.bak.)" ] || BCG_FAIL "file backup left a backup name after refusing"
cmp -s <(printf 'user bytes\n') "${BCG}/b/f" || BCG_FAIL "file backup disturbed the file it backed up"
# Empty means a listing that worked and printed nothing: `$( )` would read an
# entry named only by newlines, or a listing that failed, as empty.
mkdir -p "${BCG}/nl" "${BCG}/shut"
printf 'sentinel\n' > "${BCG}/nl/"$'\n'
chmod 300 "${BCG}/shut"
for BCG_D in nl shut; do
  [ "${BCG_D}" = shut ] && [ "$(id -u)" = 0 ] && continue # root reads it anyway
  if bash -c '. "$1"; bc_enter "$(cd "$2" && pwd -P)"' _ "${BCG}/bakcopy.sh" "${BCG}/${BCG_D}"; then
    chmod 700 "${BCG}/shut"
    BCG_FAIL "the empty-directory check accepted a directory that is not shown empty: ${BCG_D}"
  fi
done
chmod 700 "${BCG}/shut"
[ "$(cat "${BCG}/nl/"$'\n')" = sentinel ] || BCG_FAIL "the empty-directory check changed the entry it found"
BCG_LN="$(command -v ln)"
BCG_PERL="$(command -v perl || true)"
cat > "${BCG}/bin/ln" <<BCGSH
#!/bin/sh
case "\$1" in -*T*) echo "ln: illegal option -- T" >&2; exit 1 ;; esac
exec "${BCG_LN}" "\$@"
BCGSH
printf '#!/bin/sh\nexit 127\n' > "${BCG}/bin/node"
cat > "${BCG}/bin/perl" <<BCGSH
#!/bin/sh
for a in "\$@"; do last="\$a"; done
if [ -f "\${last}" ] && [ ! -L "\${last}" ]; then rm -f "\${last}"; fi
[ -n "${BCG_PERL}" ] || exit 127
exec "${BCG_PERL}" "\$@"
BCGSH
chmod +x "${BCG}/bin/"*
ln -s mine "${BCG}/b/l"
if PATH="${BCG}/bin:${PATH}" bash -c 'set -euo pipefail; . "$1"; bakcopy -P "$2" "$2"' _ \
  "${BCG}/bakcopy.sh" "${BCG}/b/l" >/dev/null 2>"${BCG}/err"; then
  BCG_FAIL "symlink backup trusted a tool that replaces a regular file at its name"
fi
grep -q 'no tool here makes a symlink at exactly a given name' "${BCG}/err" \
  || BCG_FAIL "symlink backup did not say why it stopped: $(cat "${BCG}/err")"
[ "$(readlink "${BCG}/b/l")" = mine ] || BCG_FAIL "symlink backup disturbed the symlink it backed up"
rm -rf "${BCG}"
echo "ok  backup cleanup and tool choice hold to the owner check and exact names"

# The four installers each carry the same backup helper; one that drifts
# from the others would silently lose the reservation above.
BC_REF=""
for BC_F in install.sh uninstall.sh install-codex.sh uninstall-codex.sh; do
  BC_BODY="$(awk '/^(bc_raw|bc_physical|bc_symlink|bc_enter|bakcopy)\(\) \{/,/^\}/' "${ROOT}/${BC_F}")"
  for BC_FN in bc_raw bc_physical bc_symlink bc_enter bakcopy; do
    printf '%s\n' "${BC_BODY}" | grep -q "^${BC_FN}() {" || fail "${BC_F} has no ${BC_FN} helper"
  done
  [ -n "${BC_REF}" ] || BC_REF="${BC_BODY}"
  [ "${BC_BODY}" = "${BC_REF}" ] || fail "${BC_F} bakcopy differs from install.sh"
  ! grep -q 'bakpath' "${ROOT}/${BC_F}" || fail "${BC_F} still picks backup names with bakpath"
done
echo "ok  the four installers share one reserving backup helper"

# 5d. failed settings cleanup must NOT delete the hook files (no dangling refs)
SB4="$(mktemp -d)"
CLAUDE_CONFIG_DIR="${SB4}" "${ROOT}/install.sh" --with-hooks >/dev/null
# corrupt the JSON while KEEPING a reference to our hook — the dangerous case:
# cleanup cannot run, so deleting the files would leave dangling references
printf '{broken json "%s/hooks/luciazero-verify.cjs stop"\n' "${SB4}" > "${SB4}/settings.json"
CLAUDE_CONFIG_DIR="${SB4}" "${ROOT}/uninstall.sh" >/dev/null 2>&1 || true
[ -f "${SB4}/hooks/luciazero-verify.cjs" ] \
  || { rm -rf "${SB4}"; fail "hook files deleted although settings cleanup failed (dangling references)"; }
rm -rf "${SB4}"
echo "ok  uninstall keeps hook files when settings cleanup fails"

# 5d2. settings.json is checked before anything of the pack is copied
# (roadmap R14): a file the installer cannot wire -- not JSON, the wrong
# shape, or not writable -- fails the install with no hook file in place and
# every byte of settings.json as it was. A symlinked settings.json stays a
# symlink, and the file it points at keeps its mode.
SB4B="$(mktemp -d)"
SB4B_FAIL() { rm -rf "${SB4B}"; fail "$1"; }
for SB4B_CASE in '{broken json' '[]' '{"hooks": []}' '{"hooks": {"Stop": {"x": 1}}}' readonly; do
  rm -rf "${SB4B}/cfg"; mkdir -p "${SB4B}/cfg"
  if [ "${SB4B_CASE}" = readonly ]; then
    printf '{"model": "opusplan"}\n' > "${SB4B}/cfg/settings.json"
    chmod 444 "${SB4B}/cfg/settings.json"
  else
    printf '%s\n' "${SB4B_CASE}" > "${SB4B}/cfg/settings.json"
  fi
  rm -f "${SB4B}/before"; cp -p "${SB4B}/cfg/settings.json" "${SB4B}/before"
  RC=0; CLAUDE_CONFIG_DIR="${SB4B}/cfg" "${ROOT}/install.sh" --with-hooks >/dev/null 2>&1 || RC=$?
  [ "${RC}" -ne 0 ] || SB4B_FAIL "--with-hooks accepted a settings.json it cannot wire: ${SB4B_CASE}"
  [ ! -e "${SB4B}/cfg/hooks/luciazero-verify.cjs" ] \
    || SB4B_FAIL "--with-hooks copied hook files before refusing settings.json: ${SB4B_CASE}"
  cmp -s "${SB4B}/cfg/settings.json" "${SB4B}/before" \
    || SB4B_FAIL "--with-hooks changed a settings.json it refused: ${SB4B_CASE}"
  chmod 644 "${SB4B}/cfg/settings.json"
done
rm -rf "${SB4B}/cfg"; mkdir -p "${SB4B}/cfg" "${SB4B}/dotfiles"
printf '{"model": "opusplan"}\n' > "${SB4B}/dotfiles/settings.json"
chmod 640 "${SB4B}/dotfiles/settings.json"
ln -s "${SB4B}/dotfiles/settings.json" "${SB4B}/cfg/settings.json"
CLAUDE_CONFIG_DIR="${SB4B}/cfg" "${ROOT}/install.sh" --with-hooks >/dev/null \
  || SB4B_FAIL "--with-hooks failed on a symlinked settings.json"
[ -L "${SB4B}/cfg/settings.json" ] || SB4B_FAIL "--with-hooks replaced a symlinked settings.json with a file"
grep -qF 'luciazero-verify.cjs' "${SB4B}/dotfiles/settings.json" \
  || SB4B_FAIL "--with-hooks did not wire the file a symlinked settings.json points at"
python3 -c 'import os, sys; m = os.stat(sys.argv[1]).st_mode & 0o777; sys.exit(0 if m == 0o640 else "mode " + oct(m))' \
  "${SB4B}/dotfiles/settings.json" || SB4B_FAIL "--with-hooks changed the mode of settings.json"
[ -z "$(find "${SB4B}/dotfiles" "${SB4B}/cfg" -maxdepth 1 -name '.settings.json.*' -print -quit)" ] \
  || SB4B_FAIL "--with-hooks left a temporary settings file behind"
CLAUDE_CONFIG_DIR="${SB4B}/cfg" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ -L "${SB4B}/cfg/settings.json" ] || SB4B_FAIL "uninstall replaced a symlinked settings.json with a file"
! grep -qF 'luciazero-' "${SB4B}/dotfiles/settings.json" \
  || SB4B_FAIL "uninstall did not clean the file a symlinked settings.json points at"
python3 -c 'import os, sys; m = os.stat(sys.argv[1]).st_mode & 0o777; sys.exit(0 if m == 0o640 else "mode " + oct(m))' \
  "${SB4B}/dotfiles/settings.json" || SB4B_FAIL "uninstall changed the mode of settings.json"
# the file is writable but the directory it lives in is not: the new file
# cannot be made beside it, which must be found before the hooks are copied
rm -rf "${SB4B}/cfg" "${SB4B}/dotfiles" "${SB4B}/before"; mkdir -p "${SB4B}/cfg" "${SB4B}/dotfiles"
printf '{"model": "sonnet"}\n' > "${SB4B}/dotfiles/settings.json"
ln -s "${SB4B}/dotfiles/settings.json" "${SB4B}/cfg/settings.json"
cp -p "${SB4B}/dotfiles/settings.json" "${SB4B}/before" || SB4B_FAIL "could not record settings.json"
chmod 555 "${SB4B}/dotfiles"
RC=0; CLAUDE_CONFIG_DIR="${SB4B}/cfg" "${ROOT}/install.sh" --with-hooks >/dev/null 2>&1 || RC=$?
chmod 755 "${SB4B}/dotfiles"
[ "${RC}" -ne 0 ] || SB4B_FAIL "--with-hooks accepted a settings.json whose directory cannot take the new file"
[ ! -e "${SB4B}/cfg/hooks/luciazero-verify.cjs" ] \
  || SB4B_FAIL "--with-hooks copied hook files before finding the settings directory read-only"
cmp -s "${SB4B}/dotfiles/settings.json" "${SB4B}/before" \
  || SB4B_FAIL "--with-hooks changed settings.json in a read-only directory"
# a settings.json that is a symlink loop can be neither read nor written:
# both the check and the write refuse it, with each link as it was, where
# the write once replaced one of them with a fresh file
rm -rf "${SB4B}/cfg" "${SB4B}/dotfiles"; mkdir -p "${SB4B}/cfg" "${SB4B}/dotfiles"
ln -s "${SB4B}/dotfiles/loop" "${SB4B}/cfg/settings.json"
ln -s "${SB4B}/cfg/settings.json" "${SB4B}/dotfiles/loop"
SB4B_LOOP() {
  if [ "$(readlink "${SB4B}/cfg/settings.json")" != "${SB4B}/dotfiles/loop" ] \
    || [ "$(readlink "${SB4B}/dotfiles/loop")" != "${SB4B}/cfg/settings.json" ]; then
    SB4B_FAIL "$1 replaced a link of a settings.json symlink loop"
  fi
}
for SB4B_MODE in check write; do
  RC=0; node "${ROOT}/bin/lib/settings-wiring.js" wire "${SB4B_MODE}" "${SB4B}/cfg/settings.json" \
    "${SB4B}/cfg/hooks" >/dev/null 2>&1 || RC=$?
  [ "${RC}" -ne 0 ] || SB4B_FAIL "wire ${SB4B_MODE} accepted a settings.json that is a symlink loop"
  SB4B_LOOP "wire ${SB4B_MODE}"
done
RC=0; CLAUDE_CONFIG_DIR="${SB4B}/cfg" "${ROOT}/install.sh" --with-hooks >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || SB4B_FAIL "--with-hooks accepted a settings.json that is a symlink loop"
SB4B_LOOP "--with-hooks"
[ ! -e "${SB4B}/cfg/hooks/luciazero-verify.cjs" ] \
  || SB4B_FAIL "--with-hooks copied hook files before refusing a settings.json symlink loop"
# a symlink to nothing is written at the name it points to, which makes it
# whole and keeps the link
rm -rf "${SB4B}/cfg" "${SB4B}/dotfiles"; mkdir -p "${SB4B}/cfg" "${SB4B}/dotfiles"
ln -s "${SB4B}/dotfiles/settings.json" "${SB4B}/cfg/settings.json"
CLAUDE_CONFIG_DIR="${SB4B}/cfg" "${ROOT}/install.sh" --with-hooks >/dev/null \
  || SB4B_FAIL "--with-hooks failed on a settings.json symlink to a file not made yet"
[ "$(readlink "${SB4B}/cfg/settings.json")" = "${SB4B}/dotfiles/settings.json" ] \
  || SB4B_FAIL "--with-hooks replaced a settings.json symlink to a file not made yet"
if ! { [ -f "${SB4B}/dotfiles/settings.json" ] && [ ! -L "${SB4B}/dotfiles/settings.json" ] \
  && grep -qF 'luciazero-verify.cjs' "${SB4B}/dotfiles/settings.json"; }; then
  SB4B_FAIL "--with-hooks did not make the file a dangling settings.json symlink points at"
fi
rm -rf "${SB4B}"
echo "ok  settings.json is checked before the pack is copied, and written whole beside its real file"

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

# 5f. non-ASCII config path: settings.json stores the hook paths raw, and
# --status, the dedupe and the uninstaller all still find them
SB6R="$(mktemp -d)"
SB6="${SB6R}/claudé"
mkdir -p "${SB6}"
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/install.sh" --with-hooks >/dev/null
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/install.sh" --status >/dev/null \
  || { rm -rf "${SB6R}"; fail "--status red on a healthy non-ASCII config dir"; }
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ ! -f "${SB6}/hooks/luciazero-verify.cjs" ] || { rm -rf "${SB6R}"; fail "non-ASCII-path uninstall left hook files"; }
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
