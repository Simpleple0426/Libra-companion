"""Project completed life writing into the shared timeline, once per source."""
import json
import logging
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

from infrastructure.paths import CONTENT_DATABASE_PATH, RUNTIME_ROOT
from infrastructure.sqlite.connection import connect


def display_quote(source):
    text = source['text'].strip()
    if 'book.douban.com/' in source.get('url', ''):
        # Older saved excerpts contain the website's reaction/date/source footer.
        text = re.split(r'\s*\d+\s*赞\s+\d{4}-\d{2}-\d{2}\b', text, maxsplit=1)[0]
        text = re.split(r'\s*[—–]{2,}\s*引自', text, maxsplit=1)[0]
        text = re.sub(r'\s*[（(]\s*[)）]\s*$', '', text).strip()
    return text


def entries(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    specs = [('life_movie_reviews', 'activity_id', "status='done'"),
             ('life_quotes', 'id', '1=1'),
             ('life_dynamic_drafts', 'id', "status='pending_display'")]
    for table, key, condition in specs:
        if table not in tables:
            continue
        for ident, raw in db.execute(f'SELECT {key},body FROM {table} WHERE {condition}'):
            try:
                body = json.loads(raw)
                url = ''
                if table == 'life_movie_reviews':
                    kind, label = 'movie_review', '影片影评'
                    title = body['movie']['title']
                    content = body['review']['title'] + '\n\n' + body['review']['review']
                    at = body['written_at']
                elif table == 'life_quotes':
                    movie = body['work']['kind'] == 'watching'
                    kind, label = ('movie_quote', '电影台词摘抄') if movie else ('book_quote', '书籍名句摘抄')
                    title = body['work']['title']
                    content = '「' + display_quote(body['source']) + '」'
                    if body.get('translation'):
                        content += '\n\n译文：' + body['translation']
                    content += '\n\n左然的想法\n' + body['thought']
                    # Provenance stays in the life notebook; the card shows prose only.
                    at = body['saved_at']
                else:
                    kind = body['kind']
                    if kind not in {'book_introduction', 'walk_thought', 'leisure_thought'}:
                        continue
                    label = '购书想法' if kind == 'book_introduction' else '散步随想'
                    title = (body.get('book') or {}).get('title') or body.get('place_name', '')
                    if kind == 'leisure_thought':
                        label = {'reading': '阅读随想', 'movie': '观影随想',
                                 'television': '电视随想', 'home_activity': '居家随想',
                                 'outing': '外出随想'}.get(body.get('skill'), '休闲随想')
                        title = body.get('subject', '')
                    content, at = body['body'], body['created_at']
                local = datetime.fromisoformat(at.replace('Z', '+00:00'))
                if local.tzinfo:
                    local = local.astimezone(ZoneInfo('Asia/Shanghai'))
                # Include provenance in text as well, for already-installed clients.
                heading = label + (' · 《' + title + '》' if title and kind not in {'walk_thought', 'leisure_thought'} else ' · ' + title if title else '')
                yield f'{table}:{ident}', kind, title, url, heading + '\n\n' + content, local
            except (KeyError, TypeError, ValueError):
                logging.getLogger(__name__).warning('Skipping invalid life timeline source %s:%s', table, ident)


def sync_life_moments(run_id, *, life_path=None, content_path=CONTENT_DATABASE_PATH):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', run_id or ''):
        return 0
    life_path = life_path or RUNTIME_ROOT / 'life' / run_id / 'prototype.sqlite3'
    if not life_path.is_file():
        return 0
    with closing(sqlite3.connect(life_path.as_uri() + '?mode=ro', uri=True, timeout=5)) as source:
        items = list(entries(source))
    with closing(connect(content_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            columns = {r[1] for r in db.execute('PRAGMA table_info(shared_moments)')}
            for name in ('source_kind', 'source_title', 'source_url'):
                if name not in columns:
                    db.execute(f'ALTER TABLE shared_moments ADD COLUMN {name} TEXT')
            # No FK: retain receipts after a user deletes a displayed moment.
            db.execute('CREATE TABLE IF NOT EXISTS life_moment_imports(source_key TEXT PRIMARY KEY, memory_id INTEGER NOT NULL)')
            count = 0
            for key, kind, title, url, content, at in items:
                key = run_id + ':' + key
                imported = db.execute('SELECT memory_id FROM life_moment_imports WHERE source_key=?', (key,)).fetchone()
                if imported:
                    if kind in {'book_quote', 'movie_quote'}:
                        db.execute('''UPDATE shared_moments SET content=?,source_url=?
                                      WHERE id=? AND source_kind=? AND (content!=? OR COALESCE(source_url,'')!=?)''',
                                   (content, url, imported[0], kind, content, url))
                    continue
                row = db.execute('''INSERT INTO shared_moments
                    (memory_type,author,content,event_date,status,created_at,source_kind,source_title,source_url)
                    VALUES ('moment','libra',?,?,'published',?,?,?,?)''',
                    (content, at.date().isoformat(), at.isoformat(), kind, title, url))
                db.execute('INSERT INTO life_moment_imports VALUES (?,?)', (key, row.lastrowid))
                count += 1
            db.commit()
            return count
        except BaseException:
            db.rollback()
            raise
