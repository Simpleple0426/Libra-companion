"""Versioned event and model contracts. No database or model side effects."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / 'config'
SETTINGS = json.loads((CONFIG/'emotion_v1.json').read_text(encoding='utf-8'))
EVENT_TYPES = {
    'scheduled_checkin': {'scheduled_probe'},
    'libra_life_state': {'life_event'},
    'user_manual_state': {'internal_state_change','state_transition'},
    'user_life_activity': {'activity_started','activity_ended','activity_updated','location_departed','location_arrived','checkpoint_completed','state_transition'},
    'weather': {'environment_change'}, 'habit_reminder': {'habit_due','habit_completed'},
    'conversation': {'user_message'},
    'cognition_trigger': {'response_requested'},
}


def timestamp(value=None):
    if value is None:return datetime.now(timezone.utc)
    if isinstance(value,str):value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.tzinfo is None:value=value.astimezone()
    return value.astimezone(timezone.utc)


def iso(value=None):return timestamp(value).isoformat()


def event(source, source_id, subject, event_type, description, occurred_at=None, scope='instant'):
    if source not in EVENT_TYPES or event_type not in EVENT_TYPES[source]:raise ValueError('invalid_event_mapping')
    if subject not in {'user','libra','relationship','environment','world'} or scope not in {'instant','ongoing'}:raise ValueError('invalid_event_subject_or_scope')
    if not isinstance(description,str) or not description.strip():raise ValueError('invalid_event_description')
    if len(description)>20000:description=description[:19950]+'\n[事件描述已截短；完整原始消息由 source_key 关联保存]'
    if not source_id:raise ValueError('stable_source_id_required')
    key=hashlib.sha256(f'{source}:{source_id}:{event_type}'.encode()).hexdigest()[:32]
    return {'event_id':'evt_'+key,'source':source,'subject':subject,'event_type':event_type,
            'description':description,'occurred_at':iso(occurred_at),'scope':scope}


def validate(value,schema):
    """Strict subset used by the checked-in schemas (including finite numbers)."""
    if 'oneOf' in schema:
        successes=0
        for candidate in schema['oneOf']:
            try:validate(value,candidate);successes+=1
            except ValueError:pass
        if successes!=1:raise ValueError('schema_one_of')
        return
    kind=schema.get('type')
    valid={'object':lambda:isinstance(value,dict),'array':lambda:isinstance(value,list),
           'string':lambda:isinstance(value,str),'number':lambda:type(value) in (int,float) and math.isfinite(value),
           'null':lambda:value is None}
    if kind in valid and not valid[kind]():raise ValueError('schema_type')
    if 'enum' in schema and value not in schema['enum']:raise ValueError('schema_enum')
    if kind=='object':
        if set(schema.get('required',[]))-set(value):raise ValueError('schema_required')
        if schema.get('additionalProperties') is False and set(value)-set(schema.get('properties',{})):raise ValueError('schema_unknown_field')
        for key,item in value.items():
            if key in schema.get('properties',{}):validate(item,schema['properties'][key])
    if kind=='array':
        if len(value)>schema.get('maxItems',100):raise ValueError('schema_max_items')
        for item in value:validate(item,schema['items'])
    if kind=='number' and not schema.get('minimum',-math.inf)<=value<=schema.get('maximum',math.inf):raise ValueError('schema_range')
    if kind=='string':
        if len(value)<schema.get('minLength',0) or len(value)>20000:raise ValueError('schema_string_length')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'],value):raise ValueError('schema_pattern')
        if schema.get('format')=='date-time':
            if datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is None:raise ValueError('timezone_required')


def parse_model_json(value):
    """Accept JSON itself or a single fenced JSON object, but no prose."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith('```') and text.endswith('```'):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {'```', '```json'} and lines[-1].strip() == '```':
            text = '\n'.join(lines[1:-1]).strip()
    return json.loads(text)


def model_output(kind,value):
    value=parse_model_json(value)
    validate(value,json.loads((CONFIG/f'{kind}_schema.json').read_text(encoding='utf-8')))
    return value


def prompt(kind,payload):
    instruction=(CONFIG/f'{kind}_prompt.txt').read_text(encoding='utf-8')
    if kind=='appraisal' and payload.get('appraisal_mode')=='light':
        instruction += ('\n\n【本轮为轻量 Appraisal】只判断当前事件是否直接影响 Core Goal 或明确违反/符合 Standard。'
                        '通常返回两个空数组；确有直接证据时最多输出一个 Goal Appraisal 和一个 Standard Appraisal。')
    schema=(CONFIG/f'{kind}_schema.json').read_text(encoding='utf-8')
    allowed={}
    if kind=='appraisal':
        allowed={
            'parent_core_goal_id':[item['goal_id'] for item in payload.get('core_goals',[])],
            'standard_id':[item['standard_id'] for item in payload.get('standards',[])],
            'goal_id_rule':'为本次 Active Goal 生成简短、稳定的 snake_case ID；它不是 parent_core_goal_id',
        }
    return (instruction
        +'\n<required_output_contract>\n输出必须逐项满足下面的 JSON Schema；不得遗漏 event_id、goal_id、goal_description 或 parent_core_goal_id。'
        +' event_id 必须逐字复制 input_data.event.event_id。没有适用项时使用空数组。\n'
        +schema+'\n</required_output_contract>'
        +('\n<allowed_ids>\n'+json.dumps(allowed,ensure_ascii=False)+'\n</allowed_ids>' if allowed else '')
        +'\n<input_data>\n'+json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e')+'\n</input_data>')
