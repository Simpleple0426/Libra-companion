"""Chat threads, messages, shared memories and letters repository."""
import json
from datetime import datetime, timedelta

from .database import get_connection


def get_context_message_counts(now):
    """Count all messages up to now, with calendar days in Shanghai time."""
    from zoneinfo import ZoneInfo
    from domains.affect.contracts import iso
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    connection = get_connection()
    try:
        # Legacy timestamps without an offset are local Shanghai wall time.
        row = connection.execute("""
            WITH times AS (
                SELECT julianday(CASE
                    WHEN substr(created_at, -1) = 'Z'
                         OR instr(substr(created_at, 11), '+') > 0
                         OR instr(substr(created_at, 11), '-') > 0
                    THEN created_at ELSE created_at || '+08:00' END) AS at
                FROM messages
            )
            SELECT COALESCE(SUM(at >= julianday(?)), 0) AS messages_last_60m,
                   COALESCE(SUM(at >= julianday(?)), 0) AS messages_today
            FROM times WHERE at <= julianday(?)
        """, (iso(now - timedelta(hours=1)), iso(start), iso(now))).fetchone()
        return dict(row)
    finally:
        connection.close()


def save_thread(thread_id: str, provider: str = "codex"):
    connection = get_connection()
    cursor = connection.cursor()

    now = datetime.now().isoformat()

    cursor.execute(
        """
        INSERT INTO threads (
            thread_id,
            provider,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(thread_id)
        DO UPDATE SET
            provider = excluded.provider,
            updated_at = excluded.updated_at
        """,
        (
            thread_id,
            provider,
            now,
            now,
        ),
    )

    connection.commit()
    connection.close()


def get_latest_thread(provider: str = "codex"):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT thread_id
        FROM threads
        WHERE provider = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (provider,),
    )

    row = cursor.fetchone()

    connection.close()

    if row:
        return row["thread_id"]

    return None


def save_message(
    role: str,
    content: str,
    source: str = "chat",
    message_type: str = "text",
    media_url: str | None = None,
    duration_seconds: int | None = None,
    *, connection=None, voice_emotion=None,
):
    owns_connection = connection is None
    connection = connection if connection is not None else get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO messages (
            role,
            content,
            created_at,
            source
            , message_type
            , media_url, duration_seconds
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            role,
            content,
            datetime.now().isoformat(),
            source,
            message_type,
            media_url,
            duration_seconds,
        ),
    )

    message_id = cursor.lastrowid
    # Capture raw evidence atomically with the chat message once V2 is initialized.
    # A failed insert rolls back both records; it cannot silently lose evidence.
    from domains.memory.store import capture_message
    try:
        capture_message(connection, message_id, role, content, source, message_type)
        from domains.affect.service import capture_user_message
        capture_user_message(connection, message_id, role, content, source, message_type, voice_emotion=voice_emotion)
    except Exception:
        if owns_connection:
            connection.rollback()
            connection.close()
        raise
    if owns_connection:
        connection.commit()
        connection.close()
    return message_id


def get_chat_companion_stats() -> dict:
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    connection = get_connection()
    today_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM messages
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) < datetime(?)
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()["count"]
    last_row = connection.execute(
        """
        SELECT created_at
        FROM messages
        WHERE role = 'user'
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    connection.close()
    return {
        "today_message_count": int(today_count),
        "last_chat_at": last_row["created_at"] if last_row else None,
    }

def get_messages(limit: int = 100):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT m.id, m.role, m.content, m.created_at, m.source, m.message_type,
               m.media_url, m.duration_seconds,
               (SELECT substr(ci.request_key, 6)
                  FROM cognition_inputs ci
                 WHERE ci.message_id = m.id AND ci.request_key LIKE 'chat:%'
                 LIMIT 1) AS request_id
        FROM messages m
        WHERE m.source NOT IN ('movie_watch','movie_chat','music_room')
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (limit,),
    )

    rows = cursor.fetchall()
    connection.close()

    # 因为 SQL 是从新到旧取的，
    # 返回给聊天界面时再反转成从旧到新
    rows = list(reversed(rows))

    return [
        {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
            "source": row["source"],
            "message_type": row["message_type"],
            "media_url": row["media_url"],
            "duration_seconds": row["duration_seconds"],
            "request_id": row["request_id"],
        }
        for row in rows
    ]


def get_messages_after(after_id: int, source: str | None = None, limit: int = 50):
    connection = get_connection()
    if source:
        rows = connection.execute(
            """
            SELECT m.id, m.role, m.content, m.created_at, m.source, m.message_type,
                   m.media_url, m.duration_seconds,
                   (SELECT substr(ci.request_key, 6) FROM cognition_inputs ci
                     WHERE ci.message_id=m.id AND ci.request_key LIKE 'chat:%' LIMIT 1) AS request_id
            FROM messages m
            WHERE m.id > ? AND m.source = ?
            ORDER BY m.id ASC LIMIT ?
            """,
            (after_id, source, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT m.id, m.role, m.content, m.created_at, m.source, m.message_type,
                   m.media_url, m.duration_seconds,
                   (SELECT substr(ci.request_key, 6) FROM cognition_inputs ci
                     WHERE ci.message_id=m.id AND ci.request_key LIKE 'chat:%' LIMIT 1) AS request_id
            FROM messages m
            WHERE m.id > ? AND m.source NOT IN ('movie_watch','movie_chat','music_room') ORDER BY m.id ASC LIMIT ?
            """,
            (after_id, limit),
        ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_message_updates_after(
    after_id: int,
    limit: int = 50,
) -> list[dict]:
    """Return persisted messages, including replies whose HTTP client disconnected."""
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT id, role, content, created_at, source, message_type, media_url,
               duration_seconds
        FROM messages
        WHERE id > ? AND source NOT IN ('movie_watch','movie_chat','music_room')
        ORDER BY id ASC LIMIT ?
        """,
        (after_id, max(1, min(limit, 200))),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def create_shared_memory(
    memory_type: str,
    content: str,
    *,
    author: str = "libra",
    media_url: str | None = None,
    source_message_id: int | None = None,
    source_world_event_id: str | None = None,
    event_date: str | None = None,
    location_text: str | None = None,
    taken_at: str | None = None,
    connection=None,
) -> dict:
    owns_connection = connection is None
    connection = connection if connection is not None else get_connection()
    now = datetime.now().isoformat()
    target_date = event_date or datetime.now().date().isoformat()
    cursor = connection.execute(
        """
        INSERT INTO shared_moments (
            memory_type, author, content, media_url, source_message_id,
            source_world_event_id, event_date, created_at, location_text, taken_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(memory_type, source_message_id) DO UPDATE SET
            content=excluded.content, media_url=excluded.media_url,
            author=excluded.author, status='published',
            source_world_event_id=COALESCE(excluded.source_world_event_id, shared_moments.source_world_event_id),
            location_text=COALESCE(excluded.location_text, shared_moments.location_text),
            taken_at=COALESCE(excluded.taken_at, shared_moments.taken_at)
        """,
        (memory_type, author, content, media_url, source_message_id,
         source_world_event_id, target_date, now, location_text, taken_at),
    )
    memory_id = cursor.lastrowid
    if not memory_id and source_message_id is not None:
        row = connection.execute(
            "SELECT id FROM shared_moments WHERE memory_type = ? AND source_message_id = ?",
            (memory_type, source_message_id),
        ).fetchone()
        memory_id = row["id"] if row else 0
    if owns_connection:
        connection.commit()
    row = connection.execute(
        "SELECT * FROM shared_moments WHERE id = ?", (memory_id,)
    ).fetchone()
    if owns_connection:
        connection.close()
    return dict(row) if row else {}


def get_shared_memories(memory_type: str | None = None, limit: int = 100) -> list[dict]:
    connection = get_connection()
    if memory_type:
        rows = connection.execute(
            """SELECT * FROM shared_moments
               WHERE status = 'published' AND memory_type = ?
               ORDER BY event_date DESC, id DESC LIMIT ?""",
            (memory_type, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            """SELECT * FROM shared_moments WHERE status = 'published'
               ORDER BY event_date DESC, id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    values = [dict(row) for row in rows]
    if values:
        ids = [item["id"] for item in values]
        placeholders = ",".join("?" for _ in ids)
        comments = connection.execute(
            f"""SELECT id, memory_id, author, content, created_at
                FROM shared_moment_comments
                WHERE memory_id IN ({placeholders}) ORDER BY id ASC""",
            ids,
        ).fetchall()
        grouped: dict[int, list[dict]] = {memory_id: [] for memory_id in ids}
        for comment in comments:
            grouped[comment["memory_id"]].append(dict(comment))
        for item in values:
            item["comments"] = grouped[item["id"]]
    connection.close()
    return values


def delete_shared_memory(memory_id: int) -> bool:
    connection = get_connection()
    cursor = connection.execute("DELETE FROM shared_moments WHERE id = ?", (memory_id,))
    connection.commit()
    changed = cursor.rowcount > 0
    connection.close()
    return changed


def update_shared_memory_location(memory_id: int, location_text: str | None) -> dict | None:
    connection = get_connection()
    connection.execute(
        "UPDATE shared_moments SET location_text = ? WHERE id = ?",
        (location_text or None, memory_id),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM shared_moments WHERE id = ?", (memory_id,)).fetchone()
    connection.close()
    return dict(row) if row else None


def get_shared_memory(memory_id: int) -> dict | None:
    connection = get_connection()
    row = connection.execute(
        "SELECT * FROM shared_moments WHERE id = ?", (memory_id,)
    ).fetchone()
    connection.close()
    return dict(row) if row else None


def get_shared_memory_comments(memory_id: int) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """SELECT id, memory_id, author, content, created_at
             FROM shared_moment_comments
            WHERE memory_id = ? ORDER BY id ASC""",
        (memory_id,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def create_shared_memory_comment(
    memory_id: int, author: str, content: str, *, connection=None
) -> dict:
    owns_connection = connection is None
    connection = connection if connection is not None else get_connection()
    now = datetime.now().isoformat()
    cursor = connection.execute(
        """INSERT INTO shared_moment_comments
           (memory_id, author, content, created_at) VALUES (?, ?, ?, ?)""",
        (memory_id, author, content, now),
    )
    comment_id = cursor.lastrowid
    if owns_connection:
        connection.commit()
    row = connection.execute(
        "SELECT id, memory_id, author, content, created_at FROM shared_moment_comments WHERE id = ?",
        (comment_id,),
    ).fetchone()
    if owns_connection:
        connection.close()
    return dict(row)


def get_messages_for_date(
    date_text: str,
    limit: int | None = 200,
) -> list[dict]:
    connection = get_connection()
    sql = """SELECT m.id, m.role, m.content, m.created_at, m.source,
                    m.message_type, m.media_url, m.duration_seconds,
                    (SELECT substr(ci.request_key, 6) FROM cognition_inputs ci
                      WHERE ci.message_id=m.id AND ci.request_key LIKE 'chat:%' LIMIT 1) AS request_id,
                    CASE WHEN f.message_id IS NULL THEN 0 ELSE 1 END AS favorite
             FROM messages m
             LEFT JOIN favorite_messages f ON f.message_id = m.id
             WHERE substr(m.created_at, 1, 10) = ? AND m.source NOT IN ('movie_watch','movie_chat','music_room')
             ORDER BY m.id ASC"""
    params: tuple = (date_text,)
    if limit is not None:
        sql += " LIMIT ?"
        params = (date_text, max(1, limit))
    rows = connection.execute(sql, params).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_messages_for_source_date(source: str, date_text: str) -> list[dict]:
    """Return one room's persisted conversation for a calendar day."""
    connection = get_connection()
    rows = connection.execute(
        """SELECT id, role, content, created_at, source, message_type,
                  media_url, duration_seconds
             FROM messages
            WHERE source = ? AND substr(created_at, 1, 10) = ?
            ORDER BY id ASC""",
        (source, date_text),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_messages_between(start_at: datetime, end_at: datetime, *, include_rooms: bool = False) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """SELECT m.id, m.role, m.content, m.created_at, m.source,
                  m.message_type, m.media_url, m.duration_seconds,
                  (SELECT substr(ci.request_key, 6) FROM cognition_inputs ci
                    WHERE ci.message_id=m.id AND ci.request_key LIKE 'chat:%' LIMIT 1) AS request_id,
                  CASE WHEN f.message_id IS NULL THEN 0 ELSE 1 END AS favorite
             FROM messages m
             LEFT JOIN favorite_messages f ON f.message_id = m.id
            WHERE (? OR m.source NOT IN ('movie_watch','movie_chat','music_room'))
              AND datetime(m.created_at, CASE
                  WHEN substr(m.created_at,-1)='Z' OR instr(substr(m.created_at,20),'+')>0
                    OR instr(substr(m.created_at,20),'-')>0 THEN '+8 hours' ELSE '+0 hours' END) >= datetime(?)
              AND datetime(m.created_at, CASE
                  WHEN substr(m.created_at,-1)='Z' OR instr(substr(m.created_at,20),'+')>0
                    OR instr(substr(m.created_at,20),'-')>0 THEN '+8 hours' ELSE '+0 hours' END) < datetime(?)
            ORDER BY m.id ASC""",
        (int(include_rooms), start_at.isoformat(), end_at.isoformat()),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def search_messages(query: str, limit: int = 200) -> list[dict]:
    """Search both sides of the chat history by a literal text fragment."""
    keyword = str(query or "").strip()
    if not keyword:
        return []

    # Escape LIKE metacharacters so users can search for the text they typed.
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT m.id, m.role, m.content, m.created_at, m.source, m.message_type, m.media_url,
               m.duration_seconds,
               CASE WHEN f.message_id IS NULL THEN 0 ELSE 1 END AS favorite
        FROM messages m
        LEFT JOIN favorite_messages f ON f.message_id = m.id
        WHERE m.source NOT IN ('movie_watch','movie_chat','music_room') AND m.content LIKE ? ESCAPE '\\'
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (f"%{escaped}%", max(1, min(int(limit), 500))),
    ).fetchall()
    connection.close()
    return [dict(row) for row in reversed(rows)]


def set_message_favorite(message_id: int, favorite: bool) -> dict | None:
    connection = get_connection()
    message = connection.execute(
        "SELECT id FROM messages WHERE id = ? AND role = 'assistant'",
        (message_id,),
    ).fetchone()
    if message is None:
        connection.close()
        return None
    if favorite:
        connection.execute(
            "INSERT OR IGNORE INTO favorite_messages (message_id, created_at) VALUES (?, ?)",
            (message_id, datetime.now().isoformat()),
        )
    else:
        connection.execute(
            "DELETE FROM favorite_messages WHERE message_id = ?",
            (message_id,),
        )
    connection.commit()
    connection.close()
    return {"message_id": message_id, "favorite": favorite}


def get_favorite_messages() -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """SELECT m.id, m.role, m.content, m.created_at, m.source,
                  m.message_type, m.media_url, m.duration_seconds, 1 AS favorite
           FROM favorite_messages f
           JOIN messages m ON m.id = f.message_id
           WHERE m.source NOT IN ('movie_watch','movie_chat','music_room')
           ORDER BY datetime(f.created_at) DESC, m.id DESC"""
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def create_letter(
    sender: str,
    content: str,
    subject: str = "",
    reply_to_id: int | None = None,
    *,
    letter_type: str | None = None,
    trigger_reason: str = "",
    trigger_key: str = "",
    event_date: str | None = None,
    memory_candidates: list | None = None,
    generation_source: str = "manual",
    connection=None,
) -> dict:
    now = datetime.now().isoformat()
    owns_connection = connection is None
    connection = connection if connection is not None else get_connection()
    cursor = connection.execute(
        """INSERT INTO letters
           (sender, subject, content, status, reply_to_id, created_at,
            delivered_at, read_at, letter_type, trigger_reason, trigger_key,
            event_date, memory_candidates_json, generation_source)
           VALUES (?, ?, ?, 'delivered', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sender, subject[:100], content[:10000], reply_to_id, now, now,
            now if sender == "user" else None, letter_type,
            trigger_reason[:500], trigger_key[:200], event_date,
            json.dumps(memory_candidates or [], ensure_ascii=False),
            generation_source[:40] or "manual",
        ),
    )
    if owns_connection:
        connection.commit()
    row = connection.execute("SELECT * FROM letters WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if owns_connection:
        connection.close()
    return dict(row)


def get_letter_by_trigger_key(trigger_key: str) -> dict | None:
    if not trigger_key.strip():
        return None
    connection = get_connection()
    row = connection.execute(
        "SELECT * FROM letters WHERE trigger_key = ? LIMIT 1",
        (trigger_key.strip(),),
    ).fetchone()
    connection.close()
    return dict(row) if row else None


def get_proactive_letter_for_date(event_date: str) -> dict | None:
    connection = get_connection()
    try:
        row = connection.execute("""SELECT * FROM letters
            WHERE sender='libra' AND generation_source='proactive' AND event_date=?
            ORDER BY id DESC LIMIT 1""", (event_date,)).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def get_letter(letter_id: int) -> dict | None:
    connection = get_connection()
    try:
        row = connection.execute('SELECT * FROM letters WHERE id = ?', (letter_id,)).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def get_letter_thread(letter_id: int) -> list[dict]:
    connection = get_connection()
    try:
        ancestors = connection.execute('''WITH RECURSIVE chain(id,reply_to_id) AS (
            SELECT id,reply_to_id FROM letters WHERE id=?
            UNION SELECT l.id,l.reply_to_id FROM letters l JOIN chain c ON l.id=c.reply_to_id
            ) SELECT id,reply_to_id FROM chain''', (letter_id,)).fetchall()
        if not ancestors:
            return []
        root = next((row['id'] for row in ancestors if row['reply_to_id'] is None),
                    min(row['id'] for row in ancestors))
        rows = connection.execute('''WITH RECURSIVE thread(id) AS (
            SELECT id FROM letters WHERE id=?
            UNION SELECT l.id FROM letters l JOIN thread t ON l.reply_to_id=t.id
            ) SELECT * FROM letters WHERE id IN (SELECT id FROM thread) AND id<=?
            ORDER BY created_at,id''', (root, letter_id)).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_letters(limit: int = 100) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        "SELECT * FROM letters ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(limit, 300)),),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def mark_letter_read(letter_id: int) -> dict | None:
    connection = get_connection()
    connection.execute(
        "UPDATE letters SET read_at = COALESCE(read_at, ?) WHERE id = ? AND sender = 'libra'",
        (datetime.now().isoformat(), letter_id),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM letters WHERE id = ?", (letter_id,)).fetchone()
    connection.close()
    return dict(row) if row else None


def set_letter_favorite(letter_id: int, favorite: bool) -> dict | None:
    connection = get_connection()
    connection.execute(
        "UPDATE letters SET favorite = ? WHERE id = ?",
        (1 if favorite else 0, letter_id),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM letters WHERE id = ?", (letter_id,)).fetchone()
    connection.close()
    return dict(row) if row else None
