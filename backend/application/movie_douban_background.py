"""Read existing Douban integration without modifying the user's movie library."""
import re
import unicodedata
from application.content_tools import execute
from life_prototype.douban import Douban, summary


def _name(value):
    value = unicodedata.normalize('NFKC', value)
    value = re.sub(r'\s*\((?:19|20)\d{2}\)\s*$', '', value)
    return re.sub(r'[\s《》]', '', value).casefold()


def fetch(title):
    year = re.search(r'[（(]((?:19|20)\d{2})[）)]\s*$', title)
    query = title[:year.start()].strip() if year else title.strip()
    rows = execute('movies.search', lambda query, count: Douban._run('search-movie', {'q': query, 'count': count}),
                   source='movie.background', query=query[:120], count=8)
    candidates = [summary(row) for row in rows]
    for row in candidates:
        suffix = re.search(r'[（(]((?:19|20)\d{2})[）)]\s*$', row['title'])
        if not row['year'] and suffix:
            row['year'] = suffix[1]
    matches = {row['id']: row for row in candidates if _name(row['title']) == _name(query)
               and (not year or row['year'] == year[1])}
    if len(matches) > 1:
        return {'status': 'ambiguous'}
    if not matches:
        raise ValueError('douban_title_not_confirmed')
    movie = next(iter(matches.values()))
    detail = execute('movies.detail', lambda douban_id: Douban._run('get-movie', {'id': douban_id}),
                     source='movie.background', douban_id=movie['id'])
    verified = summary(detail)
    if verified['id'] != movie['id'] or _name(verified['title']) != _name(movie['title']):
        raise ValueError('douban_identity_mismatch')
    reviews = execute('movies.reviews', lambda douban_id, count: Douban._run('list-movie-reviews', {'id': douban_id, 'count': count}),
                      source='movie.background', douban_id=movie['id'], count=3)
    introduction = str(detail.get('summary') or '').strip()[:6000]
    comments = [{'author': str(r.get('author', ''))[:80], 'content': str(r.get('content') or '')[:1800]}
                for r in reviews[:3] if isinstance(r, dict) and r.get('content')]
    if not introduction or not comments:
        raise ValueError('douban_background_incomplete')
    return {'status': 'ready', 'identity': verified, 'introduction': introduction,
            'directors': [str(d.get('name', ''))[:80] for d in detail.get('directors', [])[:5] if isinstance(d, dict)],
            'reviews': comments, 'sources': [
                {'kind': 'intro', 'title': '豆瓣电影简介', 'url': movie['url']},
                {'kind': 'review', 'title': '豆瓣电影评论', 'url': movie['url'] + 'reviews/'}]}
