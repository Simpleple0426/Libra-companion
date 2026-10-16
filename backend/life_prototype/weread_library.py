"""Cache online chapter maps for owned books; do not fetch prose or user progress."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from threading import Lock,Thread
from . import weread
from .clock import utc
from .config import canonical,digest
from .activity_engine import require
from .outing_content import norm,titles


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS life_weread_library(
        owned_id TEXT PRIMARY KEY, status TEXT NOT NULL, attempts INTEGER NOT NULL,
        retry_at TEXT, body TEXT NOT NULL)''')


def structure(book,contents):
    require(str(contents.get('bookId'))==book['weread_id'],'chapter book identity mismatch')
    rows=contents.get('chapters');require(isinstance(rows,list) and 0<len(rows)<=20000,'empty or oversized chapter map')
    offset=0;chunks=[];seen=set()
    for row in rows:
        uid=str(row.get('chapterUid',''));title=str(row.get('title') or '').strip()
        require(uid and uid!='None' and uid not in seen and title,'invalid or duplicated chapter')
        seen.add(uid)
        reported=row.get('wordCount')
        count=reported if type(reported) is int and 0<reported<=10_000_000 else 4000
        chunks.append({'id':'weread:'+uid,'chapter_uid':uid,'section':title[:500],
                       'start':offset,'end':offset+count,'char_count':count,
                       'level':row.get('level'),'chapter_index':row.get('chapterIdx'),
                       'reported_word_count':reported,
                       'length_basis':'reported_word_count' if count==reported else 'estimated_4000_per_chapter'})
        offset+=count
    version=digest(chunks)[:16];library_id='book:weread:'+book['weread_id'];key=library_id+':structure:'+version
    return key,{'title':book['title'],'author':book.get('author',''),'isbn':book.get('isbn'),
                'weread_id':book['weread_id'],'version':version,'object':'library-object:'+key,
                'source':'local_library','structure_source':'weread_agent_gateway',
                'source_reference':book.get('url') or 'weread_book:'+book['weread_id'],
                'library_id':library_id,'reading_mode':'structure_simulation','available':True,
                'total_chars':offset,'structure':chunks,
                'progress_semantics':'simulated_structure_units; word counts where provided, otherwise estimated; no prose read',
                'contains_estimated_lengths':any(c['length_basis'].startswith('estimated') for c in chunks)}


def match(owned,candidates,*,choose_edition=False):
    if owned.get('weread_id'):
        return next((x for x in candidates if x['weread_id']==owned['weread_id']),None)
    isbn=norm(owned.get('isbn'))
    exact=[x for x in candidates if isbn and norm(x.get('isbn'))==isbn]
    if len(exact)==1:return exact[0]
    authors=owned.get('authors') or [owned.get('author','')]
    from .quote_sources import author_name
    authors=[author_name(a) for a in authors if a]
    same=[x for x in candidates if titles(x)&titles(owned) and authors and
          any(a==author_name(x.get('author','')) for a in authors)]
    # A preference list specifies a work, not a purchased edition. Choose the
    # first verified edition in search order, then persist its ID permanently.
    return same[0] if same and (len(same)==1 or choose_edition) else None


def bootstrap(cog):
    root=getattr(cog,'resource_root',None)
    catalog=[]
    if root:
        try:
            catalog=json.loads((Path(root)/'libra/reading_knowledge/catalog.json').read_text(encoding='utf-8-sig')).get('books',[])
        except (OSError,ValueError):pass
    with cog.store.connect() as db:
        initialize(db)
        rows=[]
        for book in catalog:
            if not book.get('book_id') or not book.get('title'):continue
            book={**book,'aliases':book.get('alternate_titles',[])}
            rows.append(('catalog:'+book['book_id'],book,'reading_catalog'))
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='life_owned_books'").fetchone():
            rows.extend((ident,json.loads(raw),'bookstore_purchase') for ident,raw in db.execute('SELECT id,body FROM life_owned_books').fetchall())
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='life_manual_books'").fetchone():
            rows.extend(('manual:'+ident,json.loads(raw),'user_added_book') for ident,raw in
                        db.execute('SELECT id,body FROM life_manual_books').fetchall())
        for ident,book,source in rows:
            db.execute("INSERT OR IGNORE INTO life_weread_library VALUES(?,'pending',0,NULL,?)",
                       (ident,canonical({'owned':book,'source':source})))


def process_one(cog):
    bootstrap(cog)
    if not weread.status()['configured']:return False
    now=cog.clock.now()
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT owned_id,attempts,body FROM life_weread_library WHERE status IN ('pending','retry','fetching') AND (retry_at IS NULL OR retry_at<=?) ORDER BY rowid LIMIT 1",(now.isoformat(),)).fetchone()
        if not row:return False
        ident,attempt,raw=row;body=json.loads(raw);attempt+=1
        db.execute("UPDATE life_weread_library SET status='fetching',attempts=?,retry_at=? WHERE owned_id=?",
                   (attempt,(now+timedelta(minutes=10)).isoformat(),ident))
    try:
        owned=body['owned']
        if owned.get('weread_id'):book=weread.info(owned['weread_id'])
        else:
            results=weread.search(owned['title'],5)
            details=[weread.info(candidate['weread_id']) for candidate in results[:5]]
            book=match(owned,details,choose_edition=body.get('source')=='reading_catalog')
            require(book is not None,'no unique verified WeRead edition')
        contents=weread.chapters(book['weread_id']);key,resource=structure(book,contents)
        body.pop('error_type',None);body.pop('error_code',None)
        body.update(book=book,resource_id=key,resource=resource,fetched_at=cog.clock.now().isoformat())
        with cog.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE life_weread_library SET status='ready',retry_at=NULL,body=? WHERE owned_id=?",(canonical(body),ident))
            row=db.execute('SELECT body FROM life_owned_books WHERE id=?',(ident,)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='life_owned_books'").fetchone() else None
            if row:
                purchase=json.loads(row[0]);purchase.update(weread_id=book['weread_id'],structure_status='ready',reading_resource_id=key)
                db.execute('UPDATE life_owned_books SET body=? WHERE id=?',(canonical(purchase),ident))
        return True
    except Exception as exc:
        body['error_type']=type(exc).__name__
        body['error_code']=str(exc) if isinstance(exc,weread.WeReadUnavailable) else 'weread_matching_or_structure_unavailable'
        with cog.store.connect() as db:
            db.execute("UPDATE life_weread_library SET status='retry',retry_at=?,body=? WHERE owned_id=?",
                       ((cog.clock.now()+timedelta(minutes=min(1440,5*2**min(attempt,8)))).isoformat(),canonical(body),ident))
        return True


def resources(db,fresh):
    initialize(db)
    for ident,raw in db.execute("SELECT owned_id,body FROM life_weread_library WHERE status='ready'").fetchall():
        row=json.loads(raw);key=row['resource_id'];book=deepcopy(row['resource'])
        # Preserve local imports as the preferred copy of an already available work.
        existing=next((k for k,b in fresh['books'].items() if titles(b)&titles(book)),None)
        if not existing:
            fresh['books'][key]=book
            fresh['objects'][book['object']]={'name':book['title'],'parent':'home.f2.study',
                'status':'confirmed','source':'cached_weread_chapter_map'}


def mark_available(db,config):
    initialize(db)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='life_owned_books'").fetchone():return
    for ident,raw in db.execute("SELECT owned_id,body FROM life_weread_library WHERE status='ready'").fetchall():
        row=json.loads(raw);book=row['resource']
        chosen=next((key for key,b in config['books'].items() if b.get('available',True) and titles(b)&titles(book)),None)
        if not chosen:continue
        owned=db.execute('SELECT body FROM life_owned_books WHERE id=?',(ident,)).fetchone()
        if owned:
            purchase=json.loads(owned[0]);purchase.update(reading_available=True,reading_resource_id=chosen,structure_status='ready')
            db.execute('UPDATE life_owned_books SET body=? WHERE id=?',(canonical(purchase),ident))


def view(cog):
    with cog.store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='life_weread_library'").fetchone():return {**weread.status(),'books':[]}
        return {**weread.status(),'books':[{'owned_id':r[0],'status':r[1],'attempts':r[2],
                'title':json.loads(r[3])['owned'].get('title'),'source':json.loads(r[3]).get('source','bookstore_purchase'),
                'error_code':json.loads(r[3]).get('error_code')} for r in db.execute('SELECT owned_id,status,attempts,body FROM life_weread_library')]}


_lock=Lock();_workers={}


def tick(cog):
    if not getattr(cog,'resource_root',None):return
    bootstrap(cog)
    if not weread.status()['configured']:return
    key=str(cog.store.path.resolve())
    with _lock:
        if key in _workers and _workers[key].is_alive():return
        with cog.store.connect() as db:
            due=db.execute("SELECT 1 FROM life_weread_library WHERE status IN ('pending','retry','fetching') AND (retry_at IS NULL OR retry_at<=?) LIMIT 1",(cog.clock.now().isoformat(),)).fetchone()
        if not due:return
        worker=Thread(target=process_one,args=(cog,),daemon=True,name='life-weread-library')
        _workers[key]=worker;worker.start()
