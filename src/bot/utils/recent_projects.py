"""Recent active projects scanner and UI builder for /cd command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = structlog.get_logger()

RECENT_PROJECT_LIMIT = 5
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass
class RecentProject:
    """A recently active project entry."""

    path: Path
    name: str
    last_modified_ts: float
    session_count: int


def _decode_project_dir_name(dir_name: str) -> Optional[Path]:
    """Decode Claude project directory name to path.

    The encoding replaces '/' with '-'.
    E.g. '-Users-suqi3-IdeaProjects-rag-flow' -> '/Users/suqi3/IdeaProjects/rag-flow'

    Strategy: greedily match existing directory segments from left to right.
    """
    if not dir_name.startswith("-"):
        return None

    raw = "/" + dir_name[1:]

    segments = raw.split("-")
    path = Path(segments[0]) if segments[0] else Path("/")
    rest = segments[1:]

    result_parts: list[str] = [str(path)]
    buffer = ""

    for seg in rest:
        if buffer:
            candidate_next = str(Path("/".join(result_parts)) / buffer)

            if Path(candidate_next).exists():
                result_parts.append(buffer)
                buffer = seg
            else:
                buffer = buffer + "-" + seg
        else:
            buffer = seg

    if buffer:
        result_parts.append(buffer)

    candidate = Path("/".join(result_parts))
    if candidate.exists() and candidate.is_dir():
        return candidate

    return None


def _get_project_last_modified(project_dir: Path) -> tuple[float, int]:
    """Get the latest modification timestamp and session count from sessions-index.json."""
    index_file = project_dir / "sessions-index.json"
    if not index_file.exists():
        return project_dir.stat().st_mtime, 0

    try:
        data = json.loads(index_file.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        if not entries:
            return project_dir.stat().st_mtime, 0

        latest_ts = 0.0
        for entry in entries:
            modified = entry.get("modified", "")
            if modified:
                try:
                    dt = datetime.fromisoformat(modified.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                    if ts > latest_ts:
                        latest_ts = ts
                except (ValueError, TypeError):
                    pass

        if latest_ts == 0.0:
            latest_ts = project_dir.stat().st_mtime

        return latest_ts, len(entries)
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Failed to parse sessions-index.json", path=str(index_file), error=str(e))
        return project_dir.stat().st_mtime, 0


def scan_recent_projects(
    approved_directory: Path,
    limit: int = RECENT_PROJECT_LIMIT,
) -> list[RecentProject]:
    """Scan ~/.claude/projects/ for recently active projects under approved_directory."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []

    projects: list[RecentProject] = []

    for item in CLAUDE_PROJECTS_DIR.iterdir():
        if not item.is_dir() or item.name.startswith("."):
            continue

        decoded_path = _decode_project_dir_name(item.name)
        if decoded_path is None:
            continue

        try:
            if not decoded_path.is_relative_to(approved_directory):
                continue
        except (ValueError, TypeError):
            continue

        last_ts, session_count = _get_project_last_modified(item)
        projects.append(
            RecentProject(
                path=decoded_path,
                name=decoded_path.name or str(decoded_path),
                last_modified_ts=last_ts,
                session_count=session_count,
            )
        )

    projects.sort(key=lambda p: p.last_modified_ts, reverse=True)
    return projects[:limit]


def build_recent_projects_message(
    recent_projects: list[RecentProject],
    current_directory: Optional[Path],
    approved_directory: Path,
    active_engine: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build Telegram message text and inline keyboard for recent projects.

    Returns (text, reply_markup) tuple.
    """
    lines = ["**Quick Switch**", ""]

    keyboard: list[list[InlineKeyboardButton]] = []

    for proj in recent_projects:
        try:
            rel = proj.path.relative_to(approved_directory)
            rel_text = str(rel) if str(rel) not in ("", ".") else "(root)"
        except ValueError:
            rel_text = proj.name

        is_current = (
            current_directory is not None
            and current_directory.resolve() == proj.path.resolve()
        )

        marker = " (current)" if is_current else ""
        sessions_info = f", {proj.session_count} sessions" if proj.session_count else ""
        lines.append(f"{'> ' if is_current else ''}  `{rel_text}`{marker}{sessions_info}")

        button_label = f"{'> ' if is_current else ''}{proj.name}"
        if len(button_label) > 30:
            button_label = button_label[:27] + "..."

        callback_data = f"cd:{rel_text}"
        if len(callback_data) > 64:
            callback_data = f"cd:{proj.name}"

        keyboard.append(
            [InlineKeyboardButton(button_label, callback_data=callback_data)]
        )

    lines.extend(
        [
            "",
            f"Engine: `{active_engine}`",
            "",
            "Use `/cd <path>` for direct path input",
            "Use `/projects` for full project list",
        ]
    )

    keyboard.append(
        [
            InlineKeyboardButton("All Projects", callback_data="action:show_projects"),
            InlineKeyboardButton("Refresh", callback_data="action:recent_cd"),
        ]
    )

    return "\n".join(lines), InlineKeyboardMarkup(keyboard)
