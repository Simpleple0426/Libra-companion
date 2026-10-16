"""Bounded evidence preloading; model tools remain available for deeper reads."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from time import perf_counter

GREETING = re.compile(r'^(?:你好|嗨|早安|早上好|午安|晚安|在吗|嗯|嗯嗯|好|好的|谢谢|晚安啦)[！!。.?？～~\s]*$')
HISTORY = re.compile(r'以前|从前|那次|上次|往事|还记得|记不记得|一起|共同|个人线|卡面|剧情|未定|送我的|糗事|原话')


def contextual_plan(query, recent, snapshot=None, proactive=False):
    from domains.memory.recall_queries import plan
    result = plan(query, recent, snapshot, proactive)
    if proactive:
        # Verbatim user topics improve generic timer/event queries. They remain
        # historical context, never assertions about the user's present state.
        topics = [str(m.get('content') or '').strip()[:300] for m in recent[-8:]
                  if m.get('role') == 'user' and not GREETING.fullmatch(str(m.get('content') or '').strip())]
        for topic in list(dict.fromkeys(topics))[-2:]:
            if topic and topic != query:
                result.append({'text': topic, 'kind': 'context'})
    return result


def history_requested(query, planned):
    return bool(HISTORY.search(query) or any(HISTORY.search(p['text']) for p in planned))


def preload(retriever, context, query, recent, session, snapshot=None):
    """All successful results reach context before planning and generation."""
    started = perf_counter()
    trace = context['automatic_retrieval'] = {'mode': 'chat_preload', 'stores': {}}
    if not query.strip() or GREETING.fullmatch(query.strip()):
        trace['reason'] = 'greeting_or_empty'
        return
    planned = contextual_plan(query, recent, snapshot)
    context['query_plan'] = planned
    context.setdefault('degraded_components', [])
    def fetch(name, loader, count):
        entry = trace['stores'][name] = {'attempted': True}
        began = perf_counter()
        try:
            value = loader()
            entry.update(status='completed', injected_count=count(value))
            return value
        except Exception as error:
            entry.update(status='failed', error=type(error).__name__, injected_count=0)
            context['degraded_components'].append('automatic_' + name + '_unavailable')
            return None
        finally:
            entry['duration_ms'] = round((perf_counter() - began) * 1000, 2)
    history_needed = history_requested(query, planned)
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix='chat-preload') as executor:
        personal_future = executor.submit(copy_context().run, fetch, 'personal',
            lambda: retriever.personal_memory(query, thread_id=session,
                recent_messages=recent, query_plan=planned, limit=4, budget=3000),
            lambda p: len(p.get('memories', [])))
        character_future = executor.submit(copy_context().run, fetch, 'character',
            lambda: retriever.supporting_knowledge(
                query, thread_id=session, recent_messages=recent, query_plan=planned,
                character_only=True),
            lambda bundle: len(bundle.character_evidence))
        history_future = None
        if history_needed:
            def history_count(text):
                if not text:
                    return 0
                data = json.loads(text[text.index('{'):text.rindex('}') + 1])
                return len(data.get('reviewed_scenes', [])) + len(data.get('source_excerpts', []))
            history_future = executor.submit(copy_context().run, fetch, 'shared_history',
                lambda: retriever.shared_history_store.context_for(
                    query, thread_id=session, recent_messages=recent,
                    query_plan=planned, budget=4000), history_count)
        packet = personal_future.result()
        character = character_future.result()
        history = history_future.result() if history_future else None
    if packet is not None:
        context['memory_context'] = packet
        trace['stores']['personal']['degraded'] = packet.get('degraded', [])
        context['degraded_components'].extend(packet.get('degraded', []))
    if character is not None:
        context['character_evidence'] = character.character_evidence
        context['character_situations'] = character.character_situations
        trace['stores']['character']['degraded'] = character.degraded_components
        context['degraded_components'].extend(character.degraded_components)
    if history_needed:
        if history:
            context['supporting_knowledge'] = context.get('supporting_knowledge', '') + history
    else:
        trace['stores']['shared_history'] = {'attempted': False, 'reason': 'no_history_cue'}
    context['supporting_knowledge'] = (context.get('supporting_knowledge', '')
                                     + retriever.evidence_formatter(context.get('character_evidence', [])))
    trace['duration_ms'] = round((perf_counter() - started) * 1000, 2)
    context.setdefault('generation_constraints', []).append(
        '已自动提供相关记忆与角色参考。历史不是当前状态，角色语料不是用户经历；'
        '精确名称或原话证据不足时继续查工具或澄清，不得自行补全。无需为展示记忆而生硬提起往事。')
