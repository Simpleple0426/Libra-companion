"""Read-only WeRead Agent Gateway adapter; credentials never enter tool arguments."""
import json
import os
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from application.content_tools import execute
from application.tool_execution import remaining_timeout

ENDPOINT='https://i.weread.qq.com/api/agent/gateway'
VERSION='1.0.4'


class WeReadUnavailable(RuntimeError):pass


def key_path():
    from infrastructure.paths import SECRETS_ROOT
    return SECRETS_ROOT/'weread-api-key.txt'


def api_key():
    value=os.getenv('WEREAD_API_KEY','').strip()
    if not value:
        try:value=key_path().read_text(encoding='utf-8-sig').strip()
        except FileNotFoundError:pass
    return value


def status():
    return {'configured':bool(api_key()),'read_only':True,'skill_version':VERSION,
            'capabilities':['search','info','chapters']}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise WeReadUnavailable('weread_redirect_refused')


def _request(api_name,**params):
    if api_name not in {'/store/search','/book/info','/book/chapterinfo'}:raise ValueError('unsupported weread operation')
    key=api_key()
    if not key:raise WeReadUnavailable('weread_key_missing')
    if not re.fullmatch(r'wrk-[A-Za-z0-9_.-]+',key):raise WeReadUnavailable('weread_key_invalid_format')
    request=Request(ENDPOINT,data=json.dumps({'api_name':api_name,'skill_version':VERSION,**params}).encode('utf8'),
                    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with build_opener(NoRedirect).open(request,timeout=remaining_timeout(25)) as response:
            raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise WeReadUnavailable('weread_response_too_large')
        data=json.loads(raw.decode('utf8'))
    except HTTPError as exc:
        raise WeReadUnavailable('weread_http_'+str(exc.code)) from None
    except (OSError,URLError,ValueError) as exc:
        raise WeReadUnavailable('weread_transport_unavailable') from None
    if not isinstance(data,dict):raise WeReadUnavailable('weread_invalid_response')
    if data.get('upgrade_info'):raise WeReadUnavailable('weread_upgrade_required')
    if data.get('errcode',0) not in (0,'0',None):raise WeReadUnavailable('weread_api_error')
    # Official gateway returns core fields; accept a data envelope if present.
    result=data.get('data',data)
    if not isinstance(result,dict):raise WeReadUnavailable('weread_invalid_data')
    if result.get('upgrade_info'):raise WeReadUnavailable('weread_upgrade_required')
    return result


def book_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):raise ValueError('invalid weread book ID')
    return value


def card(row):
    ident=book_id(str(row.get('bookId','')));title=str(row.get('title') or '').strip()[:200]
    if not title:raise WeReadUnavailable('weread_book_title_missing')
    return {'weread_id':ident,'title':title,'author':str(row.get('author') or '')[:300],
            'authors':[str(row['author'])[:300]] if row.get('author') else [],
            'isbn':str(row.get('isbn') or '')[:32],'summary':str(row.get('intro') or '')[:4000],
            'word_count':row.get('wordCount'),'publisher':str(row.get('publisher') or '')[:200],
            'url':str(row.get('deepLink') or '')[:1000],'source':'weread_agent_gateway'}


def search(query,count=5):
    def run(query,count):
        response=_request('/store/search',keyword=query,scope=10,count=count,maxIdx=0)
        rows=[];seen=set()
        for group in response.get('results',[]):
            for entry in group.get('books',[]):
                row=entry.get('bookInfo') or {}
                if not row.get('bookId') or row.get('soldout') in (1,True):continue
                item=card(row)
                if item['weread_id'] not in seen:rows.append(item);seen.add(item['weread_id'])
                if len(rows)>=count:return rows
        return rows
    return execute('weread.search',run,source='life.weread',query=query,count=count)


def info(book_id):
    def run(book_id):
        value=card(_request('/book/info',bookId=book_id))
        if value['weread_id']!=book_id:raise WeReadUnavailable('weread_identity_mismatch')
        return value
    return execute('weread.info',run,source='life.weread',book_id=book_id)


def chapters(book_id):
    def run(book_id):
        value=_request('/book/chapterinfo',bookId=book_id)
        if str(value.get('bookId'))!=book_id or not isinstance(value.get('chapters'),list):
            raise WeReadUnavailable('weread_invalid_chapters')
        return {'bookId':book_id,'synckey':value.get('synckey'),'chapters':[
            {key:row.get(key) for key in ('chapterUid','chapterIdx','title','wordCount','level')}
            for row in value['chapters']]}
    return execute('weread.chapters',run,source='life.weread',book_id=book_id)
