"""Versioned adapters for the reading and movie libraries.

Never writes the user's/shared-reading bookmarks. Additive snapshots keep old
activities reproducible when a library entry is edited or removed.
"""
from copy import deepcopy
import json
from pathlib import Path
from .config import canonical, digest, validate

ROOT = Path(__file__).resolve().parents[2]


def effective(store, base):
    if base.get('mode') != 'local_single_user': return base
    with store.connect() as db:
        row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'resources\') AS life_resources WHERE id=1').fetchone()
    if not row: return base
    saved = json.loads(row[0])
    result = deepcopy(base)
    for key in ('objects', 'books', 'movies', 'work_items'):
        result.setdefault(key, {}).update(saved.get(key, {}))
    validate(result)
    return result


def _json(path, default):
    try: return json.loads(path.read_text(encoding='utf8'))
    except (OSError, ValueError): return default


def library(root=ROOT, *, movie_place='home.f1.living'):
    values = {'books': {}, 'objects': {}, 'movies': {}, 'work_items': {}}
    if Path(root).resolve() == ROOT.resolve():
        from infrastructure.paths import PRIVATE_READING_ROOT
        directory = PRIVATE_READING_ROOT / 'reading' / 'books'
    else:
        # Explicit fixture roots remain isolated from production data.
        directory = root/'backend/private_reading/reading/books'
    for manifest_path in directory.glob('*/manifest.json'):
        manifest = _json(manifest_path, {})
        from .skill_reading import imported_book
        imported = imported_book(manifest_path.parent, manifest)
        if imported:
            key, book = imported
            values['books'][key] = book
            values['objects'][book['object']] = {'name': book['title'], 'parent': 'home.f2.study',
                'status': 'confirmed', 'source': book['source_reference']}
    durations = _json(root/'libra/movie_knowledge/runtimes.json', {})
    for parent in _json(root/'libra/movie_knowledge/catalog.json', {}).get('movies', []):
        if parent.get('identity_status') not in {'resolved','assumed'}: continue
        parts = durations.get('collections', {}).get(parent['movie_id'])
        rows = [{**parent, **part, 'collection_id': parent['movie_id']} for part in parts] if parts else [parent]
        for row in rows:
            runtime = durations.get('movies', {}).get(row['movie_id'], {})
            duration = runtime.get('duration_seconds')
            if type(duration) is not int or duration <= 0 or not runtime.get('source_url'): continue
            key = 'movie:'+row['movie_id']
            values['movies'][key] = {'id': key, 'title': row['title'], 'place': movie_place,
                'source': 'confirmed_movie_library', 'available': True, 'viewing_mode': 'active_time_simulation',
                'duration_seconds': duration, 'edition': runtime.get('edition'),
                'duration_source': runtime['source_url'], 'year': row.get('year'), 'original_title': row.get('original_title'),
                'catalog_status': parent.get('status'), 'collection_id': row.get('collection_id'),
                'progress_semantics': 'simulated_active_viewing_seconds_not_app_player_telemetry'}
    return values




def sync(cog, root=ROOT):
    p = cog.p
    if p.config.get('mode') != 'local_single_user': return False
    movie_place = 'home.f2.media' if 'home.f2.media' in p.config['places'] else 'home.f1.living'
    fresh = library(root, movie_place=movie_place)
    with p.store.connect() as db:
        from .weread_library import resources as weread_resources
        weread_resources(db,fresh)
        for key, raw in db.execute("SELECT id,body FROM life_evidence WHERE category='discovered_movie'"):
            fresh['movies'][key] = json.loads(raw)
    before = p.snapshot()
    result = deepcopy(p.config)
    for key in ('books','movies'):
        for resource in result.get(key,{}).values(): resource['available'] = False
    for key, entries in fresh.items(): result.setdefault(key,{}).update(entries)
    # A pending work item's material and location stay stable across days.
    if result == p.config:
        from .weread_library import mark_available
        with p.store.connect() as db: mark_available(db,result)
        return False
    validate(result)
    with p.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = p.store.read(db)
        if state['revision'] != before['revision']: return False
        from .skill_reading import migrate_progress
        migrate_progress(state, p.config.get('books', {}), fresh['books'])
        for config in (p.config, result):
            db.execute("INSERT OR IGNORE INTO life_evidence(category,id,body) VALUES('resource_version',?,?)",(digest(config),canonical(config)))
        payload = {key:result.get(key,{}) for key in ('objects','books','movies','work_items')}
        from .weread_library import mark_available
        mark_available(db,result)
        db.execute("INSERT OR REPLACE INTO life_state(name,id,body) VALUES('resources',1,?)",(canonical(payload),))
        for key,task in result.get('work_items',{}).items():
            state.setdefault('work_items',{}).setdefault(key,{'progress':0,'status':'pending','artifacts':[],'materials_hash':digest(task)})
        state['revision'] += 1
        db.execute("UPDATE life_state SET body=?  WHERE name='current' AND ( id=1)",(canonical(state),))
    p.config = result
    return True
