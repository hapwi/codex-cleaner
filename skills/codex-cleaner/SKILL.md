---
name: codex-cleaner
description: "Use when the user invokes $codex-cleaner or asks to audit, explain, archive, rotate, restore, or clean local Codex Desktop or Codex CLI state. This skill runs the open-source codex-cleaner npx runner and presents a guided Codex cleanup control panel in chat."
metadata:
  short-description: "Guided Codex cleanup, history, and restore"
  version: "0.0.10"
---

# Codex Cleaner

Use this skill as a guided Codex chat control panel around the `codex-cleaner-run` npx runner.

The npx runner CLI is the source of truth for audits, cleanup, history, and restore. Run it internally with `npx`; do not show the command unless the user explicitly asks for it.

## Audit First

Run this before any cleanup:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run audit --json
```

Audit mode is read-only. It must not move files, rotate logs, edit config, archive chats, or restore chats.

If the runner returns `ok: false` with `error: "codex_cleaner_skill_update_required"`, stop and tell the user to run `npx hapwi/codex-cleaner` in a terminal, then start a new Codex chat and invoke `$codex-cleaner` again. Do not run cleanup commands until the skill is current.

The runner may read `~/.hapwicleaner/install.json` for safe install/version metadata and may fetch `https://api.github.com/repos/hapwi/codex-cleaner/releases/latest` to compare the latest public release. These checks use only Codex Cleaner metadata and do not contain Codex chats, logs, sessions, or `~/.codex` state. If the runner returns `ok: false` with `error: "codex_cleaner_remote_update_required"`, stop and tell the user to run `npx hapwi/codex-cleaner` in a terminal, then start a new Codex chat and invoke `$codex-cleaner` again.

## Guided Chat Flow

After audit, present the result like a small control panel:

```markdown
**Codex Cleaner**

Status: read-only audit complete. Nothing has been changed yet.

Health: <Clean / Light cleanup available / Needs cleanup / Needs attention>
Recommended: <plain-English recommendation from the audit>
Protected: pinned chats, memories, skills, plugins, credentials, and normal project folders
```

Then show:

1. Recommended cleanup preset.
2. Advanced individual actions.
3. History and restore options.
4. Version footer.

Keep the user-facing wording concise. Explain impact, not implementation details. Do not paste raw stdout or raw JSON unless the user asks.

## Cleanup Presets

Only run cleanup after the user clearly chooses an action.

Safe reset:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run safe-reset --json
```

Use when the user says: `run safe reset`, `safe reset`, `recommended cleanup`, or similar.

This archives old non-pinned chats, prunes stale Codex project shortcuts, archives stale Codex worktrees, and rotates logs only when the log database is free.

Sidebar cleanup:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run sidebar-cleanup --json
```

Use when the user wants the active Codex sidebar less crowded without touching other cleanup areas.

Storage cleanup:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run storage-cleanup --json
```

Use when the user wants old chat sessions, stale worktrees, and logs moved out of active Codex state.

Deep archive:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run deep-archive --json
```

Use only after the user explicitly chooses deep archive. Deep archive archives all non-pinned active chats, including recent chats.

## Advanced Cleanup Commands

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

## History And Restore

Show cleanup history:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run history --json
```

Show the most recent cleanup:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run last-cleanup --json
```

Restore the latest chat archive:

```bash
npx --yes --package github:hapwi/codex-cleaner codex-cleaner-run restore-last-chat-archive --json
```

Only run restore after the user clearly chooses it. Restore changes local Codex state and should be treated like cleanup: summarize what will happen first if the user seems unsure.

## Safety Rules

- Never permanently delete chats, sessions, logs, worktrees, memories, skills, plugins, automations, or credentials.
- Never archive pinned threads.
- Never run cleanup without user approval.
- Never run deep archive or restore from a vague "clean it up" request; ask for or infer a specific clear choice from the immediately preceding audit menu.
- Treat `logs_2.sqlite` as private. Do not print raw log bodies.
- Summarize the CLI JSON output for the user. Do not dump raw JSON unless the user asks.
- End every audit, history, restore, or cleanup response with a short version line using the CLI JSON `version` object, such as `Version: Codex Cleaner CLI v0.0.10 | skill v0.0.10`.
- After cleanup or restore, tell the user the action finished and recommend quitting/reopening Codex so the already-open UI reloads local state. A Mac restart is not needed.

## Chat Format

Recommended reply menu after audit:

```text
run safe reset
run sidebar cleanup
run storage cleanup
run deep archive
show cleanup history
show last cleanup
restore last chat archive
```

Also support these advanced replies:

```text
archive old chats 10 days
archive all chats
prune stale projects
rotate logs
archive stale worktrees
```

For cleanup or restore results, start with:

```markdown
**Codex Cleaner Finished**
```

For history results, start with:

```markdown
**Codex Cleaner History**
```
