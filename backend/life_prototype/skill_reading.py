"""Structure-only simulated reading. No prose or reading-model calls."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import math

from .clock import utc
from .config import canonical, digest

MODE = 'structure_simulation'
DEFAULT_RATE = 400  # Simulated characters/minute, configurable, not measured comprehension.
MAX_HEARTBEAT_GAP = 90


def instruction():
    return (Path(__file__).parent / 'skills/reading/SKILL.md').read_text(encoding='utf8')


def simulated(book):
    return book.get('reading_mode') == MODE


def length(book):
    return book['total_chars'] if simulated(book) else len(book.get('text', ''))


def public_books(config):
    return {key: {k: v for k, v in book.items() if k not in {'text', 'structure', 'manifest_path'}}
            for key, book in config.get('books', {}).items() if book.get('available', True)}


def imported_book(directory, manifest):
    """Read manifest metadata and file existence only, never chunk contents."""
    directory = Path(directory).resolve()
    chunks, offset = [], 0
    for chunk in manifest.get('chunks', []):
        relative = chunk.get('path') or chunk.get('file')
        count = chunk.get('charCount')
        if not relative or type(count) is not int or count <= 0 or not chunk.get('id'):
            return None
        file = (directory / relative).resolve()
        if not file.is_relative_to(directory) or not file.is_file():
            return None
        chunks.append({'id': chunk['id'], 'section': chunk.get('sectionTitle') or chunk.get('title') or chunk['id'],
                       'start': offset, 'end': offset + count, 'char_count': count,
                       'content_hash': chunk.get('chunkHash')})
        offset += count
    if not chunks or len({c['id'] for c in chunks}) != len(chunks):
        return None
    version = digest({'source': manifest.get('sourceHash'), 'chunks': chunks})[:16]
    library_id = 'book:' + str(manifest.get('bookId') or directory.name)
    key = library_id + ':structure:' + version
    return key, {'title': manifest.get('title') or directory.name, 'author': manifest.get('author') or '',
                 'isbn': manifest.get('isbn'), 'original_title': manifest.get('original_title'),
                 'version': version, 'object': 'library-object:' + key, 'source': 'local_library',
                 'source_reference': 'imported_book:' + directory.name, 'library_id': library_id,
                 'reading_mode': MODE, 'available': True, 'total_chars': offset,
                 'manifest_path': str(directory/'manifest.json'), 'structure': chunks,
                 'progress_semantics': 'simulated_time_and_structure; no_content_comprehension'}


def position(book, offset):
    total = length(book)
    offset = max(0, min(int(offset), total))
    chunk = next((c for c in book['structure'] if offset < c['end']), book['structure'][-1])
    section = [c for c in book['structure'] if c['section'] == chunk['section']]
    start, end = section[0]['start'], section[-1]['end']
    ratio = min(1, max(0, (offset-start)/(end-start)))
    return {'chapter': chunk['section'], 'chunk_id': chunk['id'],
            'chunk_offset': max(0, offset-chunk['start']), 'offset': offset,
            'chapter_percent': round(ratio*100, 1), 'book_percent': round(offset/total*100, 2),
            'completed': offset == total, 'semantics': 'simulated_reading_progress'}


def label(book, offset):
    pos = position(book, offset)
    return '全书读完' if pos['completed'] else f"{pos['chapter']}（约{pos['chapter_percent']:g}%）"


def plan(book, progress, seconds, config):
    rate = config.get('reading_simulation', {}).get('characters_per_minute', DEFAULT_RATE)
    if type(rate) not in (float, int) or not 0 < rate <= 3000:
        raise ValueError('invalid simulated reading rate')
    target = min(length(book), int(progress + seconds*rate/60))
    return {'skill': 'reading', 'mode': MODE, 'structure': deepcopy(book['structure']),
            'start': position(book, progress), 'expected_end': position(book, target),
            'characters_per_minute': rate, 'budget_seconds': seconds,
            'semantics': 'expected_range_not_completed_progress'}


def begin(config, state, activity, at):
    book = config['books'][activity['target']]
    if state['place'] != 'home.f2.study':
        raise ValueError('simulated reading requires the study')
    rate = config.get('reading_simulation', {}).get('characters_per_minute', DEFAULT_RATE)
    if type(rate) not in (float, int) or not 0 < rate <= 3000:
        raise ValueError('invalid simulated reading rate')
    activity.update(reading_mode=MODE, rate=rate, heartbeat_at=at.isoformat(),
                    reading_fraction=0.0, session_start_progress=activity['progress'], simulated_seconds=0.0)


def settle(config, state, activity, at, *, recovering=False):
    """Idempotent elapsed-time credit; no catch-up through outages or pauses."""
    if activity.get('reading_mode') != MODE or activity['status'] != 'running':
        return
    book = config['books'][activity['target']]
    previous = utc(activity['heartbeat_at'])
    until = min(at, utc(activity['reading_deadline'])) if activity.get('reading_deadline') else at
    elapsed = max(0, (until-previous).total_seconds())
    if recovering or (at-previous).total_seconds() > MAX_HEARTBEAT_GAP or state['place'] != activity['place']:
        elapsed = 0
    amount = activity.get('reading_fraction', 0) + elapsed*activity['rate']/60
    earned = math.floor(amount)
    activity['reading_fraction'] = amount-earned
    activity['progress'] = min(length(book), activity['progress']+earned)
    activity['simulated_seconds'] += elapsed
    activity['heartbeat_at'] = at.isoformat()
    activity['last_progress_at'] = at.isoformat()
    activity['revision'] += 1
    state['reading'][activity['progress_key']] = activity['progress']
    state.setdefault('reading_progress', {})[activity['target']] = {
        'book_id': book['library_id'], 'book_version': book['version'],
        **position(book, activity['progress']), 'updated_at': at.isoformat(),
        'activity_id': activity['id'], 'source': MODE}


def heartbeat(cog):
    """P4 calls this after external inputs, before any model checkpoint work."""
    p = cog.p
    with p.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = p.store.read(db)
        activity = state['activities'].get(state.get('active'))
        if not activity or activity.get('reading_mode') != MODE:
            return False
        now = p.clock.now()
        settle(p.config, state, activity, now)
        finished = activity['progress'] >= length(p.config['books'][activity['target']])
        activity['next_due_at'] = (now + timedelta(seconds=p.config['checkpoint_seconds'])).isoformat()
        state['revision'] += 1
        state['as_of'] = now.isoformat()
        db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
    if finished:
        p.command('reading-finished:' + activity['id'], state['revision'], 'interrupt',
                  activity_id=activity['id'], reason='已按模拟阅读时间读完全书')
    return True


def migrate_progress(state, previous_books, fresh_books):
    for key, book in fresh_books.items():
        if not simulated(book):
            continue
        progress_key = key + ':' + book['version']
        if progress_key in state['reading']:
            continue
        prior = [(old_key, old) for old_key, old in previous_books.items()
                 if old.get('library_id') == book['library_id'] and not simulated(old)]
        candidates = [(old_key, state['reading'].get(old_key+':'+old['version'], 0)) for old_key, old in prior]
        old_key, offset = max(candidates, key=lambda x:x[1], default=(None, 0))
        state['reading'][progress_key] = min(int(offset), length(book))
        if offset:
            state.setdefault('reading_progress', {})[key] = {
                **position(book, offset), 'book_id': book['library_id'], 'book_version': book['version'],
                'source': 'legacy_character_offset_as_simulated_estimate', 'legacy_target': old_key,
                'legacy_offset': offset, 'note': '旧验证记录保留；结构坐标中的章节位置为估算，不新增阅读经历'}
