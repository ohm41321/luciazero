---
name: show
description: Visualize code structure, changes, and verification evidence in the smallest useful view. Use for connections, flows, diffs, file maps, Mermaid diagrams, evidence maps, or focused HTML; show facts and label unknowns.
---

# Show

Answer at a glance: What connects to what? What changed? What proves it? Build
an evidence view, not a decorative diagram; source, diff, and command output
remain ground truth.

## 1. Set the focus

Use the request and repository context. Do not ask for details that can be
discovered from the repository. State the smallest boundary that answers the
question. Gather only:

- definitions, callers, consumers, configuration, and ownership;
- current diff or before/after revisions;
- verify command, exit code, decisive output, and coverage gaps.

Never expose private chain-of-thought. Show observable evidence and conclusions.

## 2. Normalize the evidence

Keep five kinds: **Entities**, **Relations**, **Changes**, **Proof**, and
**Gaps**. Label inference as `? inferred`; never draw a guessed edge as fact.

## 3. Choose the smallest useful view

Prefer the first form that carries the relationship clearly:

- decision → compact pseudocode;
- runtime calls → call tree;
- ownership → shallow tree;
- 3+ interacting parts → Mermaid flow/sequence;
- structural change → before/after diff;
- completion → requirement-to-proof map;
- clear prose → one sentence or short list.

Use one primary view. Add another only for a different question. Reserve focused
HTML for dense UI or interactive state. Keep HTML temporary unless the user asks
to keep it, and open it only with permission.

## 4. Render with a stable grammar

```text
A --> B             calls or moves data
A --owns--> B       named relation
+ / - / ~ item      added / removed / changed
[+] proven
[x] disproven
[?] unknown
[path/file:line]    source
```

Keep labels concrete and short. Omit unrelated detail. For Mermaid, keep node IDs
simple, quote punctuation-heavy labels, and put noisy source pointers outside.

## 5. Attach evidence

Every important node or edge must be traceable to source, a diff/revision, or
an exact command, exit code, and shortest decisive output. A green-looking view
is not verification. If no command ran, write `not run`. If proof misses a
claim, mark that claim `[?]` and name the gap; keep failed proof visible.

## Output contract

Return in order:

1. **Answer** — focus and conclusion in 1–2 sentences.
2. **View** — smallest useful visual.
3. **Sources** — compact file/line or revision pointers.
4. **Proof** — command, exit code, decisive output; or `not run`.
5. **Unknowns** — omit only when none exist.

## Fit into the Luciazero loop

Lifecycle skills own work and proof: `/ready` CI→verify, `/plan` boundary,
`/debug` hypothesis→observation, `/done` requirement→proof, and
`/lucia-relay` state→next action. The lifecycle skill owns the work and
verification. `/show` only exposes its structure.
