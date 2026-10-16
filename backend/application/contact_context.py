"""Bounded conversation evidence for proactive decisions, without a summary call."""
from contextlib import closing


def recent_messages(messages):
    return [{key: item.get(key) for key in ('id', 'role', 'content', 'created_at', 'source')}
            for item in messages[-20:]]


def reporting_evidence(connect):
    """Keep original reporting requests and follow-ups beyond the recent window.

    These are historical quotes, not a claim that an agreement remains active.
    The decision must check cancellation, fulfillment and timing against context.
    """
    with closing(connect()) as db:
        rows = db.execute("""SELECT id,role,content,created_at,source FROM messages
            WHERE source NOT IN ('movie_watch','movie_chat','music_room')
              AND (content LIKE '%报备%' OR content LIKE '%到%说一声%'
                   OR content LIKE '%到%告诉我%' OR content LIKE '%到了%'
                   OR content LIKE '%到律所%' OR content LIKE '%不用%说%'
                   OR content LIKE '%不用%告诉%' OR content LIKE '%不必%告诉%')
            ORDER BY id DESC LIMIT 6""").fetchall()
        found = {row['id']: dict(row) for row in rows}
        for row in rows:
            for followup in db.execute("""SELECT id,role,content,created_at,source FROM messages
                    WHERE id>? AND source NOT IN ('movie_watch','movie_chat','music_room')
                    ORDER BY id LIMIT 2""", (row['id'],)):
                found[followup['id']] = dict(followup)
    return [found[key] for key in sorted(found)][-12:]
