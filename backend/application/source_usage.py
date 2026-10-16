"""Turn-local topic preference and atomic evidence-backed usage receipts."""
import json
import re
from datetime import datetime, timedelta, timezone

WINDOW_HOURS = 2


def catalogue(context):
    items = []
    for m in context.get('memory_context', {}).get('memories', []):
        items.append({'source': 'lmc', 'id': m['memory_id'], 'content': m.get('content', '')})
    for m in context.get('character_evidence', []):
        items.append({'source': 'character', 'id': m['id'], 'content': m.get('context', '')})
    text = context.get('supporting_knowledge', '')
    match = re.search(r'<canonical_shared_history>.*?(\{.*\})\s*</canonical_shared_history>', text, re.S)
    if match:
        try:
            data = json.loads(match.group(1))
            for m in data.get('reviewed_scenes', []):
                items.append({'source': 'canonical', 'id': m['history_id'], 'content': m.get('summary', '')})
            for m in data.get('source_excerpts', []):
                items.append({'source': 'canonical', 'id': m['chunk_id'], 'content': m.get('transcript_excerpt', '')})
        except (ValueError, KeyError):
            pass
    return list({(m['source'], m['id']): m for m in items}.values())


def preferences(connection, context, proactive, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=WINDOW_HOURS)).isoformat()
    recent = {}
    for row in connection.execute("SELECT f.value_json FROM cognition_feedback f JOIN cognition_delivery d USING(turn_id) WHERE f.kind='source_usage' AND d.status='available' AND datetime(f.created_at)>=datetime(?)", (cutoff,)):
        try:
            for item in json.loads(row[0]):
                if item.get('mode') == 'mention':
                    recent[(item['source'], item['id'])] = True
        except (ValueError, KeyError, TypeError):
            continue
    return [{**m, 'topic_weight': .4 if proactive and m['source'] != 'character' and (m['source'], m['id']) in recent else 1.0,
             'recently_mentioned': (m['source'], m['id']) in recent}
            for m in catalogue(context)]


def confirmed(value, context, replies):
    if isinstance(context.get('automatic_retrieval'), dict):
        context['automatic_retrieval']['confirmed_reply_references'] = {
            source: 0 for source in ('lmc', 'character', 'canonical')}
    allowed = {(m['source'], m['id']) for m in catalogue(context)}
    result = {}
    if not isinstance(value, list):
        return []
    for item in value:
        if not isinstance(item, dict):
            continue
        source, identity, quote = item.get('source'), item.get('id'), item.get('quote')
        index = item.get('reply_index')
        mode = 'reference' if source == 'character' else 'mention'
        if (isinstance(source, str) and isinstance(identity, str) and (source, identity) in allowed
                and type(index) is int and 0 <= index < len(replies)
                and isinstance(quote, str) and quote.strip() and quote in replies[index]
                and item.get('mode') == mode):
            result[(source, identity, index)] = dict(source=source, id=identity, mode=mode, quote=quote, reply_index=index)
    confirmed_items = list(result.values())
    if isinstance(context.get('automatic_retrieval'), dict):
        context['automatic_retrieval']['confirmed_reply_references'] = {
            source: sum(item['source'] == source for item in confirmed_items)
            for source in ('lmc', 'character', 'canonical')}
    return confirmed_items
