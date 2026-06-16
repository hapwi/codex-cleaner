# Codex Cleaner

![License](https://img.shields.io/badge/license-MIT-green)
![Runtime](https://img.shields.io/badge/runtime-npx%20%2B%20python-blue)
![Codex Skill](https://img.shields.io/badge/Codex-skill-ready-00b894)
![Safety](https://img.shields.io/badge/safety-backup--first-f39c12)

![Codex Cleaner hero](./assets/codex-cleaner-hero.png)

**A safer reset button for local Codex clutter. Built for people who live in Codex every day.**

Codex Cleaner audits local Codex Desktop and Codex CLI state, explains what is taking up space, and helps archive old chats, rotate logs, prune stale project shortcuts, move old worktrees, review cleanup history, manage archive storage, and restore the latest chat archive without permanently deleting history.

## Install

Run the bootstrap command in Terminal:

```bash
npx hapwi/codex-cleaner
```

That command checks and installs the Codex skill here:

```text
~/.agents/skills/codex-cleaner
```

The first run may show npm's package prompt:

```text
Need to install the following packages:
github:hapwi/codex-cleaner
Ok to proceed? (y)
```

Answer `y`, or skip npm's prompt with:

```bash
npx --yes hapwi/codex-cleaner
```

After install or update, start a new Codex chat and invoke:

```text
$codex-cleaner
```

## Use In Codex

Inside Codex:

```text
$codex-cleaner
```

The skill runs the `codex-cleaner-run` command through `npx`, asks the runner for structured JSON, then turns the result into a guided cleanup menu in chat.

The default `$codex-cleaner` experience is a Codex-native control panel:

```text
Health: Needs cleanup
Recommended: run safe reset
Protected: pinned chats, memories, skills, plugins, credentials, and normal project folders
Findings: one row per cleanup area with count, size, and recommended reply
Size impact: active Codex state moved vs. Mac disk space freed now
```

Common replies:

```text
run safe reset
run sidebar cleanup
run storage cleanup
run deep archive
show cleanup history
show last cleanup
restore last chat archive
review archives
show restorable chats
trash non-restorable archives 30 days
```

Codex may ask for approval because the runner fetches public GitHub package code and audits private local Codex state. That is expected. The audit is read-only, and cleanup still requires an explicit follow-up choice.

## Update

Run the same bootstrap command any time:

```bash
npx hapwi/codex-cleaner
```

It checks the installed skill version and updates it when needed. Codex Cleaner also writes safe installer metadata here:

```text
~/.hapwicleaner/install.json
```

That file contains only Codex Cleaner metadata: package version, skill version, skill path, runner mode, and timestamps. It does not contain Codex chats, logs, sessions, or other `~/.codex` state.

When `$codex-cleaner` runs, the runner checks:

```text
~/.hapwicleaner/install.json
https://api.github.com/repos/hapwi/codex-cleaner/releases/latest
```

If the latest GitHub Release is newer than the installed manifest, it stops before auditing and tells the user to run:

```bash
npx hapwi/codex-cleaner
```

## What It Cleans

| Area | What Codex Cleaner Does | Safety Guard |
|---|---|---|
| Active chats | Archives old or all non-pinned active chats | Pinned chats are never archived |
| Sessions | Moves matching session files into archive storage | Restore manifests are written before cleanup |
| Logs | Rotates `logs_2.sqlite` into archived logs | Waits until the log DB is free |
| Project config | Removes saved entries for missing/temp folders | Does not delete project files |
| Worktrees | Moves stale Codex worktrees out of the active folder | Does not touch normal project folders |
| Archives | Reviews or trashes old archive storage | Chat restore archives are excluded by default |
| History | Lists prior Codex Cleaner backup folders | Reads backup metadata only |
| Restore | Restores the latest chat archive | Creates a fresh backup before restoring |

## Cleanup Presets

| Preset | Best For | What It Does |
|---|---|---|
| `safe-reset` | Normal cleanup | Archives old non-pinned chats, prunes stale projects, archives stale worktrees, rotates logs if free |
| `sidebar-cleanup` | A crowded Codex sidebar | Archives old non-pinned chats only |
| `storage-cleanup` | Local Codex storage | Archives old non-pinned chats, archives stale worktrees, rotates logs if free |
| `deep-archive` | A nearly empty sidebar | Archives all non-pinned chats, prunes stale projects, archives stale worktrees, rotates logs if free |

Audit output includes a size impact preview before anything changes. It separates:

- active Codex state moved into archives
- projected active footprint after cleanup
- Mac disk space freed immediately

Because Codex Cleaner keeps restore copies, most cleanup actions reduce active Codex clutter but free `0B` of Mac disk space immediately. Archives can be reviewed separately. Archive trash actions move matching folders to Mac Trash when available; they do not permanently delete by default.

## Archive Management

Archive management is intentionally separate from normal cleanup. The normal presets make Codex less cluttered and keep restore copies. Archive management is for reviewing or trashing those older restore/archive folders later.

Read-only archive review:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run review-archives
```

Show chat archives that can be restored:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run show-restorable-chats
```

Move old non-restorable archives to Trash:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run trash-nonrestorable-archives --days 30
```

This excludes chat restore archives by default. To include old chat restore archives too, the user must explicitly choose the include-chat-archives variant:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run trash-old-archives --days 30 --include-chat-archives
```

Every archive trash run writes a manifest in the Codex Cleaner backup folder showing what moved and where it went.

## Terminal Usage

Read-only audit:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run audit
```

Cleanup presets:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run safe-reset
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run sidebar-cleanup
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run storage-cleanup
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run deep-archive
```

Advanced cleanup commands:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run archive-old-chats --days 10
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run archive-all-chats
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run prune-stale-projects
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run rotate-logs
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run archive-stale-worktrees --days 7
```

History and restore:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run history
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run last-cleanup
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run restore-last-chat-archive
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run review-archives
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run show-restorable-chats
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run trash-nonrestorable-archives --days 30
```

Structured output for Codex agents:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run audit --json
```

The JSON response includes both a human-readable `textReport` and structured fields for Codex agents, including `health`, `recommendedReply`, `findings`, `blockedActions`, `sizeImpact`, `archiveInventory`, and `replyOptions`.

Version/status:

```bash
npx --yes hapwi/codex-cleaner version
npx --yes hapwi/codex-cleaner skill-status
```

## Skill Standardization Pattern

Codex Cleaner is intended to model a repeatable way to ship Codex skills:

| Layer | Responsibility |
|---|---|
| Bootstrap command | `npx hapwi/codex-cleaner` installs, updates, and records safe metadata |
| Installed skill | `~/.agents/skills/codex-cleaner/SKILL.md` gives Codex the workflow |
| Runner command | `codex-cleaner-run` performs the actual audit or cleanup action |
| Safe manifest | `~/.hapwicleaner/install.json` tracks installed version state without reading private Codex data |
| GitHub Release | `releases/latest` is the public source of truth for latest stable version |

This separates installation, skill routing, runtime execution, and version detection. The same pattern can be reused for other skills:

```text
npx owner/tool
  -> install/update ~/.agents/skills/tool
  -> write ~/.tool/install.json
  -> skill calls tool-run
  -> runner checks latest GitHub Release
  -> runner blocks if local install is stale
```

The goal is a consistent skill lifecycle: install with one command, invoke naturally in Codex, keep runtime behavior versioned, and give users a clear update path.

## Releases

Pushing a version tag creates or updates a GitHub Release automatically:

```bash
git tag v0.0.12
git push origin v0.0.12
```

The runner checks the latest GitHub Release, not raw `main`, when deciding whether the installed skill is current.

Plain GitHub `npx` still pulls the default branch:

```bash
npx hapwi/codex-cleaner
```

So `main` should track the latest released code. For a pinned install, use:

```bash
npx hapwi/codex-cleaner#v0.0.12
```

## Safety

- Audit mode is read-only by default.
- Cleanup requires an explicit command or user approval.
- Backups are created before state-changing actions.
- Pinned chats are protected.
- Recent chats are protected during age-based cleanup.
- Log contents are treated as private.
- Archives are not automatically deleted.
- Archive cleanup moves matching archive folders to Trash by default and excludes chat restore archives unless explicitly included.

## Development

```bash
npm run audit
node ./bin/codex-cleaner.js skill-status
node ./bin/codex-cleaner.js install-skill
npm pack --dry-run
```

## License

MIT
