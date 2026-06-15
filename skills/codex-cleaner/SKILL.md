---
name: codex-cleaner
description: "Use when the user invokes $codex-cleaner or asks to audit, explain, archive, rotate, or clean local Codex Desktop or Codex CLI state. This skill runs the open-source codex-cleaner npx runner and summarizes the result in chat."
metadata:
  short-description: "Audit and clean Codex local state safely"
  version: "0.0.8"
---

# Codex Cleaner

Use this skill as a thin Codex chat wrapper around the `codex-cleaner-run` npx runner.

The npx runner CLI is the source of truth for audits and cleanup. Run it internally with `npx`; do not show the command unless the user explicitly asks for it.

## Audit First

Run this before any cleanup:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run audit --json
```

Audit mode is read-only. It must not move files, rotate logs, edit config, or archive chats.

If the runner returns `ok: false` with `error: "codex_cleaner_skill_update_required"`, stop and tell the user to run `npx hapwi/codex-cleaner` in a terminal, then start a new Codex chat and invoke `$codex-cleaner` again. Do not run cleanup commands until the skill is current.

The runner may read `~/.hapwicleaner/install.json` for safe install/version metadata and may fetch `https://api.github.com/repos/hapwi/codex-cleaner/releases/latest` to compare the latest public release. These checks use only Codex Cleaner metadata and do not contain Codex chats, logs, sessions, or `~/.codex` state. If the runner returns `ok: false` with `error: "codex_cleaner_remote_update_required"`, stop and tell the user to run `npx hapwi/codex-cleaner` in a terminal, then start a new Codex chat and invoke `$codex-cleaner` again.

## Cleanup Commands

Only run cleanup after the user clearly chooses an action.

Archive older non-pinned chats:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run archive-old-chats --days 10 --json
```

Archive all non-pinned chats:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run archive-all-chats --json
```

Prune stale Codex project entries:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run prune-stale-projects --json
```

Rotate the Codex log database:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run rotate-logs --json
```

Archive stale Codex worktrees:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run archive-stale-worktrees --days 7 --json
```

## Safety Rules

- Never permanently delete chats, sessions, logs, worktrees, memories, skills, plugins, automations, or credentials.
- Never archive pinned threads.
- Never run cleanup without user approval.
- Treat `logs_2.sqlite` as private. Do not print raw log bodies.
- Summarize the CLI JSON output for the user. Do not dump raw JSON unless the user asks.
- End every audit or cleanup response with a short version line using the CLI JSON `version` object, such as `Version: Codex Cleaner CLI v0.0.8 | skill v0.0.8`.
- After cleanup, tell the user cleanup finished and recommend quitting/reopening Codex so the already-open UI reloads local state. A Mac restart is not needed.

## Chat Format

After audit, start with:

```markdown
**Codex Cleaner Results**

Status: read-only audit complete. Nothing has been changed yet.
```

Then explain the current state and show cleanup choices in concise Markdown tables.

Recommended replies:

```text
archive old chats 10 days
archive all chats
prune stale projects
rotate logs
archive stale worktrees
```
