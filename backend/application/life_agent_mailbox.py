"""A separate SQLite mailbox: chat delivery never waits for a life-state write."""
from contextlib import contextmanager
import sqlite3


@contextmanager
def connect(engine):
    path = engine.store.path.with_name('agent-mailbox.sqlite3')
    db = sqlite3.connect(path, timeout=1)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(engine):
    with connect(engine) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute("""CREATE TABLE IF NOT EXISTS life_agent_inbox(
            id TEXT PRIMARY KEY, content TEXT NOT NULL, goodnight INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', receipt TEXT, received_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0)""")
        db.execute('CREATE TABLE IF NOT EXISTS mailbox_meta(key TEXT PRIMARY KEY)')
        migrated = db.execute("SELECT 1 FROM mailbox_meta WHERE key='legacy_inbox_migrated'").fetchone()
    if not migrated:
        with engine.store.connect() as old:
            present = old.execute("SELECT 1 FROM sqlite_master WHERE name='life_agent_inbox'").fetchone()
            columns = {r[1] for r in old.execute('PRAGMA table_info(life_agent_inbox)')} if present else set()
            time_column = 'received_at' if 'received_at' in columns else 'NULL'
            attempts_column = 'attempts' if 'attempts' in columns else '0'
            rows = old.execute(f'SELECT id,content,goodnight,status,receipt,{time_column},{attempts_column} FROM life_agent_inbox').fetchall() if present else []
        with connect(engine) as db:
            db.executemany('INSERT OR IGNORE INTO life_agent_inbox VALUES(?,?,?,?,?,?,?)', rows)
            db.execute("INSERT OR IGNORE INTO mailbox_meta VALUES('legacy_inbox_migrated')")
