#!/usr/bin/env python3
"""
诊断 Claude Code 中 cc-codex-review / codex-battle-agent 的 MCP 调用状态。

用途：
- 快速判断 codex MCP 调用是运行中、失败还是完成
- 显示最近一次调用耗时与错误信息
- 尝试从 debug 日志中恢复“unknown message ID”里的返回结果（含 SESSION_ID）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any


def encode_project_path(path: Path) -> str:
    return str(path.resolve()).replace("/", "-")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def list_session_files_by_mtime(project_store_dir: Path) -> list[Path]:
    candidates = list(project_store_dir.glob("*.jsonl"))
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def find_latest_subagent_file(session_dir: Path) -> Path | None:
    sub_dir = session_dir / "subagents"
    if not sub_dir.exists():
        return None
    candidates = list(sub_dir.glob("agent-*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_main_session_file(project_store: Path, session_id: str) -> Path | None:
    p = project_store / f"{session_id}.jsonl"
    return p if p.exists() else None


def session_has_codex_signals(home: Path, project_store: Path, session_id: str) -> bool:
    main_file = find_main_session_file(project_store, session_id)
    if main_file and main_file.exists():
        rows = read_jsonl(main_file)
        events = extract_codex_events(rows)
        if events.get("tool_uses") or events.get("progress_events"):
            return True

    session_dir = project_store / session_id
    subagent_file = find_latest_subagent_file(session_dir)
    if subagent_file and subagent_file.exists():
        rows = read_jsonl(subagent_file)
        events = extract_codex_events(rows)
        if events.get("tool_uses") or events.get("progress_events"):
            return True

    debug_file = home / ".claude" / "debug" / f"{session_id}.txt"
    if debug_file.exists():
        text = debug_file.read_text(encoding="utf-8", errors="replace")
        if 'MCP server "codex": Tool \'codex\'' in text:
            return True
    return False


def pick_session_id(home: Path, project_store: Path, explicit_session_id: str | None) -> str | None:
    if explicit_session_id:
        return explicit_session_id

    session_files = list_session_files_by_mtime(project_store)
    if not session_files:
        return None

    latest = session_files[0].stem
    if session_has_codex_signals(home, project_store, latest):
        return latest

    # 回溯最近有 codex 信号的会话，避免“最新会话无 codex 数据”导致误判。
    for f in session_files[1:]:
        sid = f.stem
        if session_has_codex_signals(home, project_store, sid):
            return sid
    return latest


def _extract_success_session_from_obj(obj: Any) -> tuple[bool | None, str | None]:
    if not isinstance(obj, dict):
        return None, None
    target = obj.get("result")
    if not isinstance(target, dict):
        target = obj
    success = target.get("success")
    if not isinstance(success, bool):
        success = None
    session_id = target.get("SESSION_ID") or target.get("session_id")
    if session_id is not None:
        session_id = str(session_id)
    return success, session_id


def _extract_success_session_from_text(text: str) -> tuple[bool | None, str | None]:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    return _extract_success_session_from_obj(obj)


def extract_codex_events(subagent_rows: list[dict[str, Any]]) -> dict[str, Any]:
    tool_uses: list[dict[str, Any]] = []
    progress_events: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for row in subagent_rows:
        row_type = row.get("type")
        if row_type == "progress":
            data = row.get("data") or {}
            if (
                data.get("type") == "mcp_progress"
                and data.get("serverName") == "codex"
                and data.get("toolName") == "codex"
            ):
                progress_events.append(
                    {
                        "timestamp": row.get("timestamp"),
                        "status": data.get("status"),
                        "elapsed_ms": data.get("elapsedTimeMs"),
                        "tool_use_id": row.get("toolUseID"),
                    }
                )

        message = row.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                        and block.get("name") == "mcp__codex__codex"
                    ):
                        raw_input = block.get("input") or {}
                        tool_uses.append(
                            {
                                "id": block.get("id"),
                                "timestamp": row.get("timestamp"),
                                "prompt_preview": (str(raw_input.get("PROMPT", ""))[:120]),
                            }
                        )

        if row_type == "user":
            msg = row.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id")
                    ):
                        content_raw = block.get("content", "")
                        content_text = (
                            content_raw
                            if isinstance(content_raw, str)
                            else json.dumps(content_raw, ensure_ascii=False)
                        )
                        success, session_id = _extract_success_session_from_obj(content_raw)
                        if success is None and session_id is None:
                            success, session_id = _extract_success_session_from_text(content_text)

                        # Claude 主会话里可能把结构化结果放在 mcpMeta 中。
                        if success is None and session_id is None:
                            mcp_meta = row.get("mcpMeta")
                            if isinstance(mcp_meta, dict):
                                structured = mcp_meta.get("structuredContent")
                                s1, sid1 = _extract_success_session_from_obj(structured)
                                if s1 is not None or sid1 is not None:
                                    success, session_id = s1, sid1

                        tool_results.append(
                            {
                                "tool_use_id": block.get("tool_use_id"),
                                "timestamp": row.get("timestamp"),
                                "is_error": bool(block.get("is_error")),
                                "success": success,
                                "session_id": session_id,
                                "content": content_text[:600],
                            }
                        )

    return {
        "tool_uses": tool_uses,
        "progress_events": progress_events,
        "tool_results": tool_results,
    }


def merge_events(event_dicts: list[dict[str, Any]]) -> dict[str, Any]:
    merged = {
        "tool_uses": [],
        "progress_events": [],
        "tool_results": [],
    }
    for d in event_dicts:
        merged["tool_uses"].extend(d.get("tool_uses", []))
        merged["progress_events"].extend(d.get("progress_events", []))
        merged["tool_results"].extend(d.get("tool_results", []))

    merged["tool_uses"].sort(key=lambda x: str(x.get("timestamp", "")))
    merged["progress_events"].sort(key=lambda x: str(x.get("timestamp", "")))
    merged["tool_results"].sort(key=lambda x: str(x.get("timestamp", "")))
    return merged


def parse_unknown_message_responses(debug_text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    marker = "unknown message ID: "
    for line in debug_text.splitlines():
        idx = line.find(marker)
        if idx < 0:
            continue
        payload = line[idx + len(marker) :].strip()
        try:
            outer = json.loads(payload)
        except json.JSONDecodeError:
            continue

        try:
            content = outer["result"]["content"][0]["text"]
            inner = json.loads(content)
        except Exception:
            continue

        out.append(
            {
                "success": inner.get("success"),
                "session_id": inner.get("SESSION_ID"),
                "agent_messages_preview": str(inner.get("agent_messages", ""))[:800],
            }
        )
    return out


def extract_codex_debug_lines(debug_text: str) -> list[str]:
    pat = re.compile(r'MCP server "codex": Tool \'codex\' (still running|failed|completed).*')
    lines: list[str] = []
    for line in debug_text.splitlines():
        if pat.search(line):
            lines.append(line)
    return lines


def print_summary(
    project_dir: Path,
    session_id: str,
    fallback_used: bool,
    main_session_file: Path | None,
    subagent_file: Path | None,
    events: dict[str, Any],
    debug_file: Path | None,
    debug_lines: list[str],
    unknown_results: list[dict[str, Any]],
) -> None:
    print(f"项目: {project_dir}")
    print(f"Claude 会话: {session_id}")
    if fallback_used:
        print("提示: 已自动回溯到最近存在 codex 调用信号的会话")

    if main_session_file is not None:
        print(f"主会话日志: {main_session_file}")
    else:
        print("主会话日志: 未找到")

    if subagent_file is not None:
        print(f"子代理日志: {subagent_file}")
    else:
        print("子代理日志: 未找到")

    tool_uses = events.get("tool_uses", [])
    progress = events.get("progress_events", [])
    tool_results = events.get("tool_results", [])

    if tool_uses:
        last_use = tool_uses[-1]
        print(f"最近 codex 调用 ID: {last_use.get('id')} @ {last_use.get('timestamp')}")
    else:
        print("最近 codex 调用 ID: 未找到")

    if progress:
        last_p = progress[-1]
        print(
            "最近进度: "
            f"{last_p.get('status')} "
            f"(elapsed_ms={last_p.get('elapsed_ms')}, at={last_p.get('timestamp')})"
        )
    else:
        print("最近进度: 未找到")

    if tool_results:
        last_r = tool_results[-1]
        print(
            "最近 tool_result: "
            f"is_error={last_r.get('is_error')}, "
            f"success={last_r.get('success')}, "
            f"SESSION_ID={last_r.get('session_id')} "
            f"at={last_r.get('timestamp')}\n"
            f"内容预览: {last_r.get('content')}"
        )
    else:
        print("最近 tool_result: 未找到")

    if debug_file is not None:
        print(f"Debug 日志: {debug_file}")
    else:
        print("Debug 日志: 未找到")

    if debug_lines:
        print("\n最近 codex 运行轨迹:")
        for line in debug_lines[-8:]:
            print(line)
    else:
        print("\n最近 codex 运行轨迹: 未匹配到")

    if unknown_results:
        latest = unknown_results[-1]
        print("\n检测到 unknown message ID 回包（可能是中断后迟到回包）:")
        print(f"success={latest.get('success')}, SESSION_ID={latest.get('session_id')}")
        preview = latest.get("agent_messages_preview", "")
        if preview:
            print(f"agent_messages 预览: {preview}")


def follow_debug(debug_file: Path) -> None:
    print(f"开始跟踪: {debug_file}")
    print("只显示 codex MCP 相关行。按 Ctrl+C 退出。\n")
    with debug_file.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.4)
                continue
            if 'MCP server "codex"' in line or "unknown message ID" in line:
                print(line.rstrip())


def main() -> int:
    parser = argparse.ArgumentParser(description="诊断 cc-codex MCP 调用状态")
    parser.add_argument(
        "--project",
        default=".",
        help="项目目录（默认当前目录）",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="持续跟踪当前会话 debug 日志中的 codex 行",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="可选：手动指定 Claude 会话 ID（不指定则自动选择）",
    )
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    home = Path.home()
    encoded = encode_project_path(project_dir)
    project_store = home / ".claude" / "projects" / encoded
    if not project_store.exists():
        print(f"未找到项目日志目录: {project_store}", file=sys.stderr)
        return 2

    session_files = list_session_files_by_mtime(project_store)
    if not session_files:
        print(f"未找到会话文件: {project_store}/*.jsonl", file=sys.stderr)
        return 2

    latest_sid = session_files[0].stem
    session_id = pick_session_id(home, project_store, args.session_id)
    if session_id is None:
        print(f"未找到可用会话: {project_store}", file=sys.stderr)
        return 2
    fallback_used = (not args.session_id) and session_id != latest_sid

    session_dir = project_store / session_id
    main_session_file = find_main_session_file(project_store, session_id)
    main_rows = read_jsonl(main_session_file) if main_session_file else []
    main_events = extract_codex_events(main_rows)

    subagent_file = find_latest_subagent_file(session_dir)
    sub_rows = read_jsonl(subagent_file) if subagent_file else []
    sub_events = extract_codex_events(sub_rows)
    events = merge_events([main_events, sub_events])

    debug_file = home / ".claude" / "debug" / f"{session_id}.txt"
    debug_text = ""
    if debug_file.exists():
        debug_text = debug_file.read_text(encoding="utf-8", errors="replace")
    debug_lines = extract_codex_debug_lines(debug_text) if debug_text else []
    unknown_results = parse_unknown_message_responses(debug_text) if debug_text else []

    print_summary(
        project_dir=project_dir,
        session_id=session_id,
        fallback_used=fallback_used,
        main_session_file=main_session_file,
        subagent_file=subagent_file,
        events=events,
        debug_file=debug_file if debug_file.exists() else None,
        debug_lines=debug_lines,
        unknown_results=unknown_results,
    )

    if args.follow and debug_file.exists():
        print("")
        follow_debug(debug_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
