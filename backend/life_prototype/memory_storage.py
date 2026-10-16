"""Single-file life storage, with migration from the temporary split layout."""
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3
from .storage_layout import GROUPS, migrate_groups

LAYOUT_VERSION = 2
MEMORY_COLUMNS = 'id,kind,description,created_at,last_accessed,importance,keywords,evidence,actor_id,status'
MEMORY_SCHEMA = '''CREATE TABLE IF NOT EXISTS life_memories (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('event','thought')),
    description TEXT NOT NULL, created_at TEXT NOT NULL, last_accessed TEXT NOT NULL,
    importance REAL NOT NULL, keywords TEXT NOT NULL,
    evidence TEXT NOT NULL, actor_id TEXT NOT NULL, status TEXT NOT NULL
)'''

def memory_path(path):
    return Path(path)

def _safe(path):
    path = Path(path).absolute()
    if path.resolve() != path or (path.exists() and path.stat().st_nlink > 1):
        raise ValueError('redirected life database')
    return path

def attach(db, path, *, readonly=False):
    """Compatibility for immutable archived layouts; current layout never attaches."""
    version = db.execute('PRAGMA main.user_version').fetchone()[0]
    if version == LAYOUT_VERSION: return db
    if version == 0:
        from .table_names import TABLE_RENAMES
        tables = {r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
        for old, new in TABLE_RENAMES.items():
            if old in tables and new not in tables:
                db.execute(f'CREATE TEMP VIEW "{new}" AS SELECT rowid AS rowid,* FROM main."{old}"')
    if version == 1:
        memory = _safe(Path(path).with_name('memory.sqlite3'))
        if not memory.is_file(): raise ValueError('legacy memory file missing; cannot migrate without memories')
        db.execute('ATTACH DATABASE ? AS knowledge', (memory.as_uri()+'?mode=ro',))
    for destination, key in (('life_state','name'),('life_evidence','category'),('life_receipts','category')):
        if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(destination,)).fetchone(): continue
        branches=[]
        fields = {'life_state':['name','id','body'], 'life_evidence':['category','id','kind','source_id','body'],
                  'life_receipts':['category','id','request','receipt']}[destination]
        for old,(target,_,value,columns) in GROUPS.items():
            if target != destination: continue
            try: db.execute(f'SELECT * FROM "{old}" LIMIT 0')
            except sqlite3.OperationalError: continue
            reverse={new:old for old,new in columns.items()}
            selected=[f"'{value}' AS {key}"]+[f'"{reverse[f]}" AS "{f}"' if f in reverse else f'NULL AS "{f}"' for f in fields[1:]]
            branches.append(f'SELECT rowid AS rowid,{",".join(selected)} FROM "{old}"')
        if branches: db.execute(f'CREATE TEMP VIEW {destination} AS '+ ' UNION ALL '.join(branches))
    return db

@contextmanager
def connect(path, *, readonly=False):
    path = _safe(path)
    db = sqlite3.connect(path.as_uri()+ ('?mode=ro' if readonly else '?mode=rw'),uri=True,timeout=20)
    try:
        attach(db,path,readonly=readonly)
        db.execute('PRAGMA query_only=ON' if readonly else 'PRAGMA synchronous=FULL')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally: db.close()

def initialize(path):
    path = _safe(path)
    with closing(sqlite3.connect(path,timeout=20,uri=True)) as db, db:
        version=db.execute('PRAGMA user_version').fetchone()[0]
        if version == LAYOUT_VERSION: return False
        if version not in (0,1): raise ValueError('unsupported life storage version')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables:
            backup=path.parent/'migration-backups'/'before-storage-simplification.sqlite3'
            backup.parent.mkdir(exist_ok=True)
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as target,target: db.backup(target)
        if version == 1:
            memory=_safe(path.with_name('memory.sqlite3'))
            if not memory.is_file(): raise ValueError('legacy memory file missing; cannot migrate without memories')
            if 'life_memories' in tables: raise ValueError('conflicting memory stores')
            db.execute('ATTACH DATABASE ? AS knowledge',(memory.as_uri()+'?mode=ro',))
        db.execute('BEGIN IMMEDIATE')
        db.execute(MEMORY_SCHEMA)
        if version == 1:
            expected=db.execute(f'SELECT {MEMORY_COLUMNS} FROM knowledge.life_memories ORDER BY id').fetchall()
            db.execute(f'INSERT INTO main.life_memories SELECT {MEMORY_COLUMNS} FROM knowledge.life_memories')
            if expected != db.execute(f'SELECT {MEMORY_COLUMNS} FROM main.life_memories ORDER BY id').fetchall():
                raise ValueError('memory merge verification failed')
        elif 'vector' in {r[1] for r in db.execute('PRAGMA table_info(life_memories)')}:
            db.execute('ALTER TABLE life_memories DROP COLUMN vector')
        migrate_groups(db)
        db.execute(f'PRAGMA user_version={LAYOUT_VERSION}')
        return True

def backup_pair(path, destination):
    """Back up one current database; retain support for unmigrated old pairs."""
    path=_safe(path);destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    with connect(path) as source:
        paths=[path]
        if source.execute('PRAGMA user_version').fetchone()[0] == 1: paths.append(path.with_name('memory.sqlite3'))
        if any((destination/p.name).exists() for p in paths): raise ValueError('backup destination already exists')
        for original in paths:
            with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as reader,closing(sqlite3.connect(destination/original.name)) as target,target:
                reader.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('invalid backup')
    return [destination/p.name for p in paths]
