"""Coarse slots own location; room selection has no movement executor."""
from .clock import utc
from .config import canonical, digest
from .coarse_plan import schedule_day
from .coarse_plan_schema import site_id, site_name


def advance(cog):
    if cog.p.config.get('mode') != 'local_single_user':
        return False
    now = cog.clock.now()
    state = cog.p.snapshot()
    from .companionship import current
    if current(state, now) or state.get('sleep', {}).get('status') != 'awake':
        return False
    from .coarse_plan_execution import pause_mismatch, requirement
    pause_mismatch(cog)
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = cog.store.read(db)
        agenda = cog.agenda._read(db, schedule_day(now))
        item = next((i for i in (agenda or {}).get('items', []) if utc(i['start_at']) <= now < utc(i['end_at'])), None)
        if not item or item.get('activity') == 'user_time':
            return False
        if (requirement(cog, state, db=db, at=now) or {}).get('reason') == 'await_confirmed_morning_wake':
            return False
        old = state.get('coarse_location_slot') or {}
        slot_key = digest([item['kind'], item['start_at'], item['end_at'],
            site_id(item.get('place')), site_id(item.get('destination'))])
        changed = old.get('key') != slot_key
        commute = item.get('kind') == 'commute'
        site = site_id(item.get('coarse_place') or item.get('place'))
        events = []
        carrier = {}
        # An observed coarse commute completes at its own end, not after room walks.
        if (changed and old.get('kind') == 'commute' and utc(old['end_at']) <= now
                and old.get('destination') == site):
            destination = old['destination']
            events.append(('arrived', destination, old['end_at']))
        if commute:
            destination = site_id(item.get('coarse_destination') or item.get('destination'))
            if changed and site != destination:
                events.append(('moving_start', site, item['start_at']))
            place = state['place']
        else:
            required = requirement(cog, state, db=db, at=now)
            place = (required or {}).get('destination') or item.get('place')
            if (required or {}).get('kind') == 'serving':
                meal = (required.get('meal') or {})
                eat_place = meal.get('eat_place')
                if eat_place and site_id(eat_place) == site:
                    state['meals'][meal['id']]['place'] = eat_place
                    place = eat_place
            if site_id(place) != site:
                return False
            if changed and site_id(state['place']) != site and not any(e[0] == 'arrived' and e[1] == site for e in events):
                events.append(('arrived', site, now.isoformat()))
            destination = None
        if not changed and state['place'] == place:
            return False
        # Close visits at a coarse departure, not at an imaginary room walk.
        if changed and commute:
            from .skill_exercise import departure
            carrier = {'target': destination}
            departure(state, carrier, now)
            from .skill_work import departure as work_departure
            work_departure(state, carrier, now)
            state.pop('outing_visit', None)
        state['place'] = place
        state['coarse_location_slot'] = {'id': item['id'], 'key': slot_key,
            'kind': 'room_transition' if commute and destination == site else item['kind'],
            'end_at': item['end_at'], 'destination': destination}
        state['revision'] += 1
        state['as_of'] = now.isoformat()
        from .event_store import append
        for ended in carrier.get('exercise_departures', []):
            from .skill_exercise import event_text
            ident = 'coarse-exercise-departure:' + ended
            append(db, ident, {'operation': 'exercise_departure', 'activity_id': ended,
                'description': event_text(state['activities'][ended]['exercise_mode'], ending=True)},
                {'event_id': ident, 'revision': state['revision'], 'occurred_at': now.isoformat(),
                 'source': 'coarse_schedule'}, state, cog.p.config)
        work = carrier.get('work_departure')
        if work:
            ident = 'coarse-work-departure:' + item['id']
            append(db, ident, {'operation': 'work_departure', 'activity_id': work['activity_id'],
                'description': '左然结束工作，离开' + cog.p.config['places'][work['place']]['name']},
                {'event_id': ident, 'revision': state['revision'], 'occurred_at': now.isoformat(),
                 'source': 'coarse_schedule'}, state, cog.p.config)
        for index, (kind, location, occurred_at) in enumerate(events):
            name = site_name(location, cog.p.config.get('places', {}).get(location, {}).get('name', location))
            description = ('左然离开了' + name if kind == 'moving_start' else
                           '左然回到了家' if location == 'home' else '左然到达了' + name)
            ident = 'coarse-location:' + slot_key + ':' + str(index)
            db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)',
                (ident, occurred_at, description, kind, None, item['id'], None))
        db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        return True
