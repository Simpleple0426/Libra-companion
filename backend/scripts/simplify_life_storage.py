"""Offline, verified consolidation of the life database. Stop the backend first."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from life_prototype.memory_storage import backup_pair, initialize, connect, MEMORY_COLUMNS
from life_prototype.storage_layout import GROUPS, projection


def digest(rows):
    return hashlib.sha256(repr(rows).encode('utf8')).hexdigest()


def capture(path):
    with connect(path,readonly=True) as db:
        names=[n for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        groups={}
        for name in GROUPS:
            if name in names:
                groups[name]=digest(db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall())
        unchanged={name:digest(db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall())
                   for name in names if name not in GROUPS and name!='life_memories'}
        memories=digest(db.execute(f'SELECT {MEMORY_COLUMNS} FROM life_memories ORDER BY id').fetchall())
        return {'table_count':len(names),'groups':groups,'unchanged':unchanged,'memories':memories}


def verify(path,before):
    with connect(path,readonly=True) as db:
        for name,expected in before['groups'].items():
            assert digest(db.execute(projection(name)+' ORDER BY rowid').fetchall())==expected,name
        for name,expected in before['unchanged'].items():
            assert digest(db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall())==expected,name
        assert digest(db.execute(f'SELECT {MEMORY_COLUMNS} FROM life_memories ORDER BY id').fetchall())==before['memories']
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        names=[n for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        assert not set(names).intersection(GROUPS)
        assert all(row[1] in {'main','temp'} for row in db.execute('PRAGMA database_list'))
        return {'tables':names,'table_count':len(names),'memory_counts':dict(db.execute('SELECT kind,count(*) FROM life_memories GROUP BY kind'))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--backup-dir',type=Path,required=True)
    args=parser.parse_args()
    directory=args.run_dir.resolve();path=directory/'prototype.sqlite3'
    backup=args.backup_dir.resolve()
    if backup.exists(): raise ValueError('fresh backup directory required')
    # Respect the life scheduler's exclusive worker lease.
    with (directory/'p4-worker.lock').open('a+b') as lease:
        lease.seek(0)
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(lease.fileno(),msvcrt.LK_NBLCK,1)
        before=capture(path)
        backup_pair(path,backup/'before')
        backup_pair(path,backup/'rehearsal')
        staged=backup/'rehearsal'/'prototype.sqlite3'
        initialize(staged)
        verify(staged,before)
        initialize(path)
        after=verify(path,before)
        memory=directory/'memory.sqlite3'
        if memory.exists():
            archived=backup/'retired-memory.sqlite3'
            if not archived.is_relative_to(backup) or archived.exists():raise ValueError('invalid archive destination')
            memory.rename(archived)
        report={'at':datetime.now(timezone.utc).isoformat(),'before_runtime_tables':before['table_count'],
                'after':after,'merged_groups':list(before['groups']),'all_logical_records_verified':True,
                'single_database':str(path),'backup':str(backup/'before')}
        (backup/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
