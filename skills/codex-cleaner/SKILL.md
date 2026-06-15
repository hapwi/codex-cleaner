---
name: codex-cleaner
description: "Use when the user invokes $codex-cleaner or asks to audit, explain, archive, rotate, or clean local Codex Desktop or Codex CLI state. This skill runs the open-source codex-cleaner npx command and summarizes the result in chat."
metadata:
  short-description: "Audit and clean Codex local state safely"
  version: "0.0.3"
---

# Codex Cleaner

Use this skill as a thin Codex chat wrapper around the `codex-cleaner` CLI.

The CLI is the source of truth. Run it internally with `npx`; do not show the command unless the user explicitly asks for it.

## Audit First

Run this before any cleanup:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner audit --json
```

Audit mode is read-only. It must not move files, rotate logs, edit config, or archive chats.

## Cleanup Commands

Only run cleanup after the user clearly chooses an action.

Archive older non-pinned chats:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner archive-old-chats --days 10 --json
```

Archive all non-pinned chats:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner archive-all-chats --json
```

Prune stale Codex project entries:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner prune-stale-projects --json
```

Rotate the Codex log database:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner rotate-logs --json
```

Archive stale Codex worktrees:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner archive-stale-worktrees --days 7 --json
```

## Safety Rules

- Never permanently delete chats, sessions, logs, worktrees, memories, skills, plugins, automations, or credentials.
- Never archive pinned threads.
- Never run cleanup without user approval.
- Treat `logs_2.sqlite` as private. Do not print raw log bodies.
- Summarize the CLI JSON output for the user. Do not dump raw JSON unless the user asks.
- End every audit or cleanup response with a short version line using the CLI JSON `version` object, such as `Version: Codex Cleaner CLI v0.0.3 | skill v0.0.3`.
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
