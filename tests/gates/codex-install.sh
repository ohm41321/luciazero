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
# v2.7.0 installed the agent as the skill `reviewer`: the agent file minus its
# Claude-only tools:/model: lines. Untouched (it matches its snapshot), it goes.
old_codex_reviewer() {
  mkdir -p "$1"
  grep -vE '^(tools|model): ' "${ROOT}/migrations/reviewer-v2.7.0.md" > "$1/SKILL.md"
}
old_codex_reviewer "${CX}/skills/reviewer"
old_codex_reviewer "${CX}/.luciazero-managed/skills/reviewer"

CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" >/dev/null
grep -q '^# Luciazero' "${CX}/AGENTS.md" || fail "doctrine not in AGENTS.md"
[ "$(grep -cF 'luciazero:start' "${CX}/AGENTS.md")" = 1 ] || fail "marker block not added"
while IFS= read -r NS; do
  [ -f "${CX}/skills/${NS}/SKILL.md" ] || fail "codex ${NS} skill not installed"
done < <(skill_inventory)
[ -x "${CX}/skills/ready/scripts/detect.sh" ] || fail "codex detect.sh not installed or not executable"
for HELPER in ready/scripts/detect.cjs done/scripts/revert-probe.cjs bisect/scripts/safe-bisect.cjs; do
  [ -x "${CX}/skills/${HELPER}" ] || fail "codex ${HELPER} not installed or not executable"
done
[ ! -e "${CX}/skills/luciazero-bootstrap" ] \
  || fail "codex install did not migrate the retired compatibility alias"
[ -x "${CX}/skills/done/scripts/revert-probe.sh" ] || fail "codex revert-probe.sh not installed or not executable"
[ -x "${CX}/skills/bisect/scripts/safe-bisect.sh" ] || fail "codex safe-bisect.sh not installed or not executable"
[ -x "${CX}/skills/lucia-relay/scripts/relay.py" ] || fail "codex relay.py not installed or not executable"
[ -f "${CX}/.luciazero-version" ] || fail "codex version sidecar not written"
[ -f "${CX}/skills/lucia-reviewer/SKILL.md" ] || fail "codex lucia-reviewer skill not installed"
[ ! -e "${CX}/skills/reviewer" ] || fail "codex install did not migrate the untouched v2.7.0 reviewer skill"
[ ! -e "${CX}/.luciazero-managed/skills/reviewer" ] \
  || fail "codex install left the retired reviewer skill's snapshot behind"
[ ! -d "${CX}/hooks" ] || fail "Claude-only hooks leaked into codex install"
grep -q '^name: lucia-reviewer$' "${CX}/skills/lucia-reviewer/SKILL.md" || fail "lucia-reviewer skill lost frontmatter"
! grep -q '^tools: ' "${CX}/skills/lucia-reviewer/SKILL.md" || fail "Claude-only tools: line leaked into codex skill"
! grep -q '^model: ' "${CX}/skills/lucia-reviewer/SKILL.md" || fail "Claude-only model: line leaked into codex skill"
grep -q 'pre-existing codex plan' "${CX}/.luciazero-backups"/skills/plan.bak.*/SKILL.md \
  || fail "codex install did not back up a colliding generic skill"

cp "${CX}/AGENTS.md" "${CX}/AGENTS.md.snap"
old_codex_reviewer "${CX}/skills/reviewer"
echo '# my own reviewer edits' >> "${CX}/skills/reviewer/SKILL.md"
CXOUT="$(CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" 2>&1 >/dev/null)"
grep -q 'my own reviewer edits' "${CX}/skills/reviewer/SKILL.md" \
  || fail "codex install deleted a customized v2.7.0 reviewer skill"
grep -qF 'skills/reviewer (renamed lucia-reviewer) is customized or not Luciazero-owned; left untouched' <<<"${CXOUT}" \
  || fail "codex install kept a customized reviewer skill without saying so: ${CXOUT}"
rm -rf "${CX}/skills/reviewer"
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
[ ! -d "${CX}/skills/lucia-reviewer" ] || fail "codex lucia-reviewer skill left behind"
# Output is matched from a here-string, never `echo | grep -q`: grep -q
# leaves at the first match, and under pipefail an echo still writing a
# long uninstall report into the closed pipe fails the check that passed.
grep -q 'not the exact Luciazero-managed copy; left untouched' <<<"${COUT}" \
  || fail "codex uninstall did not explain preserved customizations"
[ ! -f "${CX}/.luciazero-version" ] || fail "codex version sidecar left behind"
grep -qxF '# pre-existing codex rules' "${CX}/AGENTS.md" || fail "pre-existing AGENTS.md content damaged"
! grep -qF 'luciazero:start' "${CX}/AGENTS.md" || fail "marker block left behind"
echo "ok  codex uninstall restores AGENTS.md"

# An install this version never updated: its untouched v2.7.0 reviewer skill
# goes on uninstall, by its snapshot or, with none, by the shipped copy; one
# with neither proof is someone's skill and stays. An install with no
# snapshot migrates the untouched one by the shipped copy too.
for RV_CASE in snapshot shipped foreign; do
  RV="$(mktemp -d)"
  if [ "${RV_CASE}" = foreign ]; then
    mkdir -p "${RV}/skills/reviewer"
    printf 'a reviewer of my own\n' > "${RV}/skills/reviewer/SKILL.md"
  else
    old_codex_reviewer "${RV}/skills/reviewer"
  fi
  if [ "${RV_CASE}" = snapshot ]; then old_codex_reviewer "${RV}/.luciazero-managed/skills/reviewer"; fi
  CODEX_HOME="${RV}" "${ROOT}/uninstall-codex.sh" >/dev/null 2>&1 \
    || { rm -rf "${RV}"; fail "codex uninstall failed over a v2.7.0 reviewer (${RV_CASE})"; }
  if [ "${RV_CASE}" = foreign ]; then
    grep -qx 'a reviewer of my own' "${RV}/skills/reviewer/SKILL.md" \
      || { rm -rf "${RV}"; fail "codex uninstall deleted a foreign skills/reviewer"; }
  elif [ -e "${RV}/skills/reviewer" ] || [ -e "${RV}/.luciazero-managed" ]; then
    rm -rf "${RV}"; fail "codex uninstall left an untouched v2.7.0 reviewer behind (${RV_CASE})"
  fi
  rm -rf "${RV}"
done
RV="$(mktemp -d)"
old_codex_reviewer "${RV}/skills/reviewer"
CODEX_HOME="${RV}" "${ROOT}/install-codex.sh" >/dev/null 2>&1
[ ! -e "${RV}/skills/reviewer" ] \
  || { rm -rf "${RV}"; fail "codex install kept an untouched v2.7.0 reviewer that had no snapshot"; }
# The snapshot alone proves ownership: an older release's skill goes by it,
# and a snapshot that exists but differs is not overruled by the v2.7.0 copy.
old_codex_reviewer "${RV}/skills/reviewer"
echo '# an older release' >> "${RV}/skills/reviewer/SKILL.md"
mkdir -p "${RV}/.luciazero-managed/skills"
cp -R "${RV}/skills/reviewer" "${RV}/.luciazero-managed/skills/reviewer"
CODEX_HOME="${RV}" "${ROOT}/install-codex.sh" >/dev/null 2>&1
if [ -e "${RV}/skills/reviewer" ] || [ -e "${RV}/.luciazero-managed/skills/reviewer" ]; then
  rm -rf "${RV}"; fail "codex install kept an older reviewer that matched its snapshot"
fi
old_codex_reviewer "${RV}/skills/reviewer"
old_codex_reviewer "${RV}/.luciazero-managed/skills/reviewer"
echo '# an older release' >> "${RV}/.luciazero-managed/skills/reviewer/SKILL.md"
RV_OUT="$(CODEX_HOME="${RV}" "${ROOT}/install-codex.sh" 2>&1 >/dev/null)"
[ -f "${RV}/skills/reviewer/SKILL.md" ] \
  || { rm -rf "${RV}"; fail "codex install deleted a reviewer its snapshot did not match"; }
grep -qF 'skills/reviewer (renamed lucia-reviewer) is customized or not Luciazero-owned' <<<"${RV_OUT}" \
  || { rm -rf "${RV}"; fail "codex install kept a reviewer its snapshot did not match without saying so: ${RV_OUT}"; }
rm -rf "${RV}"
echo "ok  the v2.7.0 reviewer skill migrates to lucia-reviewer only when untouched"

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
grep -q 'symlinked parent' <<<"${OUT}" \
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
# both names: the cataloged agent and the one it was renamed from
printf 'sentinel\n' > "${SM}/outside-agents/lucia-reviewer.md"
printf 'sentinel\n' > "${SM}/outside-agents/reviewer.md"
ln -s "${SM}/outside-agents" "${SM}/.luciazero-managed/agents"
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/uninstall.sh" >/dev/null 2>&1 || true
if [ ! -f "${SM}/outside-agents/lucia-reviewer.md" ] || [ ! -f "${SM}/outside-agents/reviewer.md" ]; then
  rm -rf "${SM}"; fail "uninstall deleted through a symlinked agent-snapshot parent"
fi
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
  grep -q 'markers' <<<"${OUT}" \
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
grep -q 'CLAUDE.md' <<<"${ERR}" \
  || { rm -rf "${SM}" "${EXP}"; fail "the failure did not come from the CLAUDE.md rewrite: ${ERR}"; }
cmp -s "${SM}/CLAUDE.md" "${EXP}/CLAUDE.md" \
  || { rm -rf "${SM}" "${EXP}"; fail "a failed rewrite changed CLAUDE.md"; }
[ "$(mode_of "${SM}/CLAUDE.md")" = 640 ] \
  || { M="$(mode_of "${SM}/CLAUDE.md")"; rm -rf "${SM}" "${EXP}"; fail "a failed rewrite changed CLAUDE.md mode to ${M}"; }
[ -z "$(find "${SM}" -maxdepth 1 -name 'CLAUDE.md.bak.*' -print -quit)" ] \
  || { rm -rf "${SM}" "${EXP}"; fail "a failed rewrite left a backup behind"; }
rm -rf "${SM}" "${EXP}"
echo "ok  instruction files keep their mode across install, uninstall and failure"
