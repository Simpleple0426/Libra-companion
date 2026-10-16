"""Replayable bridge from delivered chat replies to personal itinerary review."""
import json
import re
from life_prototype.config import canonical


def sync(engine, host):
    with engine.store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS life_reply_cursor(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)')
        cursor = db.execute('SELECT value FROM life_reply_cursor WHERE id=1').fetchone()
        if cursor is None:
            high = host.execute('SELECT COALESCE(MAX(id),0) FROM messages').fetchone()[0]
            db.execute('INSERT INTO life_reply_cursor VALUES(1,?)', (high,))
            return 0  # activation is not permission to replay old promises
        rows = host.execute("SELECT id,content FROM messages WHERE id>? AND role='assistant' AND source='chat' ORDER BY id LIMIT 100", (cursor[0],)).fetchall()
        count = 0
        for mid, content in rows:
            user = host.execute("SELECT id FROM messages WHERE role='user' AND id<? ORDER BY id DESC LIMIT 1", (mid,)).fetchone()
            if user:
                ident = 'app:' + str(user[0]) + ':ordinary'
                row = db.execute('SELECT m.request,a.status FROM life_received_messages m JOIN life_agenda_messages a ON a.message_id=m.id WHERE m.id=?', (ident,)).fetchone()
                if row is None:
                    goodnight = db.execute('SELECT 1 FROM life_received_messages WHERE id=?',
                        ('app:' + str(user[0]) + ':goodnight',)).fetchone()
                    if goodnight:
                        db.execute('UPDATE life_reply_cursor SET value=? WHERE id=1', (mid,))
                        continue
                    break  # inbox delivery has not committed yet; retry next poll
                if row[1] in {'pending', 'running'}:
                    break  # preserve the original request's normal interpretation
                # Only forward personal-life candidates. The agent judges actual
                # commitment, negation and quotes, rather than blindly executing.
                if row[1] != 'applied' and '陪' not in content and re.search(r'我.{0,24}(回家|回去|出发|下班|健身|运动|看书|看电影|休息|加班)', content):
                    request = json.loads(row[0])
                    if '陪' in request['content']:
                        db.execute('UPDATE life_reply_cursor SET value=? WHERE id=1', (mid,))
                        continue
                    replies = request.setdefault('assistant_replies', [])
                    if not any(r['id'] == mid for r in replies):
                        replies.append({'id': mid, 'content': content})
                        request['reply_itinerary_review'] = True
                        db.execute('UPDATE life_received_messages SET request=? WHERE id=?', (canonical(request), ident))
                        db.execute("UPDATE life_agenda_messages SET status='pending',attempts=0,retry_at=NULL WHERE message_id=?", (ident,))
                        count += 1
            db.execute('UPDATE life_reply_cursor SET value=? WHERE id=1', (mid,))
        return count
