import json
from contextlib import closing
import re
from pathlib import Path

from infrastructure.paths import BACKUP_ROOT, COGNITION_DATABASE_PATH, CONTENT_DATABASE_PATH, DATABASE_PATH
from infrastructure.sqlite.connection import COGNITION_TABLES, CONTENT_TABLES, connect, write_transaction
from datetime import datetime, timedelta
from domains.world.time_boundary import day_start as libra_day_start


DB_PATH = DATABASE_PATH


def backup_database(keep: int = 3) -> Path:
    backup_dir = BACKUP_ROOT
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    targets = []
    for source_path in (DB_PATH, CONTENT_DATABASE_PATH, COGNITION_DATABASE_PATH):
        target = backup_dir / f"{source_path.stem}_{stamp}.db"
        source = connect(source_path, attach_shards=False)
        destination = connect(target, attach_shards=False)
        try:
            source.backup(destination, name="main")
        finally:
            destination.close()
            source.close()
        targets.append(target)
    for stem in (DB_PATH.stem, CONTENT_DATABASE_PATH.stem, COGNITION_DATABASE_PATH.stem):
        backups = sorted(backup_dir.glob(f"{stem}_*.db"), key=lambda path: path.stat().st_mtime)
        for stale in backups[:-max(1, keep)]:
            stale.unlink(missing_ok=True)
    return targets[0]


def get_connection():
    # The API, the check-in worker and a few background jobs may write at the
    # same time.  Let SQLite wait for the short-lived writer instead of
    # immediately failing a check-in with "database is locked".
    return connect(DB_PATH)


def init_database():
    connection = get_connection()
    # WAL allows readers (the app polls frequently) to continue while a
    # background task commits a small update.
    connection.execute("PRAGMA journal_mode = WAL")
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT UNIQUE NOT NULL,
            provider TEXT NOT NULL DEFAULT 'codex',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    thread_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(threads)").fetchall()
    }
    if "provider" not in thread_columns:
        cursor.execute(
            "ALTER TABLE threads ADD COLUMN provider TEXT NOT NULL DEFAULT 'codex'"
        )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    message_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(messages)").fetchall()
    }
    if "source" not in message_columns:
        cursor.execute(
            "ALTER TABLE messages ADD COLUMN source TEXT NOT NULL DEFAULT 'chat'"
        )
    if "message_type" not in message_columns:
        cursor.execute(
            "ALTER TABLE messages ADD COLUMN message_type TEXT NOT NULL DEFAULT 'text'"
        )
    if "media_url" not in message_columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN media_url TEXT")
    if "duration_seconds" not in message_columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN duration_seconds INTEGER")

    # Request identity is also initialized by TurnPipeline, but message-history
    # reads can happen independently (including during startup and tests).
    # Keeping the small identity table available here lets the API reconcile a
    # persisted user message with the mobile client's optimistic bubble.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cognition_inputs (
            request_key TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            message_id INTEGER NOT NULL REFERENCES messages(id),
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS favorite_messages (
            message_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_favorite_messages_created "
        "ON favorite_messages(created_at DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mobile_state (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS important_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            date_type TEXT NOT NULL CHECK (
                date_type IN ('anniversary', 'birthday', 'yearly', 'oneTime')
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_important_dates_date "
        "ON important_dates(date, id)"
    )
    legacy_important_dates = cursor.execute(
        "SELECT value_json FROM mobile_state WHERE key = 'important_dates'"
    ).fetchone()
    existing_important_dates = cursor.execute(
        "SELECT COUNT(*) AS count FROM important_dates"
    ).fetchone()["count"]
    if legacy_important_dates is not None and existing_important_dates == 0:
        try:
            legacy_items = json.loads(legacy_important_dates["value_json"])
        except (TypeError, json.JSONDecodeError):
            legacy_items = []
        now = datetime.now().isoformat()
        for item in legacy_items if isinstance(legacy_items, list) else []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()[:120]
            date = str(item.get("date") or "").strip()
            date_type = str(item.get("dateType") or "yearly")
            if not title or not date or date_type not in {
                "anniversary", "birthday", "yearly", "oneTime",
            }:
                continue
            cursor.execute(
                """
                INSERT INTO important_dates (id, title, date, date_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (item.get("id"), title, date, date_type, now, now),
            )
        cursor.execute("DELETE FROM mobile_state WHERE key = 'important_dates'")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS letters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL CHECK(sender IN ('user', 'libra')),
            subject TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'delivered',
            reply_to_id INTEGER,
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            read_at TEXT,
            FOREIGN KEY(reply_to_id) REFERENCES letters(id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_letters_created ON letters(created_at DESC)")
    letter_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(letters)").fetchall()
    }
    if "favorite" not in letter_columns:
        cursor.execute("ALTER TABLE letters ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
    letter_migrations = {
        "letter_type": "TEXT",
        "trigger_reason": "TEXT NOT NULL DEFAULT ''",
        "trigger_key": "TEXT NOT NULL DEFAULT ''",
        "event_date": "TEXT",
        "memory_candidates_json": "TEXT NOT NULL DEFAULT '[]'",
        "generation_source": "TEXT NOT NULL DEFAULT 'manual'",
    }
    for column, definition in letter_migrations.items():
        if column not in letter_columns:
            cursor.execute(f"ALTER TABLE letters ADD COLUMN {column} {definition}")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_letters_trigger_key "
        "ON letters(trigger_key) WHERE trigger_key != ''"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'calendar',
            app_name TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            description TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_calendar_events_occurred_at "
        "ON calendar_events(occurred_at, id)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            event TEXT NOT NULL DEFAULT ''
        )
        """
    )
    timeline_columns = {r['name'] for r in cursor.execute('PRAGMA table_info(user_timeline_events)')}
    if 'event_type' not in timeline_columns:
        cursor.execute("ALTER TABLE user_timeline_events ADD COLUMN event_type TEXT NOT NULL DEFAULT 'legacy'")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_timeline_events_occurred_at "
        "ON user_timeline_events(occurred_at DESC, id DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS libra_timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            event TEXT NOT NULL DEFAULT ''
        )
        """
    )
    legacy_libra_events = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='libra_events'"
    ).fetchone()
    if legacy_libra_events:
        cursor.execute(
            """
            INSERT OR IGNORE INTO libra_timeline_events (id, occurred_at, event)
            SELECT
                id,
                TRIM(occurred_at),
                TRIM(
                    CASE
                        WHEN description != '' THEN description
                        ELSE TRIM(event_type || ' ' || event_action || ' ' || COALESCE(location, ''))
                    END
                )
            FROM libra_events
            """
        )
        cursor.execute("DROP TABLE libra_events")
    cursor.execute("DROP INDEX IF EXISTS idx_libra_events_occurred_at")
    cursor.execute("DROP INDEX IF EXISTS idx_libra_events_type_action")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_libra_timeline_events_occurred_at "
        "ON libra_timeline_events(occurred_at DESC, id DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS libra_state_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            state_type TEXT NOT NULL,
            from_location TEXT NOT NULL DEFAULT '',
            end_location TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_libra_state_events_time "
        "ON libra_state_events(start_time DESC, end_time DESC, id DESC)"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_libra_state_events_unique "
        "ON libra_state_events(start_time, IFNULL(end_time, ''), state_type, "
        "from_location, end_location)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS life_threads (
            thread_id TEXT PRIMARY KEY,
            thread_type TEXT NOT NULL,
            title TEXT NOT NULL,
            stage TEXT NOT NULL,
            state_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'ongoing' CHECK (
                status IN ('ongoing', 'completed', 'abandoned')
            ),
            started_at TEXT NOT NULL,
            next_event_after TEXT,
            last_progressed_at TEXT NOT NULL,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_life_threads_due "
        "ON life_threads(status, next_event_after, updated_at)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS world_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            source_timeline_event_id INTEGER,
            source_state_event_id INTEGER,
            location TEXT NOT NULL DEFAULT '',
            state_type TEXT NOT NULL DEFAULT '',
            participants_json TEXT NOT NULL DEFAULT '[]',
            objects_json TEXT NOT NULL DEFAULT '[]',
            valence REAL NOT NULL DEFAULT 0,
            importance REAL NOT NULL DEFAULT 0,
            shareability REAL NOT NULL DEFAULT 0,
            thread_id TEXT,
            consequence_json TEXT NOT NULL DEFAULT '{}',
            occurred_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(source_timeline_event_id) REFERENCES libra_timeline_events(id),
            FOREIGN KEY(source_state_event_id) REFERENCES libra_state_events(id),
            FOREIGN KEY(thread_id) REFERENCES life_threads(thread_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_world_events_occurred "
        "ON world_events(occurred_at DESC, event_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_world_events_state_source "
        "ON world_events(source_state_event_id, occurred_at DESC)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS libra_thoughts (
            thought_id TEXT PRIMARY KEY,
            source_event_id TEXT NOT NULL,
            thread_id TEXT,
            content TEXT NOT NULL,
            topic_type TEXT NOT NULL,
            topic_score REAL NOT NULL DEFAULT 0,
            share_value REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'available' CHECK (
                status IN ('available', 'shared', 'expired', 'dismissed')
            ),
            expires_at TEXT,
            shared_message_id INTEGER,
            last_considered_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(source_event_id) REFERENCES world_events(event_id),
            FOREIGN KEY(shared_message_id) REFERENCES messages(id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_libra_thoughts_available "
        "ON libra_thoughts(status, expires_at, topic_score DESC, created_at DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS libra_attribute_effects (
            state_type TEXT PRIMARY KEY,
            fatigue_per_hour REAL NOT NULL,
            mood_per_hour REAL NOT NULL,
            stress_per_hour REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS libra_attribute_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_at TEXT NOT NULL UNIQUE,
            fatigue REAL NOT NULL,
            mood REAL NOT NULL,
            stress REAL NOT NULL,
            current_state TEXT NOT NULL DEFAULT 'free',
            status TEXT NOT NULL DEFAULT '放松',
            created_at TEXT NOT NULL
        )
        """
    )
    snapshot_columns = {
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(libra_attribute_snapshots)"
        ).fetchall()
    }
    if "current_state" not in snapshot_columns:
        cursor.execute(
            "ALTER TABLE libra_attribute_snapshots "
            "ADD COLUMN current_state TEXT NOT NULL DEFAULT 'free'"
        )
    if "status" not in snapshot_columns:
        cursor.execute(
            "ALTER TABLE libra_attribute_snapshots "
            "ADD COLUMN status TEXT NOT NULL DEFAULT '放松'"
        )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_libra_attribute_snapshots_time "
        "ON libra_attribute_snapshots(snapshot_at DESC)"
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS libra_attribute_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            fatigue_delta REAL NOT NULL DEFAULT 0,
            stress_delta REAL NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT ''
        )"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_libra_attribute_adjustments_time "
        "ON libra_attribute_adjustments(occurred_at DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS push_tokens (
            token TEXT PRIMARY KEY,
            platform TEXT NOT NULL DEFAULT 'android',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS call_sessions (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'active',
            started_at TEXT NOT NULL,
            ended_at TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS call_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            duration_seconds INTEGER,
            voice_tone TEXT,
            FOREIGN KEY(call_id) REFERENCES call_sessions(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS checkin_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            detail TEXT,
            message_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS weather_awareness_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS xhs_notes (
            note_id TEXT PRIMARY KEY,
            xsec_token TEXT NOT NULL DEFAULT '',
            canonical_url TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            content_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_xhs_notes_fetched "
        "ON xhs_notes(fetched_at DESC)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS xhs_search_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            result_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'chat',
            status TEXT NOT NULL DEFAULT 'success',
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_xhs_search_runs_created "
        "ON xhs_search_runs(created_at DESC, id DESC)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS xhs_browse_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            motive_type TEXT NOT NULL,
            trigger_text TEXT NOT NULL DEFAULT '',
            search_query TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'planned',
            selected_note_id TEXT NOT NULL DEFAULT '',
            reaction_text TEXT NOT NULL DEFAULT '',
            shared INTEGER NOT NULL DEFAULT 0,
            source_message_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(source_message_id) REFERENCES messages(id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_xhs_browse_sessions_created "
        "ON xhs_browse_sessions(created_at DESC, id DESC)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS xhs_shared_notes (
            note_id TEXT PRIMARY KEY,
            search_query TEXT NOT NULL DEFAULT '',
            shared_at TEXT NOT NULL,
            source_message_id INTEGER,
            FOREIGN KEY(note_id) REFERENCES xhs_notes(note_id),
            FOREIGN KEY(source_message_id) REFERENCES messages(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS focus_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key TEXT UNIQUE NOT NULL,
            started_at TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_started_at ON focus_sessions(started_at)"
    )
    focus_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(focus_sessions)").fetchall()
    }
    if "content" not in focus_columns:
        cursor.execute("ALTER TABLE focus_sessions ADD COLUMN content TEXT NOT NULL DEFAULT ''")
    if "timer_mode" not in focus_columns:
        cursor.execute(
            "ALTER TABLE focus_sessions ADD COLUMN timer_mode TEXT NOT NULL DEFAULT 'countdown'"
        )

    # One row per calendar date. Festival names remain owned by the existing
    # calendar feature; this table only describes whether Libra is working or
    # resting and whether the result comes from an official adjustment.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS work_calendar (
            date TEXT PRIMARY KEY NOT NULL,
            day_type TEXT NOT NULL
                CHECK(day_type IN ('workday', 'rest_day')),
            rest_type TEXT
                CHECK(rest_type IS NULL OR rest_type IN ('normal_weekend', 'holiday_leave')),
            is_adjusted INTEGER NOT NULL DEFAULT 0
                CHECK(is_adjusted IN (0, 1)),
            holiday_period TEXT,
            CHECK(
                (day_type = 'workday' AND rest_type IS NULL)
                OR
                (day_type = 'rest_day' AND rest_type IS NOT NULL)
            )
        )
        """
    )

    # These tables store the couple's moments/timeline, not Libra's cognitive
    # long-term memory. Preserve existing installations by renaming in place.
    legacy_shared_memory = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
    ).fetchone()
    old_shared_memory = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_memories'"
    ).fetchone()
    shared_moments_exists = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_moments'"
    ).fetchone()
    if old_shared_memory and not shared_moments_exists:
        cursor.execute("ALTER TABLE shared_memories RENAME TO shared_moments")
        shared_moments_exists = True
    elif legacy_shared_memory and not shared_moments_exists:
        cursor.execute("ALTER TABLE memories RENAME TO shared_moments")
        shared_moments_exists = True

    old_comments = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_memory_comments'"
    ).fetchone()
    new_comments = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_moment_comments'"
    ).fetchone()
    if old_comments and not new_comments:
        cursor.execute("ALTER TABLE shared_memory_comments RENAME TO shared_moment_comments")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shared_moments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT 'libra',
            content TEXT NOT NULL DEFAULT '',
            media_url TEXT,
            source_message_id INTEGER,
            source_world_event_id TEXT,
            event_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'published',
            created_at TEXT NOT NULL,
            UNIQUE(memory_type, source_message_id),
            FOREIGN KEY(source_message_id) REFERENCES messages(id),
            FOREIGN KEY(source_world_event_id) REFERENCES world_events(event_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_shared_moments_date ON shared_moments(event_date DESC, id DESC)"
    )
    cursor.execute("DROP INDEX IF EXISTS idx_shared_memories_date")
    cursor.execute("DROP INDEX IF EXISTS idx_memories_date")
    memory_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(shared_moments)").fetchall()
    }
    if "location_text" not in memory_columns:
        cursor.execute("ALTER TABLE shared_moments ADD COLUMN location_text TEXT")
    if "taken_at" not in memory_columns:
        cursor.execute("ALTER TABLE shared_moments ADD COLUMN taken_at TEXT")
    if "source_world_event_id" not in memory_columns:
        cursor.execute("ALTER TABLE shared_moments ADD COLUMN source_world_event_id TEXT")
    for name in ("source_kind", "source_title", "source_url"):
        if name not in memory_columns:
            cursor.execute(f"ALTER TABLE shared_moments ADD COLUMN {name} TEXT")
    cursor.execute("""CREATE TABLE IF NOT EXISTS life_moment_imports (
        source_key TEXT PRIMARY KEY, memory_id INTEGER NOT NULL
    )""")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shared_moment_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES shared_moments(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_shared_moment_comments ON shared_moment_comments(memory_id, id)"
    )
    cursor.execute("DROP INDEX IF EXISTS idx_shared_memory_comments")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            due_date TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            notified_at TEXT,
            praised_at TEXT
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_date, done)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            active_from TEXT NOT NULL DEFAULT '1900-01-01',
            active_until TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    habit_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(habits)").fetchall()
    }
    if "active_from" not in habit_columns:
        cursor.execute(
            "ALTER TABLE habits ADD COLUMN active_from TEXT NOT NULL DEFAULT '1900-01-01'"
        )
    if "active_until" not in habit_columns:
        cursor.execute("ALTER TABLE habits ADD COLUMN active_until TEXT")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS habit_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_local_id TEXT NOT NULL,
            checked_date TEXT NOT NULL,
            UNIQUE(habit_local_id, checked_date)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_habit_checkins_date ON habit_checkins(checked_date)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            occurred_at TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            thread_id TEXT,
            source TEXT NOT NULL DEFAULT 'model_call',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            cached_input_tokens INTEGER NOT NULL DEFAULT 0,
            uncached_input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            context_window INTEGER,
            imported_from TEXT NOT NULL DEFAULT 'live',
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_usage_occurred "
        "ON llm_usage_events(occurred_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_usage_thread "
        "ON llm_usage_events(thread_id, occurred_at DESC)"
    )

    # Remove the retired kitchen-inventory feature from existing databases.
    cursor.execute("DROP TABLE IF EXISTS kitchen_items")
    # The proactive candidate queue was replaced by UnifiedEvent + Response Plan.
    cursor.execute("DELETE FROM app_settings WHERE key='proactive_contact_v1'")

    connection.commit()
    # The legacy initializer remains the authoritative schema definition, but
    # routed tables live only in their shard. DDL is intentionally not routed
    # because SQLite qualifies CREATE INDEX differently from normal DML.
    if Path(DB_PATH).resolve() == DATABASE_PATH.resolve():
        for table in sorted(CONTENT_TABLES | COGNITION_TABLES):
            connection.execute(f'DROP TABLE IF EXISTS main."{table}"')
        connection.commit()
        with closing(connect(CONTENT_DATABASE_PATH)) as content_connection:
            from .content_schema import repair_moments
            repair_moments(content_connection)
            columns = {r["name"] for r in content_connection.execute("PRAGMA table_info(shared_moments)")}
            for name in ("source_kind", "source_title", "source_url"):
                if name not in columns:
                    content_connection.execute(f"ALTER TABLE shared_moments ADD COLUMN {name} TEXT")
            content_connection.execute("""CREATE TABLE IF NOT EXISTS life_moment_imports (
                source_key TEXT PRIMARY KEY, memory_id INTEGER NOT NULL
            )""")
            content_connection.commit()
    connection.close()


def save_checkin_event(status: str, detail: str = "", message_count: int = 0):
    connection = get_connection()
    connection.execute(
        """
        INSERT INTO checkin_events (status, detail, message_count, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (status, detail[:500], message_count, datetime.now().isoformat()),
    )
    connection.commit()
    connection.close()


def save_llm_usage_event(
    *,
    event_key: str,
    occurred_at: str,
    provider: str,
    model: str = "",
    thread_id: str | None = None,
    source: str = "model_call",
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_output_tokens: int = 0,
    total_tokens: int = 0,
    context_window: int | None = None,
    imported_from: str = "live",
) -> bool:
    input_tokens = max(0, int(input_tokens or 0))
    cached_input_tokens = max(0, min(input_tokens, int(cached_input_tokens or 0)))
    output_tokens = max(0, int(output_tokens or 0))
    reasoning_output_tokens = max(0, int(reasoning_output_tokens or 0))
    total_tokens = max(0, int(total_tokens or input_tokens + output_tokens))
    connection = get_connection()
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO llm_usage_events (
            event_key, occurred_at, provider, model, thread_id, source,
            input_tokens, cached_input_tokens, uncached_input_tokens,
            output_tokens, reasoning_output_tokens, total_tokens,
            context_window, imported_from, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_key,
            occurred_at,
            provider,
            model,
            thread_id,
            source,
            input_tokens,
            cached_input_tokens,
            input_tokens - cached_input_tokens,
            output_tokens,
            reasoning_output_tokens,
            total_tokens,
            context_window,
            imported_from,
            datetime.now().isoformat(),
        ),
    )
    connection.commit()
    inserted = cursor.rowcount > 0
    connection.close()
    return inserted


def create_libra_timeline_event(occurred_at: str, event: str) -> dict:
    raise RuntimeError("Retired schedule writer; life events must come from skill execution")


def get_libra_timeline_events(
    start_at: str | None = None,
    end_at: str | None = None,
    limit: int = 200,
) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT id, occurred_at, event
        FROM libra_timeline_events
        """
    ).fetchall()
    connection.close()
    start = _parse_libra_event_time(start_at) if start_at else None
    end = _parse_libra_event_time(end_at) if end_at else None
    items = [dict(row) for row in rows]
    if start:
        items = [
            item
            for item in items
            if _parse_libra_event_time(item["occurred_at"]) >= start
        ]
    if end:
        items = [
            item
            for item in items
            if _parse_libra_event_time(item["occurred_at"]) <= end
        ]
    items.sort(
        key=lambda item: (_parse_libra_event_time(item["occurred_at"]), item["id"]),
        reverse=True,
    )
    return items[: max(1, min(limit, 1000))]


def get_libra_state_at(at: datetime | None = None) -> dict | None:
    target = (at or datetime.now()).isoformat()
    connection = get_connection()
    row = connection.execute(
        """
        SELECT id, start_time, end_time, state_type,
               from_location, end_location
        FROM libra_state_events
        WHERE datetime(start_time) <= datetime(?)
          AND (end_time IS NULL OR datetime(end_time) > datetime(?))
        ORDER BY datetime(start_time) DESC, id DESC
        LIMIT 1
        """,
        (target, target),
    ).fetchone()
    connection.close()
    return dict(row) if row else None


def get_libra_state_before(start_time: str, state_id: int) -> dict | None:
    connection = get_connection()
    row = connection.execute(
        """
        SELECT id, start_time, end_time, state_type,
               from_location, end_location
        FROM libra_state_events
        WHERE datetime(start_time) < datetime(?)
           OR (datetime(start_time) = datetime(?) AND id < ?)
        ORDER BY datetime(start_time) DESC, id DESC
        LIMIT 1
        """,
        (start_time, start_time, state_id),
    ).fetchone()
    connection.close()
    return dict(row) if row else None


def get_libra_state_events(
    start_at: datetime,
    end_at: datetime,
    limit: int = 500,
) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT id, start_time, end_time, state_type,
               from_location, end_location
        FROM libra_state_events
        WHERE datetime(start_time) >= datetime(?)
          AND datetime(start_time) < datetime(?)
        ORDER BY datetime(start_time), id
        LIMIT ?
        """,
        (start_at.isoformat(), end_at.isoformat(), max(1, min(limit, 1000))),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]










def get_latest_libra_attributes(at: datetime | None = None) -> dict | None:
    """Retired compatibility read; current needs belong to the life system."""
    return None


def get_libra_attribute_snapshots_for_date(date_text: str) -> list[dict]:
    """Return snapshots in the selected 04:00-to-04:00 schedule day."""
    start = datetime.fromisoformat(date_text).replace(hour=4)
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT id, snapshot_at, fatigue, mood, stress,
               current_state, status, created_at
        FROM libra_attribute_snapshots
        WHERE datetime(snapshot_at) >= datetime(?) AND datetime(snapshot_at) < datetime(?)
        ORDER BY datetime(snapshot_at), id
        """,
        (start.isoformat(), (start + timedelta(days=1)).isoformat()),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_libra_attribute_effects() -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        "SELECT state_type, fatigue_per_hour, mood_per_hour, stress_per_hour, updated_at "
        "FROM libra_attribute_effects ORDER BY rowid"
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def _parse_libra_event_time(value: str) -> datetime:
    text = value.strip() if isinstance(value, str) else ""
    # Older timeline rows use the dotted display format, while imported and
    # seeded rows may use SQLite/ISO timestamps.  Queries scan both sets, so a
    # single ISO row must not make the whole timeline endpoint fail.
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%Y.%m.%d %H:%M")
    except (AttributeError, ValueError) as error:
        raise ValueError("时间格式必须为：2026.8.20 16:30") from error


def _normalize_libra_event_time(value: str) -> str:
    parsed = _parse_libra_event_time(value)
    return f"{parsed.year}.{parsed.month}.{parsed.day} {parsed:%H:%M}"


def replace_work_calendar_year(year: int, days: list[dict]) -> int:
    """Atomically replace a full year of work/rest calendar records."""
    if year < 1900 or year > 9999:
        raise ValueError("year must be between 1900 and 9999")

    expected_prefix = f"{year:04d}-"
    normalized = []
    seen_dates = set()
    for day in days:
        date_text = str(day["date"])
        try:
            parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError as error:
            raise ValueError(f"invalid work calendar date: {date_text}") from error
        if not date_text.startswith(expected_prefix) or parsed_date.year != year:
            raise ValueError(f"date {date_text} does not belong to {year}")
        if date_text in seen_dates:
            raise ValueError(f"duplicate work calendar date: {date_text}")
        seen_dates.add(date_text)

        day_type = str(day["day_type"])
        rest_type = day.get("rest_type")
        if day_type not in {"workday", "rest_day"}:
            raise ValueError(f"invalid day_type for {date_text}: {day_type}")
        if rest_type not in {None, "normal_weekend", "holiday_leave"}:
            raise ValueError(f"invalid rest_type for {date_text}: {rest_type}")
        if (day_type == "workday") != (rest_type is None):
            raise ValueError(f"day_type/rest_type conflict for {date_text}")

        holiday_period = day.get("holiday_period")
        normalized.append(
            (
                date_text,
                day_type,
                rest_type,
                int(bool(day.get("is_adjusted", False))),
                str(holiday_period).strip() if holiday_period else None,
            )
        )

    first_day = datetime(year, 1, 1).date()
    expected_days = (datetime(year + 1, 1, 1).date() - first_day).days
    if len(normalized) != expected_days:
        raise ValueError(
            f"work calendar for {year} must contain {expected_days} days, got {len(normalized)}"
        )

    connection = get_connection()
    try:
        connection.execute("BEGIN")
        connection.execute(
            "DELETE FROM work_calendar WHERE date >= ? AND date < ?",
            (f"{year:04d}-01-01", f"{year + 1:04d}-01-01"),
        )
        connection.executemany(
            """
            INSERT INTO work_calendar (
                date, day_type, rest_type, is_adjusted, holiday_period
            ) VALUES (?, ?, ?, ?, ?)
            """,
            normalized,
        )
        connection.commit()
        return len(normalized)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_work_calendar_day(date_text: str) -> dict | None:
    """Return the explicit work/rest status for one ISO date."""
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("date must use YYYY-MM-DD") from error

    connection = get_connection()
    row = connection.execute(
        """
        SELECT date, day_type, rest_type, is_adjusted, holiday_period
        FROM work_calendar
        WHERE date = ?
        """,
        (date_text,),
    ).fetchone()
    connection.close()
    if row is None:
        return None
    result = dict(row)
    result["is_adjusted"] = bool(result["is_adjusted"])
    return result


def get_work_calendar_days(start_date: str, end_date: str) -> list[dict]:
    """Return explicit work/rest statuses for an inclusive ISO date range."""
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("dates must use YYYY-MM-DD") from error
    if end < start:
        raise ValueError("end_date must not be earlier than start_date")
    if (end - start).days > 370:
        raise ValueError("work calendar range cannot exceed 371 days")

    connection = get_connection()
    rows = connection.execute(
        """
        SELECT date, day_type, rest_type, is_adjusted, holiday_period
        FROM work_calendar
        WHERE date >= ? AND date <= ?
        ORDER BY date
        """,
        (start_date, end_date),
    ).fetchall()
    connection.close()
    results = []
    for row in rows:
        item = dict(row)
        item["is_adjusted"] = bool(item["is_adjusted"])
        results.append(item)
    return results


def save_weather_awareness_event(
    event_id: str,
    status: str,
    payload: str,
    message_count: int = 0,
):
    connection = get_connection()
    connection.execute(
        """
        INSERT INTO weather_awareness_events (
            event_id, status, payload, message_count, created_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            status=excluded.status,
            payload=excluded.payload,
            message_count=excluded.message_count
        """,
        (
            event_id,
            status,
            payload[:4000],
            message_count,
            datetime.now().isoformat(),
        ),
    )
    connection.commit()
    connection.close()


def save_focus_sessions(sessions: list[dict]) -> int:
    connection = get_connection()
    inserted = 0
    now = datetime.now().isoformat()
    for session in sessions:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO focus_sessions (
                session_key, started_at, duration_seconds, content, timer_mode, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session["session_key"],
                session["started_at"],
                session["duration_seconds"],
                str(session.get("content") or "")[:120],
                "countup" if session.get("timer_mode") == "countup" else "countdown",
                now,
            ),
        )
        inserted += cursor.rowcount
    connection.commit()
    connection.close()
    return inserted


def get_focus_sessions(since: str) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT session_key, started_at, duration_seconds, content, timer_mode
        FROM focus_sessions
        WHERE started_at >= ?
        ORDER BY started_at ASC
        """,
        (since,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_checkin_events(limit: int = 50):
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT id, status, detail, message_count, created_at
        FROM checkin_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def start_call(call_id: str):
    connection = get_connection()
    connection.execute(
        "INSERT INTO call_sessions (id, status, started_at) VALUES (?, 'active', ?)",
        (call_id, datetime.now().isoformat()),
    )
    connection.commit()
    connection.close()


def save_call_turn(
    call_id: str,
    role: str,
    content: str,
    duration_seconds: int | None = None,
    voice_tone: str | None = None,
    *, connection=None,
):
    owns_connection = connection is None
    connection = connection if connection is not None else get_connection()
    cursor = connection.execute(
        """
        INSERT INTO call_turns (
            call_id, role, content, created_at, duration_seconds, voice_tone
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            call_id, role, content, datetime.now().isoformat(),
            duration_seconds, voice_tone,
        ),
    )
    from domains.affect.service import capture_call_turn
    capture_call_turn(connection, cursor.lastrowid, role, content)
    if owns_connection:
        connection.commit()
        connection.close()
    return cursor.lastrowid


def get_call_turns(call_id: str, limit: int = 8):
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT role, content, created_at
        FROM call_turns
        WHERE call_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (call_id, limit),
    ).fetchall()
    connection.close()
    return [dict(row) for row in reversed(rows)]


def finish_call(call_id: str):
    connection = get_connection()
    connection.execute(
        "UPDATE call_sessions SET status = 'finished', ended_at = ? WHERE id = ?",
        (datetime.now().isoformat(), call_id),
    )
    connection.commit()
    connection.close()


def save_push_token(token: str, platform: str = "android"):
    connection = get_connection()
    now = datetime.now().isoformat()
    connection.execute(
        """
        INSERT INTO push_tokens (token, platform, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(token) DO UPDATE SET
            platform = excluded.platform,
            updated_at = excluded.updated_at
        """,
        (token, platform, now, now),
    )
    connection.commit()
    connection.close()


def get_push_tokens() -> list[str]:
    connection = get_connection()
    rows = connection.execute(
        "SELECT token FROM push_tokens ORDER BY updated_at DESC"
    ).fetchall()
    connection.close()
    return [row["token"] for row in rows]


def delete_push_token(token: str):
    connection = get_connection()
    connection.execute("DELETE FROM push_tokens WHERE token = ?", (token,))
    connection.commit()
    connection.close()


def save_user_timeline_events(events: list[dict]) -> int:
    with closing(get_connection()) as connection, write_transaction(connection):
        cursor = connection.cursor()
        inserted = 0

        from application.user_activity_context import charging
        for event in events:
            if charging(event["description"]):
                continue
            cursor.execute(
                """
                INSERT INTO user_timeline_events (occurred_at, event, event_type)
                SELECT ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM user_timeline_events
                    WHERE occurred_at = ? AND event = ?
                )
                """,
                (
                    event["occurred_at"],
                    event["description"],
                    str(event.get("event_type") or "legacy")[:40],
                    event["occurred_at"],
                    event["description"],
                ),
            )
            inserted += cursor.rowcount
            if cursor.rowcount:
                from domains.affect.service import capture_life_activity
                capture_life_activity(connection, cursor.lastrowid, event['description'], event['occurred_at'])

        return inserted


def save_calendar_events(events: list[dict]) -> int:
    with closing(get_connection()) as connection, write_transaction(connection):
        cursor = connection.cursor()
        inserted = 0
        now = datetime.now().isoformat()

        for event in events:
            cursor.execute(
                """
                INSERT OR IGNORE INTO calendar_events (
                    event_key, event_type, app_name, action,
                    description, occurred_at, created_at
                ) VALUES (?, 'calendar', ?, ?, ?, ?, ?)
                """,
                (
                    event["event_key"],
                    event["app_name"],
                    event["action"],
                    event["description"],
                    event["occurred_at"],
                    now,
                ),
            )
            inserted += cursor.rowcount

        return inserted


def sync_calendar_events(
    events: list[dict],
    sync_start: str,
    sync_end: str,
    reconcile_system: bool = False,
) -> tuple[int, int]:
    """Replace the synced calendar snapshot inside a bounded time window."""
    with closing(get_connection()) as connection, write_transaction(connection):
        cursor = connection.cursor()
        incoming_keys = {event["event_key"] for event in events}
        source_names = ["节日日历"]
        if reconcile_system:
            source_names.append("系统日历")
        placeholders = ",".join("?" for _ in source_names)
        existing = cursor.execute(
            f"""
            SELECT id, event_key
            FROM calendar_events
            WHERE datetime(occurred_at) >= datetime(?)
              AND datetime(occurred_at) < datetime(?)
              AND app_name IN ({placeholders})
            """,
            (sync_start, sync_end, *source_names),
        ).fetchall()
        stale_ids = [row["id"] for row in existing if row["event_key"] not in incoming_keys]
        if stale_ids:
            cursor.executemany(
                "DELETE FROM calendar_events WHERE id = ?",
                ((event_id,) for event_id in stale_ids),
            )

        inserted = 0
        now = datetime.now().isoformat()
        for event in events:
            cursor.execute(
                """
                INSERT INTO calendar_events (
                    event_key, event_type, app_name, action,
                    description, occurred_at, created_at
                ) VALUES (?, 'calendar', ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
                    app_name = excluded.app_name,
                    action = excluded.action,
                    description = excluded.description,
                    occurred_at = excluded.occurred_at
                """,
                (
                    event["event_key"],
                    event["app_name"],
                    event["action"],
                    event["description"],
                    event["occurred_at"],
                    now,
                ),
            )
            inserted += cursor.rowcount
        return inserted, len(stale_ids)


def set_app_setting(key: str, value: str):
    connection = get_connection()
    connection.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, datetime.now().isoformat()),
    )
    connection.commit()
    connection.close()


def get_app_setting(key: str, default: str = "") -> str:
    connection = get_connection()
    row = connection.execute(
        "SELECT value FROM app_settings WHERE key = ?",
        (key,),
    ).fetchone()
    connection.close()
    return row["value"] if row else default


def get_mobile_state(key: str):
    if key == "important_dates":
        connection = get_connection()
        rows = connection.execute(
            """
            SELECT id, title, date, date_type
            FROM important_dates
            ORDER BY date, id
            """
        ).fetchall()
        connection.close()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "date": row["date"],
                "dateType": row["date_type"],
            }
            for row in rows
        ]
    connection = get_connection()
    row = connection.execute(
        "SELECT value_json FROM mobile_state WHERE key = ?", (key,)
    ).fetchone()
    connection.close()
    if row is None:
        return None
    try:
        return json.loads(row["value_json"])
    except json.JSONDecodeError:
        return None


def set_mobile_state(key: str, value) -> None:
    if key == "important_dates":
        if not isinstance(value, list):
            raise ValueError("important_dates must be a list")
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()[:120]
            date = str(item.get("date") or "").strip()
            date_type = str(item.get("dateType") or "yearly")
            if not title or not date or date_type not in {
                "anniversary", "birthday", "yearly", "oneTime",
            }:
                continue
            normalized.append((item.get("id"), title, date, date_type))
        connection = get_connection()
        now = datetime.now().isoformat()
        with connection:
            connection.execute("DELETE FROM important_dates")
            connection.executemany(
                """
                INSERT INTO important_dates (
                    id, title, date, date_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ((*item, now, now) for item in normalized),
            )
            connection.execute(
                "DELETE FROM mobile_state WHERE key = 'important_dates'"
            )
        connection.close()
        return
    connection = get_connection()
    connection.execute(
        """
        INSERT INTO mobile_state (key, value_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
          value_json=excluded.value_json,
          updated_at=excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=False), datetime.now().isoformat()),
    )
    connection.commit()
    connection.close()


def get_recent_user_timeline_events(limit: int = 8) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT event AS description, occurred_at, event_type
        FROM user_timeline_events
        ORDER BY occurred_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in reversed(rows)]


def get_calendar_context_events(
    days_ahead: int = 14,
    limit: int = 30,
    days_before: int = 0,
) -> list[dict]:
    connection = get_connection()
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=max(0, days_before))
    end = today + timedelta(days=max(1, days_ahead + 1))
    rows = connection.execute(
        """
        SELECT event_type, app_name, action, description, occurred_at
        FROM calendar_events
        WHERE datetime(occurred_at) >= datetime(?)
          AND datetime(occurred_at) < datetime(?)
          AND description NOT LIKE '%逝世%'
          AND description NOT LIKE '%诞辰纪念%'
          AND description NOT LIKE '%宣传日%'
        ORDER BY datetime(occurred_at), id
        LIMIT ?
        """,
        (start.isoformat(), end.isoformat(), limit),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def sync_todos(items: list[dict]) -> int:
    connection = get_connection()
    now = datetime.now().isoformat()
    # Partial/stale phone snapshots must not delete chat-created arrangements.
    # Deletions use the explicit DELETE endpoint and its reminder tombstone.
    from application.reminders import settings
    for item in items:
        # Bulk cache uploads do not edit existing reminder settings. Explicit
        # PUT is the editing boundary, so stale caches cannot re-arm delivery.
        existing_reminder = connection.execute(
            'SELECT local_id FROM todo_reminders WHERE local_id=?', (item['local_id'],)
        ).fetchone() if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='todo_reminders'"
        ).fetchone() else None
        settings_item = {'local_id': item['local_id']} if existing_reminder else item
        if not settings(connection, settings_item):
            continue
        done = 1 if item.get("done") else 0
        connection.execute(
            """
            INSERT INTO todos (local_id, title, due_date, done, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(local_id) DO UPDATE SET
              title=excluded.title, due_date=excluded.due_date, done=excluded.done,
              updated_at=excluded.updated_at,
              completed_at=CASE
                WHEN excluded.done=1 AND todos.done=0 THEN excluded.completed_at
                WHEN excluded.done=0 THEN NULL
                ELSE todos.completed_at
              END
            """,
            (item["local_id"], item["title"], item["due_date"], done, now, now if done else None),
        )
    connection.commit()
    connection.close()
    return len(items)


def get_chat_day_actions(day: str) -> tuple[list[dict], list[dict]]:
    """Bound chat context to a specified local day, not the entire todo table."""
    datetime.strptime(day, '%Y-%m-%d')
    connection = get_connection()
    try:
        todos = [dict(r) for r in connection.execute(
            'SELECT title,due_date FROM todos WHERE substr(due_date,1,10)=? AND done=0 ORDER BY due_date,id LIMIT 10', (day,))]
        habits = [dict(r) for r in connection.execute('''
            SELECT h.title, EXISTS(SELECT 1 FROM habit_checkins c
                WHERE c.habit_local_id=h.local_id AND c.checked_date=?) AS done
            FROM habits h WHERE h.active_from<=?
                AND (h.active_until IS NULL OR h.active_until>=?)
            ORDER BY h.id LIMIT 10''', (day, day, day))]
        for habit in habits:
            habit['done'] = bool(habit['done'])
        return todos, habits
    finally:
        connection.close()


def get_all_todos() -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        "SELECT local_id, title, due_date, done FROM todos ORDER BY due_date, id"
    ).fetchall()
    from application.reminders import enrich
    result = enrich(connection, [dict(row) for row in rows])
    connection.commit()
    connection.close()
    return result


def upsert_todo(item: dict) -> dict:
    connection = get_connection()
    from application.reminders import settings
    if not settings(connection, item):
        connection.close()
        raise ValueError('todo was deleted')
    now = datetime.now().isoformat()
    done = 1 if item.get("done") else 0
    connection.execute(
        """
        INSERT INTO todos (local_id, title, due_date, done, updated_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(local_id) DO UPDATE SET
          title=excluded.title, due_date=excluded.due_date, done=excluded.done,
          updated_at=excluded.updated_at,
          completed_at=CASE
            WHEN excluded.done=1 AND todos.done=0 THEN excluded.completed_at
            WHEN excluded.done=0 THEN NULL ELSE todos.completed_at END
        """,
        (item["local_id"], item["title"], item["due_date"], done, now, now if done else None),
    )
    connection.commit()
    row = connection.execute(
        "SELECT local_id,title,due_date,done FROM todos WHERE local_id=?",
        (item["local_id"],),
    ).fetchone()
    connection.close()
    return dict(row)


def delete_todo(local_id: str) -> bool:
    connection = get_connection()
    from application.reminders import cancel
    cancel(connection, local_id)
    cursor = connection.execute("DELETE FROM todos WHERE local_id=?", (local_id,))
    connection.commit()
    deleted = cursor.rowcount > 0
    connection.close()
    return deleted


def find_open_todos(query: str) -> list[dict]:
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT local_id,title,due_date,done FROM todos
        WHERE done=0 AND (title=? OR title LIKE ? OR ? LIKE '%' || title || '%')
        ORDER BY CASE WHEN title=? THEN 0 ELSE 1 END, due_date, id
        """,
        (query, f"%{query}%", query, query),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_todos_for_review() -> tuple[list[dict], list[dict]]:
    connection = get_connection()
    today = datetime.now().date().isoformat()
    open_items = connection.execute(
        "SELECT * FROM todos WHERE done=0 AND date(due_date)=date(?) AND notified_at IS NULL ORDER BY due_date, id",
        (today,),
    ).fetchall()
    completed_items = connection.execute(
        "SELECT * FROM todos WHERE done=1 AND date(due_date)=date(?) AND praised_at IS NULL ORDER BY completed_at, id",
        (today,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in open_items], [dict(row) for row in completed_items]


def mark_todos_reviewed(open_ids: list[int], completed_ids: list[int]):
    if not open_ids and not completed_ids:
        return
    connection = get_connection()
    now = datetime.now().isoformat()
    if open_ids:
        connection.executemany("UPDATE todos SET notified_at=? WHERE id=?", [(now, item_id) for item_id in open_ids])
    if completed_ids:
        connection.executemany("UPDATE todos SET praised_at=? WHERE id=?", [(now, item_id) for item_id in completed_ids])
    connection.commit()
    connection.close()


def sync_habits(items: list[dict]) -> int:
    """Replace the single device's habit list and its daily check-ins."""
    connection = get_connection()
    now = datetime.now().isoformat()
    local_ids = [item["local_id"] for item in items]
    if local_ids:
        placeholders = ",".join("?" for _ in local_ids)
        connection.execute(f"DELETE FROM habits WHERE local_id NOT IN ({placeholders})", local_ids)
        connection.execute(f"DELETE FROM habit_checkins WHERE habit_local_id NOT IN ({placeholders})", local_ids)
    else:
        connection.execute("DELETE FROM habits")
        connection.execute("DELETE FROM habit_checkins")
    for item in items:
        local_id = item["local_id"]
        previous_checkins = {row[0] for row in connection.execute('SELECT checked_date FROM habit_checkins WHERE habit_local_id=?', (local_id,))}
        connection.execute(
            """
            INSERT INTO habits (local_id, title, active_from, active_until, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(local_id) DO UPDATE SET
              title=excluded.title, active_from=excluded.active_from,
              active_until=excluded.active_until, updated_at=excluded.updated_at
            """,
            (
                local_id,
                item["title"],
                item.get("active_from", "1900-01-01"),
                item.get("active_until"),
                now,
            ),
        )
        connection.execute("DELETE FROM habit_checkins WHERE habit_local_id=?", (local_id,))
        for checked_date in item.get("completed_dates", []):
            connection.execute(
                "INSERT OR IGNORE INTO habit_checkins (habit_local_id, checked_date) VALUES (?, ?)",
                (local_id, checked_date),
            )
            if checked_date == now[:10] and checked_date not in previous_checkins:
                from domains.affect.service import capture_completion
                capture_completion(connection, 'habit_reminder', local_id + ':' + checked_date, item['title'], now)
    connection.commit()
    connection.close()
    return len(items)


def get_all_habits() -> list[dict]:
    connection = get_connection()
    habits = connection.execute(
        "SELECT local_id, title, active_from, active_until FROM habits ORDER BY id"
    ).fetchall()
    checkins = connection.execute(
        "SELECT habit_local_id, checked_date FROM habit_checkins ORDER BY checked_date"
    ).fetchall()
    connection.close()
    completed: dict[str, list[str]] = {}
    for row in checkins:
        completed.setdefault(row["habit_local_id"], []).append(row["checked_date"])
    return [
        {**dict(row), "completed_dates": completed.get(row["local_id"], [])}
        for row in habits
    ]


def upsert_habit(item: dict) -> dict:
    local_id = item["local_id"]
    connection = get_connection()
    now = datetime.now().isoformat()
    connection.execute(
        """
        INSERT INTO habits (local_id,title,active_from,active_until,updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(local_id) DO UPDATE SET title=excluded.title,
          active_from=excluded.active_from, active_until=excluded.active_until,
          updated_at=excluded.updated_at
        """,
        (local_id, item["title"], item.get("active_from", "1900-01-01"), item.get("active_until"), now),
    )
    connection.commit()
    connection.close()
    return next(value for value in get_all_habits() if value["local_id"] == local_id)


def delete_habit(local_id: str) -> bool:
    connection = get_connection()
    with connection:
        connection.execute("DELETE FROM habit_checkins WHERE habit_local_id=?", (local_id,))
        cursor = connection.execute("DELETE FROM habits WHERE local_id=?", (local_id,))
    deleted = cursor.rowcount > 0
    connection.close()
    return deleted


def set_habit_checkin(local_id: str, checked_date: str, done: bool) -> bool:
    connection = get_connection()
    exists = connection.execute(
        "SELECT 1 FROM habits WHERE local_id=?", (local_id,)
    ).fetchone()
    if exists is None:
        connection.close()
        return False
    if done:
        before = connection.execute('SELECT 1 FROM habit_checkins WHERE habit_local_id=? AND checked_date=?', (local_id, checked_date)).fetchone()
        connection.execute(
            "INSERT OR IGNORE INTO habit_checkins(habit_local_id,checked_date) VALUES (?,?)",
            (local_id, checked_date),
        )
        if before is None and checked_date == datetime.now().date().isoformat():
            from domains.affect.service import capture_completion
            title = connection.execute('SELECT title FROM habits WHERE local_id=?', (local_id,)).fetchone()[0]
            capture_completion(connection, 'habit_reminder', local_id + ':' + checked_date, title, datetime.now().isoformat())
    else:
        connection.execute(
            "DELETE FROM habit_checkins WHERE habit_local_id=? AND checked_date=?",
            (local_id, checked_date),
        )
    connection.commit()
    connection.close()
    return True


def find_active_habits(query: str, check_date: str | None = None) -> list[dict]:
    target = check_date or datetime.now().date().isoformat()
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT local_id,title,active_from,active_until FROM habits
        WHERE active_from<=? AND (active_until IS NULL OR active_until>=?)
          AND (title=? OR title LIKE ? OR ? LIKE '%' || title || '%')
        ORDER BY CASE WHEN title=? THEN 0 ELSE 1 END, id
        """,
        (target, target, query, f"%{query}%", query, query),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_incomplete_habits(check_date: str | None = None) -> list[dict]:
    """Return active habits without a check-in on the requested local date."""
    target_date = check_date or datetime.now().date().isoformat()
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT h.id, h.local_id, h.title, h.active_from, h.active_until
        FROM habits h
        LEFT JOIN habit_checkins c
          ON c.habit_local_id = h.local_id AND c.checked_date = ?
        WHERE h.active_from <= ?
          AND (h.active_until IS NULL OR h.active_until >= ?)
          AND c.id IS NULL
        ORDER BY h.id
        """,
        (target_date, target_date, target_date),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]

# Public compatibility facade; implementation lives in a focused repository.
from .content_repository import (
    save_thread,
    get_latest_thread,
    save_message,
    get_chat_companion_stats,
    get_messages,
    get_messages_after,
    get_message_updates_after,
    create_shared_memory,
    get_shared_memories,
    delete_shared_memory,
    update_shared_memory_location,
    get_shared_memory,
    get_shared_memory_comments,
    create_shared_memory_comment,
    get_messages_for_date,
    get_messages_for_source_date,
    get_messages_between,
    search_messages,
    set_message_favorite,
    get_favorite_messages,
    create_letter,
    get_letter_by_trigger_key,
    get_letter,
    get_letter_thread,
    get_proactive_letter_for_date,
    get_letters,
    mark_letter_read,
    set_letter_favorite,
)
