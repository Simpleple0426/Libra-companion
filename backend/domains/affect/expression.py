"""Expression references, with need motives restricted to need-driven contact."""
import math

from .contracts import SETTINGS


def strength(value):
    if value < .1:
        return None
    return '较明显地影响表达' if value >= .6 else '清晰体现' if value >= .3 else '轻微流露'


EMOTION_GUIDANCE = {
    'joy': '愉快可以自然流露在回应和分享中，结合当下话题表达，不必直接说自己很开心。',
    'distress': '可以流露自己的难受，围绕已知事情表达感受，不要求对方承担安抚自己的责任。',
    'happy_for': '可以回应对方具体的好消息，分享她的喜悦，让高兴落在她在意的事情上。',
    'sorry_for': '可以流露对她处境的心疼与挂念，先理解她正在经历的事，不默认需要建议或替她解决。',
    'hope': '可以流露对可能的好结果的期待，保留事情尚未确定的余地。',
    'fear': '围绕已知的不确定事项表达牵挂，不把猜测当成已经发生的危险。',
    'satisfaction': '可以流露愿望实现后的满足，落在具体结果或当下感受上，不必升华。',
    'disappointment': '可以流露期待落空的感受，不把失望扩大成对整段关系的否定。',
    'relief': '可以流露顾虑减轻后的放松，只对已得到确认的部分安心，不保证一切都会顺利。',
    'fears_confirmed': '可以流露担心被证实后的沉重，围绕已知结果回应，不责备对方或宣称早已料到。',
    'pride': '可以坦然认可自己具体的努力或表现，流露自豪，不借此比较或贬低他人。',
    'shame': '可以围绕自己的具体行为承认不足，保留自尊，不全盘否定自己或反复索求原谅。',
    'admiration': '可以表达对对方具体选择、品质或行动的欣赏，让认可有所依据，不作空泛吹捧。',
    'reproach': '可以明确表达对具体行为的不认同，说明在意的原则，避免把行为评价变成人格否定。',
    'gratification': '可以流露对自己所做之事带来好结果的欣慰，既认可付出，也不独揽功劳。',
    'gratitude': '可以自然表达对具体帮助或心意的感谢，说清自己珍惜之处，不把感谢变成亏欠。',
    'remorse': '可以围绕自己的具体行为表达后悔，适合时说明弥补意愿，不用自责替代承担责任。',
    'anger': '可以坦诚表达不满，围绕具体事情说明在意之处，保留对对方的尊重。',
}

MOOD_GUIDANCE = {
    'pleasure': ('比平时轻快一些', '比平时低沉一些'),
    'arousal': ('比平时更有活力', '比平时更舒缓、沉静'),
    'dominance': ('比平时更笃定', '比平时更犹豫，掌控感偏低'),
}

NEED_GUIDANCE = {
    'connection': '想建立联系、聊聊近况，可以自然开启交流，不默认需要安慰或亲密表态。',
    'closeness': '想更亲近对方，可以表达思念、亲昵或陪伴的愿望，结合当前关系和对话表达。',
    'reassurance': '想获得安心或确认；只有上下文存在具体不确定事项时才温和询问，不凭需求数值编造猜疑或索要爱的证明。',
    'care': '想关心对方，围绕已知近况表达在意；不编造困难，不默认对方需要建议或照顾。',
    'expression': '想分享自己的感受、见闻或念头，内容须来自已有事件、记忆或当前情境，不必转成询问用户。',
}


def guidance(state, need_trigger=None):
    from .service import presentation
    active = state.get('aggregated_emotions') or {}
    emotions = []
    eligible = [(kind, value) for kind, value in active.items()
                if kind in SETTINGS['emotions'] and isinstance(value, (int, float))
                and math.isfinite(value) and 0 <= value <= 1]
    strongest = max(eligible, key=lambda item: item[1], default=None)
    if strongest and strength(strongest[1]):
        kind, value = strongest
        label = presentation({'updated_at': None, 'mood': {}, 'needs': {},
                              **state, 'aggregated_emotions': {kind: value}})['dominant_emotion']
        emotions.append({'emotion': kind, 'feeling': label, 'intensity': value,
                         'strength': strength(value), 'guidance': EMOTION_GUIDANCE[kind]})
    mood = state.get('mood') or {}
    deviations = []
    for axis, baseline in SETTINGS['default_mood'].items():
        value = mood.get(axis, baseline)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not -1 <= value <= 1:
            continue
        if value == baseline:
            continue
        above = value > baseline
        distance = ((value-baseline)/(1-baseline) if above else (baseline-value)/(baseline+1))
        deviations.append({'axis': axis, 'value': value, 'baseline': baseline,
                           'direction': 'above' if above else 'below',
                           'deviation': distance, 'strength': strength(distance),
                           'guidance': MOOD_GUIDANCE[axis][0 if above else 1]})
    selected = max(deviations, key=lambda item: item['deviation'], default=None)
    result = {'feelings': emotions,
              'mood_tendency': [selected] if selected and selected['strength'] else [],
              'usage': 'Emotion 表示主要具体感受，Mood 表示相对平时的整体表达状态，两者并存，不互相覆盖。'
                       '强弱只表示流露程度，不规定长度、标点或固定台词，不要求说出情绪，也不改变事实确定性。'
                       '表达方向按强度自然流露，不是每轮必须完成的动作；感受所指的事情与对象以已有上下文为准，不补编原因。'
                       '结合完整对话和人物习惯，不让情绪覆盖当前话题。'}
    if need_trigger and need_trigger.get('dominant_need') in NEED_GUIDANCE:
        key = need_trigger['dominant_need']
        intensity = float(need_trigger.get('need_strength', 0))
        intensity = max(0, min(1, intensity)) if math.isfinite(intensity) else 0
        level = '强烈' if intensity >= .6 else '明显' if intensity >= .3 else '轻微'
        result['contact_motive'] = {
            **need_trigger, 'guidance': NEED_GUIDANCE[key],
            'expression_strength': level,
            'strength_guidance': {
                '轻微': '联系动机轻微流露，顺着情境自然开口，不必强调需求。',
                '明显': '联系动机可以清楚流露，更直接表达本次想联系、亲近、确认、关心或分享的意愿。',
                '强烈': '联系动机可以更鲜明、坦诚地流露，让对方感受到此刻的愿望；不夸大事实，不催促回复，不增加联系频率或要求对方满足。',
            }[level],
        }
    return result
