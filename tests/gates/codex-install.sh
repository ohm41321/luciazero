# tests/gates/codex-install.sh — sandboxed Codex install/uninstall cycle.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 6. sandbox Codex install cycle — never touches the real ~/.codex
CX="$(mktemp -d)"
trap 'rm -rf "${CX}"' EXIT
printf '# pre-existing codex rules\n' > "${CX}/AGENTS.md"
mkdir -p "${CX}/skills/plan"
printf '%s\n' '---' 'name: plan' '---' '# pre-existing codex plan' > "${CX}/skills/plan/SKILL.md"
mkdir -p "${CX}/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${CX}/skills/luciazero-bootstrap/SKILL.md"
mkdir -p "${CX}/.luciazero-managed/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${CX}/.luciazero-managed/skills/luciazero-bootstrap/SKILL.md"

CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" >/dev/null
grep -q '^# Luciazero' "${CX}/AGENTS.md" || fail "doctrine not in AGENTS.md"
[ "$(grep -cF 'luciazero:start' "${CX}/AGENTS.md")" = 1 ] || fail "marker block not added"
while IFS= read -r NS; do
  [ -f "${CX}/skills/${NS}/SKILL.md" ] || fail "codex ${NS} skill not installed"
done < <(skill_inventory)
[ -x "${CX}/skills/ready/scripts/detect.sh" ] || fail "codex detect.sh not installed or not executable"
[ ! -e "${CX}/skills/luciazero-bootstrap" ] \
  || fail "codex install did not migrate the retired compatibility alias"
[ -x "${CX}/skills/done/scripts/revert-probe.sh" ] || fail "codex revert-probe.sh not installed or not executable"
[ -x "${CX}/skills/bisect/scripts/safe-bisect.sh" ] || fail "codex safe-bisect.sh not installed or not executable"
[ -x "${CX}/skills/lucia-relay/scripts/relay.py" ] || fail "codex relay.py not installed or not executable"
[ -f "${CX}/.luciazero-version" ] || fail "codex version sidecar not written"
[ -f "${CX}/skills/reviewer/SKILL.md" ] || fail "codex reviewer skill not installed"
[ ! -d "${CX}/hooks" ] || fail "Claude-only hooks leaked into codex install"
grep -q '^name: reviewer$' "${CX}/skills/reviewer/SKILL.md" || fail "reviewer skill lost frontmatter"
! grep -q '^tools: ' "${CX}/skills/reviewer/SKILL.md" || fail "Claude-only tools: line leaked into codex skill"
! grep -q '^model: ' "${CX}/skills/reviewer/SKILL.md" || fail "Claude-only model: line leaked into codex skill"
grep -q 'pre-existing codex plan' "${CX}/.luciazero-backups"/skills/plan.bak.*/SKILL.md \
  || fail "codex install did not back up a colliding generic skill"

cp "${CX}/AGENTS.md" "${CX}/AGENTS.md.snap"
CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" >/dev/null
[ "$(grep -cF 'luciazero:start' "${CX}/AGENTS.md")" = 1 ] || fail "codex install is not idempotent"
cmp -s "${CX}/AGENTS.md" "${CX}/AGENTS.md.snap" \
  || fail "codex reinstall changed AGENTS.md content (regression: accumulating blank lines)"
echo "ok  codex install + idempotent reinstall"

echo '# keep customized codex bisect' >> "${CX}/skills/bisect/SKILL.md"
# Simulate an older managed install and ensure uninstall removes the alias by
# comparing with its ownership snapshot.
mkdir -p "${CX}/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${CX}/skills/luciazero-bootstrap/SKILL.md"
mkdir -p "${CX}/.luciazero-managed/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${CX}/.luciazero-managed/skills/luciazero-bootstrap/SKILL.md"
COUT="$(CODEX_HOME="${CX}" "${ROOT}/uninstall-codex.sh" 2>&1)"
while IFS= read -r NS; do
  if [ "${NS}" = bisect ]; then
    grep -q 'keep customized codex bisect' "${CX}/skills/bisect/SKILL.md" \
      || fail "codex uninstall deleted a customized managed skill"
  else
    [ ! -d "${CX}/skills/${NS}" ] || fail "codex ${NS} skill left behind"
  fi
done < <(skill_inventory)
[ ! -e "${CX}/skills/luciazero-bootstrap" ] \
  || fail "codex uninstall left the retired compatibility alias"
[ ! -d "${CX}/skills/reviewer" ] || fail "codex reviewer skill left behind"
echo "${COUT}" | grep -q 'not the exact Luciazero-managed copy; left untouched' \
  || fail "codex uninstall did not explain preserved customizations"
[ ! -f "${CX}/.luciazero-version" ] || fail "codex version sidecar left behind"
grep -qxF '# pre-existing codex rules' "${CX}/AGENTS.md" || fail "pre-existing AGENTS.md content damaged"
! grep -qF 'luciazero:start' "${CX}/AGENTS.md" || fail "marker block left behind"
echo "ok  codex uninstall restores AGENTS.md"

# R12b: an install/uninstall cycle has to hand AGENTS.md back byte for byte.
# The installer used to trim trailing blank lines it had never written, paying
# for a separator of its own, so a file ending in no blank line came back one
# line longer and one ending in several came back shorter. The rearranged case
# also reinstalls, because moving the block is what puts the installer's own
# stripping pass -- the one that did the trimming -- over user content.
#
# The noeol cases are the same defect from the other end: both rewrites went
# through `awk`, whose print terminates every record it writes, so a file whose
# last line carried no newline came back one byte longer -- 12 bytes to 13 for
# the LF fixture, and the CRLF one the same way. The start marker needs a line
# of its own, so the install has to add that newline; it records it inside the
# block and the uninstall removes it again.
for RT_CASE in none one several rearranged noeol crlf-noeol; do
  RT="$(mktemp -d)"
  case "${RT_CASE}" in
    several)    printf '# mine\n\nkeep\n\n\n\n' > "${RT}/AGENTS.md" ;;
    one)        printf '# mine\n\nkeep\n\n'       > "${RT}/AGENTS.md" ;;
    noeol)      printf '# mine\n\nkeep'             > "${RT}/AGENTS.md" ;;
    crlf-noeol) printf '# mine\r\n\r\nkeep'         > "${RT}/AGENTS.md" ;;
    *)          printf '# mine\n\nkeep\n'           > "${RT}/AGENTS.md" ;;
  esac
  cp "${RT}/AGENTS.md" "${RT}/AGENTS.md.orig"
  CODEX_HOME="${RT}" "${ROOT}/install-codex.sh" >/dev/null 2>&1 \
    || { rm -rf "${RT}"; fail "codex install failed on the ${RT_CASE} round-trip fixture"; }
  if [ "${RT_CASE}" = rearranged ]; then
    # the user moves the block, writes above and below it, and reinstalls
    { printf 'my new note\n\n'
      sed -n '/<!-- luciazero:start -->/,/<!-- luciazero:end -->/p' "${RT}/AGENTS.md"
      printf '\n# mine\n\nkeep\n\n\n'; } > "${RT}/AGENTS.md.moved"
    mv "${RT}/AGENTS.md.moved" "${RT}/AGENTS.md"
    printf 'my new note\n\n\n# mine\n\nkeep\n\n\n' > "${RT}/AGENTS.md.orig"
    CODEX_HOME="${RT}" "${ROOT}/install-codex.sh" >/dev/null 2>&1 \
      || { rm -rf "${RT}"; fail "codex reinstall failed on a rearranged AGENTS.md"; }
  fi
  case "${RT_CASE}" in
    *noeol)
      # the record of the newline the install added is inside the block the
      # next install strips, so a second install has to read it back out
      CODEX_HOME="${RT}" "${ROOT}/install-codex.sh" >/dev/null 2>&1 \
        || { rm -rf "${RT}"; fail "codex reinstall failed on the ${RT_CASE} round-trip fixture"; }
      ;;
  esac
  CODEX_HOME="${RT}" "${ROOT}/uninstall-codex.sh" >/dev/null 2>&1 \
    || { rm -rf "${RT}"; fail "codex uninstall failed on the ${RT_CASE} round-trip fixture"; }
  cmp -s "${RT}/AGENTS.md.orig" "${RT}/AGENTS.md" || {
    RT_DIFF="$(diff "${RT}/AGENTS.md.orig" "${RT}/AGENTS.md" | tr '\n' ' ')"
    RT_SIZE="$(wc -c < "${RT}/AGENTS.md.orig" | tr -d ' ') -> $(wc -c < "${RT}/AGENTS.md" | tr -d ' ') bytes"
    rm -rf "${RT}"
    fail "codex install/uninstall cycle did not restore AGENTS.md bytes (${RT_CASE}, ${RT_SIZE}): ${RT_DIFF}"
  }
  rm -rf "${RT}"
done
echo "ok  codex install/uninstall cycle returns AGENTS.md to its original bytes"

# Retired-alias migration must not delete an exact-looking collision without a
# managed ownership snapshot, and must refuse symlinked skill parents.
SM="$(mktemp -d)"
mkdir -p "${SM}/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SM}/skills/luciazero-bootstrap/SKILL.md"
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/install.sh" >/dev/null 2>&1
[ -f "${SM}/skills/luciazero-bootstrap/SKILL.md" ] \
  || { rm -rf "${SM}"; fail "install deleted an exact-looking alias collision without ownership snapshot"; }
rm -rf "${SM}"

SM="$(mktemp -d)"
mkdir -p "${SM}/outside/luciazero-bootstrap" "${SM}/.luciazero-managed/skills/luciazero-bootstrap"
ln -s "${SM}/outside" "${SM}/skills"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SM}/outside/luciazero-bootstrap/SKILL.md"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SM}/.luciazero-managed/skills/luciazero-bootstrap/SKILL.md"
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/install.sh" >/dev/null 2>&1
[ -f "${SM}/outside/luciazero-bootstrap/SKILL.md" ] \
  || { rm -rf "${SM}"; fail "install followed a symlinked skill parent during alias migration"; }
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ -f "${SM}/outside/luciazero-bootstrap/SKILL.md" ] \
  || { rm -rf "${SM}"; fail "uninstall followed a symlinked skill parent during alias migration"; }
rm -rf "${SM}"

# A refusal has to come out BEFORE snapshot cleanup, not after it: a symlink
# anywhere between the managed root and a snapshot would otherwise redirect
# the cleanup outside the config dir. Sentinels below live outside it.
SM="$(mktemp -d)"
mkdir -p "${SM}/skills/done" "${SM}/.luciazero-managed" "${SM}/outside/done"
printf 'x\n' > "${SM}/skills/done/SKILL.md"
printf 'sentinel\n' > "${SM}/outside/done/keepme"
ln -s "${SM}/outside" "${SM}/.luciazero-managed/skills"
OUT="$(CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/uninstall.sh" 2>&1)" || true
[ -f "${SM}/outside/done/keepme" ] \
  || { rm -rf "${SM}"; fail "uninstall deleted through a symlinked snapshot parent"; }
echo "${OUT}" | grep -q 'symlinked parent' \
  || { rm -rf "${SM}"; fail "uninstall did not report the symlinked snapshot parent: ${OUT}"; }
rm -rf "${SM}"

# the same redirection one level up: a symlinked managed root
SM="$(mktemp -d)"
mkdir -p "${SM}/skills/done" "${SM}/outside/skills/done"
printf 'x\n' > "${SM}/skills/done/SKILL.md"
printf 'sentinel\n' > "${SM}/outside/skills/done/keepme"
ln -s "${SM}/outside" "${SM}/.luciazero-managed"
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/uninstall.sh" >/dev/null 2>&1 || true
[ -f "${SM}/outside/skills/done/keepme" ] \
  || { rm -rf "${SM}"; fail "uninstall deleted through a symlinked managed root"; }
rm -rf "${SM}"

# managed files carry the same policy as managed trees
SM="$(mktemp -d)"
mkdir -p "${SM}/.luciazero-managed" "${SM}/outside-agents"
printf 'sentinel\n' > "${SM}/outside-agents/reviewer.md"
ln -s "${SM}/outside-agents" "${SM}/.luciazero-managed/agents"
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/uninstall.sh" >/dev/null 2>&1 || true
[ -f "${SM}/outside-agents/reviewer.md" ] \
  || { rm -rf "${SM}"; fail "uninstall deleted through a symlinked agent-snapshot parent"; }
rm -rf "${SM}"

# Ambiguous marker structure is refused, and the refusal leaves the user's
# AGENTS.md byte-identical: no backup, no partial rewrite, no lost tail.
for CASE in incomplete duplicate nested; do
  SM="$(mktemp -d)"
  mkdir -p "${SM}/skills"
  {
    printf '# user rules\n'
    printf '<!-- luciazero:start -->\n'
    if [ "${CASE}" = nested ]; then printf '<!-- luciazero:start -->\n'; fi
    printf 'doctrine\n'
    if [ "${CASE}" != incomplete ]; then printf '<!-- luciazero:end -->\n'; fi
    if [ "${CASE}" = nested ]; then printf '<!-- luciazero:end -->\n'; fi
    if [ "${CASE}" = duplicate ]; then
      printf '<!-- luciazero:start -->\ndoctrine\n<!-- luciazero:end -->\n'
    fi
    printf 'tail the user wrote\n'
  } > "${SM}/AGENTS.md"
  chmod 640 "${SM}/AGENTS.md"
  cp "${SM}/AGENTS.md" "${SM}/AGENTS.md.expected"
  CODEX_HOME="${SM}" "${ROOT}/install-codex.sh" >/dev/null 2>&1     && { rm -rf "${SM}"; fail "codex install accepted ${CASE} markers"; }
  cmp -s "${SM}/AGENTS.md" "${SM}/AGENTS.md.expected" \
    || { rm -rf "${SM}"; fail "codex install rewrote AGENTS.md with ${CASE} markers"; }
  [ -z "$(find "${SM}" -maxdepth 1 -name 'AGENTS.md.bak.*' -print -quit)" ] \
    || { rm -rf "${SM}"; fail "codex install backed up AGENTS.md it refused to touch (${CASE})"; }
  OUT="$(CODEX_HOME="${SM}" "${ROOT}/uninstall-codex.sh" 2>&1)" || true
  cmp -s "${SM}/AGENTS.md" "${SM}/AGENTS.md.expected" \
    || { rm -rf "${SM}"; fail "codex uninstall rewrote AGENTS.md with ${CASE} markers"; }
  echo "${OUT}" | grep -q 'markers' \
    || { rm -rf "${SM}"; fail "codex uninstall did not report the ${CASE} markers: ${OUT}"; }
  [ "$(stat -c '%a' "${SM}/AGENTS.md" 2>/dev/null || stat -f '%Lp' "${SM}/AGENTS.md")" = 640 ] \
    || { rm -rf "${SM}"; fail "a refused ${CASE} rewrite changed the AGENTS.md mode"; }
  rm -rf "${SM}"
done

# the codex rewrite must not publish through a name anyone can pre-create
SM="$(mktemp -d)"
mkdir -p "${SM}/skills"
printf '# user rules\n<!-- luciazero:start -->\ndoctrine\n<!-- luciazero:end -->\n' > "${SM}/AGENTS.md"
chmod 640 "${SM}/AGENTS.md"
printf 'sentinel\n' > "${SM}/outside.txt"
ln -s "${SM}/outside.txt" "${SM}/AGENTS.md.tmp"
CODEX_HOME="${SM}" "${ROOT}/uninstall-codex.sh" >/dev/null 2>&1 || true
grep -qx sentinel "${SM}/outside.txt" \
  || { rm -rf "${SM}"; fail "codex uninstall wrote through a predictable temporary path"; }
[ ! -L "${SM}/AGENTS.md" ] \
  || { rm -rf "${SM}"; fail "codex uninstall published a symlink as AGENTS.md"; }
grep -qx '# user rules' "${SM}/AGENTS.md" \
  || { rm -rf "${SM}"; fail "codex uninstall lost user content in AGENTS.md"; }
! grep -qF 'luciazero:start' "${SM}/AGENTS.md" \
  || { rm -rf "${SM}"; fail "codex uninstall left the marker block behind"; }
[ "$(stat -c '%a' "${SM}/AGENTS.md" 2>/dev/null || stat -f '%Lp' "${SM}/AGENTS.md")" = 640 ] \
  || { rm -rf "${SM}"; fail "the mktemp rewrite changed the AGENTS.md mode"; }
rm -rf "${SM}"

# and the codex uninstaller shares the policy
SM="$(mktemp -d)"
mkdir -p "${SM}/skills/done" "${SM}/.luciazero-managed" "${SM}/outside/done"
printf 'x\n' > "${SM}/skills/done/SKILL.md"
printf 'sentinel\n' > "${SM}/outside/done/keepme"
ln -s "${SM}/outside" "${SM}/.luciazero-managed/skills"
CODEX_HOME="${SM}" "${ROOT}/uninstall-codex.sh" >/dev/null 2>&1 || true
[ -f "${SM}/outside/done/keepme" ] \
  || { rm -rf "${SM}"; fail "codex uninstall deleted through a symlinked snapshot parent"; }
rm -rf "${SM}"
echo "ok  retired alias ownership + symlink safety"

# The user's own instruction files keep the mode they had. mktemp creates its
# file 0600 and the rename publishes it, so a rewrite handed a 0640 CLAUDE.md
# back as 0600 -- a change to the user's file that nobody asked for.
mode_of() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }

SM="$(mktemp -d)"
printf '# my own rules\n' > "${SM}/CLAUDE.md"
chmod 640 "${SM}/CLAUDE.md"
EXP="$(mktemp -d)"
cp "${SM}/CLAUDE.md" "${EXP}/CLAUDE.md"
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/install.sh" >/dev/null 2>&1
[ "$(mode_of "${SM}/CLAUDE.md")" = 640 ] \
  || { M="$(mode_of "${SM}/CLAUDE.md")"; rm -rf "${SM}" "${EXP}"; fail "install changed CLAUDE.md mode to ${M}"; }
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ "$(mode_of "${SM}/CLAUDE.md")" = 640 ] \
  || { M="$(mode_of "${SM}/CLAUDE.md")"; rm -rf "${SM}" "${EXP}"; fail "uninstall changed CLAUDE.md mode to ${M}"; }
cmp -s "${SM}/CLAUDE.md" "${EXP}/CLAUDE.md" \
  || { rm -rf "${SM}" "${EXP}"; fail "install then uninstall did not restore CLAUDE.md byte for byte"; }
BK="$(find "${SM}" -maxdepth 1 -name 'CLAUDE.md.bak.*' -print -quit)"
if [ -z "${BK}" ] || [ "$(mode_of "${BK}")" != 640 ]; then
  rm -rf "${SM}" "${EXP}"
  fail "the CLAUDE.md backup did not keep the file's mode"
fi
rm -rf "${SM}" "${EXP}"

SM="$(mktemp -d)"
mkdir -p "${SM}/skills"
printf '# my codex rules\n' > "${SM}/AGENTS.md"
chmod 640 "${SM}/AGENTS.md"
CODEX_HOME="${SM}" "${ROOT}/install-codex.sh" >/dev/null 2>&1
[ "$(mode_of "${SM}/AGENTS.md")" = 640 ] \
  || { M="$(mode_of "${SM}/AGENTS.md")"; rm -rf "${SM}"; fail "codex install changed AGENTS.md mode to ${M}"; }
CODEX_HOME="${SM}" "${ROOT}/uninstall-codex.sh" >/dev/null 2>&1
[ "$(mode_of "${SM}/AGENTS.md")" = 640 ] \
  || { M="$(mode_of "${SM}/AGENTS.md")"; rm -rf "${SM}"; fail "codex uninstall changed AGENTS.md mode to ${M}"; }
grep -qxF '# my codex rules' "${SM}/AGENTS.md" \
  || { rm -rf "${SM}"; fail "codex install+uninstall lost the user's own line"; }
BK="$(find "${SM}" -maxdepth 1 -name 'AGENTS.md.bak.*' -print -quit)"
if [ -z "${BK}" ] || [ "$(mode_of "${BK}")" != 640 ]; then
  rm -rf "${SM}"
  fail "the AGENTS.md backup did not keep the file's mode"
fi
rm -rf "${SM}"

# a rewrite that cannot be written leaves the file it was going to replace
# exactly as it was: same bytes, same mode, no backup, nonzero exit
SM="$(mktemp -d)"
EXP="$(mktemp -d)"
printf '# my own rules\n@luciazero.md\n' > "${SM}/CLAUDE.md"
chmod 640 "${SM}/CLAUDE.md"
cp "${SM}/CLAUDE.md" "${EXP}/CLAUDE.md"
chmod 555 "${SM}"
ERR="$(CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/uninstall.sh" 2>&1 >/dev/null)" \
  && { chmod 755 "${SM}"; rm -rf "${SM}" "${EXP}"; fail "uninstall reported success with a config dir it cannot write"; }
chmod 755 "${SM}"
echo "${ERR}" | grep -q 'CLAUDE.md' \
  || { rm -rf "${SM}" "${EXP}"; fail "the failure did not come from the CLAUDE.md rewrite: ${ERR}"; }
cmp -s "${SM}/CLAUDE.md" "${EXP}/CLAUDE.md" \
  || { rm -rf "${SM}" "${EXP}"; fail "a failed rewrite changed CLAUDE.md"; }
[ "$(mode_of "${SM}/CLAUDE.md")" = 640 ] \
  || { M="$(mode_of "${SM}/CLAUDE.md")"; rm -rf "${SM}" "${EXP}"; fail "a failed rewrite changed CLAUDE.md mode to ${M}"; }
[ -z "$(find "${SM}" -maxdepth 1 -name 'CLAUDE.md.bak.*' -print -quit)" ] \
  || { rm -rf "${SM}" "${EXP}"; fail "a failed rewrite left a backup behind"; }
rm -rf "${SM}" "${EXP}"
echo "ok  instruction files keep their mode across install, uninstall and failure"
