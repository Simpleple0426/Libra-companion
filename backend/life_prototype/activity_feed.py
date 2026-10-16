"""Read-only projection of committed life facts for the local App.

The feed is a project UI adaptation.  It never reads proposals, predictions,
pending results, optional summaries, or rejected reflections.  Structured P1/P3
ledger rows and settled result receipts are the only sources of displayed facts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import sqlite3
from zoneinfo import ZoneInfo


def display_without_meal_details(items: list[dict], state: dict) -> list[dict]:
    """Hide meal specifics in the App projection, retaining the original ledger."""
    displayed = []
    for item in items:
        detail = item.get('detail') or {}
        activity = state.get('activities', {}).get(detail.get('activity_id'), {})
        kind = item.get('kind', '')
        if kind not in {'meal_start', 'meal_completed', 'meal_paused',
                        'eating_start', 'cooking_start', 'serving_start'}:
            displayed.append(item)
            continue
        phase = activity.get('meal_phase')
        if kind == 'meal_paused':
            text = '左然暂停了用餐' if phase == 'eating' else '左然暂停了备餐或等餐'
        elif kind == 'meal_completed':
            text = '左然吃完了' if phase == 'eating' else '左然完成了备餐或等餐'
        elif kind == 'eating_start' or phase == 'eating':
            text = '左然正在吃饭'
        elif kind == 'serving_start':
            text = '左然正在搬运餐食'
        elif phase in {'takeout', 'dine'}:
            text = '左然正在等餐'
        else:
            text = '左然正在备餐'
        displayed.append(dict(item, event=text, detail=dict(detail, content=text)))
    return displayed


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed


def _schedule_day(value: str, timezone_name: str) -> date:
    local = _dt(value).astimezone(ZoneInfo(timezone_name))
    if local.hour < 4:
        local -= timedelta(days=1)
    return local.date()


def _place_name(config: dict, place_id: str | None) -> str:
    if not place_id:
        return "未知地点"
    return config.get("places", {}).get(place_id, {}).get("name") or place_id


def _target_name(config: dict, kind: str, target: str | None) -> str:
    if kind == 'watching':
        return config.get('movies',{}).get(target or '',{}).get('title') or target or '当前影片'
    if kind == "work":
        item = config.get("work_items", {}).get(target or "", {})
        return item.get("title") or item.get("name") or target or "当前工作事项"
    if kind == "reading":
        item = config.get("books", {}).get(target or "", {})
        return item.get("title") or item.get("name") or target or "当前读物"
    return target or ""


def _correct_premature_morning(db, items: list[dict], schedule_date: date | None,
                               timezone_name: str) -> list[dict]:
    """Hide the retired 04:00-as-wake bug and expose the configured wake time.

    Older agenda revisions treated the living-day boundary as an observed wake
    and immediately emitted room/care events.  Those rows are retained for
    audit, but are not truthful activity facts.  A correction is shown only
    after the configured wake time has passed and only when that legacy pattern
    is present.
    """
    if schedule_date is None or any(item['kind'] == 'woke' for item in items):
        return items
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_daily_agendas'").fetchone():
        return items
    row = db.execute(
        "SELECT body FROM life_daily_agendas WHERE day=? ORDER BY revision DESC LIMIT 1",
        (schedule_date.isoformat(),),
    ).fetchone()
    if not row:
        return items
    try:
        agenda = json.loads(row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return items
    day_type = (agenda.get('calendar') or {}).get('day_type')
    wake_minute = 450 if day_type == 'rest_day' else 420
    local_zone = ZoneInfo(timezone_name)
    wake_at = datetime.combine(schedule_date, datetime.min.time(), tzinfo=local_zone) + timedelta(minutes=wake_minute)
    if datetime.now(local_zone) < wake_at:
        return items
    premature = [item for item in items
                 if 4 <= _dt(item['occurred_at']).astimezone(local_zone).hour
                 and _dt(item['occurred_at']).astimezone(local_zone) < wake_at
                 and item['kind'] in {'at_place', 'care_start'}]
    if not any(item['kind'] == 'care_start' for item in premature):
        return items
    hidden_ids = {item['id'] for item in premature}
    corrected = [item for item in items if item['id'] not in hidden_ids]
    corrected.append({
        'id': f'display-correction:wake:{schedule_date.isoformat()}',
        'occurred_at': wake_at.isoformat(),
        'event': '左然起床了',
        'kind': 'woke',
        'summary_source': 'corrected_legacy_day_boundary_projection',
        'detail': {
            'activity_id': None,
            'coarse_plan_id': None,
            'fine_plan_id': None,
            'content': '旧版本误将凌晨四点换日当作起床；按已确认的日常起床时间修正显示。',
            'fact_basis': 'confirmed_wake_reference_and_invalid_legacy_event_pattern',
        },
        '_original_event': '左然起床了',
    })
    corrected.sort(key=lambda item: _dt(item['occurred_at']))
    return corrected


def _movement_description(row, state: dict, config: dict) -> str:
    """Project site-boundary movement consistently for every phone surface."""
    description = row['description']
    if row['kind'] not in {'moving_start', 'arrived'} or not row['activity_id']:
        return description
    activity = state.get('activities', {}).get(row['activity_id'], {})
    route = activity.get('route') or []
    if not route:
        return description
    origin = route[0]
    target = activity.get('target') or route[-1]
    origin_in_firm = origin == 'firm' or str(origin).startswith('firm.')
    target_in_firm = target == 'firm' or str(target).startswith('firm.')
    firm_name = config.get('places', {}).get('firm', {}).get('name') or '忒弥斯律所'
    if row['kind'] == 'arrived' and not origin_in_firm and target_in_firm:
        return '左然到达了' + firm_name
    if row['kind'] == 'moving_start' and origin_in_firm and not target_in_firm:
        return '左然离开了' + firm_name
    return description


def _detail(*, activity_id=None, kind=None, source=None, revision=None,
            place_id=None, place_name=None, progress=None, total=None,
            status=None, content=None, fact_basis="committed_structured_ledger"):
    return {key: value for key, value in {
        "activity_id": activity_id, "activity_kind": kind,
        "source": source, "state_revision": revision,
        "place_id": place_id, "place_name": place_name,
        "progress": progress, "total": total, "activity_status": status,
        "content": content, "fact_basis": fact_basis,
        "display_scope": "local_life_read_only",
    }.items() if value is not None}


def project(rows, state: dict, config: dict, *, schedule_date: date | None = None,
            limit: int = 200) -> list[dict]:
    """Project committed event rows into compact summaries and auditable details."""
    timezone_name = config.get("display_timezone", "Asia/Shanghai")
    activities = state.get("activities", {})
    decoded = []
    for row_index, row in enumerate(rows):
        try:
            request = json.loads(row["request"])
            receipt = json.loads(row["receipt"])
            occurred_at = receipt["occurred_at"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if schedule_date is not None and _schedule_day(occurred_at, timezone_name) != schedule_date:
            continue
        decoded.append((row_index, row["id"], request, receipt, occurred_at))

    # A movement is shown only at its final settled segment.  Intermediate
    # route nodes remain available in the activity/result ledger, not as a
    # misleading "arrived at destination" homepage fact.
    final_result_id = {}
    for _, event_id, request, _, _ in decoded:
        if request.get("operation") == "result":
            final_result_id[request.get("activity_id")] = event_id

    items = []
    for row_index, event_id, request, receipt, occurred_at in decoded:
        operation = request.get("operation")
        revision = receipt.get("revision")
        item = None
        if operation == "start":
            payload = request.get("payload", {})
            activity_id = payload.get("activity_id")
            kind = payload.get("kind")
            activity = activities.get(activity_id, {})
            place_id = payload.get("place") or activity.get("place")
            target = _target_name(config, kind, payload.get("target"))
            if kind == "work":
                work_item = config.get("work_items", {}).get(payload.get("target") or "", {})
                stage_total = len(work_item.get("stages", [])) or 2
                item = {
                    "kind": "work_started", "event": "开始工作",
                    "detail": _detail(activity_id=activity_id, kind=kind,
                        source=receipt.get("source"), revision=revision,
                        place_id=place_id, place_name=_place_name(config, place_id),
                        progress=0, total=stage_total, status="started",
                        content=f"开始处理：{target}"),
                }
            elif kind in {"moving", "reading", "cooking", "eating", "showering", "watching"}:
                title = {
                    "moving": f"出发前往{_place_name(config, payload.get('target'))}",
                    "reading": "开始阅读",
                    "watching": "开始观影",
                    "cooking": "开始做饭",
                    "eating": "开始吃饭",
                    "showering": "开始洗澡",
                }[kind]
                item = {
                    "kind": kind + "_started", "event": title,
                    "detail": _detail(activity_id=activity_id, kind=kind,
                        source=receipt.get("source"), revision=revision,
                        place_id=place_id, place_name=_place_name(config, place_id),
                        progress=0, total=activity.get("total"), status="started",
                        content=(f"目标：{target}" if target else None)),
                }
        elif operation == "result" and receipt.get("source") in {
                "simulated_world", "model_work", "model_reading", "controlled_test"}:
            activity_id = request.get("activity_id")
            activity = activities.get(activity_id, {})
            kind = activity.get("kind")
            evidence = request.get("evidence", {})
            progress = activity.get("progress")
            total = activity.get("total")
            common = dict(activity_id=activity_id, kind=kind,
                source=receipt.get("source"), revision=revision,
                progress=progress, total=total, status=activity.get("status"))
            if kind == "moving" and final_result_id.get(activity_id) == event_id \
                    and activity.get("status") == "completed":
                place_id = evidence.get("to")
                place = _place_name(config, place_id)
                item = {"kind": "arrived", "event": f"到达{place}",
                    "detail": _detail(**common, place_id=place_id, place_name=place,
                        content=(f"本段从{_place_name(config, evidence.get('from'))}到{place}；"
                                 f"整体移动已完成，目的地为{_place_name(config, activity.get('target'))}。"))}
            elif kind == "work":
                stage = evidence.get("artifact", {}).get("stage")
                if isinstance(stage, int):
                    work_item = config.get("work_items", {}).get(activity.get("target") or "", {})
                    stage_total = len(work_item.get("stages", [])) or total or 2
                    common.update(progress=stage, total=stage_total,
                                  status="completed" if stage >= stage_total else "in_progress")
                    title = f"完成工作阶段 {stage}/{stage_total}"
                    content = evidence.get("artifact", {}).get("summary")
                    item = {"kind": "work_progress", "event": title,
                        "detail": _detail(**common, place_id=activity.get("place"),
                            place_name=_place_name(config, activity.get("place")), content=content)}
            elif kind in {"cooking", "eating", "showering", "reading"} \
                    and activity.get("status") == "completed" \
                    and final_result_id.get(activity_id) == event_id:
                title = {"cooking": "做好一餐", "eating": "吃完一餐",
                         "showering": "洗完澡", "reading": "完成阅读"}[kind]
                content = evidence.get("observation") if kind in {"reading", "cooking", "eating", "showering"} else None
                item = {"kind": kind + "_completed", "event": title,
                    "detail": _detail(**common, place_id=activity.get("place"),
                        place_name=_place_name(config, activity.get("place")), content=content)}
        elif operation == "p3":
            observation = request.get("observation", {})
            kind = observation.get("type")
            fact = observation.get("fact", {})
            if kind == "sleep_start":
                place_id = fact.get("place")
                item = {"kind": "sleep_started", "event": "入睡",
                    "detail": _detail(source=receipt.get("source"), revision=revision,
                        place_id=place_id, place_name=_place_name(config, place_id),
                        status="sleeping", content="已提交晚安后的入睡状态。")}
            elif kind == "wake":
                reason = {"natural": "自然醒来", "message": "收到消息后醒来",
                          "manual": "醒来"}.get(fact.get("reason"), "醒来")
                item = {"kind": "woke", "event": reason,
                    "detail": _detail(source=receipt.get("source"), revision=revision,
                        status="awake", content=f"本次已睡 {int(fact.get('episode_seconds', 0))} 秒。")}
        if item is None:
            continue
        items.append({"id": event_id, "occurred_at": occurred_at,
            "event": item["event"], "kind": item["kind"],
            "summary_source": "code_generated_from_verified_fields",
            "detail": item["detail"], "_order": row_index})

    items.sort(key=lambda value: (_dt(value["occurred_at"]), value["_order"]))
    for item in items:
        item.pop("_order", None)
    return items if limit is None else items[-max(1, min(int(limit), 500)):]


def read(db, state: dict, config: dict, *, schedule_date: date | None = None,
         limit: int | None = 200, collapse_consecutive: bool = True) -> list[dict]:
    """Return the concise user timeline.

    Detailed execution receipts remain in the database for scheduling and
    audit.  The phone timeline records only the beginning of a fine activity;
    pauses, resumes, progress checkpoints, endings, and route bookkeeping are
    deliberately omitted.  Sleep/wake facts are retained because they describe
    the day boundary rather than resumable activity progress.
    Durable notification delivery disables consecutive display-text collapse
    so distinct committed updates retain their source IDs.
    """
    db.row_factory = sqlite3.Row
    if 'description' in {r[1] for r in db.execute('PRAGMA table_info(events)')}:
        rows = [dict(row) for row in db.execute('SELECT * FROM events ORDER BY rowid')]
        # Home arrival is the settled outside -> home segment, even when the
        # longer route to a room later stops. Recover old display omissions
        # from committed receipts without rewriting the historical ledger.
        from .event_store import in_home
        arrivals = {}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='life_receipts'").fetchone():
            for receipt_row in db.execute("SELECT id,request,receipt FROM life_receipts WHERE category='event_control' AND json_extract(request,'$.operation')='result'"):
                request, receipt = json.loads(receipt_row['request']), json.loads(receipt_row['receipt'])
                evidence = request.get('evidence', {})
                activity_id = request.get('activity_id')
                if (state.get('activities', {}).get(activity_id, {}).get('kind') == 'moving'
                        and receipt.get('source') in {'simulated_world', 'controlled_test'}
                        and evidence.get('from') and not in_home(evidence['from']) and in_home(evidence.get('to'))):
                    arrivals[receipt_row['id']] = {'id': receipt_row['id'], 'occurred_at': receipt['occurred_at'],
                        'description': '左然回到了家', 'kind': 'arrived', 'activity_id': activity_id,
                        'coarse_plan_id': None, 'fine_plan_id': None}
        ids = {row['id'] for row in rows}
        rows.extend(row for ident, row in arrivals.items() if ident not in ids)
        normalized = []
        for row in rows:
            activity = state.get('activities', {}).get(row['activity_id'], {})
            route = activity.get('route') or []
            target = activity.get('target')
            if row['kind'] == 'moving_start' and route and in_home(route[0]) and in_home(target):
                continue
            if row['kind'] == 'arrived' and in_home(target) and row['id'] not in arrivals:
                row['description'] = '左然正在' + _place_name(config, target)
            normalized.append(row)
        rows = sorted(normalized, key=lambda row: _dt(row['occurred_at']))
        visible_kinds = {
            'work_start', 'work_arrival', 'work_break_start',
            'reading_start', 'watching_start', 'meal_start', 'housework_start',
            'care_start', 'exercise_start', 'outing_start', 'rest_start',
            'television_on', 'eating_start', 'showering_start',
            'cooking_start', 'serving_start', 'sleep_started', 'woke',
            'moving_start', 'arrived', 'at_place',
            'user_time_start',
            'companion_update',
        }
        home_place_descriptions = {
            '左然正在' + place.get('name', place_id)
            for place_id, place in config.get('places', {}).items()
            if place_id.startswith('home.')
        }
        items = [{'id': row['id'], 'occurred_at': row['occurred_at'],
                  'event': _movement_description(row, state, config),
                  'kind': row['kind'], 'summary_source': 'persisted_life_event',
                  'detail': {'activity_id': row['activity_id'], 'coarse_plan_id': row['coarse_plan_id'],
                             'fine_plan_id': row['fine_plan_id'], 'content': row['description'],
                             'fact_basis': 'committed_life_event',
                             **({'semantics': 'reserved_user_time_started; no user presence, location or outcome inferred'}
                                if row['kind'] == 'user_time_start' else {})},
                  '_original_event': row['description']}
                 for row in rows if row['kind'] in visible_kinds
                 and (row['kind'] != 'at_place' or row['description'] in home_place_descriptions)
                 and (schedule_date is None or
                 _schedule_day(row['occurred_at'], config.get('display_timezone', 'Asia/Shanghai')) == schedule_date)]
        items = _correct_premature_morning(db, items, schedule_date,
                                           config.get('display_timezone', 'Asia/Shanghai'))
        # Crossing a site boundary and reaching a room are separate facts.
        # Keep the coarse site arrival/departure and the detailed destination.
        expanded = []
        for item in items:
            original = item.pop('_original_event')
            if item['event'] != original:
                boundary = dict(item)
                boundary['id'] = item['id'] + ':site-boundary'
                boundary['detail'] = dict(item['detail'],
                    hierarchy='coarse_location_boundary')
                expanded.append(boundary)
                item['event'] = original
                item['detail'] = dict(item['detail'], hierarchy='fine_location')
            expanded.append(item)
        items = expanded
        # Older worker restarts may have produced a new activity id for the
        # same fine start.  Present that as one start inside its coarse slot.
        deduplicated = []
        seen_starts = set()
        for item in items:
            coarse_id = item['detail']['coarse_plan_id']
            key = (coarse_id, item['kind'], item['event'])
            if coarse_id and item['kind'].endswith('_start'):
                if key in seen_starts:
                    continue
                seen_starts.add(key)
            deduplicated.append(item)
        # Interrupted routes can restart with new activity and coarse ids.
        # Until an arrival is observed, repeated departures from the same
        # displayed origin are one visible departure.
        items = []
        open_departures = set()
        for item in deduplicated:
            if item['kind'] == 'moving_start':
                if item['event'] in open_departures:
                    continue
                open_departures.add(item['event'])
            elif item['kind'] == 'arrived':
                open_departures.clear()
            items.append(item)
    else:
        # Read-only archived databases retain their original schema.
        rows = db.execute("SELECT id,request,receipt FROM events ORDER BY rowid").fetchall()
        items = project(rows, state, config, schedule_date=schedule_date, limit=None)
    # A committed plan change is a communication trigger, not an activity fact.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_agenda_messages'").fetchone():
        for row in db.execute("SELECT message_id,receipt FROM life_agenda_messages WHERE status='applied' ORDER BY rowid"):
            result = json.loads(row['receipt'])
            # Companion updates share this inbox but have their own committed
            # companion_update event; they are not agenda revisions.
            if result.get('companion_proposal') is not None:
                continue
            at = result.get('at')
            if not isinstance(at, str) or not at:
                continue
            try:
                _dt(at)
            except ValueError:
                continue
            if schedule_date is not None and _schedule_day(at, config.get('display_timezone', 'Asia/Shanghai')) != schedule_date:
                continue
            items.append({'id': 'agenda-review:' + row['message_id'], 'occurred_at': at,
                'kind': 'agenda_changed', 'event': '已调整未来日程',
                'summary_source': 'code_generated_from_verified_fields',
                'detail': {'source_message': row['message_id'], 'receipt': result,
                           'fact_basis': 'committed_agenda_revision',
                           'semantics': 'future_plan_only_not_activity_started_or_completed'}})
    items.sort(key=lambda item: _dt(item['occurred_at']))
    # Repeated reports of the same ongoing activity are one display entry.
    # Keep its first timestamp; a different fact or living day starts a new run.
    compact = []
    previous = None
    seen_housework = set()
    for item in items:
        if collapse_consecutive and item['kind'] == 'housework_start':
            activity = state.get('activities', {}).get(item['detail'].get('activity_id'), {})
            step = state.get('housework_steps', {}).get(activity.get('target'), {})
            plan_id = step.get('plan_id')
            plan = state.get('housework_plans', {}).get(plan_id, {})
            routine = plan.get('routine')
            title = {'clean_dishes': '收拾餐后餐具', 'laundry': '洗衣服',
                     'dry_laundry': '晾衣服', 'fold_laundry': '整理衣物'}.get(routine, '收拾家里')
            group = plan_id or item['detail'].get('coarse_plan_id')
            if group:
                housework_key = (_schedule_day(item['occurred_at'], config.get('display_timezone', 'Asia/Shanghai')), group)
                if housework_key in seen_housework:
                    continue
                seen_housework.add(housework_key)
            item = dict(item, event='左然开始' + title,
                        detail=dict(item['detail'], content='左然开始' + title))
        key = (_schedule_day(item['occurred_at'], config.get('display_timezone', 'Asia/Shanghai')),
               item['kind'], item['event'])
        if not collapse_consecutive or key != previous:
            compact.append(item)
        previous = key
    items = compact
    return items if limit is None else items[-max(1, min(int(limit), 500)):]
