"""Small, read-only quote candidates from an exact three-host allowlist."""
import json
import os
import re
import unicodedata
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

from bs4 import BeautifulSoup
from application.content_tools import execute
from application.tool_execution import remaining_timeout

HOSTS = {'book.douban.com', 'zh.wikiquote.org', 'en.wikiquote.org'}


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def author_name(text):
    text = re.sub(r'[（(\[].*?[）)\]]', '', text)
    return normalize(re.split(r'著|；|;', text)[0])


def allowed(url):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname in HOSTS and
            not parsed.username and not parsed.password and parsed.port in (None, 443))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward cookies to login/challenge hosts or follow arbitrary links.
        raise ValueError('quote source redirect refused')


def fetch(url):
    return execute('quotes.fetch', _fetch, source='life.quotes', url=url)


def _fetch(url):
    if not allowed(url): raise ValueError('quote source not allowed')
    headers = {'User-Agent': 'LibraLocalNotebook/1.0 (personal reading quotations)',
               'Accept': 'application/json,text/html'}
    if urlsplit(url).hostname == 'book.douban.com':
        from infrastructure.paths import SECRETS_ROOT
        path = SECRETS_ROOT/'douban-cookie.txt'
        cookie = os.getenv('DOUBAN_COOKIE') or (path.read_text(encoding='utf8').strip() if path.is_file() else '')
        if cookie: headers['Cookie'] = cookie
    with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=remaining_timeout(12)) as response:
        raw = response.read(800_001)
        if len(raw) > 800_000: raise ValueError('quote page too large')
        return raw.decode('utf8')


def candidate(text, url, language, location='', **metadata):
    text = ' '.join(text.split()).strip()
    # Never truncate a long passage and present the fragment as a complete quote.
    if not 4 <= len(text) <= 180 or len(text.split()) > 35: return None
    return {'text': text, 'url': url, 'language': language, 'location': location[:160],
            'position_verified': False, **metadata}


def douban_quotes(html, url, edition):
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    # Only the book's original-excerpt body, never .comment or review prose.
    for item in soup.select('li.blockquote-item, .blockquote-list > ul > li'):
        node = item.select_one('.blockquote-content, figure')
        if not node: continue
        node = BeautifulSoup(str(node), 'html.parser')
        for extra in node.select('.blockquote-source, .report, .rec, .comment, script, style, a'):
            extra.decompose()
        location = item.select_one('.blockquote-source, figcaption')
        row = candidate(node.get_text(' ', strip=True), url, 'zh',
                        location.get_text(' ', strip=True) if location else '',
                        edition=edition, attribution='community_transcription_needs_review')
        if row: out.append(row)
    return out[:12]


def wiki_quotes(html, url, language, title):
    soup = BeautifulSoup(html, 'html.parser')
    root = soup.select_one('.mw-parser-output') or soup
    for unwanted in root.select('.toc, .navbox, .thumb, .metadata, .noprint, script, style'):
        unwanted.decompose()
    out, section, blocked = [], '', False
    excluded = ('external links','references','see also','about ', 'quotes about',
                'unsourced','misattributed','disputed','外部連結','外部链接','参考','參考','关于','關於','无来源','無來源','误传','誤傳','歌词','歌詞','lyrics','soundtrack','cast','演員','演员')
    for node in root.find_all(['h2','h3','li']):
        if node.name in {'h2','h3'}:
            section = node.get_text(' ', strip=True).replace('[edit]', '').replace('[编辑]', '').strip()
            if node.name == 'h2': blocked = any(s in section.casefold() for s in excluded)
            continue
        if blocked or any(s in section.casefold() for s in excluded): continue
        if node.find_parent('li') or node.find_parent(['table','nav']): continue
        copied = BeautifulSoup(str(node), 'html.parser')
        for extra in copied.select('ul, ol, sup, .reference'): extra.decompose()
        row = candidate(copied.get_text(' ', strip=True), url, language, section,
                        source_title=title, attribution='wikiquote_work_page')
        if row: out.append(row)
    return out[:12]


class Sources:
    def __init__(self, getter=None):
        self.get = fetch if getter is None else lambda url:execute('quotes.fetch',getter,source='life.quotes',url=url)

    def wiki(self, work, language):
        return execute('quotes.wiki',self._wiki,source='life.quotes',work=work,language=language)

    @staticmethod
    def _validate_work(work):
        if work.get('kind') not in {'reading','watching'} or not isinstance(work.get('title'),str) or not 0<len(work['title'].strip())<=200:
            raise ValueError('invalid quote work')
        for key in ('author','original_title','isbn','douban_book_id'):
            if work.get(key) is not None and (not isinstance(work[key],str) or len(work[key])>300):
                raise ValueError('invalid quote work metadata')

    def _wiki(self, work, language):
        self._validate_work(work)
        title = work.get('original_title') if language == 'en' else work['title']
        if not title: return []
        host = language+'.wikiquote.org'
        query = {'action':'query','list':'search','srsearch':title,'srnamespace':0,
                 'srlimit':4,'format':'json','formatversion':2}
        hits = json.loads(self.get('https://'+host+'/w/api.php?'+urlencode(query))).get('query',{}).get('search',[])
        for hit in hits[:4]:
            name = hit['title']
            base = re.sub(r'\s*[（(].*?[）)]\s*$', '', name)
            if normalize(base) != normalize(title): continue
            params = {'action':'parse','page':name,'redirects':1,'prop':'text','format':'json','formatversion':2}
            parsed = json.loads(self.get('https://'+host+'/w/api.php?'+urlencode(params))).get('parse', {})
            html = parsed.get('text', '')
            if not isinstance(html, str): continue
            plain = BeautifulSoup(html, 'html.parser').get_text(' ', strip=True)
            # Resolve same-title books/remakes using the page introduction.
            intro = plain[:1800]
            if work['kind'] == 'watching':
                if not work.get('year') or str(work['year']) not in intro: continue
                if not re.search(r'film|movie|电影|電影', intro, re.I): continue
            else:
                author = work.get('author', '')
                if not author or author_name(author) not in normalize(intro): continue
            actual = parsed.get('title', name)
            url = 'https://'+host+'/wiki/'+quote(actual.replace(' ', '_'), safe='')
            rows = wiki_quotes(html, url, language, actual)
            if rows: return rows
        return []

    def book(self, work):
        return execute('quotes.book',self._book,source='life.quotes',work=work)

    def _book(self, work):
        self._validate_work(work)
        from .douban import Douban, subject_id
        author = work.get('author', '')
        if not author: return []
        if work.get('douban_book_id'):
            ident = subject_id(work['douban_book_id'])
            base = 'https://book.douban.com/subject/'+ident+'/'
            soup = BeautifulSoup(self.get(base), 'html.parser')
            title = soup.select_one('h1')
            info = soup.select_one('#info')
            if not title or not info or normalize(title.get_text()) != normalize(work['title']): return []
            info = info.get_text(' ', strip=True)
            if author_name(author) not in normalize(info): return []
            isbn = re.search(r'ISBN:\s*(\d+)', info)
            isbn = isbn[1] if isbn else None
            if work.get('isbn') and isbn != work['isbn']: return []
            return douban_quotes(self.get(base+'blockquotes'),base+'blockquotes',
                {'isbn':isbn,'source_info':info[:500], 'matches_local_edition':bool(work.get('isbn') and isbn==work['isbn'])})
        query = work.get('isbn') or work['title']+' '+author
        hits = Douban.book_call('search', query=query, count=3)
        for hit in hits[:2]:
            ident = subject_id(str(hit['id']))
            detail = Douban.book_call('detail', douban_id=ident)
            if normalize(detail.get('title','')) != normalize(work['title']): continue
            if author_name(author) not in normalize(' '.join(detail.get('authors', []))): continue
            if work.get('isbn') and detail.get('isbn') != work['isbn']: continue
            edition = {k:detail.get(k) for k in ('isbn','publisher','translators','publishDate')}
            edition['matches_local_edition'] = bool(work.get('isbn') and detail.get('isbn') == work['isbn'])
            url = 'https://book.douban.com/subject/'+ident+'/blockquotes'
            rows = douban_quotes(self.get(url), url, edition)
            if rows: return rows
        return []

    def collect(self, work):
        return execute('quotes.collect',self._collect,source='life.quotes',work=work)

    def _collect(self, work):
        self._validate_work(work)
        methods = ([lambda:self.book(work)] if work['kind'] == 'reading' else [])
        methods += [lambda:self.wiki(work, 'zh'), lambda:self.wiki(work, 'en')]
        for method in methods:
            try:
                rows = method()
                if rows: return rows
            except Exception:
                # Unavailable, challenged, ambiguous or changed markup: skip, never broaden hosts.
                continue
        return []
