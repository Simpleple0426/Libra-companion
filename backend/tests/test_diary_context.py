import ast
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.diary_context import chat_transcript, life_events
from infrastructure.sqlite import database
from infrastructure.sqlite import content_repository


def test_life_events_use_local_time_and_exclude_plans_and_other_days():
    rows = [
        {'id': 'work', 'occurred_at': '2026-10-04T02:00:00Z', 'event': '开始工作'},
        {'id': 'late', 'occurred_at': '2026-10-04T17:00:00Z', 'event': '结束阅读'},
        {'id': 'future', 'occurred_at': '2026-10-05T02:00:00Z', 'event': '次日工作'},
        {'id': 'plan', 'occurred_at': '2026-10-04T12:00:00+08:00', 'event': '未来安排',
         'kind': 'agenda_changed'},
        {'id': 'bad', 'occurred_at': 'invalid', 'event': '无效'},
    ]
    mode = SimpleNamespace(activity_feed=Mock(return_value=rows))
    text = life_events(mode, datetime(2026, 10, 4), datetime(2026, 10, 5, 2))
    assert '10-04 10:00 开始工作' in text
    assert '10-05 01:00 结束阅读' in text
    assert text.count('开始工作') == 1
    assert '未来安排' not in text and '次日工作' not in text and '无效' not in text
    assert mode.activity_feed.call_args.kwargs['schedule_date'] == datetime(2026, 10, 5).date()


def test_chat_keeps_early_and_late_details_and_labels_rooms():
    messages = [
        {'created_at': '2026-10-04T02:00:00Z', 'role': 'user', 'source': 'chat',
         'content': '早间细节' + '甲' * 10000},
        {'created_at': '2026-10-04T21:00:00', 'role': 'user', 'source': 'movie_chat',
         'content': '观影细节' + '乙' * 10000},
    ]
    text = chat_transcript(messages)
    assert '早间细节' in text and '观影细节' in text
    assert '10-04 10:00' in text and '影音室对话' in text
    assert '截短' in text


def test_diary_query_includes_rooms_and_normalizes_utc(tmp_path):
    path = tmp_path / 'chat.db'
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,
            created_at TEXT,source TEXT,message_type TEXT,media_url TEXT,duration_seconds REAL);
            CREATE TABLE favorite_messages(message_id INTEGER);
            CREATE TABLE cognition_inputs(message_id INTEGER,request_key TEXT);''')
        for source, at in [('chat', '2026-10-03T17:00:00Z'),
                           ('movie_chat', '2026-10-04T20:00:00+08:00'),
                           ('music_room', '2026-10-04T21:00:00'),
                           ('chat', '2026-10-04T16:00:00Z')]:
            db.execute('INSERT INTO messages(role,content,created_at,source) VALUES(?,?,?,?)',
                       ('user', source, at, source))
    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db
    with patch.object(content_repository, 'get_connection', connect):
        rows = content_repository.get_messages_between(datetime(2026, 10, 4),
                   datetime(2026, 10, 5), include_rooms=True)
        assert [row['source'] for row in rows] == ['chat', 'movie_chat', 'music_room']
        rows = content_repository.get_messages_between(datetime(2026, 10, 4), datetime(2026, 10, 5))
        assert [row['source'] for row in rows] == ['chat']


def test_runtime_supplies_chat_and_verified_life_to_diary_prompt():
    root = Path(__file__).parents[1]
    tree = ast.parse((root / 'app/runtime.py').read_text(encoding='utf8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == '_create_daily_diary']
    run = Mock(return_value={'diary': 'test diary'})
    scope = dict(datetime=datetime, timedelta=timedelta, json=json,
                 get_shared_memories=Mock(return_value=[]), set_app_setting=Mock(),
                 get_app_setting=Mock(return_value=''),
                 get_messages_between=Mock(return_value=[{'role': 'user', 'content': '聊天细节',
                      'created_at': '2026-10-04T12:00:00', 'source': 'music_room'}]),
                 life_mode=SimpleNamespace(enabled=True, activity_feed=Mock(return_value=[
                      {'id': 'meal', 'occurred_at': '2026-10-04T11:00:00+08:00', 'event': '做午饭'}])),
                 affect_service=SimpleNamespace(history=Mock(return_value=[
                      {'created_at': '2026-10-04T23:00:00', 'event_summary': '截止后互动'},
                      {'created_at': '2026-10-04T13:00:00', 'event_summary': '真实互动'}])),
                 DIARY_PROMPT_PATH=root / 'prompts/diary.md', _run_private_memory_prompt=run,
                 _save_generated_artifact=Mock(return_value=True), create_shared_memory=Mock())
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'diary-runtime', 'exec'), scope)
    assert scope['_create_daily_diary']('2026-10-04', datetime(2026, 10, 4, 22))
    prompt = run.call_args.args[0]
    assert '聊天细节' in prompt and '音乐房对话' in prompt and '做午饭' in prompt
    assert '真实互动' in prompt and '截止后互动' not in prompt
    assert '{{' not in prompt
    assert scope['get_messages_between'].call_args.kwargs['include_rooms'] is True
