"""Read-only projection of the life Agent's movie shelf, quotes and reviews."""
import json


def view(cog):
    state = cog.p.snapshot()
    with cog.store.connect() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        quotes = [json.loads(r[0]) for r in db.execute('SELECT body FROM life_quotes')] if 'life_quotes' in tables else []
        reviews = [json.loads(r[0]) for r in db.execute("SELECT body FROM life_movie_reviews WHERE status='done'")] if 'life_movie_reviews' in tables else []
    result = []
    for ident, movie in cog.p.config.get('movies', {}).items():
        progress = state.get('viewing', {}).get(ident, 0)
        duration = movie.get('duration_seconds') or 0
        result.append({'id': ident, 'title': movie['title'], 'year': movie.get('year'),
            'position': progress, 'duration': duration,
            'completed': bool(duration and progress >= duration),
            'progress_kind': 'life_simulation',
            'quotes': [{'text': q.get('source', {}).get('text', ''),
                        'thought': q.get('thought', q.get('reflection', ''))}
                       for q in quotes if q.get('work', {}).get('target') == ident],
            'reviews': [{'text': r.get('review', {}).get('review', ''), 'date': r.get('written_at', '')}
                        for r in reviews if r.get('movie_id') == ident]})
    return result
