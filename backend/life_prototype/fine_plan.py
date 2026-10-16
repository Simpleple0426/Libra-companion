"""Persisted near-term activity blocks; proposals never count as experience."""
from datetime import timedelta
import json
from .clock import utc
from .config import canonical, digest
from .activity_engine import require
from .home_world import path
from .world_extensions import edge_seconds
from copy import deepcopy

INSTRUCTION = '''为给出的一个粗日程时段生成具体活动块。粗计划给出时间、状态大类、地点和宽泛意图，具体做什么由你结合状态、记忆和未完成事项决定。返回 {"blocks":[{"kind":"reading|watching|work","target":候选资源ID,"duration_seconds":整数}],"reason":简短依据}。
coarse_item.intent 是宽泛的优先方向，不是具体任务或资源绑定；优先遵循，资源、时间或当前需要不适合时可选择其他合法活动，并在 reason 中说明调整原因。意图为空时自主选择。constraints 中的必要日常安排和用户预约仍须遵守。
free 时可在候选资源中选择阅读、观影或工作；working 只选工作。不要把粗计划当作已经选定某本书或某项工作。
只选 resources 中存在的 ID，kind 必须匹配，只安排1至3块，不必填满时段，留出通行和转场时间。
延续已有进度与中断事项，也可选择尚未开始的书或工作。根据人物、记忆和用户约定自主选具体资源，不随机编造。
每块至少一个checkpoint_seconds，合计不超过available_seconds。未知电影片长只安排一段观看，不能承诺整部看完。
reading_mode=structure_simulation 使用本地书籍结构和模拟阅读进度，不加载正文、不生成理解或笔记；遵循 reading_skill。
work材料为模拟日常工作，不是用户的真实案件。只生成未来意图，不写笔记、剧情、工作成果或用户行为。
资源的 user_recommendation 是用户在聊天中提到的作品及消息依据：request 为明确希望你读/看，优先选择尚未完成的推荐；mention 为普通提及，可结合兴趣与已有进度选择。已完成作品不因仍在清单就反复重看。推荐不是已读/已看事实，不绕过当前粗计划意图、资源和时间限制。
无法合法安排时返回空blocks并解释原因。'''


def initialize(store):
    with store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS life_fine_agendas(id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL, body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS life_fine_execution(activity_id TEXT PRIMARY KEY, block_id TEXT NOT NULL, parent_id TEXT NOT NULL, end_at TEXT NOT NULL)')


def _same_slot(left, right):
    from .coarse_plan_updates import signature
    if any(left.get(k) != right.get(k) for k in ('activity', 'place', 'reference_id')):
        return False
    source = signature(left)
    if any(x is not None for x in source):
        return source == signature(right)
    # Older/imported plans have no legacy identity: only exact windows are safe.
    return all(left.get(k) == right.get(k) for k in ('title', 'start_at', 'end_at'))


def _retime(body, index, start, limit, checkpoint, *, first_seconds=None, preserve_due_start=False):
    """Move intentions only. Never extend beyond the enclosing coarse slot."""
    cursor = start
    for offset, block in enumerate(body['blocks'][index:]):
        due_start = utc(block['start_at'])
        block.setdefault('original_start_at', block['start_at'])
        block.setdefault('original_end_at', block['end_at'])
        seconds = first_seconds if offset == 0 and first_seconds is not None else block['duration_seconds']
        seconds = min(seconds, max(0, (limit-cursor).total_seconds()))
        minimum = 1 if block['kind'] == 'moving' else checkpoint
        if seconds < minimum:
            block['schedule_status'] = 'deferred'
            block['start_at'] = block['end_at'] = limit.isoformat()
            continue
        block.pop('schedule_status', None)
        block['start_at'] = cursor.isoformat()
        cursor += timedelta(seconds=seconds)
        block['end_at'] = cursor.isoformat()
        if offset == 0 and preserve_due_start and due_start <= start:
            # Reconciliation must not move a due action ahead of the caller's
            # captured time. Actual execution still retimes at commit/bind.
            block['start_at'] = due_start.isoformat()


def reconcile(cog):
    """Inherit uniquely corresponding slots, and retain delayed resource choices.

    Runs only on the scheduler writer. Views never mutate plans or actual facts.
    """
    if not getattr(cog, 'resource_root', None): return False
    initialize(cog.store)
    now = cog.clock.now()
    changed = False
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        from .coarse_plan import schedule_day
        agenda = cog.agenda._read(db, schedule_day(now))
        if not agenda: return False
        state = cog.store.read(db)
        rows = db.execute("SELECT id,parent_id,body FROM life_fine_agendas WHERE status='ready' ORDER BY rowid DESC").fetchall()
        bindings = {b: a for a,b in db.execute('SELECT activity_id,block_id FROM life_fine_execution')}
        occupied = {p for _,p,_ in rows if any(i['id'] == p for i in agenda['items'])}
        seen = set()
        for ident, parent_id, raw in rows:
            if parent_id in seen: continue
            seen.add(parent_id)
            body = json.loads(raw)
            if str(schedule_day(utc(body['created_at']))) != agenda['date']: continue
            original = deepcopy(body)
            parent = next((i for i in agenda['items'] if i['id'] == parent_id), None)
            if parent is None:
                old_parent = body.get('parent')
                if not old_parent:
                    old = db.execute('SELECT body FROM life_daily_agendas WHERE day=? AND revision=?',
                                     (agenda['date'], body['agenda_revision'])).fetchone()
                    if old:
                        from .coarse_plan_schema import unpack
                        old_parent = next((i for i in unpack(json.loads(old[0]))['items'] if i['id'] == parent_id), None)
                if not old_parent: continue
                candidates = [i for i in agenda['items'] if i['id'] not in occupied and
                              utc(i['end_at']) > now and _same_slot(old_parent, i)]
                # Splitting a slot is ambiguous: do not carry an activity across a reservation.
                if len(candidates) != 1: continue
                parent = candidates[0]
                occupied.add(parent['id'])
                body.setdefault('adjustments', []).append({'at':now.isoformat(), 'from_parent':parent_id,
                    'to_parent':parent['id'], 'reason':'coarse_slot_inherited'})
                body.update(parent_id=parent['id'], agenda_revision=agenda['revision'], parent_title=parent['title'])
                delta = utc(parent['start_at'])-utc(old_parent['start_at'])
                for block in body['blocks']:
                    activity = state['activities'].get(bindings.get(block['id']))
                    if not activity:
                        block['start_at'] = (utc(block['start_at'])+delta).isoformat()
                        block['end_at'] = (utc(block['end_at'])+delta).isoformat()
                    # An ongoing segment retains its real start and cannot consume a later reservation.
                    block['end_at'] = min(utc(block['end_at']), utc(parent['end_at'])).isoformat()
                db.execute('UPDATE life_fine_execution SET parent_id=? WHERE parent_id=?', (parent['id'], parent_id))
            body['parent'] = deepcopy(parent)
            for index, block in enumerate(body['blocks']):
                activity = state['activities'].get(bindings.get(block['id']))
                if not activity or activity['status'] != 'interrupted': continue
                block.setdefault('execution_started_at',activity.get('resumed_at',activity['started_at']))
                began = block.get('execution_started_at',block['start_at'])
                used = block.get('budget_used_seconds',0) + max(0,
                    (utc(activity['interrupted_at'])-utc(began)).total_seconds())
                remaining = block['duration_seconds']-used
                if remaining >= cog.p.config['checkpoint_seconds'] and utc(parent['end_at']) > now:
                    _retime(body,index,max(now,utc(parent['start_at'])),utc(parent['end_at']),
                            cog.p.config['checkpoint_seconds'],first_seconds=remaining, preserve_due_start=True)
                break
            # Do not redraw a book/movie simply because deciding or walking took longer.
            first = next((n for n,b in enumerate(body['blocks']) if b['kind'] != 'moving' and
                          b['id'] not in bindings and b.get('schedule_status') != 'deferred'), None)
            if first is not None:
                block = body['blocks'][first]
                earlier_running = any(state['activities'].get(bindings.get(b['id']), {}).get('status') in {'running','interrupted'}
                                      for b in body['blocks'][:first])
                if not earlier_running and utc(block['start_at']) < now < utc(parent['end_at']):
                    _retime(body, first, max(now,utc(parent['start_at'])), utc(parent['end_at']), cog.p.config['checkpoint_seconds'], preserve_due_start=True)
            for block in body['blocks']:
                db.execute('UPDATE life_fine_execution SET end_at=? WHERE block_id=?', (block['end_at'],block['id']))
            if body != original:
                db.execute('UPDATE life_fine_agendas SET parent_id=?,body=? WHERE id=?', (body['parent_id'],canonical(body),ident))
                changed = True
    return changed


def _progress(kind, key, state, config):
    if kind == 'reading': return state.get('reading',{}).get(key+':'+config['books'][key]['version'],0)
    if kind == 'watching': return state.get('viewing',{}).get(key,0)
    # Fine-plan progress is durable only for books and movies. Work and other
    # ordinary activities are prepared afresh for the current day's slot.
    return 0


def resources(cog, parent, state):
    from .coarse_plan_schema import detail_kinds
    p = cog.p
    result = []
    from .media_recommendations import annotations
    recommendations = annotations(cog)
    for kind in sorted(detail_kinds(parent)):
        entries = {} if kind=='work' and p.config.get('work_skill') else p.config.get({'reading':'books','watching':'movies','work':'work_items'}[kind],{})
        for key,entry in entries.items():
            if not entry.get('available',True): continue
            progress = _progress(kind,key,state,p.config)
            from .skill_reading import length, simulated
            if kind == 'reading' and p.config.get('mode') == 'local_single_user' and not simulated(entry): continue
            total = length(entry) if kind=='reading' else len(entry.get('stages', [])) or 2 if kind=='work' else entry.get('duration_seconds')
            rewatch = kind == 'watching' and entry.get('viewing_mode') == 'active_time_simulation' and total and progress >= total
            if total and progress>=total and not rewatch: continue
            if rewatch: progress = 0
            place = p.config['objects'][entry['object']]['parent'] if kind=='reading' else entry['place']
            if place != parent['place']: continue
            result.append({'id':key,'kind':kind,'title':entry['title'],'place':place,
                           'progress':progress,'total':total,'reading_mode':entry.get('reading_mode'),
                           'source':entry['source'], **({'rewatch': bool(rewatch), 'catalog_status': entry.get('catalog_status'),
                           'completed_viewings': state.get('viewing_progress', {}).get(key, {}).get('completed_viewings', 0),
                           'genres': entry.get('genres', []), 'summary': entry.get('summary', '')[:300],
                           'edition': entry.get('edition')} if kind == 'watching' else {})})
    for resource in result:
        if resource['id'] in recommendations and not resource.get('rewatch'):
            resource['user_recommendation'] = recommendations[resource['id']]
    preferred=(parent.get('constraints') or {}).get('preferred_resource_id') or parent.get('preferred_resource_id')
    ordered = sorted(result,key=lambda r:(r['id']!=preferred,
                     r.get('user_recommendation',{}).get('priority')!='request',
                     -bool(r['progress']),not bool(r.get('user_recommendation')),r.get('source') == 'douban_discovery',r['id']))
    per_kind = 60 if len({r['kind'] for r in result}) == 1 else 20
    selected, counts = [], {}
    for resource in ordered:
        kind = resource['kind']
        if counts.get(kind, 0) >= per_kind: continue
        selected.append(resource)
        counts[kind] = counts.get(kind, 0) + 1
    return selected[:60]


def prepare(cog):
    """One bounded semantic call per coarse slot; durable retry after interruption."""
    if not getattr(cog,'resource_root',None): return False
    initialize(cog.store)
    reconcile(cog)
    now = cog.clock.now()
    agenda = cog.agenda.view()
    if not agenda: return False
    parent = agenda.get('current_item')
    from .coarse_plan_schema import detail_kinds
    if not parent or not detail_kinds(parent): return False
    from .skill_work import enabled as work_enabled, routine as work_routine
    if work_enabled(cog) and work_routine(parent):return False
    state = cog.p.snapshot()
    if state['place'] != parent['place']: return False
    from .coarse_plan_execution import enter_current
    enter_current(cog)
    state = cog.p.snapshot()
    choices = resources(cog,parent,state)
    resource_hash = digest(choices)
    with cog.store.connect() as db:
        old = db.execute('SELECT status,attempts,body FROM life_fine_agendas WHERE parent_id=? ORDER BY rowid DESC LIMIT 1',(parent['id'],)).fetchone()
        generation = db.execute('SELECT COUNT(*) FROM life_fine_agendas WHERE parent_id=?',(parent['id'],)).fetchone()[0]+1
    if old:
        previous=json.loads(old[2])
        if state['active']:
            with cog.store.connect() as db:
                binding = db.execute('SELECT block_id FROM life_fine_execution WHERE activity_id=?', (state['active'],)).fetchone()
            if binding and any(b['id']==binding[0] for b in previous['blocks']): return False
        expired=bool(previous['blocks']) and all(utc(b['end_at'])<=now for b in previous['blocks'])
        content_blocks=[b for b in previous['blocks'] if b['kind']!='moving']
        completed=bool(content_blocks) and all(any(a['kind']==b['kind'] and a['target']==b['target'] and
            a['status']=='completed' and a.get('progress',0)>b['baseline'] and utc(a['started_at'])>=utc(previous['created_at'])
            for a in state['activities'].values()) for b in content_blocks)
        exhausted_resources=previous.get('resource_hash')!=resource_hash
        if old[0]=='ready':
            available_keys = {(r['kind'], r['id']) for r in choices}
            unavailable = any((b['kind'], b['target']) not in available_keys for b in content_blocks)
            if not expired and not completed and not unavailable: return False
            old=None
        elif old[0] in {'unavailable','needs_review'} or old[1]>=3:
            if not exhausted_resources: return False
            old=None
    ident = json.loads(old[2])['id'] if old else 'fine:'+parent['id']+':g'+str(generation)
    if old and utc(json.loads(old[2]).get('retry_at',now.isoformat()))>now: return False
    body = {'id':ident,'parent_id':parent['id'],'agenda_revision':agenda['revision'],
            'created_at':now.isoformat(),'parent_title':parent['title'],'parent':deepcopy(parent),'blocks':[], 'reason':'','resource_hash':resource_hash}
    attempt = old[1]+1 if old else 1
    with cog.store.connect() as db:
        db.execute('INSERT OR REPLACE INTO life_fine_agendas VALUES(?,?,?,?,?)',(ident,parent['id'],'generating',attempt,canonical(body)))
    try:
        require(bool(choices),'当前时段没有可用资源；原有粗日程保留')
        start = max(now,utc(parent['start_at']))
        route = [] if cog.p.config.get('mode') == 'local_single_user' else path(cog.p.config,state['place'],parent['place'])
        travel = sum(edge_seconds(cog.p.config,a,b) for a,b in zip(route,route[1:]))
        available = int((utc(parent['end_at'])-start).total_seconds())-travel
        require(available>=cog.p.config['checkpoint_seconds'],'当前时段剩余时间不足一个执行检查点')
        reading_titles = ' '.join(r['title'] for r in choices if r['kind'] == 'reading')
        movie_titles = ' '.join(r['title'] for r in choices if r['kind'] == 'watching')
        memories = cog.memory.retrieve((parent.get('intent') or parent['title']) + ' ' + reading_titles + ' ' + movie_titles,ident+':retrieve:'+str(attempt))
        from .skill_reading import instruction as reading_instruction
        from .skill_movie import instruction as movie_instruction
        proposal = cog.calls.ask(ident+':'+str(attempt),'fine_agenda',{
            'coarse_item':parent,'now':now.isoformat(),'available_seconds':available,
            'checkpoint_seconds':cog.p.config['checkpoint_seconds'],'resources':choices,
            'persona':cog.persona,
            'current_state': {'place': state['place'],
                              'coarse_state': state.get('coarse_state'),
                              'unfinished_activities': [a for a in state['activities'].values() if a['status'] in {'running','interrupted'}]},
            'local_now':now.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).isoformat(),
            'memories':memories,'user_constraints':agenda.get('user_constraints',{}),
            'reading_skill': reading_instruction() if reading_titles else None,
            'movie_skill': movie_instruction() if movie_titles else None,
            'prior_error':json.loads(old[2]).get('reason') if old else None})
        require(set(proposal)=={'blocks','reason'} and isinstance(proposal['reason'],str),'invalid fine proposal')
        require(isinstance(proposal['blocks'],list) and len(proposal['blocks'])<=3,'invalid fine blocks')
        current = cog.p.snapshot()
        require(current['revision']==state['revision'],'实际状态已变化，稍后重新细化')
        require(cog.agenda.read()['revision']==agenda['revision'],'粗日程已修改，稍后重新细化')
        cursor = max(cog.clock.now(),utc(parent['start_at']))
        if travel:
            body['blocks'].append({'id':ident+':travel','kind':'moving','target':parent['place'],
                'title':'前往'+parent['place_name'],'place':parent['place'],'place_name':parent['place_name'],
                'start_at':cursor.isoformat(),'end_at':(cursor+timedelta(seconds=travel)).isoformat(),
                'duration_seconds':travel,'baseline':0})
            cursor += timedelta(seconds=travel)
        for index, block in enumerate(proposal['blocks']):
            require(set(block)=={'kind','target','duration_seconds'},'unexpected fine fields')
            resource = next((x for x in choices if x['id']==block['target'] and x['kind']==block['kind']),None)
            require(resource is not None,'unknown fine resource')
            seconds = block['duration_seconds']
            require(type(seconds)is int and cog.p.config['checkpoint_seconds']<=seconds<=14400,'invalid fine duration')
            finish = cursor+timedelta(seconds=seconds)
            # Account for model latency, not a stale pre-call clock.
            finish = min(finish,utc(parent['end_at']))
            require((finish-cursor).total_seconds()>=cog.p.config['checkpoint_seconds'],'细化期间时段已结束或不足检查点')
            require(not any(x['target']==block['target'] and x['kind']==block['kind'] for x in body['blocks']), 'duplicate resource block')
            title = {'reading':'阅读','watching':'观看','work':'处理'}[block['kind']]+' · '+resource['title']
            body['blocks'].append({**block,'id':ident+':'+str(index),'title':title,
                'place':resource['place'],'place_name':cog.p.config['places'][resource['place']]['name'],
                'start_at':cursor.isoformat(),'end_at':finish.isoformat(),
                'duration_seconds':int((finish-cursor).total_seconds()),'baseline':resource['progress'],
                'reading_mode':resource['reading_mode'],'source':resource['source']})
            if block['kind'] == 'watching':
                body['blocks'][-1]['rewatch'] = resource.get('rewatch', False)
            if block['kind'] == 'reading':
                from .skill_reading import simulated, plan as reading_plan
                book = cog.p.config['books'][block['target']]
                if simulated(book):
                    body['blocks'][-1]['reading_plan'] = reading_plan(book, resource['progress'],
                        int((finish-cursor).total_seconds()), cog.p.config)
            if block['kind'] == 'watching' and cog.p.config['movies'][block['target']].get('viewing_mode') == 'active_time_simulation':
                from .skill_movie import plan as movie_plan
                body['blocks'][-1]['viewing_plan'] = movie_plan(cog.p.config['movies'][block['target']],
                    resource['progress'], int((finish-cursor).total_seconds()))
            cursor = finish
        if not proposal['blocks']: body['blocks']=[]
        body['reason']=proposal['reason']
        status = 'ready' if body['blocks'] else 'unavailable'
    except Exception as error:
        detail=str(error)[:400]
        body.update(blocks=[],reason=detail if detail and '\u4e00'<=detail[0]<='\u9fff' else '具体安排暂时无法生成，稍后重试。',
                    error=detail,retry_at=(cog.clock.now()+timedelta(seconds=60)).isoformat())
        status = 'unavailable' if not choices else 'needs_review' if attempt>=3 else 'retry'
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if status=='ready' and (cog.store.read(db)['revision']!=state['revision'] or cog.agenda._read(db,agenda['date'])['revision']!=agenda['revision']):
            status='retry'; body.update(blocks=[],reason='提交前输入已变化')
        db.execute('UPDATE life_fine_agendas SET status=?,body=? WHERE id=?',(status,canonical(body),ident))
    return True


def view(cog, state=None, *, at=None):
    state = state or cog.p.snapshot()
    agenda = cog.agenda.read()
    if not agenda: return None
    with cog.store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='life_fine_agendas'").fetchone(): return None
        rows = db.execute('SELECT parent_id,status,body FROM life_fine_agendas ORDER BY rowid').fetchall()
        bindings = dict(db.execute('SELECT activity_id,block_id FROM life_fine_execution').fetchall())
    ids = {x['id'] for x in agenda['items']}
    parents = {x['id']:x for x in agenda['items']}
    now = utc(at) if at is not None else cog.clock.now()
    plans=[]; current=None
    for parent,status,raw in rows:
        body=json.loads(raw)
        from .skill_work import enabled as work_enabled, routine as work_routine
        if work_enabled(cog) and work_routine(parents.get(parent)):continue
        from .coarse_plan import schedule_day
        if str(schedule_day(utc(body['created_at'])))!=agenda['date']: continue
        adjusted=parent not in ids
        body['status']='superseded' if adjusted else status
        for block in body['blocks']:
            actual=[a for a in state['activities'].values() if a['kind']==block['kind'] and a['target']==block['target'] and
                    (bindings.get(a['id'])==block['id'] or utc(a['started_at'])>=utc(body['created_at']) or
                     (a['status'] in {'running','interrupted'} and a.get('progress',0)>=block['baseline']))]
            block['actual_activity_ids']=[a['id'] for a in actual]
            active=next((a for a in actual if a['status']=='running'),None)
            progress=_progress(block['kind'],block['target'],state,cog.p.config) if block['kind']!='moving' else 0
            if block.get('rewatch') and not actual: progress = 0
            block['progress']=progress
            block['status']=('completed' if any(a['status']=='completed' for a in actual) else
                             'deferred' if block.get('schedule_status')=='deferred' else
                             'in_progress' if active else 'paused' if any(a['status']=='interrupted' for a in actual) else
                             'elapsed_unverified' if now>=utc(block['end_at']) else 'planned')
            if adjusted and block['status'] not in {'completed','elapsed_unverified'}: block['status']='cancelled'
            if not adjusted and utc(parents[parent]['start_at'])<=now<utc(parents[parent]['end_at']) and \
                    block['status'] not in {'completed','deferred'} and utc(block['start_at'])<=now<utc(block['end_at']): current=block
        plans.append(body)
    return {'plans':plans,'current_item':current,'semantics':'future_intentions_and_separately_verified_progress','progress_owner':'zuoran_only'}


def current(cog, state=None):
    return (view(cog,state) or {}).get('current_item')


def enforce_action(cog, state, action, at):
    if action.get('kind')=='work' and action.get('target') in state.get('work_steps',{}):return
    if not getattr(cog,'resource_root',None) or action['kind'] not in {'reading','watching','work'}: return
    block=(view(cog,state,at=at) or {}).get('current_item')
    require(block and utc(block['end_at'])>utc(at) and (block['kind'],block['target'])==(action['kind'],action['target']),
            'reading/viewing/work needs a current saved fine block; preserve progress and replan')


def validate_commit(cog, db, context, state, action, at):
    """Validate the saved choice again, allowing decision latency inside its parent."""
    if action.get('kind')=='work' and action.get('target') in state.get('work_steps',{}):return
    fine = (context.get('fine_agenda') or {}).get('current_item')
    if not fine or action['kind'] not in {'reading','watching','work'}: return
    agenda = cog.agenda._read(db, context['daily_agenda']['date'])
    require(agenda['revision']==context['daily_agenda']['revision'], 'coarse agenda changed during decision; replan')
    plan = next(p for p in context['fine_agenda']['plans'] if any(b['id']==fine['id'] for b in p['blocks']))
    parent = next((p for p in agenda['items'] if p['id']==plan['parent_id']),None)
    required_seconds=cog.p.config['checkpoint_seconds']
    if action['operation']=='continue':
        running=state['activities'].get(action['activity_id'])
        if running and running.get('next_due_at'):
            required_seconds=max(0,(utc(running['next_due_at'])-at).total_seconds())
    require(parent and utc(parent['start_at'])<=at and
            at<utc(parent['end_at']) and (utc(parent['end_at'])-at).total_seconds()>=required_seconds,
            'fine parent has insufficient time for a checkpoint; preserve choice for later')
    require((action['kind'],action['target'])==(fine['kind'],fine['target']), 'fine choice changed during decision')
    row = db.execute('SELECT body FROM life_fine_agendas WHERE id=? AND status=?',(plan['id'],'ready')).fetchone()
    require(row is not None,'saved fine plan is unavailable')
    body=json.loads(row[0])
    index=next(n for n,b in enumerate(body['blocks']) if b['id']==fine['id'])
    block=body['blocks'][index]
    used=block.get('budget_used_seconds',0)
    previous=state['activities'].get(action.get('activity_id'))
    if previous and previous['status']=='interrupted':
        linked=db.execute('SELECT block_id FROM life_fine_execution WHERE activity_id=?',(previous['id'],)).fetchone()
        if linked and linked[0]==block['id']:
            used += max(0,(utc(previous['interrupted_at'])-utc(block.get('execution_started_at',block['start_at']))).total_seconds())
    if action['operation']!='continue':
        remaining=max(0,block['duration_seconds']-used)
        require(remaining>=cog.p.config['checkpoint_seconds'],'fine budget consumed; replan remaining work')
        block['budget_used_seconds']=used
        block['execution_started_at']=at.isoformat()
        context['_fine_commit_retime']=True
        _retime(body,index,at,utc(parent['end_at']),cog.p.config['checkpoint_seconds'],first_seconds=remaining)
        db.execute('UPDATE life_fine_agendas SET body=? WHERE id=?',(canonical(body),plan['id']))
    # The commit validator already checked this exact persisted choice. The caller
    # validates all other executor constraints against a trial state as usual.
    context['fine_agenda']['current_item']=deepcopy(block)



def boundary(cog):
    data=view(cog)
    now=cog.clock.now()
    points=[utc(b[k]) for p in (data or {}).get('plans',[]) for b in p['blocks'] for k in ('start_at','end_at') if utc(b[k])>now]
    return min(points,default=None)


def bind(db, context, state):
    """Link a committed action to its time budget without changing P1 evidence."""
    block=(context.get('fine_agenda') or {}).get('current_item')
    a=state['activities'].get(state['active'])
    if block and a and (a['kind'], a['target']) == (block['kind'], block['target']):
        owner = next(p for p in context['fine_agenda']['plans'] if any(b['id'] == block['id'] for b in p['blocks']))
        db.execute('UPDATE events SET fine_plan_id=? WHERE activity_id=? AND coarse_plan_id=? AND fine_plan_id IS NULL',
                   (block['id'], a['id'], owner['parent_id']))
    if block and a and block['kind'] in {'reading','watching','work'} and (a['kind'],a['target'])==(block['kind'],block['target']):
        plan=next(p for p in context['fine_agenda']['plans'] if any(b['id']==block['id'] for b in p['blocks']))
        parent=plan['parent_id']
        if context.get('_fine_commit_retime'):
            body=json.loads(db.execute('SELECT body FROM life_fine_agendas WHERE id=?',(plan['id'],)).fetchone()[0])
            index=next(n for n,b in enumerate(body['blocks']) if b['id']==block['id'])
            saved=body['blocks'][index]
            began=utc(a.get('resumed_at',a['started_at']))
            owner=next(p for p in context['daily_agenda']['items'] if p['id']==parent)
            checkpoint=(utc(a['next_due_at'])-began).total_seconds()
            saved['execution_started_at']=began.isoformat()
            _retime(body,index,began,utc(owner['end_at']),checkpoint,
                    first_seconds=saved['duration_seconds']-saved.get('budget_used_seconds',0))
            require(saved.get('schedule_status')!='deferred' and utc(a['next_due_at'])<=utc(saved['end_at']),
                    'actual start leaves no checkpoint before the coarse boundary')
            db.execute('UPDATE life_fine_agendas SET body=? WHERE id=?',(canonical(body),plan['id']))
            block=saved
        db.execute('INSERT OR REPLACE INTO life_fine_execution VALUES(?,?,?,?)',(a['id'],block['id'],parent,block['end_at']))
        if a.get('viewing_mode') == 'active_time_simulation':
            from .skill_movie import plan as movie_plan
            a['viewing_deadline'] = block['end_at']
            a['viewing_plan'] = movie_plan({'duration_seconds': a['movie_duration_seconds'], 'edition': a.get('movie_edition')},
                a['progress'], max(0, (utc(block['end_at'])-utc(a.get('resumed_at', a['started_at']))).total_seconds()))
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        if a.get('reading_mode') == 'structure_simulation':
            from .skill_reading import plan as reading_plan
            a['reading_deadline'] = block['end_at']
            a['reading_plan'] = reading_plan(
                {'reading_mode': 'structure_simulation', 'total_chars': block['reading_plan']['structure'][-1]['end'],
                 'structure': block['reading_plan']['structure']}, a['progress'],
                max(0, (utc(block['end_at'])-utc(a.get('resumed_at', a['started_at']))).total_seconds()),
                {'reading_simulation': {'characters_per_minute': a['rate']}})
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))


def continuing_budget(cog, db, state):
    """An approved fine block owns repeated checkpoints, not new content choices."""
    if not getattr(cog,'resource_root',None) or not state['active']: return False
    row=db.execute('SELECT parent_id,end_at FROM life_fine_execution WHERE activity_id=?',(state['active'],)).fetchone()
    if not row: return False
    from .coarse_plan import schedule_day
    agenda=cog.agenda._read(db,schedule_day(cog.clock.now()))
    parent=next((i for i in (agenda or {}).get('items',[]) if i['id']==row[0]),None)
    a=state['activities'][state['active']]
    return bool(parent and utc(parent['start_at'])<=cog.clock.now()<utc(row[1]) and
                a.get('next_due_at') and utc(a['next_due_at'])<=utc(row[1]))


def pause_expired(cog):
    """End an expired fine block; only books and movies remain resumable."""
    if not getattr(cog,'resource_root',None): return False
    initialize(cog.store)
    reconcile(cog)
    state=cog.p.snapshot()
    if not state['active']: return False
    with cog.store.connect() as db:
        row=db.execute('SELECT block_id,parent_id,end_at FROM life_fine_execution WHERE activity_id=?',(state['active'],)).fetchone()
    if not row: return False
    agenda=cog.agenda.read()
    parent=next((b for b in (agenda or {}).get('items',[]) if b['id']==row[1]),None)
    valid=parent is not None and utc(parent['start_at'])<=cog.clock.now()
    if valid and cog.clock.now()<utc(row[2]): return False
    # Settle an earned checkpoint first, but never infer progress across offline
    # gaps or past the allocated budget. P4 will pause on the following cycle.
    a=state['activities'][state['active']]
    if a.get('reading_mode') != 'structure_simulation' and a.get('viewing_mode') != 'active_time_simulation' and valid and a.get('next_due_at') and utc(a['next_due_at'])<=utc(row[2]) and \
            cog.clock.now()>=utc(a['next_due_at']) and (cog.clock.now()-utc(a['last_progress_at'])).total_seconds() <= cog.p.config['max_gap_seconds']:
        return False
    resumable = a.get('kind') in {'reading', 'watching'}
    operation = 'interrupt' if resumable else 'fail'
    reason = ('具体安排已到结束时间或被调整；保留阅读或观影进度' if resumable else
              '具体安排已到结束时间或被调整；本时段活动结束，不跨时段保存进度')
    cog.p.command('fine-budget:'+row[0]+':'+str(state['revision']),state['revision'],operation,
                  activity_id=state['active'],reason=reason)
    return True
