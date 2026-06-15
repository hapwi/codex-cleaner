#!/usr/bin/env python3
"""Audit and safely clean local Codex Desktop/CLI state.

Default mode is audit-only. Cleanup requires --apply plus one or more explicit
cleanup choices.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_HEADER_RE = re.compile(r"^\[projects\.([\"'])(.+)\1\]\s*$")
TEMP_PROJECT_RE = re.compile(
    r"(\\AppData\\Local\\Temp\\|/AppData/Local/Temp/|\\Temp\\codex-|/Temp/codex-|\\Temp\\spark-|/Temp/spark-)",
    re.I,
)
MIN_ARCHIVE_OLD_DAYS = 1


@dataclass
class ThreadRow:
    thread_id: str
    title: str
    rollout_path: str | None
    created_at: int | None
    updated_at: int | None


@dataclass
class StateSnapshot:
    thread_db_found: bool
    thread_db_path: str
    threads_total: int
    threads_active: int
    threads_archived: int
    pinned_threads: int
    active_projectless_threads: int
    active_projectless_unpinned_threads: int
    active_session_storage: int
    archived_session_storage: int
    log_storage: int
    log_open: bool
    stale_projects: int
    stale_worktrees: int
    stale_worktree_storage: int
    active_older_than_24h: int
    archive_old_candidates: int
    archive_all_candidates: int
    archive_old_candidate_storage: int
    archive_all_candidate_storage: int


@dataclass
class BackupEntry:
    path: Path
    created_at: float
    actions: list[str]
    chat_manifests: list[Path]
    log_manifests: list[Path]
    worktree_manifests: list[Path]
    project_list: Path | None


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def codex_home(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    if os.environ.get("CODEX_HOME"):
        return Path(os.environ["CODEX_HOME"]).expanduser().resolve()
    return Path.home() / ".codex"


def default_backup_root() -> Path:
    return Path.home() / "Documents" / "Codex" / "codex-cleaner-backups"


def closed_codex_command(args: argparse.Namespace, flags: list[str]) -> str:
    return apply_command(args, flags)


def apply_command(args: argparse.Namespace, flags: list[str]) -> str:
    parts = ["python3", str(Path(__file__).resolve()), "--apply", *flags]
    if args.codex_home:
        parts.extend(["--codex-home", args.codex_home])
    if args.backup_root != str(default_backup_root()):
        parts.extend(["--backup-root", args.backup_root])
    return shlex.join(parts)


def size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def human_size(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f}{unit}" if unit != "B" else f"{int(amount)}B"
        amount /= 1024
    return f"{value}B"


def human_time(timestamp: float | int | None) -> str:
    if not timestamp:
        return "unknown"
    return datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d %H:%M")


def render_table(headers: list[str], rows: list[list[str]]) -> None:
    all_rows = [headers, *rows]
    widths = [max(len(str(row[index])) for row in all_rows) for index in range(len(headers))]
    rule = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    print(rule)
    print("| " + " | ".join(str(headers[index]).ljust(widths[index]) for index, width in enumerate(widths)) + " |")
    print(rule)
    for row in rows:
        print("| " + " | ".join(str(row[index]).ljust(widths[index]) for index, width in enumerate(widths)) + " |")
    print(rule)


def read_lines_if_exists(path: Path) -> list[str]:
    try:
        if path.exists():
            return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        pass
    return []


def backup_entries(root: Path) -> list[BackupEntry]:
    if not root.exists():
        return []
    entries: list[BackupEntry] = []
    for path in root.iterdir():
        if not path.is_dir() or not path.name.startswith("codex-cleaner-"):
            continue
        try:
            created_at = path.stat().st_mtime
        except OSError:
            created_at = 0
        entries.append(
            BackupEntry(
                path=path,
                created_at=created_at,
                actions=read_lines_if_exists(path / "selected-actions.txt"),
                chat_manifests=sorted(path.glob("archived-chats-*.jsonl")),
                log_manifests=sorted(path.glob("rotated-logs-*.jsonl")),
                worktree_manifests=sorted(path.glob("archived-worktrees-*.jsonl")),
                project_list=(path / "pruned-projects.txt") if (path / "pruned-projects.txt").exists() else None,
            )
        )
    return sorted(entries, key=lambda entry: entry.created_at, reverse=True)


def latest_chat_backup(root: Path) -> BackupEntry | None:
    for entry in backup_entries(root):
        if entry.chat_manifests:
            return entry
    return None


def cleanup_health(snapshot: StateSnapshot) -> tuple[str, str]:
    if not snapshot.thread_db_found:
        return "Needs attention", "Codex thread database was not found, so chat cleanup is unavailable."
    if snapshot.archive_old_candidates or snapshot.stale_projects or snapshot.stale_worktrees:
        return "Needs cleanup", "Safe reset has useful work to do."
    if snapshot.log_storage > 0:
        return "Light cleanup available", "Only log rotation appears useful right now."
    return "Clean", "No obvious Codex clutter was found."


def active_cleanup_footprint(snapshot: StateSnapshot) -> int:
    return snapshot.active_session_storage + snapshot.log_storage + snapshot.stale_worktree_storage


def candidate_session_storage(rows: list[ThreadRow], pinned: set[str], cutoff: int | None = None) -> int:
    total = 0
    for row in rows:
        if row.thread_id in pinned:
            continue
        age_time = thread_age_time(row)
        if cutoff is not None and (age_time is None or int(age_time) >= cutoff):
            continue
        if not row.rollout_path:
            continue
        path = Path(row.rollout_path)
        try:
            if path.exists() and path.is_file():
                total += path.stat().st_size
        except OSError:
            pass
    return total


def delta_number(before: int, after: int) -> str:
    delta = after - before
    if delta > 0:
        return f"+{delta}"
    return str(delta)


def delta_size(before: int, after: int) -> str:
    delta = after - before
    if delta == 0:
        return "0B"
    sign = "+" if delta > 0 else "-"
    return f"{sign}{human_size(abs(delta))}"


def connect_sqlite(path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn = sqlite3.connect(path)
    conn.execute("pragma busy_timeout=30000")
    return conn


def sqlite_backup(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = connect_sqlite(src, readonly=True)
    target = sqlite3.connect(dst)
    source.backup(target)
    target.close()
    source.close()


def copy_file_if_exists(src: Path, dst: Path) -> None:
    if src.exists() and src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def thread_db_path(home: Path) -> Path:
    candidates = [
        home / "sqlite" / "state_5.sqlite",
        home / "state_5.sqlite",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_pinned(home: Path) -> set[str]:
    try:
        data = json.loads((home / ".codex-global-state.json").read_text(encoding="utf-8"))
        return set(data.get("pinned-thread-ids", []))
    except Exception:
        return set()


def load_projectless(home: Path) -> set[str]:
    try:
        data = json.loads((home / ".codex-global-state.json").read_text(encoding="utf-8"))
        return set(data.get("projectless-thread-ids", []))
    except Exception:
        return set()


def codex_processes() -> list[str]:
    try:
        if platform.system() == "Windows":
            return []
        output = subprocess.check_output(["ps", "-axo", "pid=,comm=,args="], text=True)
    except Exception:
        return []
    hits = []
    for line in output.splitlines():
        lower = line.lower()
        if "codex" in lower and ("app-server" in lower or "openai.codex" in lower or "codex desktop" in lower):
            hits.append(line.strip())
    return hits


def files_open(paths: list[Path]) -> bool:
    existing = [str(path) for path in paths if path.exists()]
    if not existing or platform.system() == "Windows":
        return False
    try:
        result = subprocess.run(["lsof", *existing], text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception:
        return False


def wait_until_closed(paths: list[Path]) -> None:
    while codex_processes() or files_open(paths):
        print("waiting_for_codex_to_close")
        time.sleep(2)


def wait_until_logs_free(paths: list[Path], timeout_seconds: int, interval_seconds: int) -> bool:
    started = time.time()
    while files_open(paths):
        elapsed = int(time.time() - started)
        if elapsed >= timeout_seconds:
            return False
        remaining = max(timeout_seconds - elapsed, 0)
        print(f"log_database_busy waiting_for_logs_to_be_free remaining_seconds={remaining}")
        time.sleep(max(interval_seconds, 1))
    return True


def make_backup(home: Path, root: Path, selected_actions: list[str]) -> Path:
    backup = root / f"codex-cleaner-{stamp()}"
    backup.mkdir(parents=True, exist_ok=True)
    for name in [
        ".codex-global-state.json",
        "config.toml",
        "history.jsonl",
        "models_cache.json",
        "session_index.jsonl",
        "version.json",
    ]:
        copy_file_if_exists(home / name, backup / name)
    sqlite_backup(home / "state_5.sqlite", backup / "state_5.sqlite")
    sqlite_backup(home / "sqlite" / "state_5.sqlite", backup / "sqlite" / "state_5.sqlite")
    (backup / "selected-actions.txt").write_text("\n".join(selected_actions) + "\n", encoding="utf-8")
    print("Backup")
    print("------")
    render_table(
        ["Item", "Path"],
        [
            ["Backup root", str(backup)],
            ["Selected actions", ", ".join(selected_actions)],
        ],
    )
    print("")
    return backup


def active_threads(conn: sqlite3.Connection) -> list[ThreadRow]:
    rows = conn.execute(
        "select id, title, rollout_path, created_at, updated_at from threads where archived_at is null"
    ).fetchall()
    return [ThreadRow(row[0], row[1] or "", row[2], row[3], row[4]) for row in rows]


def count_threads(conn: sqlite3.Connection) -> tuple[int, int, int]:
    row = conn.execute(
        "select count(*), sum(case when archived_at is null then 1 else 0 end), "
        "sum(case when archived_at is not null then 1 else 0 end) from threads"
    ).fetchone()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def stale_config_projects(home: Path) -> tuple[list[str], list[str]]:
    path = home / "config.toml"
    if not path.exists():
        return [], []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    out: list[str] = []
    removed: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = PROJECT_HEADER_RE.match(line)
        if not match:
            out.append(line)
            i += 1
            continue
        project_path = match.group(2)
        block = [line]
        i += 1
        while i < len(lines) and not lines[i].startswith("["):
            block.append(lines[i])
            i += 1
        if TEMP_PROJECT_RE.search(project_path) or not Path(project_path).exists():
            removed.append(project_path)
        else:
            out.extend(block)
    return removed, out


def print_cleanup_details(home: Path, stale_projects: list[str], args: argparse.Namespace) -> None:
    effective_days = max(args.archive_older_than_days, MIN_ARCHIVE_OLD_DAYS)
    print("Archive Old Chats")
    print(f"- selects non-pinned active threads older than {effective_days} day(s)")
    print("- chats created within the last 24 hours will not be archived")
    print("- updates state_5.sqlite threads.archived and threads.archived_at")
    print("- moves matching rollout .jsonl files from ~/.codex/sessions to ~/.codex/archived_sessions/codex-cleaner-*")
    print("- writes archived-chats manifest and restore-archived-chats.py in the backup folder")
    print("- skips pinned threads and skips every chat newer than 24 hours")
    print("- safe when old chats are not active work you still need in the sidebar; restore is available from the generated backup")
    print("")
    print("Archive All Chats")
    print("- selects every non-pinned active thread, including chats created within the last 24 hours")
    print("- use this only when you explicitly want recent chats archived too")
    print("- updates the same thread database fields and moves the same rollout files as archive-old-chats")
    print("- use --keep-thread <id> or --keep-newest-active when one active thread should stay visible")
    print("- still skips pinned threads")
    print("- safe when you intentionally want a near-empty active chat list and have saved handoffs for anything important")
    print("")
    print("Prune Stale Projects")
    print("- edits ~/.codex/config.toml only; it does not delete project folders")
    print("- removes Codex saved project entries for folders that are missing or temporary")
    print("- this only removes Codex's saved reference/shortcut/settings for those paths")
    print("- writes pruned-projects.txt in the backup folder with the exact removed paths")
    print(f"- current candidates: {len(stale_projects)}")
    print("- each path below is a folder Codex still has saved in config")
    print("- if the folder says exists=no, that folder is not currently on disk")
    print("- pruning removes the saved Codex config entry, not files inside the folder")
    for index, project in enumerate(stale_projects[:10], start=1):
        exists = "yes" if Path(project).exists() else "no"
        print(f"- {index}. exists={exists}: {project}")
    if len(stale_projects) > 10:
        print(f"- plus {len(stale_projects) - 10} more")
    print("- safe when every listed folder is already gone, a temp throwaway folder, or a project you do not need Codex to remember")
    print("")
    print("Rotate Logs")
    print("- moves ~/.codex/logs_2.sqlite, logs_2.sqlite-wal, and logs_2.sqlite-shm to ~/.codex/archived_logs/codex-cleaner-*")
    print("- does not inspect or print log message bodies")
    print("- Codex creates a fresh small log database on the next launch")
    print("- only rotates when those log files are not actively held open")
    print("- safe when the log files are free; if they stay busy, let other chats finish or quit Codex as the fallback")
    print("")
    print("Archive Stale Worktrees")
    print("- moves old folders from ~/.codex/worktrees to ~/.codex/archived_worktrees/codex-cleaner-*")
    print("- does not touch normal project folders outside ~/.codex/worktrees")
    print("- safe when the worktree is old, no task is running there, and you do not need that temporary checkout active")
    print("")
    print("Clearing Archives")
    print("- archived_sessions, archived_logs, and archived_worktrees are restore storage, not active Codex state")
    print("- deleting an archive is permanent for that local restore copy")
    print("- safe to clear an archive only after you confirm you do not need to restore those chats/logs/worktrees, any important handoff is saved elsewhere, and Codex is closed")
    print("- codex-cleaner does not delete archives automatically")


def print_presets(snapshot: StateSnapshot, effective_days: int) -> None:
    render_table(
        ["Reply", "Best for", "Will change"],
        [
            [
                "run safe reset",
                "Normal cleanup",
                f"{human_size(snapshot.archive_old_candidate_storage + snapshot.log_storage + snapshot.stale_worktree_storage)} moved out of active state",
            ],
            [
                "run sidebar cleanup",
                "A busy Codex sidebar",
                f"{snapshot.archive_old_candidates} old non-pinned chat(s), {human_size(snapshot.archive_old_candidate_storage)}",
            ],
            [
                "run storage cleanup",
                "Local Codex storage",
                f"{human_size(snapshot.archive_old_candidate_storage + snapshot.log_storage + snapshot.stale_worktree_storage)} moved out of active state",
            ],
            [
                "run deep archive",
                "Nearly empty sidebar",
                f"{snapshot.archive_all_candidates} chats, {human_size(snapshot.archive_all_candidate_storage + snapshot.log_storage + snapshot.stale_worktree_storage)} moved",
            ],
        ],
    )


def print_size_impact_preview(snapshot: StateSnapshot, effective_days: int) -> None:
    active_now = active_cleanup_footprint(snapshot)
    safe_reset_moved = snapshot.archive_old_candidate_storage + snapshot.log_storage + snapshot.stale_worktree_storage
    sidebar_moved = snapshot.archive_old_candidate_storage
    storage_moved = snapshot.archive_old_candidate_storage + snapshot.log_storage + snapshot.stale_worktree_storage
    deep_moved = snapshot.archive_all_candidate_storage + snapshot.log_storage + snapshot.stale_worktree_storage
    log_note = "logs move when free" if snapshot.log_open else "logs free now"
    render_table(
        ["Reply", "Active Codex Footprint Now", "Moved Out Of Active State", "Active Footprint After", "Mac Disk Freed Now"],
        [
            [
                "run safe reset",
                human_size(active_now),
                f"{human_size(safe_reset_moved)} ({log_note})",
                human_size(max(active_now - safe_reset_moved, 0)),
                "0B; archives are retained",
            ],
            [
                "run sidebar cleanup",
                human_size(active_now),
                human_size(sidebar_moved),
                human_size(max(active_now - sidebar_moved, 0)),
                "0B; archives are retained",
            ],
            [
                "run storage cleanup",
                human_size(active_now),
                f"{human_size(storage_moved)} ({log_note})",
                human_size(max(active_now - storage_moved, 0)),
                "0B; archives are retained",
            ],
            [
                "run deep archive",
                human_size(active_now),
                f"{human_size(deep_moved)} ({log_note})",
                human_size(max(active_now - deep_moved, 0)),
                "0B; archives are retained",
            ],
            [
                f"archive old chats {effective_days} days",
                human_size(active_now),
                human_size(snapshot.archive_old_candidate_storage),
                human_size(max(active_now - snapshot.archive_old_candidate_storage, 0)),
                "0B; archives are retained",
            ],
            [
                "rotate logs",
                human_size(active_now),
                f"{human_size(snapshot.log_storage)} ({log_note})",
                human_size(max(active_now - snapshot.log_storage, 0)),
                "0B; logs are archived",
            ],
        ],
    )


def print_findings(snapshot: StateSnapshot, effective_days: int) -> None:
    rows = []
    if snapshot.archive_old_candidates:
        rows.append(
            [
                "Old active chats",
                f"{snapshot.archive_old_candidates} chat(s), {human_size(snapshot.archive_old_candidate_storage)}",
                f"archive old chats {effective_days} days",
                "Moves matching sessions to archived_sessions; pinned and recent chats stay active",
            ]
        )
    if snapshot.log_storage:
        rows.append(
            [
                "Log database",
                f"{human_size(snapshot.log_storage)} ({'open now' if snapshot.log_open else 'free now'})",
                "rotate logs",
                "Moves logs_2.sqlite files to archived_logs; Codex creates a fresh DB later",
            ]
        )
    if snapshot.stale_projects:
        rows.append(
            [
                "Stale project shortcuts",
                f"{snapshot.stale_projects} config entr{'y' if snapshot.stale_projects == 1 else 'ies'}",
                "prune stale projects",
                "Forgets missing/temp paths in Codex config; does not delete project folders",
            ]
        )
    if snapshot.stale_worktrees:
        rows.append(
            [
                "Stale Codex worktrees",
                f"{snapshot.stale_worktrees} folder(s), {human_size(snapshot.stale_worktree_storage)}",
                "archive stale worktrees",
                "Moves old temporary Codex worktrees to archived_worktrees",
            ]
        )
    if snapshot.archived_session_storage:
        rows.append(
            [
                "Existing chat archives",
                human_size(snapshot.archived_session_storage),
                "show cleanup history",
                "Restore storage already on disk; not deleted automatically",
            ]
        )
    if not rows:
        rows.append(
            [
                "No active cleanup findings",
                "0B",
                "none",
                "No old chats, stale projects, stale worktrees, or logs need cleanup",
            ]
        )
    render_table(["Finding", "Amount", "Recommended Reply", "What Happens"], rows)


def print_history(root: Path, limit: int) -> None:
    entries = backup_entries(root)
    print("Codex Cleaner History")
    print("=====================")
    print(f"Backup root: {root}")
    print("")
    if not entries:
        print("No Codex Cleaner backup history was found.")
        return
    rows = []
    for index, entry in enumerate(entries[:limit], start=1):
        restore = []
        if entry.chat_manifests:
            restore.append("chats")
        if entry.log_manifests:
            restore.append("logs")
        if entry.worktree_manifests:
            restore.append("worktrees")
        if entry.project_list:
            restore.append("project list")
        rows.append(
            [
                str(index),
                human_time(entry.created_at),
                ", ".join(entry.actions) if entry.actions else "unknown",
                ", ".join(restore) if restore else "backup only",
                str(entry.path),
            ]
        )
    render_table(["#", "When", "Actions", "Restore data", "Backup folder"], rows)
    print("")
    chat_entry = latest_chat_backup(root)
    if chat_entry:
        print("Latest Restorable Chat Archive")
        print("------------------------------")
        render_table(
            ["Item", "Value"],
            [
                ["When", human_time(chat_entry.created_at)],
                ["Backup", str(chat_entry.path)],
                ["Manifest", str(chat_entry.chat_manifests[-1])],
                ["Reply", "restore last chat archive"],
            ],
        )


def restore_chat_archive(home: Path, backup_root: Path) -> None:
    source_entry = latest_chat_backup(backup_root)
    if not source_entry:
        print("restore_last_chat_archive skipped_no_chat_archive")
        return
    manifest = source_entry.chat_manifests[-1]
    state = thread_db_path(home)
    if not state.exists():
        print(f"restore_last_chat_archive skipped_thread_db_missing {state}")
        return
    conn = connect_sqlite(state, readonly=False)
    restored = 0
    files_moved = 0
    bytes_moved = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        old_path = record.get("old_rollout_path")
        new_path = record.get("new_rollout_path")
        if record.get("moved") and old_path and new_path:
            source = Path(new_path)
            dest = Path(old_path)
            if source.exists():
                moved_size = source.stat().st_size
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(dest))
                files_moved += 1
                bytes_moved += moved_size
        conn.execute(
            "update threads set rollout_path=?, archived=0, archived_at=NULL where id=?",
            (old_path, record["thread_id"]),
        )
        restored += 1
    conn.commit()
    try:
        conn.execute("pragma wal_checkpoint(truncate)")
    except Exception:
        pass
    conn.close()
    print("Chat Restore Result")
    print("-------------------")
    render_table(
        ["Result", "Value"],
        [
            ["Threads restored", str(restored)],
            ["Session files moved back", str(files_moved)],
            ["Session storage moved back", human_size(bytes_moved)],
            ["Source backup", str(source_entry.path)],
            ["Manifest", str(manifest)],
        ],
    )
    print("")


def thread_age_time(row: ThreadRow) -> int | None:
    return row.created_at if row.created_at is not None else row.updated_at


def collect_state(home: Path, args: argparse.Namespace) -> tuple[StateSnapshot, list[str], list[Path]]:
    state = thread_db_path(home)
    pinned = load_pinned(home)
    projectless = load_projectless(home)
    total = active = archived = 0
    active_rows: list[ThreadRow] = []
    active_older_than_24h = 0
    archive_old_count = 0
    archive_all_count = 0
    archive_old_storage = 0
    archive_all_storage = 0
    active_projectless_count = 0
    active_projectless_unpinned_count = 0
    effective_days = max(args.archive_older_than_days, MIN_ARCHIVE_OLD_DAYS)

    if state.exists():
        conn = connect_sqlite(state, readonly=True)
        total, active, archived = count_threads(conn)
        active_rows = active_threads(conn)
        active_projectless_count = sum(1 for row in active_rows if row.thread_id in projectless)
        active_projectless_unpinned_count = sum(
            1 for row in active_rows if row.thread_id in projectless and row.thread_id not in pinned
        )
        now = int(time.time())
        day_cutoff = now - 86400
        active_older_than_24h = sum(
            1 for row in active_rows if (thread_age_time(row) or now) < day_cutoff
        )
        archive_old_cutoff = now - effective_days * 86400
        archive_old_count = sum(
            1
            for row in active_rows
            if row.thread_id not in pinned and (thread_age_time(row) or now) < archive_old_cutoff
        )
        archive_all_count = sum(1 for row in active_rows if row.thread_id not in pinned)
        archive_old_storage = candidate_session_storage(active_rows, pinned, archive_old_cutoff)
        archive_all_storage = candidate_session_storage(active_rows, pinned)
        conn.close()

    sessions = home / "sessions"
    archived_sessions = home / "archived_sessions"
    log_paths = list(home.glob("logs_2.sqlite*"))
    stale_projects, _ = stale_config_projects(home)
    worktrees = home / "worktrees"
    cutoff = time.time() - args.worktree_older_than_days * 86400
    stale_worktrees = [p for p in worktrees.iterdir() if p.is_dir() and p.stat().st_mtime < cutoff] if worktrees.exists() else []
    stale_worktree_storage = sum(size_bytes(path) for path in stale_worktrees)

    snapshot = StateSnapshot(
        thread_db_found=state.exists(),
        thread_db_path=str(state),
        threads_total=total,
        threads_active=active,
        threads_archived=archived,
        pinned_threads=len(pinned),
        active_projectless_threads=active_projectless_count,
        active_projectless_unpinned_threads=active_projectless_unpinned_count,
        active_session_storage=size_bytes(sessions),
        archived_session_storage=size_bytes(archived_sessions),
        log_storage=sum(path.stat().st_size for path in log_paths if path.exists()),
        log_open=files_open(log_paths),
        stale_projects=len(stale_projects),
        stale_worktrees=len(stale_worktrees),
        stale_worktree_storage=stale_worktree_storage,
        active_older_than_24h=active_older_than_24h,
        archive_old_candidates=archive_old_count,
        archive_all_candidates=archive_all_count,
        archive_old_candidate_storage=archive_old_storage,
        archive_all_candidate_storage=archive_all_storage,
    )
    return snapshot, stale_projects, stale_worktrees


def print_state_table(snapshot: StateSnapshot, effective_days: int) -> None:
    render_table(
        ["Area", "Current", "Meaning"],
        [
            ["Thread database", snapshot.thread_db_path, "Codex thread records used for this audit"],
            ["Chats", f"{snapshot.threads_active} active / {snapshot.threads_archived} archived", f"{snapshot.threads_total} total local thread records"],
            ["Not in folders", f"{snapshot.active_projectless_threads} active / {snapshot.active_projectless_unpinned_threads} archivable", "Projectless chats from the Codex sidebar state"],
            ["Pinned", str(snapshot.pinned_threads), "Never archived by codex-cleaner"],
            ["Recent protection", f"{snapshot.active_older_than_24h} active older than 24h", "Chats newer than 24h stay active unless all-clear is chosen"],
            ["Old-chat candidates", f"{snapshot.archive_old_candidates} / {human_size(snapshot.archive_old_candidate_storage)}", f"Non-pinned active chats older than {effective_days} day(s)"],
            ["All-chat candidates", f"{snapshot.archive_all_candidates} / {human_size(snapshot.archive_all_candidate_storage)}", "All non-pinned active chats"],
            ["Active sessions", human_size(snapshot.active_session_storage), "~/.codex/sessions"],
            ["Archived sessions", human_size(snapshot.archived_session_storage), "~/.codex/archived_sessions"],
            ["Log database", human_size(snapshot.log_storage), "Open now" if snapshot.log_open else "Closed"],
            ["Stale projects", str(snapshot.stale_projects), "Saved config entries for missing/temp folders"],
            ["Stale worktrees", f"{snapshot.stale_worktrees} / {human_size(snapshot.stale_worktree_storage)}", "Old folders under ~/.codex/worktrees"],
            ["Active cleanup footprint", human_size(active_cleanup_footprint(snapshot)), "Active sessions + logs + stale worktrees"],
        ],
    )


def print_delta_table(before: StateSnapshot, after: StateSnapshot) -> None:
    render_table(
        ["Metric", "Before", "After", "Change"],
        [
            ["Active chats", str(before.threads_active), str(after.threads_active), delta_number(before.threads_active, after.threads_active)],
            ["Archived chats", str(before.threads_archived), str(after.threads_archived), delta_number(before.threads_archived, after.threads_archived)],
            ["Pinned chats", str(before.pinned_threads), str(after.pinned_threads), delta_number(before.pinned_threads, after.pinned_threads)],
            ["Active session storage", human_size(before.active_session_storage), human_size(after.active_session_storage), delta_size(before.active_session_storage, after.active_session_storage)],
            ["Archived session storage", human_size(before.archived_session_storage), human_size(after.archived_session_storage), delta_size(before.archived_session_storage, after.archived_session_storage)],
            ["Log database", human_size(before.log_storage), human_size(after.log_storage), delta_size(before.log_storage, after.log_storage)],
            ["Stale project entries", str(before.stale_projects), str(after.stale_projects), delta_number(before.stale_projects, after.stale_projects)],
            ["Stale worktrees", str(before.stale_worktrees), str(after.stale_worktrees), delta_number(before.stale_worktrees, after.stale_worktrees)],
            ["Stale worktree storage", human_size(before.stale_worktree_storage), human_size(after.stale_worktree_storage), delta_size(before.stale_worktree_storage, after.stale_worktree_storage)],
            ["Active cleanup footprint", human_size(active_cleanup_footprint(before)), human_size(active_cleanup_footprint(after)), delta_size(active_cleanup_footprint(before), active_cleanup_footprint(after))],
            ["Mac disk space freed now", "0B", "0B", "0B"],
        ],
    )
    print("")
    print("Disk Space Note")
    print("---------------")
    print("Codex Cleaner archives by default. That reduces active Codex state, but it does not immediately free Mac disk space because the restore copies stay on disk.")


def audit(args: argparse.Namespace, home: Path) -> None:
    effective_days = max(args.archive_older_than_days, MIN_ARCHIVE_OLD_DAYS)
    snapshot, stale_projects, stale_worktrees = collect_state(home, args)
    health, health_note = cleanup_health(snapshot)
    history = backup_entries(Path(args.backup_root).expanduser().resolve())
    latest_cleanup = history[0] if history else None

    print("Codex Cleaner Audit")
    print("===================")
    print("Nothing has been changed. This is a read-only report.")
    print("")
    print("Overview")
    print("--------")
    render_table(
        ["Item", "Status"],
        [
            ["Health", health],
            ["Recommendation", health_note],
            ["Active chats", f"{snapshot.threads_active} active / {snapshot.threads_archived} archived"],
            ["Archivable old chats", f"{snapshot.archive_old_candidates} older than {effective_days} day(s)"],
            ["Pinned chats", f"{snapshot.pinned_threads} protected"],
            ["Active sessions", human_size(snapshot.active_session_storage)],
            ["Log database", f"{human_size(snapshot.log_storage)} ({'open' if snapshot.log_open else 'free'})"],
            ["Stale projects", str(snapshot.stale_projects)],
            ["Stale worktrees", f"{snapshot.stale_worktrees} / {human_size(snapshot.stale_worktree_storage)}"],
            ["Active cleanup footprint", human_size(active_cleanup_footprint(snapshot))],
            ["Last cleanup", human_time(latest_cleanup.created_at) if latest_cleanup else "none found"],
        ],
    )
    print("")
    print("Findings")
    print("--------")
    print_findings(snapshot, effective_days)
    print("")
    print("Recommended")
    print("-----------")
    if health == "Clean":
        print("No cleanup is needed right now. Optional maintenance reply:")
        print("")
        print("run safe reset")
    elif health == "Light cleanup available":
        print("Only light maintenance appears useful. Reply with:")
        print("")
        print("rotate logs")
    else:
        print("Reply with this for the normal Codex Cleaner pass:")
        print("")
        print("run safe reset")
        print("")
        print("Safe reset archives old non-pinned chats, prunes stale Codex project shortcuts, archives stale Codex worktrees, and rotates logs only if the log database is free.")
    print("")
    print("Size Impact Preview")
    print("-------------------")
    print("These are projected changes before cleanup. Archive-based cleanup moves data out of active Codex state; it does not delete the restore copy.")
    print_size_impact_preview(snapshot, effective_days)
    print("")
    print("Cleanup Presets")
    print("---------------")
    print_presets(snapshot, effective_days)
    print("")
    print("History And Restore")
    print("-------------------")
    render_table(
        ["Reply", "Shows or changes"],
        [
            ["show cleanup history", "Recent Codex Cleaner backups and restore data"],
            ["show last cleanup", "Most recent backup only"],
            ["restore last chat archive", "Moves the latest chat archive back into active Codex state"],
        ],
    )
    print("")
    print("Current State")
    print("-------------")
    if not snapshot.thread_db_found:
        print("- Codex thread database was not found, so chat cleanup cannot run.")
    else:
        print_state_table(snapshot, effective_days)
    print("")

    print("Advanced Cleanup")
    print("----------------")
    print("Use these when you want one exact action instead of a preset:")
    render_table(
        ["Reply", "Will change", "Protects"],
        [
            [
                f"archive old chats {effective_days} days",
                f"{snapshot.archive_old_candidates} non-pinned chat(s), {human_size(snapshot.archive_old_candidate_storage)} older than {effective_days} day(s)",
                "Pinned + chats from last 24h",
            ],
            [
                "archive all chats",
                f"{snapshot.archive_all_candidates} non-pinned chat(s), {human_size(snapshot.archive_all_candidate_storage)}, including recent ones",
                "Pinned chats only",
            ],
            [
                "prune stale projects",
                f"{snapshot.stale_projects} saved config project entry/entries",
                "Actual folders/files",
            ],
            [
                "rotate logs",
                f"{human_size(snapshot.log_storage)} log database",
                "Log contents are archived, not deleted",
            ],
            [
                "archive stale worktrees",
                f"{snapshot.stale_worktrees} old Codex worktree folder(s), {human_size(snapshot.stale_worktree_storage)}",
                "Normal project folders",
            ],
        ],
    )
    print("")
    print("Commands Behind The Menu")
    print("------------------------")
    render_table(
        ["Reply", "Command"],
        [
            [f"archive old chats {effective_days} days", apply_command(args, ["--archive-old-chats", "--archive-older-than-days", str(effective_days)])],
            ["archive all chats", apply_command(args, ["--archive-all-chats"])],
            ["prune stale projects", apply_command(args, ["--prune-stale-projects"])],
            ["rotate logs", apply_command(args, ["--rotate-logs", "--wait-for-logs-free"]) if snapshot.log_open else apply_command(args, ["--rotate-logs"])],
            ["archive stale worktrees", apply_command(args, ["--archive-stale-worktrees", "--worktree-older-than-days", str(args.worktree_older_than_days)])],
        ],
    )
    if snapshot.log_open:
        print("")
        print("Log Rotation Wait Step")
        print("----------------------")
        print("Codex is using the log DB right now. Let other chats finish, then run:")
        print(apply_command(args, ["--rotate-logs", "--wait-for-logs-free"]))
        print("If it keeps timing out, quit Codex and run the same command again.")
    print("")
    if stale_projects:
        print("Stale Project Entries")
        print("---------------------")
        print("These are saved Codex project entries. Pruning forgets these paths in Codex config; it does not delete project files.")
        render_table(
            ["#", "Folder Codex Would Forget", "On Disk"],
            [[str(index), project, "yes" if Path(project).exists() else "missing"] for index, project in enumerate(stale_projects, start=1)],
        )
        print("")
    print("Safety Notes")
    print("------------")
    print("- Backups are created before cleanup actions that change Codex state.")
    print("- Chat archiving writes a restore script in the backup folder.")
    print("- Pinned chats are never archived.")
    print("- Chats created within the last 24 hours are not archived unless you choose 'archive all chats'.")
    print("- Clearing archives is a separate permanent delete step; codex-cleaner does not do that automatically.")
    print("")
    print("More Detail")
    print("-----------")
    print_cleanup_details(home, stale_projects, args)


def select_chat_candidates(
    conn: sqlite3.Connection,
    pinned: set[str],
    args: argparse.Namespace,
) -> list[ThreadRow]:
    rows = active_threads(conn)
    keep = set(args.keep_thread or [])
    if args.keep_newest_active and rows:
        newest = max(rows, key=lambda row: row.updated_at or 0)
        keep.add(newest.thread_id)
    cutoff = None
    if args.archive_old_chats and not args.archive_all_chats:
        effective_days = max(args.archive_older_than_days, MIN_ARCHIVE_OLD_DAYS)
        cutoff = int((datetime.now() - timedelta(days=effective_days)).timestamp())
    candidates = []
    for row in rows:
        if row.thread_id in keep:
            continue
        if row.thread_id in pinned:
            continue
        age_time = thread_age_time(row)
        if cutoff is not None and (age_time is None or int(age_time) >= cutoff):
            continue
        candidates.append(row)
    return candidates


def archive_chats(home: Path, backup: Path, args: argparse.Namespace) -> None:
    state = thread_db_path(home)
    sessions = home / "sessions"
    archive_root = home / "archived_sessions" / f"codex-cleaner-{stamp()}"
    manifest = backup / f"archived-chats-{stamp()}.jsonl"
    conn = connect_sqlite(state, readonly=False)
    pinned = load_pinned(home)
    candidates = select_chat_candidates(conn, pinned, args)
    now = int(time.time())
    moved = 0
    bytes_moved = 0
    archive_root.mkdir(parents=True, exist_ok=True)
    records = []

    for row in candidates:
        old_path = row.rollout_path
        new_path = old_path
        moved_file = False
        moved_bytes = 0
        if old_path:
            source = Path(old_path)
            try:
                rel = source.resolve(strict=False).relative_to(sessions.resolve(strict=False))
            except ValueError:
                rel = None
            if rel is not None and source.exists() and source.is_file():
                dest = archive_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                moved_bytes = source.stat().st_size
                shutil.move(str(source), str(dest))
                new_path = str(dest)
                moved_file = True
                moved += 1
                bytes_moved += moved_bytes
        conn.execute(
            "update threads set rollout_path=?, archived=1, archived_at=? where id=?",
            (new_path, now, row.thread_id),
        )
        records.append(
            {
                "thread_id": row.thread_id,
                "old_rollout_path": old_path,
                "new_rollout_path": new_path,
                "moved": moved_file,
                "bytes": moved_bytes,
            }
        )

    conn.commit()
    try:
        conn.execute("pragma wal_checkpoint(truncate)")
    except Exception:
        pass
    conn.close()

    with manifest.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    write_chat_restore_script(manifest, state, backup)
    print("Chat Archive Result")
    print("-------------------")
    render_table(
        ["Result", "Value"],
        [
            ["Threads archived", str(len(candidates))],
            ["Session files moved", str(moved)],
            ["Session storage moved", human_size(bytes_moved)],
            ["Archive folder", str(archive_root)],
            ["Manifest", str(manifest)],
        ],
    )
    print("")


def write_chat_restore_script(manifest: Path, state: Path, backup: Path) -> None:
    restore = backup / "restore-archived-chats.py"
    restore.write_text(
        f'''#!/usr/bin/env python3
import json
import shutil
import sqlite3
from pathlib import Path

manifest = Path(r"{manifest}")
state = Path(r"{state}")
conn = sqlite3.connect(state)
conn.execute("pragma busy_timeout=30000")
for line in manifest.read_text(encoding="utf-8").splitlines():
    rec = json.loads(line)
    old_path = rec.get("old_rollout_path")
    new_path = rec.get("new_rollout_path")
    if rec.get("moved") and old_path and new_path:
        src = Path(new_path)
        dest = Path(old_path)
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
    conn.execute(
        "update threads set rollout_path=?, archived=0, archived_at=NULL where id=?",
        (old_path, rec["thread_id"]),
    )
conn.commit()
conn.close()
print("restored_threads", len(manifest.read_text(encoding="utf-8").splitlines()))
''',
        encoding="utf-8",
    )
    restore.chmod(0o700)
    print(f"Restore script: {restore}")


def rotate_logs(home: Path, backup: Path, args: argparse.Namespace) -> None:
    paths = list(home.glob("logs_2.sqlite*"))
    if not paths:
        print("rotate_logs skipped_no_logs")
        return
    if args.wait_for_codex_exit:
        wait_until_closed(paths)
    elif args.wait_for_logs_free and files_open(paths):
        if not wait_until_logs_free(paths, args.log_wait_timeout_seconds, args.log_wait_interval_seconds):
            print("rotate_logs skipped_logs_still_open")
            print("rotate_logs_hint wait for other Codex chats to finish, then rerun --apply --rotate-logs --wait-for-logs-free")
            print("rotate_logs_fallback if it keeps timing out, quit Codex and rerun the same command")
            return
    if files_open(paths):
        print("rotate_logs skipped_logs_are_open")
        print("rotate_logs_hint wait for other Codex chats to finish, then rerun with --apply --rotate-logs --wait-for-logs-free")
        print(f"run_when_ready {apply_command(args, ['--rotate-logs', '--wait-for-logs-free'])}")
        return
    archive_root = home / "archived_logs" / f"codex-cleaner-{stamp()}"
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest = backup / f"rotated-logs-{stamp()}.jsonl"
    total = 0
    with manifest.open("w", encoding="utf-8") as handle:
        for source in paths:
            dest = archive_root / source.name
            size = source.stat().st_size
            shutil.move(str(source), str(dest))
            total += size
            handle.write(json.dumps({"from": str(source), "to": str(dest), "bytes": size}) + "\n")
    print("Log Rotation Result")
    print("-------------------")
    render_table(
        ["Result", "Value"],
        [
            ["Log storage moved", human_size(total)],
            ["Archive folder", str(archive_root)],
            ["Manifest", str(manifest)],
        ],
    )
    print("")


def prune_config(home: Path, backup: Path) -> None:
    config = home / "config.toml"
    stale, out = stale_config_projects(home)
    (backup / "pruned-projects.txt").write_text("\n".join(stale) + ("\n" if stale else ""), encoding="utf-8")
    if stale:
        config.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("Project Config Result")
    print("---------------------")
    rows = [["Entries pruned", str(len(stale))], ["Config file", str(config)], ["Removed-path list", str(backup / "pruned-projects.txt")]]
    render_table(["Result", "Value"], rows)
    print("")


def archive_worktrees(home: Path, backup: Path, args: argparse.Namespace) -> None:
    root = home / "worktrees"
    if not root.exists():
        print("archived_worktrees 0")
        return
    cutoff = time.time() - args.worktree_older_than_days * 86400
    candidates = [path for path in root.iterdir() if path.is_dir() and path.stat().st_mtime < cutoff]
    archive_root = home / "archived_worktrees" / f"codex-cleaner-{stamp()}"
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest = backup / f"archived-worktrees-{stamp()}.jsonl"
    total = 0
    with manifest.open("w", encoding="utf-8") as handle:
        for source in candidates:
            dest = archive_root / source.name
            item_size = size_bytes(source)
            shutil.move(str(source), str(dest))
            total += item_size
            handle.write(json.dumps({"from": str(source), "to": str(dest), "bytes": item_size}) + "\n")
    print("Worktree Archive Result")
    print("-----------------------")
    render_table(
        ["Result", "Value"],
        [
            ["Worktrees archived", str(len(candidates))],
            ["Storage moved", human_size(total)],
            ["Archive folder", str(archive_root)],
            ["Manifest", str(manifest)],
        ],
    )
    print("")


def selected_actions(args: argparse.Namespace) -> list[str]:
    actions = []
    if args.restore_last_chat_archive:
        actions.append("restore-last-chat-archive")
    if args.archive_all_chats:
        actions.append("archive-all-chats")
    if args.archive_old_chats:
        actions.append(f"archive-old-chats:{max(args.archive_older_than_days, MIN_ARCHIVE_OLD_DAYS)}d")
    if args.rotate_logs:
        actions.append("rotate-logs")
    if args.prune_stale_projects:
        actions.append("prune-stale-projects")
    if args.archive_stale_worktrees:
        actions.append(f"archive-stale-worktrees:{args.worktree_older_than_days}d")
    return actions


def print_restart_notice(actions: list[str]) -> None:
    needs_restart = any(
        action.startswith("archive-")
        or action == "rotate-logs"
        or action == "prune-stale-projects"
        or action == "restore-last-chat-archive"
        for action in actions
    )
    if not needs_restart:
        return
    print("Restart Notice")
    print("--------------")
    print("Cleanup finished. Quit and reopen Codex so the app reloads the updated local state.")
    print("Why: the cleaner changed local Codex files/database entries that the already-open UI may have cached.")
    print("You do not need to restart your Mac.")
    print("")


def apply_cleanup(args: argparse.Namespace, home: Path) -> int:
    actions = selected_actions(args)
    if not actions:
        print("nothing_to_apply choose one or more cleanup flags")
        return 2
    if args.include_pinned:
        print("include_pinned_ignored pinned threads are always protected")
    if actions == ["rotate-logs"] and args.wait_for_codex_exit:
        log_paths = list(home.glob("logs_2.sqlite*"))
        if files_open(log_paths) or codex_processes():
            wait_until_closed(log_paths)
    if actions == ["rotate-logs"] and args.wait_for_logs_free and not args.wait_for_codex_exit:
        log_paths = list(home.glob("logs_2.sqlite*"))
        if files_open(log_paths) and not wait_until_logs_free(log_paths, args.log_wait_timeout_seconds, args.log_wait_interval_seconds):
            print("rotate_logs skipped_logs_still_open")
            print("rotate_logs_hint wait for other Codex chats to finish, then rerun --apply --rotate-logs --wait-for-logs-free")
            print("rotate_logs_fallback if it keeps timing out, quit Codex and rerun the same command")
            return 0
    if actions == ["rotate-logs"] and not args.wait_for_codex_exit and not args.wait_for_logs_free:
        log_paths = list(home.glob("logs_2.sqlite*"))
        if files_open(log_paths):
            print("rotate_logs skipped_logs_are_open")
            print("rotate_logs_hint wait for other Codex chats to finish, then rerun with --apply --rotate-logs --wait-for-logs-free")
            print(f"run_when_ready {apply_command(args, ['--rotate-logs', '--wait-for-logs-free'])}")
            return 0
    before_snapshot, _, _ = collect_state(home, args)
    backup = make_backup(home, Path(args.backup_root).expanduser().resolve(), actions)
    if args.restore_last_chat_archive:
        restore_chat_archive(home, Path(args.backup_root).expanduser().resolve())
    if args.archive_all_chats or args.archive_old_chats:
        archive_chats(home, backup, args)
    if args.rotate_logs:
        rotate_logs(home, backup, args)
    if args.prune_stale_projects:
        prune_config(home, backup)
    if args.archive_stale_worktrees:
        archive_worktrees(home, backup, args)
    after_snapshot, _, _ = collect_state(home, args)
    print("Before / After")
    print("--------------")
    print_delta_table(before_snapshot, after_snapshot)
    print("")
    print_restart_notice(actions)
    print("Done")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and safely clean Codex local app state.")
    parser.add_argument("--codex-home")
    parser.add_argument("--backup-root", default=str(default_backup_root()))
    parser.add_argument("--apply", action="store_true", help="Apply selected cleanup actions. Omit for audit only.")
    parser.add_argument("--history", action="store_true", help="Show Codex Cleaner backup history.")
    parser.add_argument("--history-limit", type=int, default=10)
    parser.add_argument("--safe-reset", action="store_true", help="Preset: old chats, stale projects, stale worktrees, logs if free.")
    parser.add_argument("--sidebar-cleanup", action="store_true", help="Preset: archive old non-pinned chats.")
    parser.add_argument("--storage-cleanup", action="store_true", help="Preset: old chats, stale worktrees, logs if free.")
    parser.add_argument("--deep-archive", action="store_true", help="Preset: archive all non-pinned chats plus other safe cleanup.")
    parser.add_argument("--archive-all-chats", action="store_true")
    parser.add_argument("--archive-old-chats", action="store_true")
    parser.add_argument("--archive-older-than-days", type=int, default=10)
    parser.add_argument("--include-pinned", action="store_true", help="Deprecated and ignored. Pinned threads are always protected.")
    parser.add_argument("--keep-thread", action="append", help="Thread id to leave active. Repeatable.")
    parser.add_argument("--keep-newest-active", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--rotate-logs", action="store_true")
    parser.add_argument("--wait-for-codex-exit", action="store_true")
    parser.add_argument("--wait-for-logs-free", action="store_true", help="Wait until logs_2.sqlite files are not held open, without requiring Codex to quit.")
    parser.add_argument("--log-wait-timeout-seconds", type=int, default=300)
    parser.add_argument("--log-wait-interval-seconds", type=int, default=5)
    parser.add_argument("--prune-stale-projects", action="store_true")
    parser.add_argument("--archive-stale-worktrees", action="store_true")
    parser.add_argument("--worktree-older-than-days", type=int, default=7)
    parser.add_argument("--restore-last-chat-archive", action="store_true")
    args = parser.parse_args(argv)
    presets = [args.safe_reset, args.sidebar_cleanup, args.storage_cleanup, args.deep_archive]
    if sum(1 for selected in presets if selected) > 1:
        parser.error("choose only one cleanup preset")
    if args.safe_reset:
        args.archive_old_chats = True
        args.prune_stale_projects = True
        args.archive_stale_worktrees = True
        args.rotate_logs = True
    if args.sidebar_cleanup:
        args.archive_old_chats = True
    if args.storage_cleanup:
        args.archive_old_chats = True
        args.archive_stale_worktrees = True
        args.rotate_logs = True
    if args.deep_archive:
        args.archive_all_chats = True
        args.prune_stale_projects = True
        args.archive_stale_worktrees = True
        args.rotate_logs = True
    if args.archive_all_chats and args.archive_old_chats:
        parser.error("choose --archive-all-chats or --archive-old-chats, not both")
    cleanup_flags = [
        args.archive_all_chats,
        args.archive_old_chats,
        args.rotate_logs,
        args.prune_stale_projects,
        args.archive_stale_worktrees,
    ]
    if args.restore_last_chat_archive and any(cleanup_flags):
        parser.error("restore-last-chat-archive must run by itself")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.history:
        print_history(Path(args.backup_root).expanduser().resolve(), max(args.history_limit, 1))
        return 0
    home = codex_home(args.codex_home)
    if not home.exists():
        print(f"codex_home_missing {home}")
        return 2
    if not args.apply:
        audit(args, home)
        return 0
    return apply_cleanup(args, home)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
