"""Shared persistence worker used explicitly by individual leisure skills."""
from datetime import timedelta
import json
from threading import Lock, Thread
from .clock import utc
from .config import canonical, digest
from .outing_content import initialize as initialize_drafts

INSTRUCTION = '''你是左然。根据固定人设、当前真实娱乐活动和已提供的真实记忆，写一条30到120字的私人想法。
可以自然想到她、想与你分享、讨论或以后一起体验，但不假定她在场，不编造她的偏好、共同经历、现场景色、作品情节或已经说出口的话。
你是在给恋人留下自己的想法，提到她时用“你”称呼她，也可以使用输入中明确提供的称呼。绝不称她为“用户”，正文不得出现“用户”“与用户”“和用户”等系统视角称呼。
这是尚未发送的私人想法，不要在正文解释“只是自己的念头”“尚未发送”或保存、展示、系统等内部机制。不发消息、不要求她回复。返回 {"body":"正文"}。
表达以作品、原句或当下观察引发的具体理解和个人感受为主。与恋人有关可以自然体现在观点和感受中，不要求每篇直接称“你”、联系关系或末尾邀请；没有自然关联时停留在内容本身即可。不要固定写成“分析内容—想到你—邀请讨论”，也不要用讨论题、陪伴承诺或未来共同计划完成收尾。“若你愿意”“以后有机会”“以后或许可以一起”只在确有具体意图且合乎上下文时使用，不作为默认套话。同居关系中表达可以自然直接，不必反复客气试探。愿望与已发生事实仍须区分，但正文无需解释“只是自己的念头”或未发送等内部状态。
'''
_lock=Lock();_workers={}

def enqueue(cog,activity,*,skill,subject):
    if not getattr(cog,'resource_root',None):return
    if not activity or activity.get('status')!='running':return
    clock=getattr(cog,'clock',None) or cog.p.clock
    if (clock.now()-utc(activity['started_at'])).total_seconds()<300:return
    ident='leisure-thought:'+activity['id']
    with cog.store.connect() as db:
        initialize_drafts(db)
        db.execute('''CREATE TABLE IF NOT EXISTS life_leisure_thought_jobs(
            id TEXT PRIMARY KEY,status TEXT NOT NULL,attempts INTEGER NOT NULL,retry_at TEXT,body TEXT NOT NULL)''')
        if db.execute('SELECT 1 FROM life_dynamic_drafts WHERE visit_id=? AND kind=?',(activity['id'],'leisure_thought')).fetchone():return
        body={'activity_id':activity['id'],'skill':skill,'subject':subject,'place':activity['place'],'started_at':activity['started_at']}
        db.execute("INSERT OR IGNORE INTO life_leisure_thought_jobs VALUES(?,'pending',0,NULL,?)",(ident,canonical(body)))
    _start(cog,ident)

def _start(cog,ident):
    key=str(cog.store.path.resolve())
    with _lock:
        if key in _workers and _workers[key].is_alive():return
        worker=Thread(target=_process,args=(cog,ident),name='life-leisure-thought',daemon=True)
        _workers[key]=worker;worker.start()

def _process(cog,ident):
    try:
        clock=getattr(cog,'clock',None) or cog.p.clock
        with cog.store.connect() as db:
            row=db.execute("SELECT attempts,body FROM life_leisure_thought_jobs WHERE id=? AND status IN ('pending','retry') AND (retry_at IS NULL OR retry_at<=?)",(ident,clock.now().isoformat())).fetchone()
            if not row:return
            attempts,raw=row;body=json.loads(raw);attempts+=1
            db.execute("UPDATE life_leisure_thought_jobs SET status='writing',attempts=? WHERE id=?",(attempts,ident))
        memories=cog.memory.retrieve(body['subject']+' 用户 与用户的交流 共同回忆',ident+':memory')
        result=cog.calls.ask(ident+':'+str(attempts),'leisure_thought',{'persona':cog.persona,'skill':body['skill'],'activity':body['subject'],'place_id':body['place'],'started_at':body['started_at'],'memories':memories})
        text=result.get('body')
        if not isinstance(text,str) or not 0<len(text.strip())<=600:raise ValueError('invalid leisure thought')
        if '用户' in text:raise ValueError('system address leaked into leisure thought')
        at=clock.now().isoformat();draft_id='leisure-draft:'+digest(ident)[:24]
        draft={'body':text.strip(),'kind':'leisure_thought','activity_id':body['activity_id'],'skill':body['skill'],'subject':body['subject'],'occurred_at':body['started_at'],'created_at':at,'status':'pending_display','audience':'user','published_at':None}
        with cog.store.connect() as db:
            initialize_drafts(db)
            db.execute('INSERT OR IGNORE INTO life_dynamic_drafts VALUES(?,?,?,?,?,?)',(draft_id,body['activity_id'],'leisure_thought','pending_display',at,canonical(draft)))
            db.execute("UPDATE life_leisure_thought_jobs SET status='done',retry_at=NULL WHERE id=?",(ident,))
    except Exception:
        with cog.store.connect() as db:
            row=db.execute('SELECT attempts FROM life_leisure_thought_jobs WHERE id=?',(ident,)).fetchone()
            if row:
                clock=getattr(cog,'clock',None) or cog.p.clock
                db.execute('UPDATE life_leisure_thought_jobs SET status=?,retry_at=? WHERE id=?',('failed' if row[0]>=3 else 'retry',(clock.now()+timedelta(minutes=10)).isoformat(),ident))
