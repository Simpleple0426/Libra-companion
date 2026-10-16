"""Import the authorized household catalog while the backend is stopped.

Backs up first, holds the life worker lock, preserves all actor progress and
history, and records configuration evidence rather than invented experiences.
"""
import argparse
from contextlib import contextmanager, closing
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from life_prototype.config import canonical, digest, validate
from life_prototype.home_catalog import apply_to_world, catalog


@contextmanager
def stopped_worker(directory):
    with (directory / 'p4-worker.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def migrate(database, backup):
    database, backup = Path(database).resolve(), Path(backup).resolve()
    if not database.is_file() or backup.exists() or database == backup:
        raise ValueError('Existing life database and fresh backup path required')
    with stopped_worker(database.parent):
        backup.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database)) as db, closing(sqlite3.connect(backup)) as target, db:
            db.backup(target)
            db.execute('BEGIN IMMEDIATE')
            read = lambda name: json.loads(db.execute('SELECT body FROM life_state WHERE name=?', (name,)).fetchone()[0])
            world = read('world')
            if world.get('mode') != 'local_single_user':
                raise ValueError('Only the authorized local household may be imported')
            updated = apply_to_world(world)
            row = db.execute("SELECT body FROM life_state WHERE name='resources'").fetchone()
            resources = json.loads(row[0]) if row else {}
            updated_resources = deepcopy(resources)
            for movie in updated_resources.get('movies', {}).values():
                if movie.get('source') == 'confirmed_movie_library' and movie.get('place') == 'home.f1.living':
                    movie['place'] = 'home.f2.media'
            effective = deepcopy(updated)
            for key in ('objects', 'books', 'movies', 'work_items'):
                effective.setdefault(key, {}).update(updated_resources.get(key, {}))
            validate(effective)
            from life_prototype.home_world import path
            for place in catalog()['places']:
                if place != 'home':
                    path(effective, 'home.f1.living', place)
            changed = updated != world or updated_resources != resources
            if changed:
                for value in (world, updated):
                    db.execute("INSERT OR IGNORE INTO life_evidence(category,id,body) VALUES('resource_version',?,?)", (digest(value), canonical(value)))
                db.execute("UPDATE life_state SET body=? WHERE name='world'", (canonical(updated),))
                if row:
                    db.execute("UPDATE life_state SET body=? WHERE name='resources'", (canonical(updated_resources),))
                current = read('current')
                current['revision'] += 1
                db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(current),))
                scheduler = read('scheduler')
                scheduler.update(dirty=True, next_decision=datetime.now(timezone.utc).isoformat())
                db.execute("UPDATE life_state SET body=? WHERE name='scheduler'", (canonical(scheduler),))
                evidence = {'authorization': catalog()['authorization'], 'backup': str(backup),
                            'at': datetime.now(timezone.utc).isoformat(),
                            'previous_world_hash': digest(world), 'world_hash': digest(updated),
                            'revision': current['revision'], 'events_generated': 0,
                            'catalog_places': len(catalog()['places']), 'catalog_objects': len(catalog()['objects'])}
                db.execute("INSERT INTO life_evidence(category,id,body) VALUES('world_configuration',?,?)",
                           ('household:' + digest(evidence), canonical(evidence)))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity check failed')
    return {'changed': changed, 'backup': str(backup), 'catalog_places': len(catalog()['places']),
            'catalog_objects': len(catalog()['objects']), 'movies_at_media': sum(
                m.get('place') == 'home.f2.media' for m in updated_resources.get('movies', {}).values())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.database, args.backup), ensure_ascii=False, indent=2))
