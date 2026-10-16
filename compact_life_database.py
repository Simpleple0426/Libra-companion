from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import zipfile


DATABASE = Path(r"E:\LIbra-companion\data\life\local-life-v1\prototype.sqlite3")
BACKUP_DIR = Path(r"E:\LIbra-companion\backups\database\manual")


def main() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_backup = BACKUP_DIR / f"prototype-before-compact-{stamp}.sqlite3"
    archive = raw_backup.with_suffix(".zip")

    source = sqlite3.connect(DATABASE)
    backup = sqlite3.connect(raw_backup)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        zipped.write(raw_backup, raw_backup.name)
    raw_backup.unlink()

    before = DATABASE.stat().st_size
    db = sqlite3.connect(DATABASE)
    try:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM life_scheduler_logs")
        db.execute("DELETE FROM life_model_transport_attempts")
        cutoff = db.execute(
            "SELECT rowid FROM life_model_calls ORDER BY rowid DESC LIMIT 1 OFFSET 199"
        ).fetchone()
        if cutoff:
            db.execute(
                "DELETE FROM life_model_calls WHERE rowid < ? AND status IN ('received','failed')",
                (cutoff[0],),
            )
        stale_runs = [row[0] for row in db.execute(
            "SELECT id FROM life_agent_runs WHERE status='done' ORDER BY rowid DESC LIMIT -1 OFFSET 30"
        )]
        if stale_runs:
            db.executemany("DELETE FROM life_agent_steps WHERE run_id=?", ((item,) for item in stale_runs))
            db.executemany("DELETE FROM life_agent_runs WHERE id=?", ((item,) for item in stale_runs))
        db.execute(
            "DELETE FROM life_scheduler_attempts WHERE status!='running' AND rowid NOT IN "
            "(SELECT rowid FROM life_scheduler_attempts ORDER BY rowid DESC LIMIT 50)"
        )
        db.execute(
            "DELETE FROM life_cognition_runs WHERE status IN ('committed','rejected') AND rowid NOT IN "
            "(SELECT rowid FROM life_cognition_runs ORDER BY rowid DESC LIMIT 100)"
        )
        for category, keep in (("world_check", 20), ("memory_retrieval", 50)):
            db.execute(
                "DELETE FROM life_evidence WHERE category=? AND rowid NOT IN "
                "(SELECT rowid FROM life_evidence WHERE category=? ORDER BY rowid DESC LIMIT ?)",
                (category, category, keep),
            )
        db.commit()
        db.execute("VACUUM")
        check = db.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"integrity check failed: {check}")
    finally:
        db.close()

    for suffix in ("-wal", "-shm"):
        Path(str(DATABASE) + suffix).unlink(missing_ok=True)
    after = DATABASE.stat().st_size
    print(f"backup={archive}")
    print(f"before={before}")
    print(f"after={after}")
    print("integrity=ok")


if __name__ == "__main__":
    main()
