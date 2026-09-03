# ADR 0003: Agent Bus Git isolation, approval provenance, and threat model

Status: accepted 2026-09-03 for milestone M3

## Context

After M2 the bus can carry tasks, messages, and artifact references between
Codex and Claude sessions, but nothing ties a worker to the place it writes,
nothing stops two workers from editing the same checkout, an artifact
reference is an unchecked string, and a message can say "approved" without
that meaning anything. Before the pull beta runs real work (M4), the daemon
needs rules that hold even when an agent is confused, stale, or fed a
manipulated message.

## Decision

### One worktree per writing worker, read by the daemon

- An agent that writes code calls `worktree_bind` with an absolute path. The
  daemon runs `git` itself and records the toplevel (real path), the
  repository identity (the sorted root commit ids), the branch, HEAD, the
  base commit, and whether the tree is dirty. The agent never supplies those
  values.
- The toplevel is unique across agents. A path another agent holds is
  refused, including through a symlink or a subdirectory, so concurrent
  writers never share a worktree. Rebinding your own record is an upsert.
- Detached HEAD, a directory that is not a git worktree, an empty repository,
  a relative or over-long path, and a path carrying a secret shape are
  refused at bind time.
- Rebinding to a different toplevel or repository while holding claimed
  `requires_worktree` tasks is refused: finish or block them first. The
  `worktree.bound` event records the previous path.
- Before every `task_claim` and `artifact_publish` the daemon re-reads the
  bound worktree. A different toplevel, a different repository identity, a
  different branch, or a path that no longer works refuses the operation with
  `WorktreeMismatch` and records a `worktree.mismatch` event. HEAD and the
  dirty flag are refreshed on success; they may change freely because that is
  the worker doing its job.
- A task created with `requires_worktree` cannot be claimed without a bound
  worktree. Tasks without it (review, reading) can. `task_complete` with
  `blocked` always works, so a worker whose worktree vanished can still report.
- The re-read happens before the write transaction so a slow `git` never
  holds the SQLite write lock. The gap between the check and the commit is
  accepted under the threat model below.

### Artifact references are contained

- `commit` refs are full 40- or 64-hex object ids that must exist in the
  producer's bound worktree. Branch names, short ids, and URLs are refused.
- Every other kind (`patch`, `report`, `log`, `relay`) is a path relative to
  the bound worktree. Absolute paths, `~`, empty, `.` and `..` segments, any
  component spelled `.git` in any case or at any depth, any component that
  is the worktree's git dir or common dir by inode (so `.GIT` on a
  case-insensitive filesystem and linked-worktree layouts are covered), a
  symlink at any component (even one that stays inside), a path whose real
  location leaves the worktree, a missing or non-regular file, and files
  over 32 MiB are refused with `UnsafeReference`.
- The daemon computes the file's sha256 and stores it. A caller-supplied
  digest must match; a mismatch is refused. `commit` refs carry no digest
  at all: the object id is the digest, and a caller-supplied one is refused.
- An artifact ref (file name) or the file's content carrying a strict secret
  shape (approval nonce, bearer credential, platform token, private key, URL
  userinfo, the daemon token) is refused, because a path or a file cannot be
  scrubbed without breaking it. The heuristic `key = value` tier never
  refuses an artifact, so ordinary source code in a patch publishes.
- Any `scheme://user:secret@host` string inside a message, task, or result
  payload is refused, not scrubbed: a peer that needs a repository fetches
  it with its own credentials.

### Approval provenance

Sensitive operations are a fixed set: `delete`, `deploy`, `production`,
`spend`, `force_push`, `public_contract`, `scope_expansion`.

- No MCP tool can create an approval. The tool list carries exactly one
  approval tool, `approval_consume`, and the security suite asserts that no
  handler references `grant_approval`.
- An agent `decision` message is a recommendation only. The `/lucia-bus`
  skill and the server `instructions` say so, and the daemon enforces it by
  never reading consent from a message.
- The human channel is `python3 -m luciazero_agentd approve TASK OPERATION`.
  It refuses to run without an interactive terminal on both stdin and stdout,
  shows the task and its claim holder, asks once, and writes the store
  directly. It never goes through the agent-facing HTTP endpoint, so the
  bearer token grants no approval power.
- An approval is one row bound to one task, one operation, and one nonce
  (`lzap_` plus 32 hex chars, 128 random bits). Only the sha256 of the nonce
  is stored; the plain nonce is printed once on the approver's terminal. It
  expires after 15 minutes by default and is single use: one conditional
  update decides, exactly like a task claim.
- Only the agent holding the task's claim can consume it. A refusal (wrong
  holder, wrong task or operation, used, expired, unknown) is recorded as an
  `approval.refused` event without the nonce and returned as
  `ApprovalRefused`.
- A nonce cannot be forwarded or replayed through the bus: the redactor
  replaces the `lzap_` shape in every message payload (keys included), task
  title, task payload, result, agent role and capability before storage, so
  a peer that receives "use lzap_..." receives `[redacted:approval-nonce]`.
  Id-shaped fields (`agent_id`, `correlation_id`, `idempotency_key`,
  `reply_to`, task ids) cannot be scrubbed, so an id carrying a strict shape
  or the daemon's own token is refused; every id check runs through the
  store's redactor, which knows that token, never the pattern-only default.
  Artifact refs and contents are refused likewise (above). Tool results are
  scrubbed once more on the way out. The real nonce, handed to the agent in
  its own session by the user, still works exactly once.

### Secret redaction

Everything a peer can write into the store, and everything the daemon
returns, passes through `luciazero_agentd.redact.Redactor`: message payloads
(keys and values), task titles and payloads, results, agent roles and
capabilities, event payloads, tool results, tool error messages, and the
`/status` document. The daemon's own bearer token is a literal in that
scrubber. Two tiers: strict shapes (PEM private keys, any value after
`Authorization: Bearer`, a bare `Bearer` value only when it carries a
digit, approval nonces, AWS access keys, GitHub tokens, `sk-` API
keys with a digit, Slack tokens, URL userinfo in any scheme case, empty
user included) both scrub free text and refuse ids, refs, files and paths;
the heuristic tier (`key = value` where the key ends in a secret word and
the value carries a digit, plus JSON values under such keys) scrubs free
text only, so prose and ordinary code survive and a patch is never refused
for it. Every quantifier is bounded so a 64 KiB payload stays linear.
Provider adapters (M6) must pass captured model output through the same
scrubber before it becomes a run log or an event.

Redaction is defense in depth, not a promise of completeness: an unknown
secret shape passes, and so does an all-letter opaque token pasted bare
after the word "Bearer" outside a header (the digit rule is what keeps
"the bearer credentials keep other users out" intact). The rule for agents stays "never paste secrets into the
bus"; the scrubber limits the damage when that rule is broken.

### Threat model

v1 defends against cooperative-agent mistakes: a stale worker writing in
the wrong checkout, two workers sharing a tree, a confused agent treating a
peer's message as consent, an agent pasting a token into a finding, an
artifact reference pointing outside the repository or through a symlink,
oversized or malformed input.

v1 does not defend against a malicious local process running as the same OS
user. Such a process can read the token file, open the SQLite database,
edit any worktree, and drive the CLIs directly; the loopback bind and the
bearer token keep other users and other machines out, nothing more. The
approval CLI's TTY check stops accidental piping and any MCP-only agent; a
process with a shell can allocate a pseudo-terminal (`script(1)`) and reach
the prompt, so the real boundary is the operating-system user account plus
the skill rule that an agent never runs `approve` itself. Moving that
boundary is out of scope for the single-user v1.

Prompt injection through messages and artifacts is in scope as a
cooperative-mistake problem: every payload an agent reads from the bus is
untrusted input that can carry evidence and recommendations only. The
mechanical guarantees are that no payload can create an approval, no
payload can widen the sensitive-operation set, a forwarded nonce is
scrubbed, and the daemon never executes anything a payload names. The rest
is skill guidance (`/lucia-bus`, `/done`), which is why sensitive
operations always return to the user's own session for consent.

## Consequences

- Publishing any artifact now needs a bound worktree; a reviewer that only
  reads still binds its own checkout. This is the cost of "concurrent writers
  never share a worktree" and is deliberate.
- The daemon shells out to `git` on bind, claim, and publish (a few
  milliseconds on a warm repository, bounded by a 15 s timeout). `git` is
  therefore a runtime requirement of the daemon, which the README states.
- The tool contract grows from 12 to 15 tools (`worktree_bind`,
  `worktree_get`, `approval_consume`) and `task_create` gains
  `requires_worktree`. Both real CLIs still discover the contract (M2 gate).
- Schema version 2 adds `worktrees`, `approvals`, and
  `tasks.requires_worktree`; migration is forward only.
- Evidence: `./test.sh --agent-bus-security` (the M3 fixtures also run inside
  `--agent-bus-store` and therefore in `--fast` and `--full`), the crash
  suite covers `bind_worktree` and `consume_approval` at both commit points,
  and the approval CLI is exercised on a real pseudo-terminal plus a piped
  stdin that must be refused.

## Rollback

Revert the M3 commit. Schema version 2 tables can stay in an existing
database; a version-1 daemon refuses a newer schema, so downgrading also
means deleting the state directory, which holds no source of truth beyond
the bus queue.
