"""Transport shape schemas mirror host contracts; no semantic or state authority."""

S={'type':'string'}; I={'type':'integer'}; B={'type':'boolean'}
NS={'type':['string','null']}; NI={'type':['integer','null']}
def obj(**properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def arr(item):return {'type':'array','items':item}
REF=arr(S)
ACTION=obj(operation={'type':'string','enum':['start','continue','resume','switch','wait']},activity_id=NS,
           kind={'type':['string','null'],'enum':['reading','cooking','eating','moving','serving','work','showering','exercising','personal_care','housework','television','rest','outing','watching',None]},target=NS)
MOVE_PURPOSE=obj(kind={'type':'string','enum':['meal','workday_duty','pending_work','reading','cooking','shower','housework','work_skill','general_study','return_home','resume_activity','daily_agenda','fine_agenda']},reference_id=NS)
PURPOSE_OR_NULL={'anyOf':[MOVE_PURPOSE,{'type':'null'}]}
def movement_variants(fields, action_field, payload=None):
    """Constrain the purpose to new movement, including before host validation."""
    from copy import deepcopy
    variants=[]
    for moving, operations in ((True,['start','switch']), (False,['continue','resume','wait']), (False,['start','switch'])):
        branch=deepcopy(fields)
        action=branch[action_field]['properties']
        action['operation']={'type':'string','enum':operations}
        if moving:
            action['kind']={'type':'string','enum':['moving']}
            action['activity_id']={'type':'null'}
            branch['movement_purpose']=MOVE_PURPOSE
        else:
            if operations == ['start','switch']:
                action['kind']={'type':['string','null'],'enum':['reading','cooking','eating','serving','work','showering','exercising','personal_care','housework','television','rest','outing','watching',None]}
            branch['movement_purpose']={'type':'null'}
        variants.append(obj(**branch))
    resumed_switch=deepcopy(fields)
    resumed_switch[action_field]['properties'].update(
        operation={'type':'string','enum':['switch']},
        kind={'type':'string','enum':['moving']}, activity_id={'type':'string'})
    resumed_switch['movement_purpose']={'type':'null'}
    variants.append(obj(**resumed_switch))
    state = (payload or {}).get('state')
    if state is not None:
        active = state.get('active')
        for branch in variants:
            operation = branch['properties'][action_field]['properties']['operation']
            allowed = {'continue','switch'} if active else {'start','resume','wait'}
            operation['enum'] = [op for op in operation['enum'] if op in allowed]
        variants = [branch for branch in variants if branch['properties'][action_field]['properties']['operation']['enum']]
    return variants
FACTS=obj(segment_from=NS,segment_to=NS,final_destination=NS,activity_completed={'type':['boolean','null']})


def schema(stage,payload):
    if stage == 'library_intro': return obj(body=S)
    if stage == 'outing_query': return obj(query=S)
    if stage == 'outing_choose': return obj(book_id=S)
    if stage in {'outing_intro','outing_walk'}: return obj(body=S)
    if stage == 'leisure_thought': return obj(body=S)
    if stage == 'meal_plan':
        return obj(mode={'type':'string','enum':['cook','takeout','packed','dine']},place=S,dishes=arr(S),
                   spice={'type':'string','enum':['none']},user_consideration=S,reason=S)
    if stage == 'quote_note':
        return obj(entries=arr(obj(candidate_id=S, translation=S, thought=S)))
    if stage == 'movie_review':
        return obj(consult_short_reviews=B, title=S, review=S, memory_summary=S)
    if stage == 'life_agent':
        from .autonomous_agent import TOOLS
        return obj(tool={'type':'string','enum':list(TOOLS)}, arguments_json=S)
    if stage=='fine_agenda':
        return obj(blocks=arr(obj(kind={'type':'string','enum':['reading','watching','work']},target=S,duration_seconds=I)),reason=S)
    if stage=='media_mentions':
        return obj(items=arr(obj(kind={'type':'string','enum':['book','movie']},title=S,author=S,year=S,
                                 priority={'type':'string','enum':['request','mention']},evidence_quote=S)))
    if stage=='agenda_reaction':
        return obj(decision={'type':'string','enum':['none','revise','clarify']},reason=S,evidence_quote=S,
                   cancel_item_ids=REF,cancel_appointment_ids=REF,
                   appointments=arr(obj(title=S,start_at=NS,duration_seconds=I)),
                   itinerary_changes=arr(obj(operation={'type':'string','enum':['cancel','replace','reschedule','return_home']},
                       item_id=NS,start_at=NS,end_at=NS,activity=NS,place_id=NS)))
    if stage=='contract_probe':
        return obj(**{k: B if isinstance(v,bool) else I if isinstance(v,int) else S for k,v in payload['expected'].items()})
    if stage in {'guard','p3_guard'}:return obj(approved=B,issues=REF)
    if stage=='movement_expression':return obj(facts=FACTS,supported=B,issues=REF)
    if stage=='movement_summary':return obj(summary=S,movement_facts=FACTS)
    if stage=='assimilate':
        fields=dict(importance=I,keywords=REF,summary=S,evidence_ids=REF)
        if payload.get('movement_evidence'):fields['movement_facts']=FACTS
        return obj(**fields)
    if stage=='focal':return obj(questions=REF)
    if stage=='reflect':return obj(insights=arr(obj(description=S,importance=I,keywords=REF,evidence_ids=REF)))
    if stage=='plan':
        fields=dict(id=S,goal=S,start_after_seconds=I,duration_seconds=NI,evidence_ids=REF)
        if payload.get('executor_constraints'):
            fields['execution']=obj(**ACTION['properties'],scope={'type':'string','enum':['checkpoint','complete']})
            fields['additional_actions']=arr(obj(action=S,place=S,duration_seconds=I))
            if payload.get('movement_purpose_contract'):fields['movement_purpose']=PURPOSE_OR_NULL
        variants=movement_variants(fields,'execution') if payload.get('movement_purpose_contract') and payload.get('executor_constraints') else [obj(**fields)]
        # Delegated route timing has no model-known end offset. Return that
        # immediate item alone, or supply a fully timed sequence for host checks.
        from copy import deepcopy
        timed=[]
        for variant in variants:
            timed_item=deepcopy(variant)
            timed_item['properties']['duration_seconds']={'type':'integer','minimum':1}
            timed.append(timed_item)
        return obj(items={'anyOf':[
            {'type':'array','items':{'anyOf':movement_variants(fields,'execution',payload) if payload.get('movement_purpose_contract') and payload.get('executor_constraints') else variants},'minItems':1,'maxItems':1},
            {'type':'array','items':{'anyOf':timed},'minItems':2,'maxItems':6}]})
    if stage=='decompose':
        fields=dict(intent=S,duration_seconds=I,evidence_ids=REF)
        if payload.get('near_executor_check',{}).get('route_check'):fields['route_span']=obj(from_index=I,to_index=I)
        return obj(plan_item_id=S,steps=arr(obj(**fields)))
    if stage=='candidates':
        fields=dict(id=S,description=S,action=ACTION,evidence_ids=REF)
        if payload.get('movement_purpose_contract'):fields['movement_purpose']=PURPOSE_OR_NULL
        entry={'anyOf':movement_variants(fields,'action',payload)} if payload.get('movement_purpose_contract') else obj(**fields)
        return obj(candidates=arr(entry))
    if stage=='predict':return obj(forecasts=arr(obj(candidate_id=S,summary=S,evidence_ids=REF)))
    if stage=='select':return obj(candidate_id=S,summary=S,evidence_ids=REF)
    if stage=='read':return obj(note=S,evidence_ids=REF,claims=arr(obj(statement=S,quote=S,evidence_id=S)))
    if stage=='work':return obj(stage=I,entries=arr(obj(source_id=S,quote=S,field=S,quantity=I,status=S)),discrepancy=NI,summary=S)
    if stage=='p3_reply':return obj(reply=S,basis=S,evidence_ids=REF)
    raise ValueError('no CLI schema for stage '+stage)
