"""Bounded, read-only adapter to jackjin1997/douban-mcp's JSON CLI."""
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from application.content_tools import execute
from application.tool_execution import remaining_timeout, ToolBusy

from .clock import utc
from .config import canonical, digest

PACKAGE = Path(__file__).resolve().parents[1]/'integrations/douban/node_modules/douban-mcp-cli/dist/index.js'


class DoubanUnavailable(RuntimeError):
    pass


def durations(value):
    """Keep alternate cuts separate. Douban's bare content attribute is minutes."""
    raw = str(value or '').strip()
    parts = re.split(r'\s*[/／]\s*', raw)
    out = []
    for part in parts:
        match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(?:分钟|分|minutes?|mins?)?\s*(?:[（(].*[）)])?', part, re.I)
        if match:
            seconds = round(float(match[1])*60)
        else:
            match = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', part, re.I)
            seconds = sum(int(v or 0)*scale for v, scale in zip(match.groups(), (3600, 60, 1))) if match else 0
        if 60 <= seconds <= 24*3600:
            out.append({'duration_seconds': seconds, 'label': part})
    return out


def subject_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,16}', value):
        raise ValueError('invalid Douban subject id')
    return value


def summary(row):
    ident = subject_id(str(row.get('id', '')))
    title = str(row.get('title', '')).strip()[:200]
    if not title: raise ValueError('Douban movie title missing')
    return {'id': ident, 'title': title, 'year': str(row.get('year') or '')[:10],
            'rating': row.get('rating') if type(row.get('rating')) in (int, float) else None,
            'url': f'https://movie.douban.com/subject/{ident}/'}


class Douban:
    def __init__(self, cog, runner=None):
        self.cog = cog
        self.store = cog.store
        self.runner = runner or self._run

    @staticmethod
    def status():
        from infrastructure.paths import SECRETS_ROOT
        return {'installed': PACKAGE.is_file(),
                'cookie_configured': bool(os.getenv('DOUBAN_COOKIE')) or (SECRETS_ROOT/'douban-cookie.txt').is_file(),
                'read_only': True, 'detail_may_require_cookie': True}

    @staticmethod
    def _run(command, args):
        if not PACKAGE.is_file(): raise DoubanUnavailable('douban_cli_not_installed')
        node = os.getenv('LIBRA_DOUBAN_NODE') or shutil.which('node')
        if not node: raise DoubanUnavailable('node_not_found')
        from infrastructure.paths import SECRETS_ROOT
        cookie_file = SECRETS_ROOT/'douban-cookie.txt'
        cookie = os.getenv('DOUBAN_COOKIE') or (cookie_file.read_text(encoding='utf8').strip() if cookie_file.is_file() else '')
        env = {k: v for k,v in os.environ.items() if k.upper() in {
            'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','HOME','USERPROFILE','APPDATA','LOCALAPPDATA'}}
        env.update(DOUBAN_ENABLE_WRITE='false', DOUBAN_DATA_SOURCE='html', DOUBAN_LOG_LEVEL='silent')
        if cookie: env['DOUBAN_COOKIE'] = cookie
        argv = [node, str(PACKAGE), '--json', command]
        for key, value in args.items(): argv += ['--'+key, str(value)]
        try:
            run = subprocess.run(argv, cwd=PACKAGE.parent, env=env, capture_output=True, timeout=remaining_timeout(25),
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if run.returncode:
                raise DoubanUnavailable('douban_access_failed; configure_cookie_or_retry_later')
            if len(run.stdout) > 200_000: raise DoubanUnavailable('douban_response_too_large')
            data = json.loads(run.stdout.decode('utf8'))
            if isinstance(data, dict) and 'error' in data: raise DoubanUnavailable('douban_reported_error')
            return data
        except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as exc:
            raise DoubanUnavailable('douban_transport_unavailable') from exc

    def call(self, operation, **args):
        names = {'search':'movies.search','detail':'movies.detail','reviews':'movies.reviews','chart':'movies.chart'}
        if operation not in names: raise ValueError('Douban read operation not allowed')
        arguments = { {'q':'query','id':'douban_id'}.get(k,k):v for k,v in args.items() }
        def adapter(**values):
            values = { {'query':'q','douban_id':'id'}.get(k,k):v for k,v in values.items() }
            return self._call(operation, **values)
        try:
            return execute(names[operation], adapter, source='life.content', **arguments)
        except (TimeoutError, ToolBusy) as exc:
            # Preserve callers' existing local-data fallback after a uniform receipt.
            raise DoubanUnavailable('douban_transport_unavailable') from exc

    @staticmethod
    def book_call(operation, *, source="life.quotes", **args):
        if operation == 'search':
            return execute('books.search', lambda query,count:Douban._run('search-book',{'q':query,'count':count}),
                           source=source, **args)
        if operation == 'detail':
            return execute('books.detail', lambda douban_id:Douban._run('get-book',{'id':douban_id}),
                           source=source, **args)
        raise ValueError('Douban book operation not allowed')

    def _call(self, operation, **args):
        allowed = {'search': ('search-movie', {'q','count'}), 'detail': ('get-movie', {'id'}),
                   'reviews': ('list-movie-reviews', {'id','count'}), 'chart': ('movie-chart', {'kind','count'})}
        if operation not in allowed: raise ValueError('Douban read operation not allowed')
        command, fields = allowed[operation]
        if set(args) != fields: raise ValueError('invalid Douban arguments')
        if 'id' in args: subject_id(args['id'])
        if 'count' in args and (type(args['count']) is not int or not 1 <= args['count'] <= 8):
            raise ValueError('Douban count must be 1..8')
        if 'q' in args and (not isinstance(args['q'], str) or not 0 < len(args['q'].strip()) <= 120):
            raise ValueError('invalid movie query')
        if 'kind' in args and args['kind'] not in {'top250','weekly','new'}: raise ValueError('invalid movie chart')
        key = digest({'operation': operation, 'args': args})
        now = self.cog.clock.now()
        with self.store.connect() as db:
            row = db.execute("SELECT body FROM life_evidence WHERE category='douban_cache' AND id=?", (key,)).fetchone()
        if row:
            saved = json.loads(row[0])
            if utc(saved['expires_at']) > now:
                if saved.get('error'): raise DoubanUnavailable(saved['error'])
                return saved['data']
        failure = None
        try:
            raw = self.runner(command, args)
            if operation in {'search','chart'}:
                data = [summary(r) for r in raw[:args['count']]]
            elif operation == 'detail':
                data = {**summary(raw), 'duration_raw': str(raw.get('duration') or '')[:200],
                        'duration_options': durations(raw.get('duration')),
                        'summary': str(raw.get('summary') or '')[:3000],
                        'genres': [str(v)[:40] for v in raw.get('genres', [])[:8]],
                        'directors': [str(v.get('name', ''))[:80] for v in raw.get('directors', [])[:5]]}
                if data['id'] != args['id']: raise ValueError('movie detail identity mismatch')
            else:
                data = [{'author': str(r.get('author', ''))[:80], 'content': str(r.get('content', ''))[:600],
                         'rating': r.get('rating') if type(r.get('rating')) in (int,float) else None,
                         'published_at': str(r.get('publishedAt', ''))[:40]} for r in raw[:args['count']]]
            body = {'data': data, 'fetched_at': now.isoformat(),
                    'expires_at': (now+timedelta(hours=6) if operation=='detail' else now+timedelta(minutes=30)).isoformat()}
        except (DoubanUnavailable, ValueError, TypeError, KeyError, AttributeError) as exc:
            failure = exc
            body = {'error': 'douban_unavailable; details_and_comments_may_require_cookie',
                    'expires_at': (now+timedelta(minutes=5)).isoformat()}
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO life_evidence(category,id,body) VALUES('douban_cache',?,?)", (key, canonical(body)))
        if body.get('error'): raise DoubanUnavailable(body['error']) from failure
        return body['data']


def add_candidate(cog, ident, runtime_index):
    return execute('movies.add', lambda douban_id,runtime_index:_add_candidate(cog,douban_id,runtime_index),
                   source='life.content', douban_id=ident,runtime_index=runtime_index)


def _add_candidate(cog, ident, runtime_index):
    detail = Douban(cog).call('detail', id=ident)
    if type(runtime_index) is not int or not 0 <= runtime_index < len(detail['duration_options']):
        raise ValueError('select one verified runtime option; missing duration cannot be scheduled')
    duration = detail['duration_options'][runtime_index]
    key = 'movie:douban:'+ident
    movie = {'id': key, 'title': detail['title'], 'year': detail['year'], 'place': 'home.f2.media',
             'source': 'douban_discovery', 'available': True, 'viewing_mode': 'active_time_simulation',
             'duration_seconds': duration['duration_seconds'], 'edition': duration['label'],
             'duration_source': detail['url'], 'douban_id': ident, 'summary': detail['summary'],
             'genres': detail['genres'], 'catalog_status': 'discovered', 'source_detail': detail}
    remaining_timeout(1)
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute("SELECT body FROM life_evidence WHERE category='discovered_movie' AND id=?", (key,)).fetchone()
        if prior:
            if json.loads(prior[0])['edition'] != movie['edition']:
                raise ValueError('existing movie edition is pinned; do not replace viewing progress')
            return {'movie_id': key, 'added': False}
        db.execute("INSERT INTO life_evidence(category,id,body) VALUES('discovered_movie',?,?)", (key, canonical(movie)))
        row = db.execute("SELECT body FROM life_state WHERE name='resources'").fetchone()
        resources = json.loads(row[0]) if row else {}
        resources.setdefault('movies', {})[key] = movie
        db.execute("INSERT OR REPLACE INTO life_state(name,id,body) VALUES('resources',1,?)", (canonical(resources),))
        state = cog.store.read(db)
        state['revision'] += 1
        db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
    cog.p.config.setdefault('movies', {})[key] = movie
    return {'movie_id': key, 'added': True, 'movie': movie}
