"""Human-readable life facts, separate from internal transactional receipts."""
import json
from .config import canonical

SCHEMA = '''CREATE TABLE events (
    id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, description TEXT NOT NULL,
    kind TEXT NOT NULL, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT
)'''


def in_home(place):
    return bool(place and (place == 'home' or place.startswith('home.')))


def initialize(db):
    columns = {r[1] for r in db.execute('PRAGMA table_info(events)')}
    if 'description' in columns:
        return False
    if not columns:
        db.execute(SCHEMA)
        return False
    if columns != {'id', 'request', 'receipt'}:
        raise ValueError('unrecognized events schema')
    mapping = {0: 0}
    for index, ident, request, receipt in db.execute('SELECT rowid,id,request,receipt FROM events ORDER BY rowid').fetchall():
        old = db.execute("SELECT request,receipt FROM life_receipts WHERE category='event_control' AND id=?", (ident,)).fetchone()
        if old and tuple(old) != (request, receipt):
            raise ValueError('conflicting event control receipt')
        db.execute("INSERT OR IGNORE INTO life_receipts(category,id,request,receipt) VALUES('event_control',?,?,?)", (ident, request, receipt))
        mapping[index] = db.execute("SELECT rowid FROM life_receipts WHERE category='event_control' AND id=?", (ident,)).fetchone()[0]
    row = db.execute("SELECT body FROM life_state WHERE name='cognition' AND id=1").fetchone()
    if row:
        meta = json.loads(row[0])
        for key in ('cursor', 'enabled_after_event'):
            old_index = meta.get(key, 0)
            meta[key] = mapping[max(i for i in mapping if i <= old_index)]
        db.execute("UPDATE life_state SET body=? WHERE name='cognition' AND id=1", (canonical(meta),))
    # User requested a clean history. Do not replay old receipts into new events.
    db.execute('DROP TABLE events')
    db.execute(SCHEMA)
    return True


def append(db, event_id, request, receipt, state, config):
    """Record control + optional life fact atomically with the state change."""
    encoded, returned = canonical(request), canonical(receipt)
    old = db.execute("SELECT request,receipt FROM life_receipts WHERE category='event_control' AND id=?", (event_id,)).fetchone()
    if old:
        if tuple(old) != (encoded, returned):
            raise ValueError('event id reused with different content')
        return
    db.execute("INSERT INTO life_receipts(category,id,request,receipt) VALUES('event_control',?,?,?)", (event_id, encoded, returned))
    fact = describe(event_id, request, receipt, state, config)
    if fact is None:
        return
    activity_id, kind, description = fact
    coarse_id = fine_id = None
    if request.get('operation') == 'coarse_state':
        coarse_id = request['fact']['plan_id']
        if request['fact'].get('appointment_id'):
            duplicate = db.execute('''SELECT 1 FROM events e JOIN life_receipts r
                ON r.category='event_control' AND r.id=e.id WHERE e.kind='user_time_start'
                AND json_extract(r.request,'$.fact.appointment_id')=? LIMIT 1''',
                (request['fact']['appointment_id'],)).fetchone()
            if duplicate:
                return
        # Arrival can have just emitted exactly the same room description.
        last = db.execute('SELECT description,occurred_at FROM events ORDER BY rowid DESC LIMIT 1').fetchone()
        if last and last[0] == description:
            from .clock import utc
            if 0 <= (utc(receipt['occurred_at']) - utc(last[1])).total_seconds() <= 60:
                return
    if activity_id:
        previous = db.execute('SELECT coarse_plan_id,fine_plan_id FROM events WHERE activity_id=? ORDER BY rowid DESC LIMIT 1', (activity_id,)).fetchone()
        if previous and request.get('operation') not in {'start', 'resume'}:
            coarse_id, fine_id = previous
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='life_fine_execution'").fetchone():
            binding = db.execute('SELECT parent_id,block_id FROM life_fine_execution WHERE activity_id=?', (activity_id,)).fetchone()
            if binding and request.get('operation') not in {'start', 'resume'}:
                coarse_id, fine_id = binding
    if coarse_id is None and request.get('operation') in {'start', 'resume'}:
        from .clock import utc
        from .coarse_plan import schedule_day
        at = utc(receipt['occurred_at'])
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='life_daily_agendas'").fetchone():
            row = db.execute('SELECT body FROM life_daily_agendas WHERE day=? ORDER BY revision DESC LIMIT 1', (str(schedule_day(at)),)).fetchone()
            if row:
                from .coarse_plan_schema import unpack
                item = next((i for i in unpack(json.loads(row[0]))['items'] if utc(i['start_at']) <= at < utc(i['end_at'])), None)
                coarse_id = item['id'] if item else None
    # A worker restart can begin the same fine activity again with a new
    # activity id.  On the user timeline that is still one start within the
    # same coarse slot, so keep only the first identical start fact.
    if coarse_id is not None and kind.endswith('_start'):
        duplicate = db.execute(
            'SELECT 1 FROM events WHERE coarse_plan_id=? AND kind=? AND description=? LIMIT 1',
            (coarse_id, kind, description),
        ).fetchone()
        if duplicate:
            return
    work_activity=state.get('activities',{}).get(activity_id,{})
    if work_activity.get('work_mode'):
        step=state['work_steps'][work_activity['target']]
        coarse_id=state['work_sessions'][step['plan_id']]['parent_id'];fine_id=step['id']
    db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?)',
               (event_id, receipt['occurred_at'], description, kind, activity_id, coarse_id, fine_id))
    for ended in state.get('activities',{}).get(activity_id,{}).get('exercise_departures',[]) if request.get('operation')=='start' else []:
        activity=state['activities'][ended]
        from .skill_exercise import event_text
        description=event_text(activity['exercise_mode'],ending=True)
        departure_id=event_id+':exercise:'+ended
        append(db,departure_id,{'operation':'exercise_departure','activity_id':ended,'description':description},
               {**receipt,'event_id':departure_id},state,config)
    departure=state.get('activities',{}).get(activity_id,{}).get('work_departure') if request.get('operation')=='start' else None
    if departure:
        departure_id=event_id+':work-departure'
        from .activity_feed import _place_name
        append(db,departure_id,{'operation':'work_departure','activity_id':departure['activity_id'],
            'description':'左然结束工作，离开'+_place_name(config,departure['place'])},
            {**receipt,'event_id':departure_id},state,config)
    if kind == 'outing_start':
        from .outing_content import enqueue
        enqueue(db,state['activities'][activity_id],event_id,state,config,receipt['occurred_at'])
    if kind == 'watching_end' and state['activities'][activity_id]['status'] == 'completed':
        from .movie_reviews import enqueue
        enqueue(db, activity_id, event_id, state, config, receipt['occurred_at'])


def describe(event_id, request, receipt, state, config):
    if request.get('operation') == 'companionship':
        return None, 'companion_update', request['description']
    """Only committed self activity and sleep/wake facts; never host diagnostics."""
    from .activity_feed import _place_name, _target_name
    operation = request.get('operation')
    if operation=='work_departure':return request['activity_id'],'work_departure',request['description']
    if operation=='exercise_departure':
        return request['activity_id'],'exercise_completed',request['description']
    if operation=='household_timer':
        return None,request['kind'],request['description']
    if operation == 'coarse_state':
        if request['fact'].get('activity') == 'user_time':
            return None, 'user_time_start', '左然正在' + request['fact']['title']
        place_id = request['fact']['place']
        if not place_id.startswith('home.'):
            return None
        return None, 'at_place', '左然正在' + _place_name(config, place_id)
    payload = request.get('payload', {})
    ident = request.get('activity_id') if operation == 'result' else payload.get('activity_id')
    if operation == 'recover':
        ident = receipt.get('work_session_ended') or receipt.get('reading_session_ended') or receipt.get('viewing_session_ended') or receipt.get('meal_session_ended') or receipt.get('care_session_ended') or receipt.get('housework_session_ended') or receipt.get('exercise_session_ended') or receipt.get('television_session_ended') or receipt.get('rest_session_ended') or receipt.get('outing_session_ended')
    activity = state.get('activities', {}).get(ident, {})
    kind = activity.get('kind', payload.get('kind'))
    target = activity.get('target', payload.get('target'))
    title = _target_name(config, kind, target)
    if activity.get('work_mode'):
        from .skill_work import event
        fact=event(activity,operation)
        if not fact:return None
        event_kind,text=fact
        if event_kind=='work_arrival':text+=_place_name(config,activity['place'])
        return ident,event_kind,text
    if activity.get('outing_mode'):
        from .skill_outing import event_text
        if operation=='start': return ident,'outing_start',event_text(activity['outing_category'])
        if operation in {'interrupt','fail','recover'}: return ident,'outing_end',event_text(activity['outing_category'],True)
        return None
    if activity.get('rest_mode'):
        if operation=='start': return ident,'rest_start','左然开始休息'
        if operation in {'interrupt','fail','recover'}: return ident,'rest_end','左然结束了休息'
        return None
    if activity.get('television_mode'):
        if operation=='start': return ident,'television_on','左然打开了电视'
        if operation in {'interrupt','fail','recover'}: return ident,'television_off','左然关掉了电视'
        return None
    if activity.get('exercise_mode'):
        from .skill_exercise import event_text
        if operation=='start': return ident,'exercise_start',event_text(activity['exercise_mode'])
        if operation=='interrupt' and activity['status']=='completed': return ident,'exercise_completed',event_text(activity['exercise_mode'],ending=True)
        return None
    if activity.get('housework_mode'):
        if operation in {'start','resume'}:
            return ident,'housework_start' if operation=='start' else 'housework_resume','左然'+('开始' if operation=='start' else '继续')+activity['housework_title']
        if operation in {'interrupt','fail','recover'}:
            if activity['status']=='completed': return ident,'housework_completed','左然已完成：'+activity['housework_title']
            return ident,'housework_paused','左然暂停了'+activity['housework_title']+'，保留进度'
    if activity.get('care_mode'):
        from .skill_personal_care import description
        if operation in {'start','resume'}: return ident,'care_start',description(activity)
        if operation in {'interrupt','fail','recover'}:
            if activity['status']=='completed': return ident,'care_completed',description(activity)
            return ident,'care_paused','左然暂停了'+activity['care_title']+'，保留已完成步骤的进度'
    if activity.get('meal_mode'):
        from .skill_dining import description
        dishes = '、'.join(activity['dishes'])
        if operation in {'start','resume'}:
            return ident,'meal_start','左然'+description(activity)
        if operation in {'interrupt','fail','recover'}:
            if activity['status']=='completed':
                text = {'cook':'做好了','takeout':'收到了外卖：','packed':'热好了自带的','dine':'等到了餐食：','eating':'吃完了'}[activity['meal_phase']]
                return ident,'meal_completed','左然'+text+dishes
            return ident,'meal_paused','左然暂停了这次'+('用餐' if activity['meal_phase']=='eating' else '备餐或等餐')+'，保留'+dishes+'的进度'
    reading = config.get('books', {}).get(target, {})
    if activity.get('viewing_mode') == 'active_time_simulation':
        from .skill_movie import label as viewing_position
        location = viewing_position(activity)
        if operation in {'start', 'resume'}:
            return ident, 'watching_start', f'左然正在观看《{title}》，进度：{location}'
        if operation in {'interrupt', 'fail', 'recover'}:
            finished = '，本轮已看完' if activity['progress'] >= activity['movie_duration_seconds'] else ''
            return ident, 'watching_end', f'左然结束观看《{title}》，进度：{location}{finished}'
    if activity.get('reading_mode') == 'structure_simulation':
        from .skill_reading import label as reading_position
        location = reading_position(reading, activity['progress'])
        if operation in {'start', 'resume'}:
            return ident, 'reading_start', f'左然正在阅读《{title}》（{location}）'
        if operation in {'interrupt', 'fail', 'recover'}:
            return ident, 'reading_end', f'左然结束阅读《{title}》，进度：{location}'
    reading_label = '回顾作品资料' if reading.get('reading_mode') == 'knowledge_review' else '阅读'
    label = {'moving': '前往' + _place_name(config, target), 'reading': reading_label + '《' + title + '》',
             'watching': '观看《' + title + '》', 'work': '处理“' + title + '”',
             'cooking': '做饭', 'eating': '吃饭', 'showering': '洗澡', 'serving': '送餐'}.get(kind)
    if operation in {'start', 'resume', 'interrupt', 'fail'} and label:
        if operation == 'start':
            if kind == 'moving':
                origin = activity.get('route', [state.get('place')])[0]
                if in_home(origin) and in_home(target):
                    return None
                name = '家' if in_home(origin) else _place_name(config, origin)
                return ident, 'moving_start', '左然离开了' + name
            if kind == 'eating': return ident, 'eating_start', '左然正在用餐中'
            if kind == 'work': return ident, 'work_start', '左然正在工作中'
            if kind == 'showering':
                return ident, 'showering_start', '左然正在' + _place_name(config, state.get('place')) + '洗澡'
        verb = {'start': '开始', 'resume': '继续', 'interrupt': '暂停', 'fail': '未能继续'}[operation]
        return ident, kind + '_' + operation, '左然' + verb + label + '。'
    if operation == 'result' and label:
        evidence = request.get('evidence', {})
        complete = activity.get('status') == 'completed'
        if kind == 'moving':
            if in_home(evidence.get('to')) and evidence.get('from') and not in_home(evidence['from']):
                return ident, 'arrived', '左然回到了家'
            if not complete:
                return None
            place = evidence.get('to') or target
            name = _place_name(config, place)
            origin = activity.get('route', [evidence.get('from')])[0]
            if in_home(place):
                description = '左然正在' + name
            else:
                description = '左然到达了' + name
            return ident, 'arrived', description
        if kind == 'reading':
            amount = evidence.get('end', 0) - evidence.get('start', 0)
            detail = f'，本次处理了 {amount} 个字符' if amount > 0 else ''
            return ident, 'reading_completed' if complete else 'reading_progress', '左然' + ('完成' if complete else '继续') + label + detail + '。'
        if kind == 'work':
            stage = evidence.get('artifact', {}).get('stage')
            if stage is None:
                return None
            return ident, 'work_progress', f'左然完成了“{title}”的第 {stage} 个工作阶段。'
        if kind == 'watching':
            return ident, 'watching_completed' if complete else 'watching_progress', '左然' + ('看完了' if complete else '继续观看') + '《' + title + '》。'
        if complete:
            description = {'cooking': '左然做好了一餐。', 'eating': '左然吃完了一餐。',
                           'showering': '左然洗完澡。', 'serving': '左然将餐食送到了目的地。'}.get(kind)
            return (ident, kind + '_completed', description) if description else None
    if operation == 'p3':
        observation = request.get('observation', {})
        kind = observation.get('type')
        if kind == 'sleep_start':
            return None, 'sleep_started', '左然正在睡觉中'
        if kind == 'wake':
            reason = observation.get('fact', {}).get('reason')
            return None, 'woke', '左然收到消息后醒来' if reason == 'message' else '左然起床了'
    return None
