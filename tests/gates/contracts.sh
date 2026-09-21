# tests/gates/contracts.sh — skill and agent frontmatter, prompt word budgets and behavioral clauses, doctrine budget.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 4. skill + agent frontmatter: name + description drive discovery and auto-trigger
SKILL_DESC_WORDS=0
while IFS= read -r NAME; do
  SKILL="${ROOT}/skills/${NAME}/SKILL.md"
  head -1 "${SKILL}" | grep -qx -- '---' || fail "${NAME}/SKILL.md missing frontmatter"
  grep -q "^name: ${NAME}\$" "${SKILL}" || fail "${NAME}/SKILL.md missing 'name: ${NAME}'"
  grep -q '^description: .' "${SKILL}" || fail "${NAME}/SKILL.md missing description"
  DESC_WORDS="$(sed -n 's/^description:[[:space:]]*//p' "${SKILL}" | wc -w | tr -d '[:space:]')"
  [ "${DESC_WORDS}" -le 40 ] \
    || fail "${NAME}/SKILL.md description is ${DESC_WORDS} words (limit 40)"
  SKILL_DESC_WORDS=$((SKILL_DESC_WORDS + DESC_WORDS))
done < <(skill_inventory)
while IFS= read -r AGENT_NAME; do
  AGENT="${ROOT}/claude/agents/${AGENT_NAME}.md"
  head -1 "${AGENT}" | grep -qx -- '---' || fail "${AGENT_NAME}.md missing frontmatter"
  grep -q "^name: ${AGENT_NAME}\$" "${AGENT}" || fail "${AGENT_NAME}.md missing name"
  grep -q '^description: .' "${AGENT}" || fail "${AGENT_NAME}.md missing description"
  AGENT_DESC_WORDS="$(sed -n 's/^description:[[:space:]]*//p' "${AGENT}" | wc -w | tr -d '[:space:]')"
  [ "${AGENT_DESC_WORDS}" -le 40 ] \
    || fail "${AGENT_NAME}.md description is ${AGENT_DESC_WORDS} words (limit 40)"
  grep -q '^model: inherit$' "${AGENT}" || fail "${AGENT_NAME}.md must inherit the authoring model"
done < <(catalog "${ROOT}/claude/agents/catalog.txt")
cmp -s "${ROOT}/agents/reviewer.md" "${ROOT}/claude/agents/reviewer.md" \
  || fail "plugin agents/reviewer.md drifted from the classic reviewer source"
python3 - "${ROOT}" <<'PY' || fail "reviewer/ready prompt budget or contract drift"
import pathlib, re, sys

root = pathlib.Path(sys.argv[1])
reviewer = (root / "claude/agents/reviewer.md").read_text()
ready = (root / "skills/ready/SKILL.md").read_text()

def normalized(text):
    return " ".join(text.casefold().split())

def section_bodies(text, expected, strip_fences):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    if strip_fences:
        text = re.sub(r"(?ms)^(?:```|~~~).*?^(?:```|~~~)[ \t]*$", "", text)
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    matches = list(re.finditer(r"(?m)^## (.+?)[ \t]*$", text))
    names = [match.group(1) for match in matches]
    assert all(names.count(name) == 1 for name in expected), f"lost or duplicated sections: {expected}"
    indices = [names.index(name) for name in expected]
    assert indices == sorted(indices), f"sections out of order: {expected}"
    bodies = {"__intro__": text[:matches[0].start()] if matches else text}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        bodies[match.group(1)] = text[match.end():end]
    return bodies

def frontmatter(text, label, expected_name, expected_fields):
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.S)
    assert match, f"{label} lost frontmatter block"
    block = match.group(1)
    fields = {"name": expected_name, **expected_fields}
    for field, expected in fields.items():
        values = re.findall(rf"(?m)^{re.escape(field)}:[ \t]*(.+)$", block)
        assert values == [expected], f"{label} frontmatter {field} drift: {values}"
        assert not re.search(rf"(?m)^{re.escape(field)}:[ \t]*", text[match.end():]), \
            f"{label} has {field} outside frontmatter"
    descriptions = re.findall(r"(?m)^description:[ \t]*(.+)$", block)
    assert len(descriptions) == 1, f"{label} needs one frontmatter description"
    assert not re.search(r"(?m)^description:[ \t]*", text[match.end():]), \
        f"{label} has description outside frontmatter"
    return descriptions[0]

def validate(text, label, expected_name, expected_fields, expected, contracts, code_contracts, budget):
    prose = section_bodies(text, expected, strip_fences=True)
    raw = section_bodies(text, expected, strip_fences=False)
    prose["__description__"] = frontmatter(text, label, expected_name, expected_fields)
    for section, clauses in contracts.items():
        body = normalized(prose[section])
        missing = [clause for clause in clauses if normalized(clause) not in body]
        assert not missing, f"{label} {section} lost behavioral clauses: {missing}"
    for section, literal in code_contracts:
        assert literal in raw[section], f"{label} {section} lost code contract"
    assert len(text.split()) <= budget, f"{label} prompt is {len(text.split())} words (budget {budget})"

reviewer_sections = ("Route the search", "Evidence discipline", "Output")
reviewer_contracts = {
    "__description__": ("Prefer built-in review; otherwise use this agent independently.",),
    "__intro__": ("Refute the change; do not approve or praise it.",),
    "Route the search": (
        "rank risks by impact and reachability",
        "trace each changed trust boundary from external input to a sensitive sink",
        "identify the old observable shape, then search callers, consumers, fixtures, docs, serializers, migrations, and compatibility code",
        "prioritize error paths, state transitions, concurrency, resource cleanup, and material edge cases",
        "A changed test is suspect if it would still pass when the implementation is reverted.",
    ),
    "Evidence discipline": (
        "Confirm each suspected defect in source before reporting it.",
        "Never edit, commit, or push.", "Stay inside the diff's causal scope.",
        "Report every verified `blocker`/`major`; report at most three `minor` findings",
    ),
    "Output": ("output exactly `No findings.`",),
}
ready_sections = (
    "1. Detect", "2. Establish verification", "3. Add smoke tests only when absent",
    "4. Add only paying guardrails", "5. Record project knowledge", "6. Prove the loop",
)
ready_contracts = {
    "1. Detect": ("Run the bundled scan first", "CI config: use what CI runs."),
    "2. Establish verification": (
        "exit non-zero on failure and run unattended", "work offline without credentials, GPU, network, or secrets",
        "Run `verify` on every edit loop; run `verify-full` at closeout and before a PR.",
        "root full suite as fallback", "references/smart-verification.md",
        "ask first before offering exact-match", "Never commit this variable",
        "This setting caches CI truth; update it whenever CI's verify command changes.",
    ),
    "3. Add smoke tests only when absent": (
        "Add 3–6 small tests for catastrophic failures", "never the user's real data paths",
        "enforce a hard timeout and cleanup",
    ),
    "4. Add only paying guardrails": (
        "on Codex or another harness, put necessary constraints in AGENTS.md instead",
        "Never add a hook that deploys, pushes, deletes, or writes outside the repository.",
    ),
    "5. Record project knowledge": ("Every line becomes future context cost.",),
    "6. Prove the loop": ("Flake check", "Red check", "restore exactly that edit", "does not cover"),
}

reviewer_code = (("Output", "```\npath:line — severity — problem. Concrete fix.\n```"),)
ready_code = (("1. Detect", "```\n<this-skill-dir>/scripts/detect.sh <repo-root>\n```"),)
reviewer_fields = {"tools": "Read, Grep, Glob, Bash", "model": "inherit"}
validate(reviewer, "reviewer", "reviewer", reviewer_fields, reviewer_sections,
         reviewer_contracts, reviewer_code, 400)
validate(ready, "ready", "ready", {}, ready_sections, ready_contracts, ready_code, 1000)

def assert_rejected(text, label, expected_name, expected_fields, expected, contracts, code_contracts, budget):
    try:
        validate(text, label, expected_name, expected_fields, expected, contracts, code_contracts, budget)
    except AssertionError:
        return
    raise AssertionError(f"{label} validator accepted adversarial stuffing")

all_reviewer_clauses = " ".join(clause for clauses in reviewer_contracts.values() for clause in clauses)
reviewer_frame = ("---\nname: reviewer\n"
                  "description: Prefer built-in review; otherwise use this agent independently.\n"
                  "tools: Read, Grep, Glob, Bash\nmodel: inherit\n---\n")
reviewer_headings = "\n".join(f"## {section}" for section in reviewer_sections)
assert_rejected(reviewer_frame + reviewer_headings + f"\n<!-- {all_reviewer_clauses} -->",
                "reviewer comment bag", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
assert_rejected(reviewer_frame + reviewer_headings + f"\n```\n{all_reviewer_clauses}\n```",
                "reviewer code bag", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
wrong_section = (reviewer_frame + "\nRefute the change; do not approve or praise it.\n"
                 + f"## Route the search\n{all_reviewer_clauses}\n"
                 + "## Evidence discipline\n\n## Output\n```\npath:line — severity — problem. Concrete fix.\n```\n")
assert_rejected(wrong_section, "reviewer wrong-section bag", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
fenced_description = reviewer.replace(
    "description: Adversarial reviewer with general, security, and contract routes. Use for diffs or risky closeout. Prefer built-in review; otherwise use this agent independently. Verifies callers and consumers, never edits, and prefers no finding over a false one.\n",
    "",
).replace("# Reviewer\n", "```yaml\ndescription: moved outside frontmatter\n```\n\n# Reviewer\n")
assert_rejected(fenced_description, "reviewer fenced description", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
fenced_tools = reviewer.replace("tools: Read, Grep, Glob, Bash\n", "").replace(
    "# Reviewer\n", "```yaml\ntools: Read, Grep, Glob, Bash\n```\n\n# Reviewer\n",
)
assert_rejected(fenced_tools, "reviewer fenced tools", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
print(f"ok  prompt budgets (reviewer {len(reviewer.split())}/400; ready {len(ready.split())}/1000 words)")
PY
python3 "${ROOT}/scripts/check-skill-prompts.py" \
  || fail "remaining skill prompt budget or contract drift"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/skills/lucia-relay/scripts/relay.py" || fail "relay.py syntax"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT}/test_lucia_relay.py" >/dev/null \
  || fail "focused lucia-relay trust regressions"
echo "ok  focused lucia-relay trust regressions"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/scripts/check-skill-prompts.py" || fail "skill prompt checker syntax"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/eval/evidence.py" || fail "evidence.py syntax"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/eval/result_schema.py" || fail "result_schema.py syntax"
echo "ok  skill + agent frontmatter (descriptions ${SKILL_DESC_WORDS} words; max 40 each)"

# Routine edits with obvious scope/proof must not pay for planning/debugging
# ceremony. The descriptions are the auto-trigger contract exposed to agents.
grep -q 'skip routine edits with clear scope and proof' \
  "${ROOT}/skills/plan/SKILL.md" || fail "plan skill still auto-triggers on routine edits"
grep -q 'Not for routine obvious failures' "${ROOT}/skills/debug/SKILL.md" \
  || fail "debug skill still auto-triggers on a first obvious failure"
echo "ok  routine-task skill trigger boundaries"

# 4b. doctrine budget — loaded on every turn of every session; this enforces "stays short"
DOCTRINE_FILE="${ROOT}/claude/luciazero.md"
W="$(wc -w < "${DOCTRINE_FILE}" | tr -d ' ')"
[ "${W}" -le 420 ] || fail "doctrine is ${W} words (limit 420) — every line costs context on every turn; cut a word to add a word"
! grep -qi 'subagent' "${DOCTRINE_FILE}" || fail "doctrine uses Claude-only 'subagent' vocabulary; phrase platform-neutrally"
grep -q 'fastest relevant check' "${DOCTRINE_FILE}" \
  || fail "doctrine does not prefer targeted intermediate verification"
grep -q 'full verification once at closeout' "${DOCTRINE_FILE}" \
  || fail "doctrine does not reserve full verification for closeout"
echo "ok  doctrine budget (${W}/420 words)"
