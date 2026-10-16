"""Minimal writer projection; decisions and response content stay separate."""
import json


def expression_plan(plan):
    if isinstance(plan.get('tone_guidance'), str):
        return {'should_send': plan.get('should_send', True), 'tone_guidance': plan['tone_guidance']}
    guide = plan.get('expression_guidance') or {}
    tone = []
    for item in guide.get('feelings', [])[:1]:
        if item.get('feeling'):
            tone.append(str(item['feeling']))
    for item in guide.get('mood_tendency', [])[:1]:
        if item.get('guidance'):
            tone.append(str(item['guidance']))
    return {'should_send': plan.get('should_send', True), 'tone_guidance': '；'.join(tone)}


def recalled_memories(packet):
    """Only readable memory text reaches the writer; provenance stays in the packet."""
    return [('（已被更新的历史记录）' if item.get('epistemic_label') == 'historical_fact' else '')
            + item['content'] for item in packet.get('memories', []) if item.get('content')]


def memory_block(packet):
    """Shared memory presentation for every event's response generator."""
    text = '\n\n'.join(recalled_memories(packet)).replace('<', '\\u003c').replace('>', '\\u003e')
    if not text:
        return ''
    return ('\n<retrieved_memory>\n相关历史记忆，仅作背景，不代表当前状态或安排；当前事件优先。\n'
            + text + '\n</retrieved_memory>\n')


def contact_prompt(context):
    """Use the event as data, not the scheduler's old acting instructions."""
    current = context.get('current_event') or {}
    event = context.get('unified_event') or {}
    data = {'description': event.get('description') or current.get('content', ''),
            'source': event.get('source') or current.get('source'),
            'occurred_at': event.get('occurred_at') or current.get('occurred_at')}
    if current.get('contact_authorization'):
        data['contact_authorization'] = current['contact_authorization']
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
    from application.proactive_novelty import RULE
    from application.proactive_topic import writing_context
    life_detail_guidance = (
        '本次是主动分享生活，只简短表达值得分享的近况或感受，不展开动态详情。'
        '不要主动列出吃了什么、菜名、食材、菜单、份量或做饭步骤；这些事实保留为背景，'
        '等用户在后续聊天中明确追问时，再根据已有记录回答。'
        '用户此前明确要求主动告知的具体内容按其约定回答；不要自行假设存在这种要求。'
        if data['source'] == 'libra_life_state' else '')
    if context.get('requested_life_report'):
        life_detail_guidance += (
            '她希望你在吃饭、上班和实际回到家时主动说一声。本轮是其中一个已发生的节点，'
            '自然简短地告知这次事实即可；上班开始不等于刚出门，出发不等于已经到家。'
            '不补造饭菜、位置变化或她的状态，不要求回复，也不追加完成后报到的约定。')
    return (RULE + writing_context(context) + '<event>\n' + encoded + '\n</event>\n'
            + life_detail_guidance +
            '已决定主动发送 1 条消息。只输出 JSON：{"messages":["消息内容"]}。'
            '可用 [[voice:内容]] 发语音，或单独用 [[pat:短语]] 拍一拍。')
