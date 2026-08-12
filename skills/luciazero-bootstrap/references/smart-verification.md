# Repo-owned smart verification

Use this only when timing proves the full monorepo suite is too slow for each loop. A small repository keeps one command.

## Contract

Create a repository command named by its convention, conceptually `verify-changed`, with these properties:

1. Use the native task/dependency graph when one exists (Nx, Turbo, Bazel, workspace filters, Cargo packages, Go packages). Read the repository's pinned tool version and CI before choosing its actual syntax.
2. Include unstaged, staged, untracked, deleted, and renamed files. Define how the merge base is selected in local work and CI.
3. Expand shared-library, root-config, lockfile, build-tool, and code-generation changes to all affected consumers.
4. Fall back to `verify-full` when the base revision is unavailable, the graph command fails, or a changed path cannot be mapped safely. Unknown impact means broader verification, never a silent skip.
5. Exit non-zero if any selected check fails and run unattended/offline.
6. Print the selected projects and the reason for a full fallback so the scope is auditable.

Set `LUCIAZERO_VERIFY_CMD` to this repo-owned fast command. `/done` still runs `verify-full`; change targeting reduces iteration latency, not closeout coverage.

## Proof fixtures

Before adopting the command, prove at least:

- a leaf-package change selects that package;
- a shared-library change selects every dependent package;
- a root config or lockfile change selects the full tier;
- staged, unstaged, untracked, deleted, and renamed files are seen;
- an unavailable merge base or unsupported path falls back to full verification;
- a selected failing test makes the command non-zero.

Do not add `LUCIAZERO_SMART_VERIFY` logic to the global hook. The hook cannot know each repository's dependency graph or CI base semantics; that policy belongs with the repository and evolves with it.
