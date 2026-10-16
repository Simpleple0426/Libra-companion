"""Evidence-linked understanding of the user's current expressed emotion."""
from datetime import timedelta

from application.diary_context import event_time
from domains.persona.situation import character_situations


def understand(messages, now, model):
    recent = [item for item in messages
              if item.get('role') in {'user', 'assistant'}
              and (at := event_time(item.get('created_at'))) is not None
              and now - timedelta(hours=24) <= at <= now]
    latest = next((item for item in reversed(recent)
                   if item.get('role') == 'user' and str(item.get('content') or '').strip()), None)
    if latest is None:
        return []
    query = str(latest['content'])
    index = recent.index(latest)
    return character_situations(query, recent[max(0, index - 6):index], [], model,
                                emotional_only=True)
