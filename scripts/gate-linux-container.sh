#!/usr/bin/env bash
# Release gate item 5: install, upgrade and uninstall proved on a machine that
# is not the one this was developed on, and proved to leave the user's own
# configuration alone.
#
# Two ways to run it, and they answer slightly different questions.
#
#   ./scripts/gate-linux-container.sh
#       Installs nothing here: it starts a Debian container, clones this
#       checkout inside it, and runs the checks against a home that began
#       empty. Needs docker or podman. A container proves Linux; it does not
#       prove a second machine.
#
#   LUCIAZERO_GATE_HOME=/tmp/gate ./scripts/gate-linux-container.sh --inner
#       The same checks in the current shell, against the home you name. This
#       is the path to use on a real second machine, which is what the gate
#       actually asks for.
#
# Network footprint, stated exactly because the gate is about footprints:
#
#   * The container path ALWAYS uses the network. It pulls the image and runs
#     `apt-get update` and `apt-get install git python3 ca-certificates`
#     inside it, before any check begins.
#   * The --inner path makes no network call at all unless --from-origin is
#     passed, which clones from GitHub instead of from this checkout.
#
# No provider is ever started: the only launcher invocations are `--help` and
# a read command, neither of which reaches `cmd_run`.
#
# What each phase proves, and what it does not:
#
#   Phase 1, empty home. Install, read-only invocations, a SECOND install of
#     the SAME revision -- that is a reinstall, not an upgrade -- then
#     uninstall, then a comparison of the PATH MANIFEST of the home before and
#     after. Paths only: it catches a file or a directory left behind, and it
#     says nothing about the contents of a path that appears in both lists.
#   Phase 2, seeded home, legacy upgrade. A home carrying a CLAUDE.md and an
#     AGENTS.md that a user wrote. Install an older released revision, install
#     this one over it -- a real upgrade -- then uninstall both. The older
#     release left no record of adding its blank separator, so this uninstaller
#     will not remove it; what is asserted is that every line the user wrote
#     survives unchanged and the residue is at most one trailing blank line.
#   Phase 3, seeded home, this revision on both sides. Where the provenance
#     record exists, the bar is byte-identical, and that is what is compared.
set -euo pipefail

IMAGE="${LUCIAZERO_GATE_IMAGE:-debian:bookworm-slim}"
OLD_REF="${LUCIAZERO_GATE_OLD_REF:-v2.4.3}"
FROM_ORIGIN=0
INNER=0
for arg in "$@"; do
  case "${arg}" in
    --inner) INNER=1 ;;
    --from-origin) FROM_ORIGIN=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

fail() { printf 'gate5: %s\n' "$*" >&2; exit 1; }
ok() { printf '  ok  %s\n' "$*"; }

if [ "${INNER}" = 0 ]; then
  RUNTIME=""
  for candidate in docker podman; do
    if command -v "${candidate}" >/dev/null 2>&1; then RUNTIME="${candidate}"; break; fi
  done
  [ -n "${RUNTIME}" ] || fail "no docker or podman on this machine.
  Either install one, or run the checks directly on a second machine with:
    LUCIAZERO_GATE_HOME=/tmp/gate ./scripts/gate-linux-container.sh --inner"
  ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
  echo "gate5: ${RUNTIME} ${IMAGE}, source mounted read-only from ${ROOT}"
  echo "gate5: the container path uses the network (image pull + apt-get)"
  exec "${RUNTIME}" run --rm -i \
    -v "${ROOT}:/src:ro" \
    -e LUCIAZERO_GATE_HOME=/root/gatehome \
    -e LUCIAZERO_GATE_SRC=/src \
    -e LUCIAZERO_GATE_OLD_REF="${OLD_REF}" \
    -e LUCIAZERO_GATE_FROM_ORIGIN="${FROM_ORIGIN}" \
    "${IMAGE}" sh -c '
      set -eu
      apt-get update -qq >/dev/null
      apt-get install -y -qq git python3 ca-certificates >/dev/null
      exec bash /src/scripts/gate-linux-container.sh --inner'
fi

# ---------------------------------------------------------------- inner ----
# The installers below read their destination from the environment before they
# fall back to $HOME: CLAUDE_CONFIG_DIR and CODEX_HOME name the two config
# directories, LUCIAZERO_BIN_DIR the launcher directory, LUCIAZERO_SERVICE_ROOT
# the service root the uninstaller sweeps, and LUCIAZERO_AGENT_BUS_HOME the bus
# a read command opens. Every phase sets HOME, and HOME loses to all of them.
# So a shell that exports one -- an operator's own dotfile, a wrapper, a CI job
# -- sends these installs into the caller's real configuration, and the run
# still ends by reporting that nothing was written outside its own root. The
# gate is a claim about footprints; the environment it makes that claim in is
# its own to control, not the runbook's to remember.
unset CLAUDE_CONFIG_DIR CODEX_HOME LUCIAZERO_BIN_DIR LUCIAZERO_SERVICE_ROOT \
  LUCIAZERO_AGENT_BUS_HOME
GATE_ROOT="${LUCIAZERO_GATE_HOME:-}"
[ -n "${GATE_ROOT}" ] || fail "set LUCIAZERO_GATE_HOME to a directory this may install into.
  It must not be your real home: the point of this check is that a home which
  started clean ends clean."
WORK="${GATE_ROOT}/.gate-work"
CLONE="${WORK}/luciazero"

# A path handed in from outside is not disposable: `/tmp`, a workspace, or
# somebody else's home would all have passed a check that rejected only the
# empty string and $HOME.
case "${GATE_ROOT}" in
  /|//) fail "LUCIAZERO_GATE_HOME is the filesystem root; refusing" ;;
  /*) : ;;
  *) fail "LUCIAZERO_GATE_HOME must be an absolute path; got ${GATE_ROOT}" ;;
esac
[ "${GATE_ROOT}" != "${HOME}" ] || fail "LUCIAZERO_GATE_HOME is your real home; refusing"
case "${HOME}/" in
  "${GATE_ROOT}"/*) fail "LUCIAZERO_GATE_HOME contains your home directory; refusing" ;;
esac
# Nothing here deletes a path that came from outside this script, under any
# proof of ownership. A marker file is only evidence that something once wrote
# a marker file, and evidence is a poor thing to weigh a `rm -rf` against: a
# stray copy, a restored backup, or a symlink named like the marker would each
# have been enough. So the rule is the one that cannot go wrong -- the
# directory must not exist, and cleaning up an old run is the caller's to do
# and to see.
[ ! -e "${GATE_ROOT}" ] || fail "${GATE_ROOT} already exists.
  This script will not delete a directory it was handed. Point
  LUCIAZERO_GATE_HOME at a path that does not exist yet, or remove that one
  yourself once you have looked at what is in it."
mkdir -p "${WORK}"

command -v git >/dev/null 2>&1 || fail "git is not installed"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "python3 is older than 3.10; the daemon needs 3.10+"
ok "$(python3 --version) and $(git --version)"

if [ "${LUCIAZERO_GATE_FROM_ORIGIN:-0}" = 1 ]; then
  git clone --quiet https://github.com/ohm41321/luciazero.git "${CLONE}"
else
  git clone --quiet "${LUCIAZERO_GATE_SRC:-$(cd "$(dirname "$0")/.." && pwd -P)}" "${CLONE}"
fi
HEAD_REF="$(git -C "${CLONE}" rev-parse HEAD)"
ok "clone at ${HEAD_REF}"

# Paths only, and named so nobody reads more into it than that. Everything the
# run itself creates lives under .gate-work, which is pruned.
path_manifest() {
  find "$1" -path "${WORK}" -prune -o -print 2>/dev/null | sed "s|^$1||" | sort
}

# ------------------------------------------------------- phase 1: empty ----
H1="${GATE_ROOT}/home-empty"
mkdir -p "${H1}"
path_manifest "${H1}" > "${WORK}/p1-before.txt"

HOME="${H1}" "${CLONE}/install.sh" > "${WORK}/p1-install.log" 2>&1 \
  || fail "install.sh failed; see ${WORK}/p1-install.log"
ok "phase 1: install.sh into a home that started empty"

BIN="${H1}/.claude/bin"
for name in luciazero-agentd lucia; do
  [ -x "${BIN}/${name}" ] || fail "${name} not installed"
  grep -qF 'luciazero-managed: agentd-launcher' "${BIN}/${name}" \
    || fail "${name} carries no ownership marker"
done
[ "$(cat "${H1}/.claude/.luciazero-agentd-home")" = "${CLONE}/agentd" ] \
  || fail "package pointer does not name the clone"
ok "phase 1: both launcher names installed, marked, and pointed at the clone"

USAGE="$(cd / && HOME="${H1}" "${BIN}/lucia" claude --help)" || fail "lucia claude --help failed"
printf '%s' "${USAGE}" | grep -q '^usage: lucia claude' \
  || fail "lucia printed the long name back: ${USAGE}"
ok "phase 1: lucia claude --help runs from / and says 'lucia'"

BUS="${WORK}/bus"
SESS="$(cd / && HOME="${H1}" LUCIAZERO_AGENT_BUS_HOME="${BUS}" "${BIN}/lucia" sessions 2>&1)" \
  && fail "lucia sessions found a bus that never ran: ${SESS}"
printf '%s' "${SESS}" | grep -q 'no bus database' \
  || fail "lucia sessions failed for another reason: ${SESS}"
[ ! -e "${BUS}/bus.sqlite3" ] || fail "a read command created a bus database"
ok "phase 1: lucia sessions on an unused bus says so and creates nothing"

HOME="${H1}" "${CLONE}/install.sh" > "${WORK}/p1-reinstall.log" 2>&1 \
  || fail "the second install.sh failed; see ${WORK}/p1-reinstall.log"
ok "phase 1: install.sh is idempotent over the same revision (a reinstall, not an upgrade)"

HOME="${H1}" "${CLONE}/uninstall.sh" > "${WORK}/p1-uninstall.log" 2>&1 \
  || fail "uninstall.sh failed; see ${WORK}/p1-uninstall.log"
[ ! -e "${BIN}/luciazero-agentd" ] || fail "uninstall left the long launcher behind"
[ ! -e "${BIN}/lucia" ] || fail "uninstall left the short name behind"
[ ! -e "${H1}/.claude/.luciazero-agentd-home" ] || fail "uninstall left the package pointer behind"
ok "phase 1: uninstall.sh removed both names and the package pointer"

path_manifest "${H1}" > "${WORK}/p1-after.txt"
if ! diff -u "${WORK}/p1-before.txt" "${WORK}/p1-after.txt" > "${WORK}/p1-delta.txt"; then
  echo "gate5: phase 1: the home did not come back to what it was:" >&2
  cat "${WORK}/p1-delta.txt" >&2
  fail "uninstall left a footprint (delta above, also in ${WORK}/p1-delta.txt)"
fi
ok "phase 1: the home that started clean ended clean, path for path"

# ------------------------------------------------- phase 2: real upgrade ----
H2="${GATE_ROOT}/home-seeded"
mkdir -p "${H2}/.claude" "${H2}/.codex"
cat > "${H2}/.claude/CLAUDE.md" <<'SEED'
# My own instructions

Never touch this line.
SEED
cat > "${H2}/.codex/AGENTS.md" <<'SEED'
# My own codex instructions

Never touch this line either.
SEED
cp "${H2}/.claude/CLAUDE.md" "${WORK}/seed-claude.md"
cp "${H2}/.codex/AGENTS.md" "${WORK}/seed-codex.md"
SEED_CLAUDE="$(shasum -a 256 < "${H2}/.claude/CLAUDE.md")"
SEED_CODEX="$(shasum -a 256 < "${H2}/.codex/AGENTS.md")"
SEED_CLAUDE_BODY="$(awk '{ l[NR] = $0 } END { n = NR; while (n > 0 && l[n] == "") n--; for (i = 1; i <= n; i++) print l[i] }' "${H2}/.claude/CLAUDE.md" | shasum -a 256)"
SEED_CODEX_BODY="$(awk '{ l[NR] = $0 } END { n = NR; while (n > 0 && l[n] == "") n--; for (i = 1; i <= n; i++) print l[i] }' "${H2}/.codex/AGENTS.md" | shasum -a 256)"

git -C "${CLONE}" rev-parse --verify --quiet "${OLD_REF}" >/dev/null \
  || fail "no ref ${OLD_REF} in the clone; set LUCIAZERO_GATE_OLD_REF to a released tag"
git -C "${CLONE}" -c advice.detachedHead=false checkout --quiet "${OLD_REF}"
HOME="${H2}" "${CLONE}/install.sh" > "${WORK}/p2-old.log" 2>&1 \
  || fail "install.sh at ${OLD_REF} failed; see ${WORK}/p2-old.log"
HOME="${H2}" "${CLONE}/install-codex.sh" > "${WORK}/p2-old-codex.log" 2>&1 \
  || fail "install-codex.sh at ${OLD_REF} failed; see ${WORK}/p2-old-codex.log"
ok "phase 2: installed the older released revision ${OLD_REF}"

git -C "${CLONE}" -c advice.detachedHead=false checkout --quiet "${HEAD_REF}"
HOME="${H2}" "${CLONE}/install.sh" > "${WORK}/p2-new.log" 2>&1 \
  || fail "the upgrading install.sh failed; see ${WORK}/p2-new.log"
HOME="${H2}" "${CLONE}/install-codex.sh" > "${WORK}/p2-new-codex.log" 2>&1 \
  || fail "the upgrading install-codex.sh failed; see ${WORK}/p2-new-codex.log"
ok "phase 2: upgraded ${OLD_REF} -> ${HEAD_REF} in place"

HOME="${H2}" "${CLONE}/uninstall-codex.sh" > "${WORK}/p2-uninstall-codex.log" 2>&1 \
  || fail "uninstall-codex.sh failed; see ${WORK}/p2-uninstall-codex.log"
HOME="${H2}" "${CLONE}/uninstall.sh" > "${WORK}/p2-uninstall.log" 2>&1 \
  || fail "uninstall.sh failed; see ${WORK}/p2-uninstall.log"

# An upgrade FROM a release that left no provenance record cannot end
# byte-identical, and deliberately so: v2.4.3's install.sh appended a blank
# separator without recording that it had, so this uninstaller cannot prove
# the blank is its own and refuses to remove it. What must still hold is that
# every line the user wrote survives unchanged and nothing of theirs is
# dropped, and that the residue is at most one trailing blank line.
body() { awk '{ l[NR] = $0 } END { n = NR; while (n > 0 && l[n] == "") n--; for (i = 1; i <= n; i++) print l[i] }' "$1"; }
for pair in ".claude/CLAUDE.md:${SEED_CLAUDE_BODY}" ".codex/AGENTS.md:${SEED_CODEX_BODY}"; do
  file="${H2}/${pair%%:*}"
  [ -f "${file}" ] || fail "${pair%%:*} was deleted; the user wrote it"
  [ "$(body "${file}" | shasum -a 256)" = "${pair#*:}" ] \
    || fail "${pair%%:*} lost or changed a line the user wrote; it now reads:
$(cat "${file}")"
  extra=$(( $(wc -l < "${file}") - $(body "${file}" | wc -l) ))
  [ "${extra}" -le 1 ] || fail "${pair%%:*} grew ${extra} trailing blank lines, not at most one"
  printf '  ok  phase 2: %s kept every line the user wrote (%s trailing blank line left by the pre-provenance release)\n' \
    "${pair%%:*}" "${extra}"
done

# Same home shape, but installed and uninstalled by THIS revision on both
# sides, which is where the provenance record exists and byte-identical is the
# bar.
H3="${GATE_ROOT}/home-seeded-current"
mkdir -p "${H3}/.claude" "${H3}/.codex"
cp "${WORK}/seed-claude.md" "${H3}/.claude/CLAUDE.md"
cp "${WORK}/seed-codex.md" "${H3}/.codex/AGENTS.md"
HOME="${H3}" "${CLONE}/install.sh" > "${WORK}/p3-install.log" 2>&1 \
  || fail "install.sh failed on the seeded home; see ${WORK}/p3-install.log"
HOME="${H3}" "${CLONE}/install-codex.sh" > "${WORK}/p3-install-codex.log" 2>&1 \
  || fail "install-codex.sh failed on the seeded home; see ${WORK}/p3-install-codex.log"
HOME="${H3}" "${CLONE}/uninstall-codex.sh" > "${WORK}/p3-uninstall-codex.log" 2>&1 \
  || fail "uninstall-codex.sh failed; see ${WORK}/p3-uninstall-codex.log"
HOME="${H3}" "${CLONE}/uninstall.sh" > "${WORK}/p3-uninstall.log" 2>&1 \
  || fail "uninstall.sh failed; see ${WORK}/p3-uninstall.log"
[ "$(shasum -a 256 < "${H3}/.claude/CLAUDE.md")" = "${SEED_CLAUDE}" ] \
  || fail "CLAUDE.md is not byte-identical after this revision installed and uninstalled it:
$(diff "${WORK}/seed-claude.md" "${H3}/.claude/CLAUDE.md" || true)"
ok "phase 3: CLAUDE.md is byte-identical after this revision installed and uninstalled it"
# AGENTS.md is deliberately weaker, and the asymmetry is the point rather than
# an oversight. `uninstall.sh` may remove its blank separator because
# `install.sh` records that it added one and hashes the file it left;
# `uninstall-codex.sh` has no such record, so it removes the block and leaves
# the separator, and a cycle costs one blank line. Deleting it without proof
# would risk a blank line of the user's, which is the worse failure.
[ "$(body "${H3}/.codex/AGENTS.md" | shasum -a 256)" = "${SEED_CODEX_BODY}" ] \
  || fail "AGENTS.md lost or changed a line the user wrote; it now reads:
$(cat "${H3}/.codex/AGENTS.md")"
extra=$(( $(wc -l < "${H3}/.codex/AGENTS.md") - $(body "${H3}/.codex/AGENTS.md" | wc -l) ))
[ "${extra}" -le 1 ] || fail "AGENTS.md grew ${extra} trailing blank lines, not at most one"
printf '  ok  phase 3: AGENTS.md kept every line the user wrote (%s trailing blank line; the codex side has no ownership record yet)\n' "${extra}"

printf '\nGATE 5 GREEN on %s -- no provider started, nothing written outside %s\n' \
  "$(uname -s -m)" "${GATE_ROOT}"
