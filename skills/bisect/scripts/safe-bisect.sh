#!/usr/bin/env bash
# Locate a first bad commit in a detached temporary worktree. The caller's
# branch, index, and untracked files are never checked out or mutated.
set -u

usage() {
  echo "usage: safe-bisect.sh --good REV --bad REV [--retries N] -- COMMAND [ARG ...]" >&2
  exit 64
}

GOOD=""
BAD=""
RETRIES=2
while [ "$#" -gt 0 ]; do
  case "$1" in
    --good) [ "$#" -ge 2 ] || usage; GOOD="$2"; shift 2 ;;
    --bad) [ "$#" -ge 2 ] || usage; BAD="$2"; shift 2 ;;
    --retries) [ "$#" -ge 2 ] || usage; RETRIES="$2"; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done
[ -n "${GOOD}" ] && [ -n "${BAD}" ] && [ "$#" -gt 0 ] || usage
case "${RETRIES}" in ''|*[!0-9]*|0) usage ;; esac

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "safe-bisect: not inside a git repository" >&2
  exit 69
}
GOOD_SHA="$(git -C "${REPO}" rev-parse --verify "${GOOD}^{commit}" 2>/dev/null)" || {
  echo "safe-bisect: good revision is not a commit: ${GOOD}" >&2
  exit 65
}
BAD_SHA="$(git -C "${REPO}" rev-parse --verify "${BAD}^{commit}" 2>/dev/null)" || {
  echo "safe-bisect: bad revision is not a commit: ${BAD}" >&2
  exit 65
}
git -C "${REPO}" merge-base --is-ancestor "${GOOD_SHA}" "${BAD_SHA}" 2>/dev/null || {
  echo "safe-bisect: good revision must be an ancestor of bad revision" >&2
  exit 65
}

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/luciazero-bisect.XXXXXX")" || exit 70
WORKTREE="${TMP_ROOT}/worktree"
RUNNER="${TMP_ROOT}/run-criterion.sh"
BISECT_ACTIVE=0
WORKTREE_ADDED=0

cleanup() {
  if [ "${BISECT_ACTIVE}" = 1 ] && [ -d "${WORKTREE}" ]; then
    git -C "${WORKTREE}" bisect reset >/dev/null 2>&1 || true
  fi
  if [ "${WORKTREE_ADDED}" = 1 ]; then
    git -C "${REPO}" worktree remove --force "${WORKTREE}" >/dev/null 2>&1 || true
  fi
  find "${TMP_ROOT}" -depth -delete >/dev/null 2>&1 || true
  git -C "${REPO}" worktree prune >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

git -C "${REPO}" worktree add --detach "${WORKTREE}" "${BAD_SHA}" >/dev/null 2>&1 || {
  echo "safe-bisect: could not create temporary worktree" >&2
  exit 70
}
WORKTREE_ADDED=1

# Keep the runner outside the bisected tree so old revisions cannot replace it.
{
  printf '%s\n' '#!/usr/bin/env bash' '"$@"' 'rc=$?'
  printf '%s\n' 'git reset --hard -q HEAD >/dev/null 2>&1 || true' 'git clean -ffdqx >/dev/null 2>&1 || true'
  printf '%s\n' 'case "${rc}" in 126|127) echo "safe-bisect: verify command is missing or not executable" >&2; exit 128 ;; *) exit "${rc}" ;; esac'
} > "${RUNNER}"
chmod +x "${RUNNER}"

sample_endpoint() { # sample_endpoint REV expected-label COMMAND...
  REV="$1"; EXPECT="$2"; shift 2
  git -C "${WORKTREE}" checkout --detach --quiet "${REV}" || return 70
  I=1
  while [ "${I}" -le "${RETRIES}" ]; do
    (cd "${WORKTREE}" && "${RUNNER}" "$@") >/dev/null 2>&1
    RC=$?
    if [ "${RC}" -ge 128 ] || [ "${RC}" -eq 125 ]; then
      echo "safe-bisect: ${EXPECT} endpoint could not be evaluated (exit ${RC})" >&2
      return 66
    fi
    if [ "${EXPECT}" = good ] && [ "${RC}" -ne 0 ]; then
      echo "safe-bisect: known-good endpoint failed on sample ${I}; criterion is unstable or the endpoint is wrong" >&2
      return 67
    fi
    if [ "${EXPECT}" = bad ] && [ "${RC}" -eq 0 ]; then
      echo "safe-bisect: known-bad endpoint passed on sample ${I}; criterion is unstable or the endpoint is wrong" >&2
      return 67
    fi
    I=$((I + 1))
  done
}

sample_endpoint "${GOOD_SHA}" good "$@" || exit $?
sample_endpoint "${BAD_SHA}" bad "$@" || exit $?
git -C "${WORKTREE}" checkout --detach --quiet "${BAD_SHA}" || exit 70

git -C "${WORKTREE}" bisect start "${BAD_SHA}" "${GOOD_SHA}" >/dev/null || exit 70
BISECT_ACTIVE=1
set +e
BISECT_OUT="$(git -C "${WORKTREE}" bisect run "${RUNNER}" "$@" 2>&1)"
BISECT_RC=$?
set -e
printf '%s\n' "${BISECT_OUT}"
[ "${BISECT_RC}" -eq 0 ] || {
  echo "safe-bisect: git bisect could not identify a unique first bad commit (exit ${BISECT_RC})" >&2
  exit "${BISECT_RC}"
}

# `git bisect run` may leave HEAD at the last tested good revision. The bad
# ref is the authoritative result after a successful run.
FIRST_BAD="$(git -C "${WORKTREE}" rev-parse refs/bisect/bad)" || exit 70
SUMMARY="$(git -C "${WORKTREE}" show -s --format='%h %an — %s' "${FIRST_BAD}")"
echo "FIRST_BAD ${FIRST_BAD}"
echo "SUMMARY ${SUMMARY}"
