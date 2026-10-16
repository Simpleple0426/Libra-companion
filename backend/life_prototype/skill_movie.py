"""Movie selection metadata and elapsed active-time settlement, without a content LLM."""
from datetime import timedelta
from pathlib import Path
from .clock import utc
from .config import canonical

MODE = 'active_time_simulation'


def instruction():
    return (Path(__file__).parent/'skills/movie/SKILL.md').read_text(encoding='utf8')


def position(duration, seconds):
    seconds = max(0, min(seconds, duration))
    return {'watched_seconds': seconds, 'duration_seconds': duration,
            'percent': round(seconds/duration*100, 2), 'completed': seconds >= duration,
            'semantics': 'active_life_time_not_player_telemetry'}


def label(activity):
    seconds, duration = activity['progress'], activity['movie_duration_seconds']
    def stamp(value):
        value = int(value)
        return f'{value//3600:02d}:{value%3600//60:02d}:{value%60:02d}'
    return f"{stamp(seconds)} / {stamp(duration)}（{seconds/duration*100:.1f}%）"


def plan(movie, progress, seconds):
    duration = movie['duration_seconds']
    start = 0 if progress >= duration else progress
    return {'skill': 'movie', 'mode': MODE, 'start': position(duration, start),
            'expected_end': position(duration, start+seconds), 'budget_seconds': seconds,
            'edition': movie.get('edition'), 'semantics': 'expected_range_not_completed_progress'}


def begin(config, state, activity, at, *, resuming=False):
    movie = config['movies'][activity['target']]
    if not movie.get('available', True) or state['place'] != movie['place']:
        raise ValueError('movie unavailable or wrong place')
    duration = activity.get('movie_duration_seconds') if resuming else None
    duration = duration or movie.get('duration_seconds')
    if type(duration) is not int or duration <= 0:
        raise ValueError('movie needs a verified reference duration')
    if activity['progress'] >= duration:
        if resuming:
            raise ValueError('movie already completed; start a new viewing')
        activity['progress'] = 0
    activity.update(viewing_mode=MODE, movie_duration_seconds=duration,
                    movie_edition=activity.get('movie_edition', movie.get('edition')),
                    heartbeat_at=at.isoformat(), session_start_progress=activity['progress'])
    activity.pop('viewing_deadline', None)
    state.setdefault('viewing', {})[activity['target']] = activity['progress']
    previous = state.setdefault('viewing_progress', {}).get(activity['target'], {})
    state['viewing_progress'][activity['target']] = {
        **previous, **position(duration, activity['progress']), 'movie_id': activity['target'],
        'edition': activity['movie_edition'], 'activity_id': activity['id'], 'updated_at': at.isoformat()}


def elapsed_seconds(state, activity, at):
    """Running time is independent of how often a busy worker can settle it."""
    if (activity.get('viewing_mode') != MODE or activity['status'] != 'running'
            or state['place'] != activity['place']):
        return 0
    previous = utc(activity['heartbeat_at'])
    until = min(at, utc(activity['viewing_deadline'])) if activity.get('viewing_deadline') else at
    return max(0, (until-previous).total_seconds())


def settle(config, state, activity, at, *, recovering=False):
    if activity.get('viewing_mode') != MODE or activity['status'] != 'running':
        return
    # Explicit worker recovery owns offline gaps. A delayed model call or
    # foreground chat must not discard otherwise continuous watching time.
    elapsed = 0 if recovering else elapsed_seconds(state, activity, at)
    activity['progress'] = min(activity['movie_duration_seconds'], activity['progress']+elapsed)
    activity.update(heartbeat_at=at.isoformat(), last_progress_at=at.isoformat(), revision=activity['revision']+1)
    state.setdefault('viewing', {})[activity['target']] = activity['progress']
    previous_record = state.setdefault('viewing_progress', {}).get(activity['target'], {})
    state['viewing_progress'][activity['target']] = {
        **position(activity['movie_duration_seconds'], activity['progress']),
        'movie_id': activity['target'], 'edition': activity.get('movie_edition'),
        'activity_id': activity['id'], 'updated_at': at.isoformat(),
        'completed_viewings': previous_record.get('completed_viewings', 0),
        'last_completed_activity': previous_record.get('last_completed_activity')}
    record = state['viewing_progress'][activity['target']]
    if record['completed'] and record['last_completed_activity'] != activity['id']:
        record['completed_viewings'] += 1
        record['last_completed_activity'] = activity['id']


def heartbeat(cog):
    p = cog.p
    with p.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = p.store.read(db)
        activity = state['activities'].get(state.get('active'))
        if not activity or activity.get('viewing_mode') != MODE:
            return False
        now = p.clock.now()
        settle(p.config, state, activity, now)
        complete = activity['progress'] >= activity['movie_duration_seconds']
        activity['next_due_at'] = (now+timedelta(seconds=p.config['checkpoint_seconds'])).isoformat()
        state.update(revision=state['revision']+1, as_of=now.isoformat())
        db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        if complete:
            # Final position, completion count and end event commit together.
            p._commit_locked(db, 'movie-finished:'+activity['id'],
                {'expected_revision': state['revision'], 'operation': 'interrupt',
                 'payload': {'activity_id': activity['id'], 'reason': '本轮累计观看时长已达到电影片长'}}, None)
    return True
