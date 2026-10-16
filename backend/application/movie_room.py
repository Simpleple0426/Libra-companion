"""Movie-room records. Conversation text remains in the shared messages table."""
from contextlib import closing
from datetime import datetime
import json


class MovieRoom:
    def __init__(self, connect, memory_store=None):
        self.connect = connect
        self.memory_store = memory_store
        with closing(connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS movie_viewings (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'watching',
                    position REAL, summary TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL DEFAULT 'none', review TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS movie_message_links (
                    message_id INTEGER PRIMARY KEY, viewing_id TEXT);
                CREATE TABLE IF NOT EXISTS movie_quotes (
                    id INTEGER PRIMARY KEY, viewing_id TEXT NOT NULL, text TEXT NOT NULL,
                    thought TEXT NOT NULL, position REAL, created_at TEXT NOT NULL,
                    UNIQUE(viewing_id,text));
                CREATE TABLE IF NOT EXISTS movie_chat_requests (
                    id TEXT PRIMARY KEY, message_id INTEGER NOT NULL, viewing_id TEXT,
                    content TEXT NOT NULL, replies TEXT);
                CREATE INDEX IF NOT EXISTS movie_messages_viewing ON movie_message_links(viewing_id);
                CREATE INDEX IF NOT EXISTS movie_message_source_date ON messages(source,created_at,id);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(movie_viewings)')}
            for name, default in [('discussion_status', 'none'), ('discussion', '')]:
                if name not in columns:
                    db.execute(f"ALTER TABLE movie_viewings ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
            db.execute("UPDATE movie_viewings SET discussion_status='error' WHERE discussion_status='writing'")
            # A process restart ends capture; it does not mean the film finished.
            db.execute("UPDATE movie_viewings SET status='stopped' WHERE status IN ('watching','paused')")
            db.execute("UPDATE movie_viewings SET review_status='error' WHERE review_status='writing'")
            db.commit()

    def start(self, session):
        now = datetime.now().isoformat()
        with closing(self.connect()) as db:
            db.execute("UPDATE movie_viewings SET status='stopped' WHERE status IN ('watching','paused')")
            db.execute('INSERT INTO movie_viewings(id,title,started_at,updated_at) VALUES(?,?,?,?)',
                       (session['id'], session['title'].strip() or '未命名电影', now, now))
            db.commit()

    def control(self, ident, action):
        state = {'stop': 'stopped', 'pause': 'paused', 'resume': 'watching', 'finish': 'completed'}.get(action)
        with closing(self.connect()) as db:
            if state:
                db.execute("UPDATE movie_viewings SET status=?,updated_at=? WHERE id=? AND status!='completed'",
                           (state, datetime.now().isoformat(), ident))
            if action == 'finish' and self.memory_store:
                viewing = db.execute('SELECT * FROM movie_viewings WHERE id=?', (ident,)).fetchone()
                if viewing:
                    self.memory_store.record_completed_viewing(db, dict(viewing))
            if action == 'resync':
                db.execute("UPDATE movie_viewings SET summary='' WHERE id=?", (ident,))
            db.commit()

    def observed(self, session):
        with closing(self.connect()) as db:
            db.execute('UPDATE movie_viewings SET position=?,updated_at=? WHERE id=?',
                       (session.get('position'), datetime.now().isoformat(), session['id']))
            db.commit()

    def record(self, session, summary, replies, messages):
        cues = session.get('subtitles', [])
        proposals = getattr(replies, 'payload', {}).get('watch_quotes', [])
        with closing(self.connect()) as db:
            db.execute('UPDATE movie_viewings SET summary=? WHERE id=?', (summary, session['id']))
            for message in messages:
                db.execute('INSERT OR IGNORE INTO movie_message_links VALUES(?,?)', (message['id'], session['id']))
            if isinstance(proposals, list):
                for item in proposals[:3]:
                    if not isinstance(item, dict):
                        continue
                    text, thought = item.get('text'), item.get('thought', '')
                    if not isinstance(text, str) or not 2 <= len(text.strip()) <= 120 or not isinstance(thought, str):
                        continue
                    text = text.strip()
                    cue = next((c for c in cues if text in c['text']), None)
                    if cue is None:
                        continue
                    db.execute('INSERT OR IGNORE INTO movie_quotes(viewing_id,text,thought,position,created_at) VALUES(?,?,?,?,?)',
                               (session['id'], text, thought[:1000], cue['start'], datetime.now().isoformat()))
            db.commit()

    def messages(self, date=None, before=None, limit=100):
        conditions = ["m.source IN ('movie_watch','movie_chat')"]
        args = []
        if date:
            datetime.strptime(date, '%Y-%m-%d')
            conditions.append('substr(m.created_at,1,10)=?')
            args.append(date)
        if before is not None:
            conditions.append('m.id<?')
            args.append(before)
        with closing(self.connect()) as db:
            rows = db.execute('SELECT m.*, l.viewing_id, r.id AS request_id FROM messages m LEFT JOIN movie_message_links l ON l.message_id=m.id LEFT JOIN movie_chat_requests r ON r.message_id=m.id WHERE '
                              + ' AND '.join(conditions) + ' ORDER BY m.id DESC LIMIT ?', (*args, limit)).fetchall()
            return [dict(row) for row in reversed(rows)]

    def viewings(self):
        with closing(self.connect()) as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM movie_viewings ORDER BY started_at DESC')]
            for row in rows:
                row['quotes'] = [dict(q) for q in db.execute('SELECT * FROM movie_quotes WHERE viewing_id=? ORDER BY position,id', (row['id'],))]
            return rows

    def get(self, ident):
        return next((row for row in self.viewings() if row['id'] == ident), None)

    def accept_chat(self, ident, content, viewing_id, save):
        with closing(self.connect()) as db:
            previous = db.execute('SELECT * FROM movie_chat_requests WHERE id=?', (ident,)).fetchone()
            if previous:
                if previous['content'] != content or previous['viewing_id'] != viewing_id:
                    raise ValueError('不能用同一请求号发送不同内容')
                return dict(previous)
            mid = save('user', content, source='movie_chat', connection=db)
            db.execute('INSERT INTO movie_message_links VALUES(?,?)', (mid, viewing_id))
            db.execute('INSERT INTO movie_chat_requests VALUES(?,?,?,?,NULL)', (ident, mid, viewing_id, content))
            db.commit()
            return {'message_id': mid, 'replies': None}

    def chat_receipt(self, ident):
        with closing(self.connect()) as db:
            row = db.execute('SELECT r.*, m.created_at FROM movie_chat_requests r JOIN messages m ON m.id=r.message_id WHERE r.id=?', (ident,)).fetchone()
            return dict(row) if row else None

    def finish_chat(self, ident, viewing_id, messages):
        with closing(self.connect()) as db:
            for message in messages:
                db.execute('INSERT OR IGNORE INTO movie_message_links VALUES(?,?)', (message['id'], viewing_id))
            db.execute('UPDATE movie_chat_requests SET replies=? WHERE id=?', (json.dumps(messages, ensure_ascii=False), ident))
            db.commit()

    def claim_review(self, ident):
        with closing(self.connect()) as db:
            changed = db.execute("UPDATE movie_viewings SET review_status='writing' WHERE id=? AND status='completed' AND review_status IN ('none','error')", (ident,)).rowcount
            db.commit()
            return bool(changed)

    def claim_discussion(self, ident):
        with closing(self.connect()) as db:
            changed = db.execute("UPDATE movie_viewings SET discussion_status='writing' WHERE id=? AND status='completed' AND discussion_status IN ('none','error')", (ident,)).rowcount
            db.commit()
            return bool(changed)

    def discussion_messages(self, ident):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute('''SELECT m.id,m.role,m.content,m.created_at
                FROM messages m JOIN movie_message_links l ON l.message_id=m.id
                WHERE l.viewing_id=? AND m.source='movie_chat'
                AND (m.role='assistant' OR EXISTS(SELECT 1 FROM movie_chat_requests r
                    WHERE r.message_id=m.id AND r.replies IS NOT NULL)) ORDER BY m.id''', (ident,))]

    def discussion_result(self, ident, items=None, messages=()):
        with closing(self.connect()) as db:
            text = '\n'.join(item['text'] for item in items) if items else ''
            if items and self.memory_store:
                self.memory_store.record_viewing_discussion(db, ident, items, messages)
            db.execute('UPDATE movie_viewings SET discussion_status=?,discussion=? WHERE id=?',
                       ('ready' if items is not None else 'error', text, ident))
            db.commit()

    def review_result(self, ident, text=None):
        with closing(self.connect()) as db:
            db.execute('UPDATE movie_viewings SET review_status=?,review=? WHERE id=?',
                       ('ready' if text else 'error', text or '', ident))
            db.commit()
