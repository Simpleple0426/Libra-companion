"""Replayable bridge from delivered chat replies to personal itinerary review."""
import json
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
                if row[1] == 'running':
                    break  # preserve the original request's normal interpretation
                # Every delivered reply is context. Only the agent decides
                # whether it expresses a commitment; wording never gates review.
                if row[1] != 'applied':
                    request = json.loads(row[0])
                    replies = request.setdefault('assistant_replies', [])
                    if not any(r['id'] == mid for r in replies):
                        replies.append({'id': mid, 'content': content})
                        request['reply_itinerary_review'] = True
                        db.execute('UPDATE life_received_messages SET request=? WHERE id=?', (canonical(request), ident))
                        db.execute("UPDATE life_agenda_messages SET status='pending',attempts=0,retry_at=NULL WHERE message_id=?", (ident,))
                        count += 1
            db.execute('UPDATE life_reply_cursor SET value=? WHERE id=1', (mid,))
        return count
