"""Evidence-bound query planning and weighted rank fusion, without usage writes."""
import math
import re
from .base import identity_tokens

QUERY_WEIGHTS = {'original': 1.0, 'resolved': .9, 'fallback': .6, 'context': .7, 'situation': 1.0}
CHANNEL_WEIGHTS = {'vector': 1.0, 'fts': 1.0, 'graph': .5, 'emotion': .35, 'perception': .25}
REFERENCE = re.compile(r'那个|那件事|那次|上次|之前说的|以前提过|后来|结果|后续')


def plan(query, recent, snapshot=None, proactive=False):
    result = [{'text': query, 'kind': 'original'}]
    if REFERENCE.search(query):
        evidence = next((str(m.get('content') or '').strip()[:300] for m in reversed(list(recent))
                         if m.get('role') == 'user' and str(m.get('content') or '').strip()
                         and str(m.get('content')).strip() != query), '')
        if evidence:
            # Keep verbatim evidence; do not invent a resolved entity or intention.
            result.append({'text': query + '\n' + evidence, 'kind': 'resolved'})
    if proactive and snapshot:
        libra = snapshot.get('libra') or {}
        for field in ('activity', 'location_name'):
            observation = libra.get(field) or {}
            value = observation.get('value') if isinstance(observation, dict) else None
            if value and value != 'unknown' and observation.get('confidence', 1) >= .5:
                activities = {'working': '工作', 'commuting': '通勤', 'eating': '吃饭',
                              'resting': '休息', 'leisure': '休闲', 'exercising': '运动',
                              'sleeping': '睡眠', 'studying': '学习', 'free': '空闲'}
                label = activities.get(str(value), str(value)) if field == 'activity' else str(value)
                result.append({'text': '左然当前活动：' + label if field == 'activity' else '左然当前地点：' + label, 'kind': 'context',
                               'source_ref': 'current_context.libra.' + field})
    return result


def fallback_queries(planned):
    texts = []
    for item in planned:
        terms = sorted({word for term in identity_tokens(item['text'])
                        for word in term.split()}, key=lambda t: (-len(t), t))
        terms = [t for t in terms if len(t) >= 2][:12]
        if terms:
            texts.append({'text': ' '.join(terms), 'kind': 'fallback'})
    seen = {p['text'] for p in planned}
    result = []
    for item in texts:
        if item['text'] not in seen:
            seen.add(item['text'])
            result.append(item)
    return result[:2]


def fuse(searches, association_channels, query_weights=None, channel_weights=None, k=60):
    k = float(k)
    if not math.isfinite(k) or k < 0:
        raise ValueError('invalid_rrf_k')
    qw = {**QUERY_WEIGHTS, **(query_weights or {})}
    cw = {**CHANNEL_WEIGHTS, **(channel_weights or {})}
    if any(not math.isfinite(float(v)) or float(v) < 0 for v in [*qw.values(), *cw.values()]):
        raise ValueError('invalid_recall_weight')
    parts = {}
    for kind, channels in searches:
        for channel, ids in channels.items():
            for rank, mid in enumerate(dict.fromkeys(ids), 1):
                score = float(qw[kind]) * float(cw[channel]) / (k + rank)
                if score == 0:
                    continue
                record = parts.setdefault(mid, {})
                # Paraphrases cannot stack votes within the same evidence channel.
                record[channel] = max(record.get(channel, 0), score)
    for channel, ids in association_channels.items():
        if float(cw.get(channel, 1)) == 0:
            continue
        for rank, mid in enumerate(dict.fromkeys(ids), 1):
            parts.setdefault(mid, {})[channel] = float(cw.get(channel, 1)) / (k + rank)
    return {mid: sum(values.values()) for mid, values in parts.items()}, parts


def ranked_search(search, query, query_plan=None, limit=6, key='id'):
    """Retain each source's native ranking; fuse query variants without duplicate votes."""
    planned = query_plan or plan(query, ())
    scores, records = {}, {}
    def collect(item):
        found = search(item['text'])
        for rank, record in enumerate(found, 1):
            identity = record[key]
            records[identity] = record
            scores[identity] = max(scores.get(identity, 0), QUERY_WEIGHTS[item['kind']] / (60 + rank))
        return bool(found)
    found = False
    for item in planned:
        found = collect(item) or found
    if not found:
        for item in fallback_queries(planned):
            if collect(item):
                break
    return [records[mid] for mid in sorted(scores, key=scores.get, reverse=True)[:limit]]
