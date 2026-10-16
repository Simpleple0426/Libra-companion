"""Ground contact intentions in a selected topic before writing a message."""
import json


INSTRUCTION = (
    '先判断近期话题状态，再选择本次联系契机。已确认、已解决、已收尾的话题不能仅换措辞重发。'
    '从当前真实事件、已提供的个人记忆、明确未完成的话题或新的自然交流意图中最多选一个。'
    '回忆必须与当前情境有自然联系；近期已提过的回忆不能仅重复原结论。'
    '旧记忆不是刚发生的事，不能包装成“我刚才又……”；用户过去的感受不是现在的感受。'
    '新进展可以延续已结束话题，但必须说明新增价值。没有合适契机时should_send=false，'
    '即使长时间未联系也不能为凑频率复述。不要在选题阶段代写最终消息。'
    '发送时额外返回topic对象：{"kind":"memory|event|unfinished|new",'
    '"angle":"要交流的主题或角度","novelty":"相对近期交流新增的价值",'
    '"memory_ids":["memory_context中真实ID"],"evidence_quotes":["近期对话或当前事件中的逐字依据"]}。'
    'memory类型必须引用记忆ID；event和unfinished类型必须引用逐字依据。'
)


def validate_topic(topic, context):
    if not isinstance(topic, dict) or topic.get('kind') not in {'memory', 'event', 'unfinished', 'new'}:
        raise ValueError('missing_contact_topic')
    for field in ('angle', 'novelty'):
        if not isinstance(topic.get(field), str) or not 1 <= len(topic[field].strip()) <= 600:
            raise ValueError('invalid_topic_' + field)
    ids = topic.get('memory_ids', [])
    quotes = topic.get('evidence_quotes', [])
    memories = {m['memory_id'] for m in context.get('memory_context', {}).get('memories', [])}
    if not isinstance(ids, list) or len(ids) > 2 or any(not isinstance(i, str) or i not in memories for i in ids):
        raise ValueError('unobserved_topic_memory')
    text = '\n'.join(str(m.get('content', '')) for m in context.get('decision_recent_messages', []))
    text += '\n' + str(context.get('unified_event', {}).get('description', ''))
    text += '\n' + '\n'.join(str(m.get('content', '')) for m in context.get('reporting_evidence', []))
    continuity = (context.get('context_snapshot', {}).get('local_life') or {}).get('life_continuity') or {}
    facts = [item.get('description', '') for item in continuity.get('recent_events', [])]
    for thread in continuity.get('threads', []):
        facts.extend(item.get('description', '') for item in thread.get('milestones', []))
    text += '\n' + '\n'.join(str(fact) for fact in facts)
    # A saved thought may ground a new exchange, but never a claimed event.
    if topic['kind'] == 'new':
        text += '\n' + '\n'.join(str(item.get('body', '')) for item in continuity.get('private_thoughts', []))
        text += '\n' + '\n'.join(str(item.get('thought', '')) for item in continuity.get('work_notes', []))
    if not isinstance(quotes, list) or len(quotes) > 3 or any(
            not isinstance(q, str) or not q.strip() or q not in text for q in quotes):
        raise ValueError('unobserved_topic_evidence')
    if topic['kind'] == 'memory' and not ids:
        raise ValueError('memory_topic_requires_source')
    if topic['kind'] in {'event', 'unfinished'} and not quotes:
        raise ValueError('topic_requires_evidence')
    return {k: topic.get(k, []) for k in ('kind', 'angle', 'novelty', 'memory_ids', 'evidence_quotes')}


def writing_context(context):
    topic = context.get('contact_topic')
    if not topic:
        return ''
    return ('\n<contact_topic>\n' + json.dumps(topic, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
            + '\n</contact_topic>\n围绕已选角度自然交流，不重新选择已结束话题；回忆明确作为过去经历，'
              '不要用“我刚才又想了一遍”包装旧结论。不必向用户解释选题机制。\n')
