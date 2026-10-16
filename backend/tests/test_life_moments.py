import json
import sqlite3
from pathlib import Path

from application.life_moments import sync_life_moments, display_quote


def test_quote_display_removes_web_footer_only():
    source = {'url': 'https://book.douban.com/subject/1/blockquotes',
              'text': '有的凶手犯下的罪不受法律的制裁 ( ) 27赞 2017-01-16 12:53:57 —— 引自章节：无人还生'}
    assert display_quote(source) == '有的凶手犯下的罪不受法律的制裁'
    source['text'] = '原句（保留句中说明）。 —— 引自第278页'
    assert display_quote(source) == '原句（保留句中说明）。'
    source['url'] = 'https://zh.wikiquote.org/wiki/example'
    assert display_quote(source) == source['text']


def test_projection_preserves_sources_and_does_not_resurrect_deleted_items(tmp_path):
    life, content = tmp_path / 'life.db', tmp_path / 'content.db'
    with sqlite3.connect(life) as db:
        db.execute('CREATE TABLE life_quotes(id TEXT,body TEXT)')
        db.execute('CREATE TABLE life_movie_reviews(activity_id TEXT,status TEXT,body TEXT)')
        db.execute('CREATE TABLE life_dynamic_drafts(id TEXT,status TEXT,body TEXT)')
        for kind in ('reading', 'watching'):
            db.execute('INSERT INTO life_quotes VALUES (?,?)', (kind, json.dumps({
                'work': {'kind': kind, 'title': '作品'}, 'source': {'text': '原句', 'url': 'https://example.org'},
                'thought': '感想', 'translation': '译文', 'saved_at': '2026-09-27T23:14:00+00:00'})))
        review = json.dumps({'movie': {'title': '影片'}, 'review': {'title': '标题', 'review': '影评全文'},
                             'written_at': '2026-09-28T09:00:00+08:00'})
        db.execute('INSERT INTO life_movie_reviews VALUES (?,?,?)', ('done', 'done', review))
        db.execute('INSERT INTO life_movie_reviews VALUES (?,?,?)', ('pending', 'pending', review))
        for kind in ('book_introduction', 'walk_thought'):
            db.execute('INSERT INTO life_dynamic_drafts VALUES (?,?,?)', (kind, 'pending_display', json.dumps({
                'kind': kind, 'body': '想法正文', 'book': {'title': '新书'} if kind == 'book_introduction' else None,
                'place_name': '公园', 'created_at': '2026-09-28T10:00:00+08:00'})))
        db.execute('INSERT INTO life_dynamic_drafts VALUES (?,?,?)', ('leisure', 'pending_display', json.dumps({
            'kind': 'leisure_thought', 'skill': 'reading', 'subject': '阅读新书', 'body': '阅读中的想法',
            'created_at': '2026-09-28T10:00:00+08:00'})))
    with sqlite3.connect(content) as db:
        db.execute('''CREATE TABLE shared_moments(id INTEGER PRIMARY KEY, memory_type TEXT, author TEXT,
                      content TEXT,event_date TEXT,status TEXT,created_at TEXT)''')
        db.execute("INSERT INTO shared_moments(memory_type,content) VALUES ('diary','keep')")
    assert sync_life_moments('run', life_path=life, content_path=content) == 6
    assert sync_life_moments('run', life_path=life, content_path=content) == 0
    with sqlite3.connect(content) as db:
        assert db.execute("SELECT count(*) FROM shared_moments WHERE memory_type='diary'").fetchone()[0] == 1
        rows = db.execute("SELECT source_kind,source_title,content,event_date,created_at FROM shared_moments WHERE memory_type='moment'").fetchall()
        assert {r[0] for r in rows} == {'movie_review','book_quote','movie_quote','book_introduction','walk_thought','leisure_thought'}
        quote = next(r for r in rows if r[0] == 'book_quote')
        assert quote[1] == '作品' and '原句' in quote[2] and '译文' in quote[2] and '感想' in quote[2]
        assert '左然的想法' in quote[2] and '我的感想' not in quote[2]
        assert quote[3] == '2026-09-28' and '07:14:00+08:00' in quote[4]
        db.execute("DELETE FROM shared_moments WHERE source_kind='book_quote'")
    assert sync_life_moments('run', life_path=life, content_path=content) == 0


def test_absent_or_empty_life_database(tmp_path):
    assert sync_life_moments('../bad', life_path=tmp_path / 'absent') == 0
    assert sync_life_moments('run', life_path=tmp_path / 'absent') == 0
