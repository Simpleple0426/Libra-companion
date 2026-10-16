"""Minimal model projection; the private full snapshot still guards commits."""
from copy import deepcopy
from .cognition_contracts import shape, text, texts, refs
from .activity_engine import require


def observation_input(context):
    from .state_schema import facts_only
    context = facts_only(context)
    payload = deepcopy({"observation": context["observation"],
        "calculation_context": {"state_revision": context["state"]["revision"],
                                "role": "calculation_only_not_event_evidence"},
        "persona": {k: context["persona"][k] for k in ("id", "version", "boundary")},
        "config_source": context["config_source"]})
    fact = payload["observation"].get("fact", {})
    if context.get("movement_evidence"):
        payload["movement_evidence"] = deepcopy(context["movement_evidence"])
        payload["movement_place_names"] = deepcopy(context["movement_place_names"])
        payload["movement_node_contract"] = {
            "semantics": "Each named node is an actual checkpoint position, including stairs and floor nodes. Describe only segment_from -> segment_to; never expand it to an earlier floor or the entire staircase traversal.",
            "origin": {"id": context["movement_evidence"]["segment_from"], "name": context["movement_place_names"][context["movement_evidence"]["segment_from"]]},
            "destination": {"id": context["movement_evidence"]["segment_to"], "name": context["movement_place_names"][context["movement_evidence"]["segment_to"]]}}
        if context.get("movement_validation_feedback"):
            payload["movement_validation_feedback"] = deepcopy(context["movement_validation_feedback"])
    if context.get('control_event_evidence'):
        payload['control_event_evidence']=deepcopy(context['control_event_evidence'])
    if fact.get("kind") == "reading" and fact.get("operation") == "result":
        result = fact["actual_result"]
        payload["embedded_content"] = {
            "role": "book_content_not_actor_real_world_actions",
            "source_observation_id": payload["observation"]["id"],
            "text": result.pop("text", None), "note": result.pop("note", None)}
        payload["event_scope"] = {"actor": fact.get("actor"), "actual_action": "reading",
                                  "book": fact.get("target"),
                                  "embedded_actors_are_not_the_reader": True}
        payload['progress_unit_contract'] = {'unit': 'unicode_code_points', 'range': [result.get('start'), result.get('end')],
            'line_page_chapter_paragraph_mapping': None, 'rule': 'offsets are characters, never counts of paragraphs/lines/pages'}
    if fact.get("kind") == "work":
        payload["event_scope"] = {"actual_action": "test_document_work", "not_real_case": True,
            "material_events_are_not_actor_actions": True, "completion_means": "validated test artifact only, not delivery or legal outcome"}
    return payload


def control_event_evidence(p, db, observation):
    """Verify self-control fact against immutable command+receipt, not prose."""
    import json
    fact=observation.get('fact',{})
    operation=fact.get('operation')
    event_type=observation.get('type')
    if event_type=='care_completed':
        row=db.execute("SELECT receipt FROM life_receipts WHERE category='event_control' AND id=?",(observation['source_event'],)).fetchone()
        receipt=json.loads(row[0]) if row else {}
        require(fact==receipt.get('care_completed') and receipt.get('occurred_at')==observation.get('occurred_at'),
                'care observation must match committed completion')
        return {**fact,'source_event':observation['source_event'],'occurred_at':receipt['occurred_at'],'state_revision':receipt['revision']}
    if event_type=='meal_completed':
        row=db.execute("SELECT receipt FROM life_receipts WHERE category='event_control' AND id=?",(observation['source_event'],)).fetchone()
        receipt=json.loads(row[0]) if row else {}
        require(fact==receipt.get('meal_completed') and receipt.get('occurred_at')==observation.get('occurred_at'),
                'meal observation must match committed completion')
        return {**fact,'source_event':observation['source_event'],'occurred_at':receipt['occurred_at'],
                'state_revision':receipt['revision']}
    deterministic_p3={'sleep_start','sleep_progress','wake','sleep_schedule_correction','runtime_gap'}
    if operation not in {'start','interrupt','resume','fail'} and event_type not in deterministic_p3:
        return None
    row=db.execute('SELECT request,receipt FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category=\'event_control\') WHERE id=?',(observation['source_event'],)).fetchone()
    require(row is not None,'observation lacks committed source')
    request,receipt=map(json.loads,row)
    if request.get('operation')=='p3' and event_type in deterministic_p3:
        source=request.get('observation',{})
        for key in ('type','fact','occurred_at','knowledge_basis'):
            require(observation.get(key)==source.get(key),'structured P3 observation/source mismatch')
        require(receipt.get('occurred_at')==observation.get('occurred_at'),
                'structured P3 observation/receipt time mismatch')
        return {'event_type':event_type,'fact':fact,'source_event':observation['source_event'],
                'occurred_at':receipt['occurred_at'],'state_revision':receipt['revision']}
    if operation not in {'start','interrupt','resume','fail'}:return None
    activity=p.store.read(db)['activities'].get(fact.get('activity_id'))
    require(activity is not None,'control observation activity missing')
    expected={'actor':p.config['persona']['id'],'operation':request['operation'],
        'activity_id':request['payload']['activity_id'],'kind':activity['kind'],'target':activity['target']}
    if request['operation']=='fail':expected['feedback']=request['payload']['reason']
    require(fact==expected and observation['occurred_at']==receipt['occurred_at'],
            'control observation source/time/fact mismatch')
    return {**expected,'source_event':observation['source_event'], 'occurred_at':receipt['occurred_at'],
            'state_revision':receipt['revision']}


def control_factual_output(payload, output=None):
    import json
    if output is None:
        output = {
            'importance': 3,
            'keywords': [],
            'summary': '',
            'evidence_ids': [payload['observation']['id']],
        }
    facts=payload['control_event_evidence']
    # The source receipt was already verified by control_event_evidence. The
    # model may draft wording, but cannot rename this immutable observation ID.
    output={**output,'evidence_ids':[payload['observation']['id']]}
    if facts.get('event_type'):
        return {**output,'summary':json.dumps({
            'source':'code_generated_verified_structured_life_event_not_dialogue',**facts},
            ensure_ascii=False,sort_keys=True),
            'keywords':['verified_structured_life_event',facts['event_type']]}
    return {**output,'summary':json.dumps({'source':'code_generated_verified_control_event_not_dialogue',**facts},
             ensure_ascii=False,sort_keys=True),'keywords':['verified_control_event',facts['kind'],facts['operation']]}


def reading_factual_output(payload, output):
    fact = payload['observation']['fact']
    evidence = fact['actual_result']
    # Raw result was validated/settled by the reading executor; no new progress.
    record = {'source':'code_generated_verified_reading_event_not_dialogue',
        'activity_id':fact['activity_id'], 'book':fact['target'], 'unit':'unicode_code_points',
        'range':[evidence['start'],evidence['end']], 'new_characters':evidence['end']-evidence['start'],
        'validated_content_note':payload['embedded_content']['note']}
    return {**output, 'summary':__import__('json').dumps(record,ensure_ascii=False,sort_keys=True),
            'keywords':['verified_reading_event',fact['target'],'unicode_code_points']}


def validate_optional_reading_prose(output):
    """Local unit check for optional wording; semantic support remains model-reviewed."""
    import re
    prose=output.get('summary','')
    require(not re.search(r'(?:第)?(?:\d+|[一二三四五六七八九十百两]+)\s*(?:行|页|章|段)|(?:line|page|chapter|paragraph)\s*\d+',prose,re.I),
            'optional reading prose uses unsupported line/page/chapter/paragraph unit')


def validate_update(output, payload):
    fields = {"importance", "keywords", "summary", "evidence_ids"}
    if payload.get("movement_evidence"): fields.add("movement_facts")
    shape(output, fields)
    if payload.get("movement_evidence"):
        from .movement_evidence import validate_facts
        validate_facts(output["movement_facts"], payload["movement_evidence"])
    require(type(output["importance"]) is int and 1 <= output["importance"] <= 10, "invalid importance")
    texts(output["keywords"]); text(output["summary"])
    refs(output["evidence_ids"], {payload["observation"]["id"]})
