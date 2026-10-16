"""Policy and durable records for Libra's self-directed Xiaohongshu browsing."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from infrastructure.sqlite.database import get_connection


def day_counts(now: datetime) -> dict[str, int]:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    connection = get_connection()
    try:
        row = connection.execute(
            """SELECT COUNT(*) AS browsed,
                      COALESCE(SUM(CASE WHEN shared=1 THEN 1 ELSE 0 END),0) AS shared
                 FROM xhs_browse_sessions WHERE created_at>=?""",
            (start,),
        ).fetchone()
        return {"browsed": int(row[0]), "shared": int(row[1])}
    finally:
        connection.close()


def may_browse(now: datetime, state: dict | None) -> tuple[bool, str]:
    if not 10 <= now.hour < 23:
        return False, "outside_browsing_window"
    state_type = str((state or {}).get("state_type") or "free")
    if state_type not in {"free", "leisure", "resting"}:
        return False, f"state_{state_type}"
    return True, "allowed"


def may_share(now: datetime) -> bool:
    return True


def recent_context(limit: int = 6) -> str:
    connection = get_connection()
    try:
        rows = connection.execute(
            """SELECT motive_type,trigger_text,search_query,status,reaction_text,shared,created_at
                 FROM xhs_browse_sessions ORDER BY created_at DESC,id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        return "最近没有自主浏览记录。"
    lines = []
    for row in reversed(rows):
        reaction = str(row[4] or "").strip()
        lines.append(
            f"- {str(row[6])[-16:]} [{row[0]}] {row[2]}；"
            f"状态={row[3]}；已分享={'是' if row[5] else '否'}"
            + (f"；留下的想法={reaction[:180]}" if reaction else "")
        )
    return "\n".join(lines)


def retained_chat_context(now: datetime | None = None, limit: int = 3) -> str:
    """Unshared, actually-read discoveries that may become later conversation topics."""
    current = now or datetime.now()
    cutoff = (current - timedelta(days=7)).isoformat()
    connection = get_connection()
    try:
        rows = connection.execute(
            """SELECT session_id,trigger_text,search_query,selected_note_id,
                      reaction_text,created_at
                 FROM xhs_browse_sessions
                WHERE status='retained' AND reaction_text<>'' AND created_at>=?
                ORDER BY created_at DESC,id DESC LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        return ""
    lines = [
        "\n<retained_xiaohongshu_thoughts>",
        "以下是你过去七天确实浏览过、但没有主动发给用户的内容所留下的想法。",
        "它们只是可选话题；仅在当前对话自然相关时引用。不得说成刚刚看到，也不得补造原文细节或链接。",
    ]
    for row in rows:
        lines.append(
            f"- [{row[0]}] 浏览时间={row[5]}；关键词={row[2]}；"
            f"当时缘由={row[1]}；留下的想法={row[4]}"
        )
    lines.append("</retained_xiaohongshu_thoughts>")
    return "\n".join(lines)


def create_session(motive_type: str, trigger_text: str, query: str, now: datetime) -> str:
    session_id = f"xhs-{now:%Y%m%d}-{uuid.uuid4().hex[:12]}"
    connection = get_connection()
    try:
        connection.execute(
            """INSERT INTO xhs_browse_sessions
               (session_id,motive_type,trigger_text,search_query,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, motive_type[:40], trigger_text[:500], query[:100],
             "planned", now.isoformat(), now.isoformat()),
        )
        connection.commit()
        return session_id
    finally:
        connection.close()


def finish_session(
    session_id: str, *, status: str, selected_note_id: str = "",
    reaction_text: str = "", shared: bool = False,
    source_message_id: int | None = None, now: datetime | None = None,
) -> None:
    current = now or datetime.now()
    connection = get_connection()
    try:
        connection.execute(
            """UPDATE xhs_browse_sessions
                  SET status=?,selected_note_id=?,reaction_text=?,shared=?,
                      source_message_id=?,updated_at=? WHERE session_id=?""",
            (status, selected_note_id, reaction_text[:1200], int(shared),
             source_message_id, current.isoformat(), session_id),
        )
        connection.commit()
    finally:
        connection.close()
