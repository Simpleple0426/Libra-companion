"""Add catalogued dining venues to the executable simulation, without teleporting."""
from copy import deepcopy
import json
from pathlib import Path
from .config import canonical, digest, validate


def configured(config, rules):
    from .firm_catalog import configured as firm_configured
    result=firm_configured(config)
    source='docs/character/左然城市地点清单.md; user-authorized dining locations via libra/world/schedule_rules.json'
    names=list(dict.fromkeys(rules['locations'].get('restaurants',[])+rules['locations'].get('breakfast_shops',[])))
    from .skill_outing import CATEGORIES
    if not names and not any(rules['locations'].get(kind) for kind in ('courts','procuratorates','police','work_visits','gym','swimming','shooting',*CATEGORIES)):return result
    result['places'].setdefault('city.dining_access',{'name':'城市餐饮通行区域','parent':None,'status':'confirmed',
        'source':source+'; simulation connector, not a real named venue'})
    edges=result['household_world']['edges']
    existing={frozenset(pair) for pair in edges}
    def edge(a,b,seconds):
        if frozenset((a,b)) not in existing:
            edges.append([a,b]);existing.add(frozenset((a,b)))
        result.setdefault('edge_seconds',{}).setdefault('|'.join(sorted((a,b))),seconds)
    for origin,seconds in (('home',600),('firm',300)):
        if origin in result['places']:edge(origin,'city.dining_access',seconds)
    from .home_world import path
    for indoor, entrance in (('home.f1','home'),('firm.office','firm')):
        if indoor in result['places'] and entrance in result['places']:
            try: path(result,indoor,entrance)
            except ValueError: edge(indoor,entrance,result['checkpoint_seconds'])
    for name in names:
        prior=next((key for key,value in result['places'].items() if value['name']==name),None)
        ident=prior or 'city.dining.'+digest(name)[:12]
        result['places'].setdefault(ident,{'name':name,'parent':None,'status':'confirmed','source':source})
        edge('city.dining_access',ident,180)
    result['dining_catalog']={'source':source,'names':names,
        'travel_semantics':'simulation estimate: home access 600s, firm access 300s, venue access 180s; not map distances or measured travel'}
    for kind in ('gym','swimming','shooting'):
        for name in rules['locations'].get(kind, []):
            prior=next((key for key,value in result['places'].items() if value['name']==name),None)
            ident=prior or 'city.'+kind+'.'+digest(name)[:12]
            result['places'].setdefault(ident,{'name':name,'parent':None,'status':'confirmed',
                'source':'docs/character/左然城市地点清单.md; schedule_rules.json '+kind+'; simulated travel via shared city access'})
            result['places'][ident]['exercise_mode']=kind
            edge('city.dining_access',ident,180)
    for group,category in CATEGORIES.items():
        for name in rules['locations'].get(group,[]):
            prior=next((key for key,value in result['places'].items() if value['name']==name),None)
            ident=prior or 'city.outing.'+digest(name)[:12]
            result['places'].setdefault(ident,{'name':name,'parent':None,'status':'confirmed',
                'source':'docs/character/左然城市地点清单.md; schedule_rules.json '+group+'; simulated travel'})
            result['places'][ident]['outing_category']='bookstore' if '旧书' in name else category
            edge('city.dining_access',ident,180)
    for group in ('courts','procuratorates','police','work_visits'):
        for name in rules['locations'].get(group,[]):
            prior=next((key for key,value in result['places'].items() if value['name']==name),None)
            ident=prior or 'city.work.'+digest(name)[:12]
            result['places'].setdefault(ident,{'name':name,'parent':None,'status':'confirmed','source':source})
            result['places'][ident]['work_category']=group
            edge('city.dining_access',ident,180)
    validate(result)
    return result


def install(cog):
    rules=json.loads((Path(cog.resource_root)/'libra/world/schedule_rules.json').read_text(encoding='utf8'))
    config=configured(cog.p.config,rules)
    if config==cog.p.config:return True
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM result_controls WHERE status='pending' LIMIT 1").fetchone():return False
        for value in (cog.p.config,config):
            db.execute("INSERT OR IGNORE INTO life_evidence(category,id,body) VALUES('resource_version',?,?)",(digest(value),canonical(value)))
        row=db.execute("SELECT body FROM life_state WHERE name='work_extension'").fetchone()
        record=json.loads(row[0]) if row else {}
        record.update(base_config_hash=digest(cog.store.config),config=config,
                      dining_installed_at=cog.clock.now().isoformat())
        db.execute("INSERT OR REPLACE INTO life_state(name,id,body) VALUES('work_extension',1,?)",(canonical(record),))
        state=cog.store.read(db);state['revision']+=1
        db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
    cog.p.config=config
    return True
