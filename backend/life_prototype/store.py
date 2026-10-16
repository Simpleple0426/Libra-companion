"""Life runtime transactions, with a separate authoritative memory database."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3

from .config import canonical, digest, validate

SANDBOX = Path(__file__).resolve().parents[2] / "output" / "life-prototype"


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, run_id, config, clock, root=None):
        validate(config)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
            raise ValueError("run_id must be a simple isolated directory name")
        # Reject symlink/junction escapes before creating or opening anything.
        root = Path(root if root is not None else SANDBOX).absolute()
        if root.resolve() != root:
            raise ValueError("redirected sandbox")
        directory = root / run_id
        if directory.resolve() != directory:
            raise ValueError("redirected run directory")
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "prototype.sqlite3"
        if self.path.resolve() != self.path or (self.path.exists() and self.path.stat().st_nlink > 1):
            raise ValueError("redirected database")
        from .table_names import migrate
        migrate(self.path)
        from .memory_storage import initialize
        initialize(self.path)
        self.config = json.loads(canonical(config))
        self.clock = clock
        with self.connect() as db:
            existing = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if any(row[0] not in {'life_state','life_evidence','life_receipts','life_memories'} for row in existing) and not db.execute("SELECT 1 FROM life_state WHERE name='world'").fetchone():
                raise ValueError("not a prototype database")
            db.executescript('\n                CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, body TEXT NOT NULL, receipt TEXT)')
            db.execute("BEGIN IMMEDIATE")
            from .event_store import initialize as initialize_events
            initialize_events(db)
            old = db.execute('SELECT config FROM (SELECT rowid,"id" AS "id","body" AS "config" FROM life_state WHERE name=\'world\') AS prototype_meta WHERE id=1').fetchone()
            if old and digest(json.loads(old[0])) != digest(config):
                raise Conflict("configuration/content changed; use a new run_id")
            # Additive schema, only inside the isolated prototype database.
            # Legacy results have no captured checkpoint: never invent one.
            db.execute("""CREATE TABLE IF NOT EXISTS result_controls (
                result_id TEXT PRIMARY KEY, root_id TEXT NOT NULL, parent_id TEXT UNIQUE,
                status TEXT NOT NULL CHECK(status IN ('pending','superseded','void','settled')),
                context TEXT, mode TEXT NOT NULL CHECK(mode IN ('standard','deferred'))
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS one_settlement_per_source
                ON result_controls(root_id) WHERE status='settled'""")
            db.execute('SELECT 1')
            db.execute("""CREATE TABLE IF NOT EXISTS result_attempts (
                result_id TEXT NOT NULL, state_revision INTEGER NOT NULL,
                error TEXT NOT NULL, recorded_at TEXT NOT NULL,
                PRIMARY KEY(result_id, state_revision, error)
            )""")
            db.execute("""INSERT OR IGNORE INTO result_controls
                SELECT id, id, NULL, CASE WHEN receipt IS NULL THEN 'pending' ELSE 'settled' END,
                       NULL, 'standard' FROM results""")
            if not old:
                now = clock.now().isoformat()
                production = config.get("mode") == "local_single_user"
                state = {"revision": 0, "as_of": now, "place": config["initial"]["place"],
                         "source": "user_confirmed_initial_state" if production else "test_fixture",
                         "active": None, "activities": {}, "reading": {},
                         "inventory": config["initial"]["inventory"], "meals": {},
                         "gaps": []}
                if not production:
                    state["test_hunger"] = config["initial"]["hunger"]
                if config.get("work_items"):
                    state["work_items"] = {key: {"progress": 0, "status": "pending", "artifacts": [],
                        "materials_hash": digest(task)} for key, task in config["work_items"].items()}
                db.execute("INSERT INTO life_state(name,id,body) VALUES('world',1, ?)", (canonical(config),))
                db.execute("INSERT INTO life_state(name,id,body) VALUES('current',1, ?)", (canonical(state),))

    @contextmanager
    def connect(self):
        from .memory_storage import connect
        with connect(self.path) as db:
            yield db

    def snapshot(self):
        with self.connect() as db:
            return self.read(db)

    @staticmethod
    def read(db):
        return json.loads(db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'current\') AS snapshot WHERE id=1').fetchone()[0])

    def inspect(self):
        from .storage_layout import audit_cursor
        with self.connect() as db:
            db.execute("BEGIN")
            return {"state": self.read(db), **{
                table: [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
                for table in ("events", "proposals", "results", "reading_records",
                              "result_controls", "result_reviews", "result_attempts")
                for cursor in [audit_cursor(db, table)]
            }}
