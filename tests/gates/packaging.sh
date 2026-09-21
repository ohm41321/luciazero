# tests/gates/packaging.sh — READMEs, CI example, plugin manifests, plugin doctrine and double-install, installer options, npm package.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 4d5. the Thai README exists, cross-links, and stays structurally in sync
# with the English default (a silently rotten translation is worse than none)
[ -f "${ROOT}/README.th.md" ] || fail "README.th.md missing"
grep -q 'README.th.md' "${ROOT}/README.md" || fail "README.md lost its link to the Thai version"
grep -qF '](README.md)' "${ROOT}/README.th.md" || fail "README.th.md lost its link back to English"
EN_H="$(grep -c '^## ' "${ROOT}/README.md")"
TH_H="$(grep -c '^## ' "${ROOT}/README.th.md")"
[ "${EN_H}" -eq $((TH_H + 1)) ] \
  || fail "README section drift: ${EN_H} EN sections vs ${TH_H} TH (EN must be TH+1 for its ภาษาไทย pointer) — update README.th.md alongside README.md"
for README in "${ROOT}/README.md" "${ROOT}/README.th.md"; do
  grep -qF 'bash docs/assets/agent-bus-demo.sh' "${README}" \
    || fail "$(basename "${README}") lost the Agent Bus demo command"
  grep -qF 'lucia claude' "${README}" \
    || fail "$(basename "${README}") lost the Claude short-form Bus command"
  grep -qF 'lucia codex' "${README}" \
    || fail "$(basename "${README}") lost the Codex short-form Bus command"
  grep -qF "| \`/lucia-chat\` |" "${README}" \
    || fail "$(basename "${README}") lost lucia-chat from its skill table"
  grep -qF 'nudge ─►' "${README}" \
    || fail "$(basename "${README}") lost the nudge step from its Bus flow"
  # the review policy is one pass at most (skills/done/SKILL.md step 3); a
  # README that still promises two passes makes readers spawn two reviewers
  grep -qE 'two separate passes|separate passes|สองรอบ' "${README}" \
    && fail "$(basename "${README}") still promises two review passes; /done runs one at most"
  grep -qF 'docs/agent-bus.md#start-here' "${README}" \
    || fail "$(basename "${README}") lost its link to the one-time Bus setup"
  grep -qF 'docs/agent-bus.md#approvals' "${README}" \
    || fail "$(basename "${README}") lost its link to the Bus approval boundary"
  grep -qF 'SECURITY.md' "${README}" \
    || fail "$(basename "${README}") lost its link to the trust boundary"
done
grep -qF '**Agent Bus is beta, opt-in, and checkout only.**' "${ROOT}/README.md" \
  || fail "README.md no longer labels its Agent Bus demo checkout-only"
grep -qF '**Agent Bus เป็น beta แบบ opt-in และใช้ได้จาก checkout เท่านั้น**' "${ROOT}/README.th.md" \
  || fail "README.th.md no longer labels its Agent Bus demo checkout-only"
echo "ok  Thai README present + in sync"

# 4e. luciazero-ci example stays inert and shaped right
CI_EX="${ROOT}/examples/luciazero-ci.example.yml"
[ -f "${CI_EX}" ] || fail "examples/luciazero-ci.example.yml missing"
grep -q 'workflow_run' "${CI_EX}" || fail "luciazero-ci example lost its workflow_run trigger"
grep -q 'REPLACE-ME' "${CI_EX}" || fail "luciazero-ci example must ship with REPLACE-ME gates"
[ ! -e "${ROOT}/.github/workflows/luciazero-ci.yml" ] || fail "luciazero-ci example must not be active in this repo"
echo "ok  luciazero-ci example inert"

# 4f. plugin + marketplace manifests stay valid and point at real files
python3 - "${ROOT}" <<'PY' || fail "plugin/marketplace manifest check failed"
import json, os, sys
root = sys.argv[1]
ver = None
for line in open(os.path.join(root, "CHANGELOG.md")):
    if line.startswith("## [") and line[4].isdigit():
        ver = line.split("[", 1)[1].split("]", 1)[0]
        break
plug = json.load(open(os.path.join(root, ".claude-plugin", "plugin.json")))
assert plug["name"] == "luciazero", "plugin.json name"
assert plug["version"] == ver, f"plugin.json version {plug['version']} != CHANGELOG {ver}"
assert "agents" not in plug, "plugin must use default root agents/ discovery"
for p in [plug["skills"], plug["hooks"]]:
    assert os.path.exists(os.path.join(root, p)), f"plugin.json path missing: {p}"
assert os.path.isfile(os.path.join(root, "agents", "reviewer.md")), "default plugin reviewer missing"
mkt = json.load(open(os.path.join(root, ".claude-plugin", "marketplace.json")))
assert mkt["name"] == "luciazero" and mkt["owner"]["name"], "marketplace name/owner"
assert mkt["plugins"][0]["name"] == "luciazero", "marketplace plugin entry"
assert mkt["plugins"][0]["source"] == "./", "marketplace plugin source"
hooks = json.load(open(os.path.join(root, "claude", "hooks", "hooks.json")))
cmds = [h["command"]
        for entries in hooks["hooks"].values()
        for e in entries for h in e["hooks"]]
for sub in ("prompt", "skill-prompt", "bash-start", "edit", "bash",
            "bash-failure", "skill", "stop", "session", "doctrine"):
    assert any(c.endswith("luciazero-verify.sh " + sub) for c in cmds), f"hooks.json missing {sub} wiring"
for c in cmds:
    assert c.startswith("LUCIAZERO_CHANNEL=plugin ${CLAUDE_PLUGIN_ROOT}/"), \
        f"hook command must carry the plugin channel marker (double-install dedupe depends on it): {c}"
    rel = c.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1].rsplit(" ", 1)[0]
    assert os.access(os.path.join(root, rel), os.X_OK), f"hook script not executable: {rel}"
PY
echo "ok  plugin manifests valid + wired"

# 4g. plugin doctrine mode: emits the doctrine once, never twice
DCT="$(mktemp -d)"
OUT="$(CLAUDE_CONFIG_DIR="${DCT}" "${ROOT}/claude/hooks/luciazero-verify.sh" doctrine </dev/null)" \
  || fail "doctrine mode exited non-zero"
[ "${OUT}" = "$(cat "${ROOT}/claude/luciazero.md")" ] \
  || fail "doctrine mode output does not match claude/luciazero.md"
touch "${DCT}/luciazero.md"
OUT2="$(CLAUDE_CONFIG_DIR="${DCT}" "${ROOT}/claude/hooks/luciazero-verify.sh" doctrine </dev/null)" \
  || fail "doctrine mode (classic install present) exited non-zero"
[ -z "${OUT2}" ] || fail "doctrine mode must stay silent when a classic install exists (double-load)"
rm -rf "${DCT}"
echo "ok  plugin doctrine session context"

# 4g2. plugin/classic double-install: the plugin-channel copy stands down
# exactly when classic wiring exists (dedupe), and runs normally otherwise
DD="$(mktemp -d)"
DTMP="$(mktemp -d)"
mkdir -p "${DD}/hooks"
cp "${ROOT}/claude/hooks/luciazero-verify.sh" "${DD}/hooks/luciazero-verify.sh"
printf '{"hooks": {"x": "%s/hooks/luciazero-verify.sh"}}\n' "${DD}" > "${DD}/settings.json"
printf '{"cwd": "%s", "tool_input": {"file_path": "%s/a.py"}}' "${DD}" "${DD}" \
  | env TMPDIR="${DTMP}" CLAUDE_CONFIG_DIR="${DD}" LUCIAZERO_CHANNEL=plugin \
    "${ROOT}/claude/hooks/luciazero-verify.sh" edit \
  || fail "deduped plugin edit exited non-zero"
[ -z "$(ls -A "${DTMP}" 2>/dev/null)" ] \
  || fail "plugin copy must stand down when classic wiring exists (state was written)"
rm -f "${DD}/settings.json"
printf '{"cwd": "%s", "tool_input": {"file_path": "%s/a.py"}}' "${DD}" "${DD}" \
  | env TMPDIR="${DTMP}" CLAUDE_CONFIG_DIR="${DD}" LUCIAZERO_CHANNEL=plugin \
    "${ROOT}/claude/hooks/luciazero-verify.sh" edit \
  || fail "plugin edit (no classic wiring) exited non-zero"
[ -n "$(ls -A "${DTMP}" 2>/dev/null)" ] \
  || fail "plugin copy must run normally when classic wiring is absent"
rm -rf "${DD}" "${DTMP}"
echo "ok  plugin channel dedupe"

# 4g3. mutating installers reject unknown options instead of silently acting
# (pre-fix, `npx luciazero codex --status` performed a full install)
AR="$(mktemp -d)"
set +e
OUT_A="$(CODEX_HOME="${AR}/cx" bash "${ROOT}/install-codex.sh" --status 2>&1)"; RC_A=$?
OUT_B="$(CLAUDE_CONFIG_DIR="${AR}/cl" bash "${ROOT}/uninstall.sh" --force 2>&1)"; RC_B=$?
OUT_C="$(CODEX_HOME="${AR}/cx2" bash "${ROOT}/uninstall-codex.sh" -q 2>&1)"; RC_C=$?
set -e
{ [ "${RC_A}" -ne 0 ] && [ ! -e "${AR}/cx" ]; } \
  || fail "install-codex.sh must reject unknown options without installing (rc=${RC_A})"
printf '%s\n' "${OUT_A}" | grep -q 'unknown option' || fail "install-codex.sh rejection message missing"
[ "${RC_B}" -ne 0 ] || fail "uninstall.sh must reject unknown options (rc=${RC_B})"
printf '%s\n' "${OUT_B}" | grep -q 'unknown option' || fail "uninstall.sh rejection message missing"
[ "${RC_C}" -ne 0 ] || fail "uninstall-codex.sh must reject unknown options (rc=${RC_C})"
printf '%s\n' "${OUT_C}" | grep -q 'unknown option' || fail "uninstall-codex.sh rejection message missing"
rm -rf "${AR}"
echo "ok  installers reject unknown options"

# 4h. npm wrapper package: parseable, complete payload, no lifecycle scripts
python3 - "${ROOT}" <<'PY' || fail "package.json check failed"
import json, os, re, sys
root = sys.argv[1]
pkg = json.load(open(os.path.join(root, "package.json")))
assert pkg["name"] == "luciazero", "package name"
ver = None
for line in open(os.path.join(root, "CHANGELOG.md")):
    if line.startswith("## [") and line[4].isdigit():
        ver = line.split("[", 1)[1].split("]", 1)[0]
        break
assert pkg["version"] == ver, f"package.json version {pkg['version']} != CHANGELOG {ver}"
for bad in ("preinstall", "install", "postinstall", "prepare"):
    assert bad not in pkg.get("scripts", {}), f"lifecycle script '{bad}' forbidden (npm v12 blocks them; scanners flag them)"
assert not pkg.get("dependencies"), "npm wrapper must remain dependency-free"
files = set(pkg["files"])
for need in ("bin", "agents", "claude", "skills", "install.sh", "uninstall.sh",
             "install-codex.sh", "uninstall-codex.sh", "migrations"):
    assert need in files, f"files allowlist missing {need} — npx install would ship a broken payload"
assert "CHANGELOG.md" not in files, "release changelog must not inflate the npm runtime payload"
for base in ("bin", "agents", "claude", "skills", "migrations"):
    for directory, subdirs, names in os.walk(os.path.join(root, base)):
        assert "__pycache__" not in subdirs, f"npm payload contains Python cache dir: {directory}"
        assert not any(name.endswith((".pyc", ".pyo")) for name in names), \
            f"npm payload contains Python bytecode: {directory}"
with open(os.path.join(root, pkg["bin"]["luciazero"])) as f:
    assert f.readline().startswith("#!/usr/bin/env node"), "bin shebang"
assert os.access(os.path.join(root, pkg["bin"]["luciazero"]), os.X_OK), "bin must be executable"
shim = os.path.join(root, "bin", "luciazero-agentd")
assert os.access(shim, os.X_OK), "the agentd launcher must be executable"
with open(shim) as f:
    head = f.read(4096)
assert head.startswith("#!/bin/sh"), "the agentd launcher must be POSIX sh, not bash"
assert "luciazero-managed: agentd-launcher" in head, "the launcher must carry its ownership marker"
assert not any(line.lstrip().startswith("cd ") for line in head.splitlines()), \
    "the launcher must not change the caller's directory (attach records it)"
assert not any(re.match(r"\s*(export\s+)?PYTHONPATH=", line) for line in head.splitlines()), \
    "PYTHONPATH is colon-separated: a checkout path containing ':' would split into two entries"
def catalog(rel):
    return [x.strip() for x in open(os.path.join(root, rel)) if x.strip() and not x.lstrip().startswith("#")]
skills = catalog("skills/catalog.txt")
aliases = catalog("skills/aliases.txt")
agents = catalog("claude/agents/catalog.txt")
actual_skills = sorted(name for name in os.listdir(os.path.join(root, "skills"))
                       if os.path.isfile(os.path.join(root, "skills", name, "SKILL.md")))
actual_agents = sorted(os.path.splitext(name)[0] for name in os.listdir(os.path.join(root, "claude", "agents"))
                       if name.endswith(".md"))
assert sorted(skills + aliases) == actual_skills, \
    f"skill inventory drift: {skills + aliases} != {actual_skills}"
assert sorted(agents) == actual_agents, f"agent catalog drift: {agents} != {actual_agents}"
assert len(skills) == 13, f"expected 13 cataloged skills, found {len(skills)}"
assert aliases == [], f"unexpected compatibility aliases: {aliases}"
for metadata in ("package.json", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
    assert "13 skills" in open(os.path.join(root, metadata)).read(), f"{metadata} skill count drift"
for readme in ("README.md", "README.th.md"):
    # a translation that keeps the old count is worse than no translation:
    # README.th.md read "skill 12 ตัว" for a whole release after lucia-chat landed
    text = open(os.path.join(root, readme), encoding="utf-8").read()
    named = re.findall(r"(\d+) skills\b", text) + re.findall(r"skill (?:ทั้ง )?(\d+) ตัว", text)
    assert named, f"{readme} no longer names its skill count"
    drift = sorted({n for n in named if int(n) != len(skills)})
    assert not drift, f"{readme} names {drift} skills, the catalog has {len(skills)}"
    for command in ("npx luciazero@latest global-install", "luciazero global-status",
                    "luciazero global-uninstall"):
        assert command in text, f"{readme} lost the persistent CLI command: {command}"
publishing = open(os.path.join(root, "docs/publishing.md")).read()
assert "carries the 13 skills" in publishing, "publishing channel skill count drift"
release_workflow = open(os.path.join(root, ".github/workflows/release.yml")).read()
gate = release_workflow.find("- name: Validate release versions")
publish = release_workflow.find("- name: Publish GitHub Release")
assert 0 <= gate < publish, "release version gate must run before GitHub publishing"
gate_end = release_workflow.find("\n      - name:", gate + 1)
assert gate_end > gate, "release version gate boundary missing"
gate_block = release_workflow[gate:gate_end]
for token in ("RELEASE_TAG: ${{ github.ref_name }}", "package.json",
              ".claude-plugin/plugin.json", "CHANGELOG.md"):
    assert token in gate_block, f"release version gate missing {token}"
assert "\\d+\\.\\d+\\.\\d+" in gate_block, \
    "release version gate must skip the Unreleased changelog heading"
stage = release_workflow.find("scripts/stage-npm-package.sh")
npm_publish = release_workflow.find('npm publish "${PACKAGE_DIR}"')
assert 0 <= stage < npm_publish, "npm release must publish the English-README staging package"
show = open(os.path.join(root, "skills/show/SKILL.md")).read()
for contract in ("What connects to what?", "What changed?", "What proves it?", "exit code", "Unknowns"):
    assert contract in show, f"show skill missing output contract: {contract}"
imouto = open(os.path.join(root, "skills/imouto-mode/SKILL.md")).read()
imouto_normalized = " ".join(imouto.split())
for contract in ("Default: off", "on", "focus", "off", "work first", "non-romantic", "Never auto-trigger",
                 "tsundere", "care through useful action", "Never insult", "Never withhold"):
    assert contract in imouto_normalized, f"imouto-mode missing contract: {contract}"
assert "disable-model-invocation: true" in imouto, "imouto-mode must disable Claude model invocation"
imouto_meta = open(os.path.join(root, "skills/imouto-mode/agents/openai.yaml")).read()
assert "allow_implicit_invocation: false" in imouto_meta, "imouto-mode must be explicit-only"
PY
if command -v node >/dev/null 2>&1; then
  NP_GUARD="$(mktemp -d)"
  printf 'keep\n' > "${NP_GUARD}/sentinel"
  NRC=0
  "${ROOT}/scripts/stage-npm-package.sh" "${NP_GUARD}" >/dev/null 2>&1 || NRC=$?
  if [ "${NRC}" -ne 64 ] || ! grep -qx keep "${NP_GUARD}/sentinel"; then
    rm -rf "${NP_GUARD}"
    fail "npm staging accepted or changed a non-empty directory"
  fi
  rm -rf "${NP_GUARD}"

  NP_STAGE="$(mktemp -d)"
  NP_CACHE="$(mktemp -d)"
  NP_DIR="$(NPM_CONFIG_CACHE="${NP_CACHE}" \
    "${ROOT}/scripts/stage-npm-package.sh" "${NP_STAGE}")" \
    || { rm -rf "${NP_STAGE}" "${NP_CACHE}"; fail "npm staging script failed"; }
  NP_JSON="$(NPM_CONFIG_CACHE="${NP_CACHE}" npm pack "${NP_DIR}" --dry-run --json)" \
    || { rm -rf "${NP_STAGE}" "${NP_CACHE}"; fail "staged npm payload could not be packed"; }
  printf '%s' "${NP_JSON}" | python3 -c '
import json, os, sys
pkg = json.load(sys.stdin)[0]
paths = [item["path"] for item in pkg["files"]]
readmes = [path for path in paths if os.path.basename(path).upper().startswith("README")]
assert readmes == ["README.md"], f"staged npm README selection is ambiguous: {readmes}"
assert "README.th.md" not in paths, "Thai README leaked into staged npm package"
assert "CHANGELOG.md" not in paths, "changelog leaked into staged npm package"
for required in ("bin/luciazero.js", "bin/global.js", "bin/luciazero-agentd", "install.sh",
                 "install-codex.sh", "claude/luciazero.md"):
    assert required in paths, f"staged npm package lost {required}"
' || { rm -rf "${NP_STAGE}" "${NP_CACHE}"; fail "staged npm payload contract failed"; }
  NP_VERSION="$(node -p "require('${NP_DIR}/package.json').version")"
  NP_CLAUDE="$(mktemp -d)"
  NP_CODEX="$(mktemp -d)"
  CLAUDE_CONFIG_DIR="${NP_CLAUDE}" bash "${NP_DIR}/install.sh" >/dev/null \
    || { rm -rf "${NP_STAGE}" "${NP_CACHE}" "${NP_CLAUDE}" "${NP_CODEX}"; fail "staged Claude installer failed"; }
  CODEX_HOME="${NP_CODEX}" bash "${NP_DIR}/install-codex.sh" >/dev/null \
    || { rm -rf "${NP_STAGE}" "${NP_CACHE}" "${NP_CLAUDE}" "${NP_CODEX}"; fail "staged Codex installer failed"; }
  if [ "$(cat "${NP_CLAUDE}/.luciazero-version")" != "${NP_VERSION}" ] \
    || [ "$(cat "${NP_CODEX}/.luciazero-version")" != "${NP_VERSION}" ]; then
    rm -rf "${NP_STAGE}" "${NP_CACHE}" "${NP_CLAUDE}" "${NP_CODEX}"
    fail "staged installers lost the package version sidecar"
  fi
  rm -rf "${NP_CLAUDE}" "${NP_CODEX}"
  rm -rf "${NP_STAGE}" "${NP_CACHE}"
  echo "ok  npm staging selects README.md + trims docs + installs with version"

  NB="$(mktemp -d)"
  set +e
  NOUT="$(CLAUDE_CONFIG_DIR="${NB}" node "${ROOT}/bin/luciazero.js" --status 2>&1)"
  NRC=$?
  set -e
  [ "${NRC}" -eq 1 ] || fail "npx wrapper --status on empty config dir: want rc 1, got ${NRC}"
  printf '%s\n' "${NOUT}" | grep -q 'MISS' || fail "npx wrapper --status lost install.sh's MISS output"
  rm -rf "${NB}"

  # An explicit global install uses only a user-owned prefix and leaves a
  # durable command on PATH.  The npm process is a fixture here: this tests
  # the public CLI boundary without contacting the registry or this machine's
  # real npm configuration.
  GI="$(mktemp -d)"
  mkdir -p "${GI}/home" "${GI}/bin"
  cat > "${GI}/bin/npm" <<'SH'
#!/bin/sh
printf '%s\n' "$@" > "${LUCIAZERO_TEST_NPM_LOG}"
if [ "$1" = install ]; then
  [ "${LUCIAZERO_TEST_NPM_FAIL:-0}" != 1 ] || exit 42
  mkdir -p "$4/bin"
  printf '#!/bin/sh\n' > "$4/bin/luciazero"
  chmod +x "$4/bin/luciazero"
elif [ "$1" = uninstall ]; then
  rm -f "$4/bin/luciazero"
fi
exit 0
SH
  chmod +x "${GI}/bin/npm"
  printf '# user shell config\n' > "${GI}/home/.zshrc"
  chmod 0640 "${GI}/home/.zshrc"
  ( umask 077
    HOME="${GI}/home" SHELL=/bin/zsh LUCIAZERO_TEST_NPM_LOG="${GI}/npm.log" \
      PATH="${GI}/bin:${PATH}" node "${ROOT}/bin/luciazero.js" global-install --yes >/dev/null ) \
    || { rm -rf "${GI}"; fail "global-install --yes failed"; }
  printf '%s\n' install --global --prefix "${GI}/home/.local/npm" luciazero@latest \
    > "${GI}/want.log"
  cmp -s "${GI}/want.log" "${GI}/npm.log" \
    || { rm -rf "${GI}"; fail "global-install invoked npm with the wrong contract"; }
  grep -qF "export PATH=\"\$HOME/.local/npm/bin:\$PATH\"" "${GI}/home/.zshrc" \
    || { rm -rf "${GI}"; fail "global-install did not put its user-owned bin on zsh PATH"; }
  [ "$(stat -c '%a' "${GI}/home/.zshrc" 2>/dev/null || stat -f '%Lp' "${GI}/home/.zshrc")" = 640 ] \
    || { rm -rf "${GI}"; fail "global-install changed the shell config mode under a restrictive umask"; }
  FIRST_RC="$(cat "${GI}/home/.zshrc")"
  HOME="${GI}/home" SHELL=/bin/zsh LUCIAZERO_TEST_NPM_LOG="${GI}/npm.log" \
    PATH="${GI}/bin:${PATH}" node "${ROOT}/bin/luciazero.js" global-install --yes >/dev/null \
    || { rm -rf "${GI}"; fail "global-install reinstall failed"; }
  [ "$(cat "${GI}/home/.zshrc")" = "${FIRST_RC}" ] \
    || { rm -rf "${GI}"; fail "global-install duplicated or changed its PATH block on reinstall"; }
  GSTATUS="$(HOME="${GI}/home" SHELL=/bin/zsh node "${ROOT}/bin/luciazero.js" global-status)" \
    || { rm -rf "${GI}"; fail "global-status rejected the installed command"; }
  printf '%s\n' "${GSTATUS}" | grep -qF 'luciazero is installed globally' \
    || { rm -rf "${GI}"; fail "global-status omitted the installed state"; }
  HOME="${GI}/home" SHELL=/bin/zsh LUCIAZERO_TEST_NPM_LOG="${GI}/npm.log" \
    PATH="${GI}/bin:${PATH}" node "${ROOT}/bin/luciazero.js" global-uninstall --yes >/dev/null \
    || { rm -rf "${GI}"; fail "global-uninstall --yes failed"; }
  printf '%s\n' uninstall --global --prefix "${GI}/home/.local/npm" luciazero \
    > "${GI}/want.log"
  cmp -s "${GI}/want.log" "${GI}/npm.log" \
    || { rm -rf "${GI}"; fail "global-uninstall invoked npm with the wrong contract"; }
  ! grep -qF 'luciazero:start global-npm-path' "${GI}/home/.zshrc" \
    || { rm -rf "${GI}"; fail "global-uninstall left its PATH block behind"; }
  RC=0
  HOME="${GI}/home" SHELL=/bin/zsh node "${ROOT}/bin/luciazero.js" global-status >/dev/null 2>&1 || RC=$?
  [ "${RC}" -eq 1 ] \
    || { rm -rf "${GI}"; fail "global-status did not report the absent command (rc=${RC})"; }

  # A shell startup file is user code.  A symlink or a block whose bytes no
  # longer match ours is not authority to write, remove, or even run npm.
  rm -f "${GI}/npm.log" "${GI}/home/.zshrc"
  printf 'keep target\n' > "${GI}/target"
  ln -s "${GI}/target" "${GI}/home/.zshrc"
  RC=0
  HOME="${GI}/home" SHELL=/bin/zsh LUCIAZERO_TEST_NPM_LOG="${GI}/npm.log" \
    PATH="${GI}/bin:${PATH}" node "${ROOT}/bin/luciazero.js" global-install --yes >/dev/null 2>&1 || RC=$?
  if [ "${RC}" -ne 1 ] || [ -e "${GI}/npm.log" ] || ! grep -qxF 'keep target' "${GI}/target"; then
    rm -rf "${GI}"
    fail "global-install followed a shell-config symlink or ran npm after refusal"
  fi
  rm "${GI}/home/.zshrc"
  printf '%s\n' '# mine' '# luciazero:start global-npm-path' 'changed' \
    '# luciazero:end global-npm-path' > "${GI}/home/.zshrc"
  cp "${GI}/home/.zshrc" "${GI}/before"
  RC=0
  HOME="${GI}/home" SHELL=/bin/zsh LUCIAZERO_TEST_NPM_LOG="${GI}/npm.log" \
    PATH="${GI}/bin:${PATH}" node "${ROOT}/bin/luciazero.js" global-uninstall --yes >/dev/null 2>&1 || RC=$?
  if [ "${RC}" -ne 1 ] || [ -e "${GI}/npm.log" ] \
    || ! cmp -s "${GI}/before" "${GI}/home/.zshrc"; then
    rm -rf "${GI}"
    fail "global-uninstall changed a customized PATH block or ran npm after refusal"
  fi

  rm -f "${GI}/home/.zshrc" "${GI}/npm.log"
  RC=0
  HOME="${GI}/home" SHELL=/bin/zsh LUCIAZERO_TEST_NPM_LOG="${GI}/npm.log" \
    LUCIAZERO_TEST_NPM_FAIL=1 PATH="${GI}/bin:${PATH}" \
    node "${ROOT}/bin/luciazero.js" global-install --yes >/dev/null 2>&1 || RC=$?
  if [ "${RC}" -ne 1 ] || [ -e "${GI}/home/.zshrc" ]; then
    rm -rf "${GI}"
    fail "a failed npm install changed the shell config"
  fi

  rm -f "${GI}/npm.log"
  RC=0
  HOME="${GI}/home" SHELL=/bin/zsh LUCIAZERO_TEST_NPM_LOG="${GI}/npm.log" \
    PATH="${GI}/bin:${PATH}" node "${ROOT}/bin/luciazero.js" global-install </dev/null >/dev/null 2>&1 || RC=$?
  if [ "${RC}" -ne 1 ] || [ -e "${GI}/npm.log" ] || [ -e "${GI}/home/.zshrc" ]; then
    rm -rf "${GI}"
    fail "a non-interactive global install proceeded without --yes"
  fi
  rm -rf "${GI}"
  echo "ok  global npm install is explicit, user-owned, reversible, and shell-config safe"

  # Explicit update checks are deterministic under an injected registry
  # response. Merely requiring the module must never perform network or writes.
  UC="$(mktemp -d)"
  mkdir -p "${UC}/claude/hooks" "${UC}/codex"
  printf '1.9.0\n' > "${UC}/claude/.luciazero-version"
  printf '{"hooks":{"Stop":[{"hooks":[{"command":"%s/hooks/luciazero-verify.sh stop"}]}]}}\n' \
    "${UC}/claude" > "${UC}/claude/settings.json"
  printf '2.0.0\n' > "${UC}/codex/.luciazero-version"
  node - "${ROOT}" "${UC}" <<'JS' \
    || { rm -rf "${UC}"; fail "update helper unit checks failed"; }
const assert = require("node:assert");
const path = require("node:path");
const [root, fixture] = process.argv.slice(2);
const updater = require(path.join(root, "bin/update.js"));
const currentVersion = require(path.join(root, "package.json")).version;
const futureVersion = `${Number(currentVersion.split(".")[0]) + 1}.0.0`;

assert.strictEqual(updater.compareSemver("1.9.0", "2.0.0"), -1);
assert.strictEqual(updater.compareSemver("2.0.0", "2.0.0"), 0);
assert.strictEqual(updater.compareSemver("2.1.0", "2.0.0"), 1);
assert.strictEqual(updater.compareSemver("2.0.0-beta.2", "2.0.0-beta.10"), -1);
assert.strictEqual(updater.compareSemver("not-a-version", "2.0.0"), null);

const installations = updater.detectInstallations({
  claudeDir: path.join(fixture, "claude"),
  codexDir: path.join(fixture, "codex"),
});
assert.strictEqual(installations.length, 2);
assert.strictEqual(installations[0].channel, "claude-classic");
assert.strictEqual(installations[0].hooks, true, "dangling hook wiring must preserve hook mode");
assert.strictEqual(installations[1].channel, "codex");

const out = [];
const err = [];
(async () => {
  let requestedUrl = "";
  let requestSignal;
  const fetchedVersion = await updater.fetchLatestVersion({
    registry: "https://registry.example.test/npm/",
    fetch: async (url, options) => {
      requestedUrl = String(url);
      requestSignal = options.signal;
      return {ok: true, json: async () => ({version: futureVersion})};
    },
  });
  assert.strictEqual(fetchedVersion, futureVersion);
  assert.strictEqual(requestedUrl, "https://registry.example.test/npm/luciazero/latest");
  assert.ok(requestSignal instanceof AbortSignal, "registry request must carry an AbortSignal");
  await assert.rejects(
    updater.fetchLatestVersion({
      timeoutMs: 5,
      fetch: (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        });
      }),
    }),
    /timed out/
  );
  await assert.rejects(
    updater.fetchLatestVersion({fetch: async () => ({ok: false, status: 503})}),
    /HTTP 503/
  );
  await assert.rejects(
    updater.fetchLatestVersion({fetch: async () => ({ok: true, json: async () => ({version: "bad"})})}),
    /invalid version/
  );

  const rc = await updater.runCheck(["--json"], {
    detectInstallations: () => installations,
    fetchLatestVersion: async () => futureVersion,
    stdout: {write: (value) => out.push(String(value))},
    stderr: {write: (value) => err.push(String(value))},
  });
  assert.strictEqual(rc, 0);
  assert.strictEqual(err.join(""), "");
  const report = JSON.parse(out.join(""));
  assert.strictEqual(report.latestVersion, futureVersion);
  assert.strictEqual(report.cliUpdateAvailable, true);
  assert.strictEqual(report.updateAvailable, true);
  assert.deepStrictEqual(report.installations.map((item) => item.status), [
    "update-available", "update-available",
  ]);

  const malformedCheckOut = [];
  const malformedCheckRc = await updater.runCheck([], {
    detectInstallations: () => [{
      channel: "codex", configDir: fixture, installedVersion: "broken", versionFilePresent: true,
      hooks: false,
    }],
    fetchLatestVersion: async () => futureVersion,
    stdout: {write: (value) => malformedCheckOut.push(String(value))},
    stderr: {write: () => {}},
  });
  assert.strictEqual(malformedCheckRc, 0);
  assert.match(malformedCheckOut.join(""), /Cannot update installs with a malformed/);
  assert.doesNotMatch(malformedCheckOut.join(""), /Update detected classic\/Codex installs/);

  let spawnCount = 0;
  const downgradeErrors = [];
  const downgradeRc = updater.runUpdate([], {
    detectInstallations: () => [{
      channel: "codex", configDir: fixture, installedVersion: "99.0.0", hooks: false,
    }],
    spawnSync: () => { spawnCount += 1; return {status: 0}; },
    stdout: {write: () => {}},
    stderr: {write: (value) => downgradeErrors.push(String(value))},
  });
  assert.strictEqual(downgradeRc, 1);
  assert.strictEqual(spawnCount, 0, "an older updater must not overwrite a newer install");
  assert.match(downgradeErrors.join(""), /Refusing to downgrade Codex/);

  const malformedErrors = [];
  const malformedRc = updater.runUpdate([], {
    detectInstallations: () => [{
      channel: "codex", configDir: fixture, installedVersion: "broken", versionFilePresent: true,
      hooks: false,
    }],
    spawnSync: () => { spawnCount += 1; return {status: 0}; },
    stdout: {write: () => {}},
    stderr: {write: (value) => malformedErrors.push(String(value))},
  });
  assert.strictEqual(malformedRc, 1);
  assert.strictEqual(spawnCount, 0, "malformed version metadata must fail before writes");
  assert.match(malformedErrors.join(""), /version is malformed/);

  let legacySpawnCount = 0;
  const legacyRc = updater.runUpdate([], {
    detectInstallations: () => [{
      channel: "codex", configDir: fixture, installedVersion: null, versionFilePresent: false,
      hooks: false,
    }],
    spawnSync: () => { legacySpawnCount += 1; return {status: 0}; },
    stdout: {write: () => {}},
    stderr: {write: () => {}},
  });
  assert.strictEqual(legacyRc, 0, "legacy installs without a sidecar must remain updatable");
  assert.strictEqual(legacySpawnCount, 1);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
JS
  node "${ROOT}/bin/luciazero.js" check-update --help | grep -q 'never changes files' \
    || { rm -rf "${UC}"; fail "check-update CLI route/help missing"; }
  node "${ROOT}/bin/luciazero.js" update --help | grep -q 'preserves Claude hook mode' \
    || { rm -rf "${UC}"; fail "update CLI route/help missing"; }
  rm -rf "${UC}"

  # The updater repairs every detected channel, preserves both possible
  # classic modes, and refuses to turn "update" into a fresh install.
  UU="$(mktemp -d)"
  mkdir -p "${UU}/plain" "${UU}/hooks" "${UU}/codex" "${UU}/empty-claude" "${UU}/empty-codex"
  CLAUDE_CONFIG_DIR="${UU}/plain" "${ROOT}/install.sh" >/dev/null
  printf '1.0.0\n' > "${UU}/plain/.luciazero-version"
  printf '# customized doctrine\n' >> "${UU}/plain/luciazero.md"
  CLAUDE_CONFIG_DIR="${UU}/plain" CODEX_HOME="${UU}/empty-codex" \
    node "${ROOT}/bin/luciazero.js" update >/dev/null \
    || { rm -rf "${UU}"; fail "update failed for classic-without-hooks"; }
  [ ! -d "${UU}/plain/hooks" ] \
    || { rm -rf "${UU}"; fail "update enabled hooks for a no-hooks install"; }
  cmp -s "${UU}/plain/luciazero.md" "${ROOT}/claude/luciazero.md" \
    || { rm -rf "${UU}"; fail "update did not refresh the doctrine"; }
  grep -q 'customized doctrine' "${UU}/plain/.luciazero-backups"/luciazero.md.bak.* \
    || { rm -rf "${UU}"; fail "update overwrote a customized doctrine without backup"; }

  CLAUDE_CONFIG_DIR="${UU}/hooks" "${ROOT}/install.sh" --with-hooks >/dev/null
  CODEX_HOME="${UU}/codex" "${ROOT}/install-codex.sh" >/dev/null
  printf '1.0.0\n' > "${UU}/hooks/.luciazero-version"
  printf '1.0.0\n' > "${UU}/codex/.luciazero-version"
  printf '# stale hook\n' >> "${UU}/hooks/hooks/luciazero-verify.sh"
  UOUT="$(CLAUDE_CONFIG_DIR="${UU}/hooks" CODEX_HOME="${UU}/codex" \
    node "${ROOT}/bin/luciazero.js" update)" \
    || { rm -rf "${UU}"; fail "multi-channel update failed"; }
  cmp -s "${UU}/hooks/hooks/luciazero-verify.sh" "${ROOT}/claude/hooks/luciazero-verify.sh" \
    || { rm -rf "${UU}"; fail "update did not refresh a stale hook"; }
  PV="$(node -p "require('${ROOT}/package.json').version")"
  [ "$(cat "${UU}/hooks/.luciazero-version")" = "${PV}" ] \
    || { rm -rf "${UU}"; fail "Claude update did not refresh version sidecar"; }
  [ "$(cat "${UU}/codex/.luciazero-version")" = "${PV}" ] \
    || { rm -rf "${UU}"; fail "Codex update did not refresh version sidecar"; }
  printf '%s\n' "${UOUT}" | grep -q 'Claude classic + hooks' \
    || { rm -rf "${UU}"; fail "update output omitted detected hook mode"; }
  printf '%s\n' "${UOUT}" | grep -q 'Codex' \
    || { rm -rf "${UU}"; fail "update output omitted detected Codex install"; }
  RC=0
  CLAUDE_CONFIG_DIR="${UU}/empty-claude" CODEX_HOME="${UU}/empty-codex" \
    node "${ROOT}/bin/luciazero.js" update >/dev/null 2>&1 || RC=$?
  [ "${RC}" -eq 1 ] \
    || { rm -rf "${UU}"; fail "update without an installation must refuse (rc=${RC})"; }
  if [ -e "${UU}/empty-claude/.luciazero-version" ] \
    || [ -e "${UU}/empty-codex/.luciazero-version" ]; then
    rm -rf "${UU}"
    fail "update without an installation wrote files"
  fi
  rm -rf "${UU}"
  echo "ok  npm wrapper package + update/check routing"
else
  echo "ok  npm wrapper package (routing skipped: node not installed)"
fi
