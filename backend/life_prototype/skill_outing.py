"""Place-category outings; content work is queued separately from life ticks."""
from datetime import timedelta
from application.content_tools import execute
from .skill_personal_care import enabled
from .clock import utc
from .config import canonical
from .activity_engine import require

CATEGORIES = {'groceries':'shopping','shopping':'shopping','markets':'shopping',
              'bookstores':'bookstore','walks':'walk','parks':'walk',
              'museums':'exhibition','galleries':'exhibition','exhibitions':'exhibition',
              'amusement_parks':'play','theatre':'play','cinemas':'play','bars':'play',
              'coffee_and_drinks':'outing','relaxation':'outing','errands':'errand'}
LABELS = {'shopping':('购物','购物'), 'bookstore':('逛书店','书店闲逛'),
          'walk':('散步','散步'), 'exhibition':('参观','参观'), 'play':('游玩','游玩'),
          'errand':('办理事务','这次办事'), 'outing':('外出活动','这次外出活动')}


def routine(item):
    if not item or str(item.get('place','')).startswith('home') or item.get('kind')=='commute': return False
    if item.get('state_type') in {'commuting','working','eating','exercising','sleeping'}: return False
    if (item.get('constraints') or {}).get('required_routine'): return False
    if item.get('intent'): return item['intent'] in {'外出活动','外出办事','购物','散步','逛书店','参观','游玩','娱乐','晚间活动'}
    return item.get('activity') in {'outing','short_purchase','short_leisure'}


def category(config,item):
    venue=config['places'].get(item['place'],{})
    if venue.get('outing_category') in LABELS: return venue['outing_category']
    name=venue.get('name','')
    for words,kind in [(('书店','书城','旧书市集'),'bookstore'),(('公园','步道'),'walk'),
                       (('美术馆','博物馆','展览馆'),'exhibition'),(('商场','超市','便利店','市集'),'shopping'),
                       (('游乐园',),'play')]:
        if any(word in name for word in words): return kind
    return 'errand' if item.get('intent')=='外出办事' else 'outing'


def event_text(kind,ending=False):
    return '左然'+('结束了'+LABELS[kind][1] if ending else '开始'+LABELS[kind][0])


def requirement(cog,state,item,result,at):
    plan=state.get('outing_sessions',{}).get('outing:'+item['id'])
    if not plan:return {**result,'mode':'needs_detail','reason':'call_outing_prepare'}
    if plan.get('closed_at'):return {**result,'mode':'hold','reason':'outing_ended'}
    return {**result,'mode':'action','kind':'outing','targets':[plan['id']],'reason':'execute_outing_skill'}


def prepare(cog):
    return execute('outing.prepare',lambda:_prepare(cog),source='life.outing')


def _prepare(cog):
    item=(cog.agenda.view() or {}).get('current_item');require(enabled(cog) and routine(item),'no current outing slot')
    now=cog.clock.now();ident='outing:'+item['id']
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        require(state['place']==item['place'] and state['sleep']['status']=='awake','arrive awake before outing')
        plans=state.setdefault('outing_sessions',{})
        if ident in plans:return {'outing':plans[ident]}
        require(not state.get('active') and utc(item['end_at'])>now,'outing slot unavailable')
        plan={'id':ident,'parent_id':item['id'],'place':item['place'],
              'place_name':cog.p.config['places'][item['place']]['name'],
              'category':category(cog.p.config,item),'end_at':item['end_at']}
        plans[ident]=plan;state['revision']+=1
        db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
    return {'outing':plan}


def begin(config,state,activity,at):
    plan=state.get('outing_sessions',{}).get(activity['target'])
    require(plan and not plan.get('opened_at') and at<utc(plan['end_at']),'outing already started or unavailable')
    require(state['place']==plan['place'] and state['sleep']['status']=='awake','outing place/awake mismatch')
    visit=state.get('outing_visit')
    if not visit or visit['place']!=plan['place']:
        visit={'id':'visit:'+activity['id'],'place':plan['place'],'started_at':at.isoformat()}
        state['outing_visit']=visit
    plan.update(opened_at=at.isoformat(),visit_id=visit['id'])
    activity.update(outing_mode='events_and_drafts',outing_category=plan['category'],visit_id=visit['id'],
                    description='左然正在'+LABELS[plan['category']][0])


def close(state,activity,at):
    if not activity.get('outing_mode'):return
    plan=state['outing_sessions'][activity['target']]
    if plan.get('closed_at'):return
    plan['closed_at']=at.isoformat()
    activity.update(status='completed',completed_at=at.isoformat(),next_due_at=None,
                    description=event_text(plan['category'],True))


def heartbeat(cog):
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db);activity=state['activities'].get(state.get('active'))
        if not activity or not activity.get('outing_mode'):return False
        now=cog.clock.now()
        if now>=utc(state['outing_sessions'][activity['target']]['end_at']):
            cog.p._commit_locked(db,'outing-end:'+activity['id'],{'expected_revision':state['revision'],
                'operation':'interrupt','payload':{'activity_id':activity['id'],'reason':'外出时段结束'}},None)
        else:
            activity['next_due_at']=(now+timedelta(seconds=cog.p.config['checkpoint_seconds'])).isoformat()
            state.update(revision=state['revision']+1,as_of=now.isoformat())
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        thought_activity=dict(activity)
    # Walk already has a walk thought; bookstore has its purchase/introduction
    # draft.  The remaining entertainment outings use the shared draft worker.
    if thought_activity.get('outing_category') not in {'walk','bookstore','errand'}:
        from .leisure_thoughts import enqueue as enqueue_thought
        subject=LABELS.get(thought_activity.get('outing_category'),LABELS['outing'])[0]
        enqueue_thought(cog,thought_activity,skill='outing',subject=subject)
    return True
