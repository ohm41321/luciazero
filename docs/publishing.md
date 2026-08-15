# Publishing checklist

How luciazero reaches each distribution channel, in dependency order. Facts
below were verified 2026-08-13; re-check anything marked (†) before relying
on it, since third-party processes change.

## 0. Prerequisites (everything depends on this)

- [x] `git init` + first commit — done 2026-08-10
- [x] Create the GitHub repo `luciazero` and push — github.com/ohm41321/luciazero
- [x] Cut `v2.0.0` per CONTRIBUTING — changelog and both manifests agree;
      GitHub Release and npm publish completed 2026-08-13
- [x] `repository`/`homepage` fields added to `package.json` and
      `.claude-plugin/plugin.json` — done 2026-08-10
- [x] `./test.sh` green; `claude plugin validate .` passes — verified locally
      and in GitHub Actions for `v2.0.0`

Version sync rule: a release bumps `CHANGELOG.md`, `.claude-plugin/plugin.json`,
and `package.json` together — `test.sh` fails on any mismatch.

**Release-state rule:** the source manifest, Git tag, GitHub Release, and npm
registry must agree before a version is described as public. Check the registry
with `npm view luciazero version` and inspect `dist.attestations`; a prepared
manifest or pushed tag alone is not a completed release.

## 1. Claude Code plugin (live the moment the repo is public)

Users need no setup from us beyond the push:

```
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

Third-party marketplace auto-update is off by default. Users can enable it for
`luciazero` in `/plugin` → Marketplaces, or update explicitly with
`claude plugin update luciazero@luciazero` and `/reload-plugins`. Because
`plugin.json` supplies an explicit version, every plugin release must bump it;
new commits at the same version are not delivered as updates.

To get listed in Anthropic's catalogs (†):

- Community/official directory submission form: <https://platform.claude.com/plugins/submit>
  (Team/Enterprise admins have their own path via claude.ai admin settings).
  Approved plugins land pinned-to-SHA in
  [anthropics/claude-plugins-community](https://github.com/anthropics/claude-plugins-community);
  sync is nightly, allow ~24h. The official tier (`claude-plugins-official`)
  is curated by Anthropic at their discretion — superpowers lives there; that
  is the long-term target.
- Review criteria they state: valid manifest, no file access outside the
  plugin dir, clear skill instructions, adequate README. Note for the
  submission: our hooks keep verify-state under a user-owned
  `$TMPDIR/luciazero-verify-state-<uid>` directory (never the repo), and the
  strict gate only runs a command the *user* set via
  `LUCIAZERO_STRICT_VERIFY_CMD`.

## 2. `npx skills add ohm41321/luciazero` (live the moment the repo is public)

[vercel-labs/skills](https://github.com/vercel-labs/skills) scans public GitHub
repos for `skills/<name>/SKILL.md` with `name` + `description` frontmatter —
that is exactly our root `skills/` layout, so there is nothing to register.
The [skills.sh](https://skills.sh) leaderboard populates itself from install
telemetry; the only lever is people actually running the command. (†)

## 3. npm — `npx luciazero`

One-time setup, in this order:

- [x] npm account with 2FA-on-publish — done 2026-08-10
- [x] First publish of `luciazero` — 1.5.0 live 2026-08-10 (browser 2FA flow)
- [x] Configure **trusted publishing** (OIDC) — registered 2026-08-10:
      npmjs.com/package/luciazero → Settings → Trusted Publisher → GitHub
      Actions → user `ohm41321`, repo `luciazero`, workflow `release.yml`,
      environment blank. Exercised by `v2.0.0` on 2026-08-13;
      `npm view luciazero dist.attestations` reports SLSA provenance. npm
      generated it under OIDC without a `--provenance` flag.
- [x] Publish from a GitHub Actions workflow with `permissions: id-token: write`, done 2026-08-10 — `release.yml` job `npm-publish` runs on every `v*` tag (skips versions already live),
      npm CLI ≥ 11.5.1
- [ ] Never add lifecycle scripts (`postinstall` etc.): npm v12 blocks them by
      default and scanners flag packages that carry them. `test.sh` enforces
      this; keep it that way.
- [x] npmjs.com does not resolve relative image paths in READMEs — README image
      tags use absolute `raw.githubusercontent.com` URLs (GitHub renders them
      too).

Users check and apply classic/Codex updates explicitly with
`npx luciazero@latest check-update` and `npx luciazero@latest update`.
`check-update` is the only installer-path command that contacts the npm
registry; `update` preserves the detected classic hook mode and runs the
already-downloaded installers. No lifecycle or background updater is allowed.

## 4. Directories, once live

- [ ] awesome-claude-code: submissions ONLY via their web issue form
      ("Recommend a new resource"); eligibility is repo ≥ 14 days old and
      actively developed, or ≥ 100 stars; human PRs are rejected (†)
- [ ] Codex side: "Awesome Codex CLI" pinned discussion on openai/codex;
      OpenAI's curated set is [openai/skills](https://github.com/openai/skills)
      (curated-acceptance process unconfirmed) (†)

## Channel honesty

The classic `./install.sh` remains the reference channel — it is the only one
that carries the statusline and the CLAUDE.md import. The plugin substitutes a
`SessionStart` doctrine hook (same capped text, silent when a classic install
exists); `npx skills` carries the 11 skills plus the temporary
`/luciazero-bootstrap` compatibility alias — no doctrine, no reviewer
agent, no hooks. Do not describe the channels as equivalent.
