---
name: show
description: Visualize code structure, changes, and verification evidence in the smallest useful view. Use for connections, flows, diffs, file maps, Mermaid diagrams, evidence maps, or focused HTML; show facts and label unknowns.
---

# Show — make the evidence visible

Answer three questions at a glance:

1. What connects to what?
2. What changed?
3. What proves it?

Build an evidence view, not a decorative diagram. The view summarizes reality;
source files, diffs, and command results remain the ground truth.

## 1. Set the focus

Use the user's question and current task context as the input. Do not ask for
details that can be discovered from the repository. Narrow broad requests to
the smallest boundary that answers the question, and state that boundary.

Gather only the relevant evidence:

- definitions, callers, consumers, configuration, and ownership;
- the current diff or before/after revisions;
- verification command, exit code, shortest decisive output, and coverage gaps.

Never expose private chain-of-thought. Show observable structure, evidence, and
concise conclusions instead.

## 2. Normalize the evidence

Reduce what was found to five kinds of information:

- **Entities** — files, functions, components, services, states, or commands;
- **Relations** — calls, owns, reads, writes, emits, depends on, or verifies;
- **Changes** — added, removed, or modified entities and relations;
- **Proof** — commands and observations that confirm or refute a claim;
- **Gaps** — unknown, inferred, or unverified parts.

Label inference as `? inferred`; never draw a guessed edge as fact.

## 3. Choose the smallest useful view

Prefer the first form that carries the relationship clearly:

| Question | View |
|---|---|
| What does this logic decide? | Compact pseudocode |
| Who calls what at runtime? | Call tree |
| Who owns or contains what? | Component or shallow file tree |
| How do 3+ parts exchange control or data? | Mermaid flow or sequence |
| What changed structurally? | Before/after structural diff |
| Why is this considered complete? | Requirement-to-proof evidence map |
| Is prose already clearer? | One sentence or a short list; draw nothing |

Use one primary view. Add a second only when it answers a different question.
Use focused HTML only for dense UI, layout, or interactive state that text and
Mermaid cannot show clearly. Keep HTML temporary unless the user asks to keep
it, and open it only when the harness and user permissions allow.

## 4. Render with a stable grammar

Use these marks consistently in text views:

```text
A --> B              calls or moves data to
A --owns--> B        named relationship
+ item               added
- item               removed
~ item               changed
[+] proven           verification passed
[x] disproven        verification failed
[?] unknown          not verified
[path/to/file:line]  source pointer
```

Keep labels concrete and short. Omit unrelated files, helper calls, props,
states, and branches. A reader should not need a legend beyond the grammar
above.

For Mermaid, keep node IDs simple, quote labels containing punctuation, and
put source pointers outside the diagram when they would make nodes noisy.

## 5. Attach evidence

Every important node or edge must be traceable to at least one of:

- `path/to/file:line` for source structure;
- a diff hunk or revision for a change;
- an exact command, exit code, and shortest decisive output for proof.

Do not use a green-looking diagram as verification. If no command ran, write
`not run`. If a check does not cover a shown claim, mark that claim `[?]` and
name the missing coverage. Failed proof remains visible as `[x]`; do not hide it
to make the view look complete.

## Output contract

Return, in this order:

1. **Answer** — one or two sentences naming the focus and conclusion.
2. **View** — the smallest useful visual.
3. **Sources** — compact file/line or revision pointers.
4. **Proof** — command, exit code, and decisive output; or `not run`.
5. **Unknowns** — uncovered or inferred parts; omit only when there are none.

For a completed change, an evidence map may look like:

```text
request
  --> ~ skills/catalog.txt
  --> + skills/show/SKILL.md
  --> ~ README.md / README.th.md
        |
        +--verified by--> [+] ./test.sh (exit 0)
                           `PASS  all checks green`

[?] Real invocation in a fresh agent session was not exercised.
```

## Fit into the Luciazero loop

- With `/ready`, show the path from CI to the repository verify command.
- With `/plan`, show the proposed before/after boundary and acceptance proof.
- With `/debug`, show hypothesis → observation → conclusion without replacing
  the reproduction or hypothesis ledger.
- With `/done`, show requirement → changed artifact → verification evidence.
- With `/lucia-relay`, show current state → next action → blocker.

The lifecycle skill owns the work and verification. `/show` only makes its
structure and evidence easier to inspect.
