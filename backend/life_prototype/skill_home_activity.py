"""Refine one site-level home intention into an existing executable skill."""
from copy import deepcopy
from .clock import utc
from .config import canonical, digest


def routine(item):
    return bool(item and str(item.get('place','')).startswith('home') and
                item.get('intent') in {'起床及晨间准备','家中活动','晚间活动'} and
                not item.get('home_activity_choice'))


def enabled(cog):
    return cog.p.config.get('mode')=='local_single_user' and bool(getattr(cog,'resource_root',None))


def requirement(cog,state,item,result,at):
    return {**result,'mode':'needs_detail','reason':'call_home_prepare'}


def _choices(config,item):
    if item.get('intent')=='起床及晨间准备':
        place=config.get('daily_routines',{}).get('morning_wash',{}).get('place','home.f2.bathroom')
        if place not in config['places']: place='home.f2.bathroom'
        return [{'choice':'morning_care','intent':'洗漱','activity':'morning_wash','place':place}]
    choices=[]
    for key,book in config.get('books',{}).items():
        obj=config.get('objects',{}).get(book.get('object'),{})
        place=obj.get('parent')
        if place and place.startswith('home') and book.get('available',True):
            choices.append({'choice':'reading','intent':'阅读','activity':'reading','place':place,'resource_id':key})
    for key,movie in config.get('movies',{}).items():
        place=movie.get('place')
        if place and place.startswith('home') and movie.get('available',True):
            choices.append({'choice':'movie','intent':'看电影','activity':'watch_movie','place':place,'resource_id':key})
    living='home.f1.living' if 'home.f1.living' in config['places'] else item['place']
    choices.append({'choice':'housework','intent':'家务','activity':'housework','place':living})
    return choices


def prepare(cog):
    if not enabled(cog): raise ValueError('home activity skill disabled')
    now=cog.clock.now(); body=cog.agenda.read(now); state=cog.p.snapshot()
    item=next((x for x in (body or {}).get('items',[]) if utc(x['start_at'])<=now<utc(x['end_at'])),None)
    if not routine(item): raise ValueError('no current unrefined home activity')
    choices=_choices(cog.p.config,item)
    used={x.get('home_activity_choice') for x in body.get('items',[]) if x.get('home_activity_choice')}
    available=[x for x in choices if x['choice'] not in used] or choices
    choice=available[int(digest([item['id'],body['revision']])[:8],16)%len(available)]
    revised=deepcopy(body); target=next(x for x in revised['items'] if x['id']==item['id'])
    target.update(intent=choice['intent'],activity=choice['activity'],place=choice['place'],
                  place_name=cog.p.config['places'][choice['place']]['name'],
                  coarse_intent=item['intent'],home_activity_choice=choice['choice'])
    target.setdefault('constraints',{}).pop('home_activity',None)
    target.setdefault('constraints',{})['home_activity_choice']=choice['choice']
    if choice.get('resource_id'): target['constraints']['preferred_resource_id']=choice['resource_id']
    revision=body['revision']+1
    revised.update(revision=revision,change_reason='home_activity_refined',generated_at=now.isoformat(),
                   evidence_id=f"agenda:{body['date']}:r{revision}")
    for index,row in enumerate(revised['items']): row['id']=f"agenda:{body['date']}:r{revision}:{index}"
    from .coarse_plan_schema import pack
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=cog.agenda._read(db,body['date'])
        if current!=body or cog.store.read(db)['revision']!=state['revision']:
            from .store import Conflict
            raise Conflict('agenda or life state changed during home refinement')
        db.execute('INSERT INTO life_daily_agendas VALUES(?,?,?)',(body['date'],revision,canonical(pack(revised))))
    return {'status':'ready','choice':choice,'agenda_revision':revision,
            'skill':'home_activity','delegates_to':choice['choice']}
