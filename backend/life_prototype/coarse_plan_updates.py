"""LLM interpretation followed by bounded, transactional future-plan edits."""
from copy import deepcopy
from datetime import timedelta
from zoneinfo import ZoneInfo
import json
import math

from .clock import utc
from .config import canonical, digest
from .activity_engine import require
from .cognition_contracts import shape, text
from .store import Conflict


INSTRUCTION = """判断最新用户消息是否应影响左然的未来安排，并给出最小调整。
assistant_replies是角色已经发送的回复。明确答应调整自身行程时，使用itinerary_changes落实，可以自主选择可行时间；例如“我早点回家”“我准备回去”。客套、否定、引用、假设不是承诺。回复不能授权陪伴或用户预约。立即回家包括“急急急 回家！”；start_at使用null，不填写模型调用时的钟点。
这是语义判断，不是关键词匹配。结合固定人设、消息上下文、当前时间/地点、原计划和 upcoming_appointments 判断。可以预约未来日期、取消或改期未来预约。
普通闲聊、讲述过去、引用别人的话、假设、玩笑、否定请求不自动修改计划，返回 none。
用户明确希望陪伴、改期、取消或更换活动时，可以调整左然自己的计划；不代替用户承诺到场，不制造实际活动。
两条路径必须区分：明确陪伴由companion.revise处理；早点回家、取消健身、改运动时间、在家看书属于自己的行程调整，使用itinerary_changes，不得生成陪用户预约。
itinerary_changes每项为{operation:"cancel|replace|reschedule|return_home",item_id:ID或null,start_at:ISO或明确现在时null,end_at:ISO或null,activity:活动或null,place_id:真实地点ID或null}。
cancel仅填item_id；reschedule填item_id及新起止时间；replace填起止时间、activity和place_id；return_home只填出发时间start_at，其余null。未使用字段必须null。
活动可选home_activity/resting/working/reading/watch_movie/watch_tv/exercising/housework/outing。只改本生活日剩余时段，不覆盖必要用餐洗漱、已有预约和陪伴；return_home后在家自主生活，正常通勤不瞬移。
模糊的早点先clarify协商具体时间，明确取消已有活动可直接按ID取消；无关聊天none。行程修改时其他修改数组为空；none/clarify时所有修改数组都为空。
无法确定日期、时间或指代，返回 clarify，reason 写清需要澄清什么。相对日期以消息 received_at 为准，不以处理时间推移。
只能修改未来安排。不要改变睡眠状态、工作日历、用户状态或已发生事实。
cancel_item_ids 只列原计划中不再需要的可选活动 ID，例如取消观影；不可取消用餐、洗澡、睡前洗漱或卧室准备。
例如用户要求今晚20点陪她说话，原定晚间电影与陪伴冲突时，应取消该电影计划并添加20点的聊天预约，不把电影拆成预约前后两段继续执行。
appointments 为用户预留时间，可用于漫展、约会、聊天等任意用户约定事项，不限已有 Skill。
每项只需 title、start_at、duration_seconds。title 写“陪用户＋具体事项”，例如“陪用户逛漫展”；不要写日期、地点核验或泛化为“陪伴交流”。时间为带时区ISO时间；“现在”用 start_at:null。
用户约定不需要地点、不查询地点目录或路线，也不因地点未知而澄清或拒绝；只预留约定时段，不生成通勤、到场、购票或用户行动。
现有预约改期须在 cancel_appointment_ids 中取消旧 ID，再列新预约。
duration_seconds 若用户没指定可估计15至60分钟，并在 reason 说明是暂定；单次超过4小时或跨凌晨04:00生活日边界请澄清，可拆为多项。未来预约只保存意图，到对应日期再落实日程。
必要餐食/洗澡可由代码顺延到合法时段，但不能被删除或缩短。优先选择不冲突的时间。
用户已经取消的活动不要重新加入。只处理最新消息，历史消息仅用于理解指代。
返回 {decision:"none|revise|clarify",reason:字符串,evidence_quote:最新消息的逐字引文,
cancel_item_ids:[ID],cancel_appointment_ids:[ID],appointments:[{title,start_at,duration_seconds}],itinerary_changes:[上述行程调整]}。
none/clarify 时所有修改数组必须为空。revise 必须有实际修改且 evidence_quote 非空。
这里只生成调整意图，不生成聊天回复；最终是否采用以代码校验及提交回执为准。
"""


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS life_agenda_messages(
        message_id TEXT PRIMARY KEY, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        retry_at TEXT, receipt TEXT)""")
    from .appointments import initialize as initialize_appointments
    initialize_appointments(db)


def enqueue(db, message_id):
    db.execute("INSERT OR IGNORE INTO life_agenda_messages(message_id,status) VALUES(?,'pending')", (message_id,))


def latest(agenda):
    with agenda.store.connect() as db:
        row = db.execute("SELECT message_id,status,receipt FROM life_agenda_messages ORDER BY rowid DESC LIMIT 1").fetchone()
    return ({"message_id": row[0], "status": row[1], "detail": json.loads(row[2]) if row[2] else None,
             "rule": "Only applied means the schedule changed; pending/clarify/failed do not confirm an appointment."}
            if row else None)


def protected(item):
    return item["kind"] in {"meal", "shower", "bedtime"} or item.get("activity") in {
        "bedtime_wash", "bedtime_preparation", "await_goodnight"}


def signature(item):
    # Stable across revision IDs, and specific enough not to cancel a different
    # activity after a calendar/template change.
    return item.get('source_window') or [item.get(k) for k in ("legacy_activity", "legacy_place", "legacy_start_at", "legacy_end_at")]


def validate_proposal(proposal, message, body, state, config, now):
    shape({k:v for k,v in proposal.items() if k != 'itinerary_changes'}, {"decision", "reason", "evidence_quote", "cancel_item_ids", "cancel_appointment_ids", "appointments"})
    changes = proposal.get('itinerary_changes', [])
    require(isinstance(changes, list) and len(changes) <= 12, 'too many itinerary changes')
    require(proposal["decision"] in {"none", "revise", "clarify"}, "invalid agenda decision")
    text(proposal["reason"])
    require(isinstance(proposal["evidence_quote"], str), "invalid message quote")
    for key in ("cancel_item_ids", "cancel_appointment_ids", "appointments"):
        require(isinstance(proposal[key], list) and len(proposal[key]) <= 12, "too many agenda edits")
    if proposal["decision"] != "revise":
        require(not changes and not any(proposal[k] for k in ("cancel_item_ids", "cancel_appointment_ids", "appointments")),
                "non-revision contains edits")
        return None
    require(proposal["evidence_quote"] and proposal["evidence_quote"] in message["content"], "agenda edit lacks message evidence")
    require(changes or any(proposal[k] for k in ("cancel_item_ids", "cancel_appointment_ids", "appointments")), "empty agenda revision")
    require(not changes or not any(proposal[k] for k in ('appointments', 'cancel_appointment_ids', 'cancel_item_ids')),
            '行程调整与预约修改须分别协商提交，不能混合覆盖')
    if message.get('assistant_replies'):
        require(changes and not any(proposal[k] for k in ('appointments', 'cancel_appointment_ids', 'cancel_item_ids')),
                'chat reply review only permits personal itinerary changes')
    rules = deepcopy(body.get("user_constraints", {"cancelled": [], "appointments": []}))
    if changes:
        from .itinerary_updates import validate
        rules.setdefault('itinerary', []).extend(validate(changes, body, state, config, now, message))
    items = {i["id"]: i for i in body["items"]}
    for ident in proposal["cancel_item_ids"]:
        require(isinstance(ident, str) and ident in items, "unknown agenda item")
        item = items[ident]
        require(utc(item["end_at"]) > now and not protected(item) and item["kind"] != "commute"
                and not item.get("appointment_id"), "cannot cancel past, protected, travel or appointment item")
        key = signature(item)
        require(any(key), "item has no stable source; replace its time with an appointment")
        cancellation = {"source": key, "from": max(now, utc(item["start_at"])).isoformat(),
                        "until": item["end_at"]}
        if cancellation not in rules["cancelled"]:
            rules["cancelled"].append(cancellation)
    existing = {a["id"]: a for a in rules["appointments"]}
    for ident in proposal["cancel_appointment_ids"]:
        require(isinstance(ident, str) and ident in existing and utc(existing[ident]["end_at"]) > now,
                "unknown or past appointment")
        rules["appointments"] = [a for a in rules["appointments"] if a["id"] != ident]
    from .coarse_plan import _at, schedule_day
    from .appointments import display_title
    for index, appointment in enumerate(proposal["appointments"]):
        require(isinstance(appointment, dict) and {'title', 'start_at', 'duration_seconds'} <= appointment.keys()
                <= {'title', 'start_at', 'duration_seconds', 'place_id'}, 'invalid appointment fields')
        text(appointment["title"])
        require(len(appointment["title"]) <= 160, "appointment title too long")
        seconds = appointment["duration_seconds"]
        require(type(seconds) is int and 60 <= seconds <= 14400, "invalid appointment duration")
        if appointment['start_at'] is None and message.get('received_at'):
            require(schedule_day(utc(message['received_at'])) == schedule_day(now),
                    'stale immediate request requires clarification; do not move it to today')
        start = now if appointment["start_at"] is None else utc(appointment["start_at"])
        finish = start + timedelta(seconds=seconds)
        end = _at(schedule_day(start) + timedelta(days=1), "04:00")
        require(now <= start < finish <= end, "appointment must be future and fit its target living day")
        rules["appointments"].append({"id": "appointment:" + digest([message["id"], index])[:24],
            "title": display_title(appointment['title']), "start_at": start.isoformat(), "end_at": finish.isoformat(),
            "place": None, "location_policy": "unspecified", "source_message": message["id"], "evidence_quote": proposal["evidence_quote"],
            "semantics": "zuoran_plan_not_user_presence_or_activity_result"})
    appointments = sorted(rules["appointments"], key=lambda x: utc(x["start_at"]))
    for a, b in zip(appointments, appointments[1:]):
        require(utc(a["end_at"]) <= utc(b["start_at"]), "appointments overlap")
    rules["appointments"] = appointments
    return rules


def reflow(body, rules, state, config, now):
    """Keep past intentions verbatim; overlay reservations on future soft blocks.

    Only plan rows change. Movement is rebuilt from the actual location. Hard
    routines keep their duration and may move later within their valid window.
    A conflict rejects the entire proposal, rather than partially applying it.
    """
    from .coarse_plan import _route, _at, schedule_day, LOCAL
    from .coarse_plan_schema import site_id
    original_body = body
    if rules.get('itinerary'):
        from .itinerary_updates import apply
        body = apply(body, rules['itinerary'], state, config, now)
    day = schedule_day(now)
    end = _at(day + timedelta(days=1), "04:00")
    slots = [{**a, "place": None, "start": max(now, utc(a["start_at"])), "end": utc(a["end_at"])}
             for a in rules["appointments"] if utc(a["end_at"]) > now]
    # A past agenda interval does not discharge an overdue real obligation.
    # Reserve enough time for outstanding meals even if their old plan rows
    # have elapsed, so a new "chat now" slot cannot bypass the eating guard.
    if slots:
        from .daily_obligations import status as routine_status, descendant
        obligations = routine_status(config, state, now, lambda _: body["calendar"])
        available, origin = now, state["place"]
        for obligation in obligations:
            if obligation["kind"] != "meal" or obligation["status"] not in {"due", "overdue"}:
                continue
            resource = state.get("meals", {}).get(obligation["id"], {})
            destination = resource.get("place") or ("firm.office" if descendant(config, origin, "firm")
                else config["household_world"]["dining_place"])
            _, seconds = _route(config, origin, destination)
            units = resource.get("remaining", config["daily_routines"]["meal_units"][obligation["meal"]])
            seconds += math.ceil(units/config["household_world"]["portion_per_checkpoint"]) * config["checkpoint_seconds"]
            available += timedelta(seconds=seconds)
            origin = destination
        require(all(a["start"] >= available for a in slots), "required meal must finish before this reserved time")
    blocks = []
    def travel_between(origin, destination):
        # User time has no physical destination. It must not create a route
        # requirement or pretend that the actor arrived anywhere.
        if origin is None or destination is None or site_id(origin) == site_id(destination):
            return 0
        return _route(config, origin, destination)[1]

    hard_end, hard_place = None, None
    done = {a["target"] for a in state["activities"].values()
            if a["status"] == "completed" and a["kind"] in {"eating", "showering"}}
    for item in body["items"]:
        if item["kind"] == "commute" or item.get("appointment_id") or utc(item["end_at"]) <= now:
            continue
        if item.get("reference_id") in done:
            continue
        start, finish = max(now, utc(item["start_at"])), utc(item["end_at"])
        if protected(item):
            seconds = (finish-start).total_seconds()
            if hard_end is not None:
                _, passage = _route(config, hard_place, item["place"])
                if site_id(hard_place)==site_id(item["place"]): passage=0
                start = max(start, hard_end + timedelta(seconds=passage))
            if item["kind"] == "shower":
                start = max(start, _at(day, "18:00"),
                            _at(day, config["daily_routines"]["shower"]["available_after"]))
                seconds = max(seconds, config["daily_routines"]["shower"]["duration_seconds"])
            if item["kind"] == "meal":
                units = state.get("meals", {}).get(item.get("reference_id"), {}).get("remaining",
                    config["daily_routines"]["meal_units"][item["activity"]])
                seconds = max(seconds, math.ceil(units/config["household_world"]["portion_per_checkpoint"])
                              * config["checkpoint_seconds"])
            if item.get("activity") not in {"await_goodnight", "bedtime_preparation"}:
                for slot in slots:
                    onward = travel_between(item['place'], slot['place'])
                    if start < slot["end"] and start + timedelta(seconds=seconds + onward) > slot["start"]:
                        back = travel_between(slot['place'], item['place'])
                        start = slot["end"] + timedelta(seconds=back)
                finish = start + timedelta(seconds=seconds)
            else:
                start = max([start] + [a["end"] for a in slots])
                finish = end
            blocks.append({"item": deepcopy(item), "start": start, "end": finish, "hard": True})
            hard_end, hard_place = finish, item["place"]
        else:
            fragments = [(start, finish)]
            cancellations = [{"start": utc(c["from"]), "end": utc(c["until"])}
                             for c in rules["cancelled"] if c["source"] == signature(item)]
            for slot in slots + cancellations:
                pieces = []
                for left, right in fragments:
                    if slot["end"] <= left or slot["start"] >= right:
                        pieces.append((left, right))
                    else:
                        if left < slot["start"]: pieces.append((left, slot["start"]))
                        if slot["end"] < right: pieces.append((slot["end"], right))
                fragments = pieces
            blocks.extend({"item": deepcopy(item), "start": left, "end": right, "hard": False,
                           "fixed": bool(item.get('itinerary_fixed'))}
                          for left, right in fragments)
    for slot in slots:
        from .appointments import display_title
        title = display_title(slot['title'])
        blocks.append({"item": {"kind": "interaction", "title": title, "intent": title, "activity": "user_time",
            "place": None, "location_policy": "unspecified", "execution": "reserved_user_time", "appointment_id": slot["id"],
            "source_message": slot["source_message"], "semantics": "planned_not_observed"},
            "start": slot["start"], "end": slot["end"], "hard": False, "fixed": True})
    blocks.sort(key=lambda b: (b["start"], not b.get("fixed"), not b["hard"]))
    cursor, place, output = now, state["place"], []

    def append(item, finish):
        nonlocal cursor
        if finish <= cursor: return
        require(finish <= end, "revised activity exceeds living day")
        output.append({**item, "start_at": cursor.astimezone(LOCAL).isoformat(),
                       "end_at": finish.astimezone(LOCAL).isoformat(),
                       "place_name": config["places"][item["place"]]["name"] if item.get('place') else '',
                       "semantics": "planned_not_observed"})
        cursor = finish

    def move(destination):
        nonlocal place
        path, seconds = _route(config, place, destination)
        if site_id(place)==site_id(destination):
            place=destination
            return
        if seconds:
            append({"kind": "commute", "title": "前往" + config["places"][destination]["name"],
                    "place": place, "destination": destination, "destination_name": config["places"][destination]["name"],
                    "route": path, "purpose": "user_adjusted_agenda"}, cursor + timedelta(seconds=seconds))
        place = destination

    for index, block in enumerate(blocks):
        item = block["item"]
        travel = travel_between(place, item['place'])
        start = max(cursor + timedelta(seconds=travel), block["start"])
        finish = block["end"]
        if block.get("fixed"):
            require(start <= block["start"], "cannot reach appointment on time")
        elif block["hard"] and item.get("activity") not in {"await_goodnight", "bedtime_preparation"}:
            finish = start + (block["end"]-block["start"])
            if item["kind"] == "meal":
                meal = item["activity"]
                windows = config["daily_routines"]["meal_windows"][body["calendar"]["day_type"]]
                latest_start = _at(day, windows[meal][1])
                # Do not worsen an already overdue source plan.
                require(start <= max(latest_start, utc(item["start_at"]), now), "revision would delay a required meal beyond its window")
        else:
            following = next((b for b in blocks[index+1:] if b.get("fixed") or b["hard"]), None)
            if following:
                onward = travel_between(item['place'], following['item']['place'])
                finish = min(finish, following["start"]-timedelta(seconds=onward))
            if start >= finish: continue
        if block["hard"] and item.get("activity") not in {"await_goodnight", "bedtime_preparation"}:
            for slot in slots:
                require(finish <= slot["start"] or start >= slot["end"], "required activity conflicts with appointment")
        # Fill only actual gaps; avoid parking for hours in a service room.
        service = {config["household_world"]["dining_place"], config["daily_routines"]["shower"]["place"]}
        if item.get('place') and start - cursor > timedelta(minutes=15) and place in service and "home.f1.living" in config["places"]:
            _, out = _route(config, place, "home.f1.living")
            _, onward = _route(config, "home.f1.living", item["place"])
            if cursor + timedelta(seconds=out+onward+600) <= start:
                move("home.f1.living")
                travel = onward
        if start - timedelta(seconds=travel) > cursor:
            cursor=start-timedelta(seconds=travel)
        if item.get('place'):
            move(item["place"])
        append(item, finish)
    require(output, "revision left no remaining plan")
    revised = deepcopy(body)
    past = [deepcopy(x) for x in original_body["items"] if utc(x["end_at"]) <= now]
    for x in original_body["items"]:
        if utc(x["start_at"]) < now < utc(x["end_at"]):
            past.append({**deepcopy(x), "end_at": now.astimezone(LOCAL).isoformat(), "preserved_elapsed_intention": True})
    revised.update(items=output, past_items=body.get("past_items", [])+past,
                   user_constraints=deepcopy(rules))
    return revised


def process_pending(agenda, *, proposal=None, message_id=None, expected_revision=None):
    """One durable bounded review per pump, outside the chat response path."""
    now = agenda.p.clock.now()
    with agenda.store.connect() as db:
        row = db.execute("SELECT message_id,status,attempts,retry_at FROM life_agenda_messages WHERE status IN ('pending','running') ORDER BY rowid LIMIT 1").fetchone()
        if not row or (proposal is None and row[3] and utc(row[3]) > now): return False
        if message_id is not None:
            require(row[0] == message_id, 'another message precedes this request')
        message_id, _, attempts, _ = row
        if attempts >= 3:
            db.execute("UPDATE life_agenda_messages SET status='needs_review' WHERE message_id=?", (message_id,))
            return True
        request, receipt = db.execute("SELECT request,receipt FROM life_received_messages WHERE id=?", (message_id,)).fetchone()
        request = json.loads(request)
        message = {"id": message_id, **request,
                   "received_at": request.get('received_at') or json.loads(receipt)["occurred_at"]}
        recent = [{"id": i, "content": json.loads(r)["content"]} for i, r in db.execute(
            "SELECT id,request FROM life_received_messages WHERE rowid <= (SELECT rowid FROM life_received_messages WHERE id=?) ORDER BY rowid DESC LIMIT 8", (message_id,))][::-1]
    body = agenda.read()
    state = agenda.p.snapshot()
    if body is None or state.get("sleep", {}).get("status") != "awake": return False
    if expected_revision is not None:
        require(body['revision'] == expected_revision, 'agenda changed; read it again')
    from .appointments import upcoming, for_day, save, validate_future
    with agenda.store.connect() as db:
        appointments_before = upcoming(db, now)
    validation_body = deepcopy(body)
    validation_body.setdefault('user_constraints', {'cancelled': [], 'appointments': []})['appointments'] = appointments_before
    attempts += 1
    with agenda.store.connect() as db:
        db.execute("UPDATE life_agenda_messages SET status='running',attempts=? WHERE message_id=?", (attempts, message_id))
    payload = {"message": message, "recent_messages": recent, "now": now.isoformat(),
        "local_now": now.astimezone(ZoneInfo('Asia/Shanghai')).isoformat(),
        "persona": agenda.cog.persona, "actual_place": state["place"], "daily_agenda": body,
        "appointment_location_policy": "unspecified; no place or route required", "upcoming_appointments": appointments_before,
        "itinerary_places": {k:v['name'] for k,v in agenda.p.config['places'].items()},
        "protected_item_ids": [x["id"] for x in body["items"] if protected(x)],
        "prior_review": latest(agenda), "semantics": "received messages and plans; no assumed user actions"}
    from .daily_obligations import status as routine_status
    payload["daily_obligations"] = routine_status(agenda.p.config, state, now, agenda.cog.calendar_provider)
    payload["actual_activity"] = state["activities"].get(state.get("active"))
    payload["unfinished_activities"] = [a for a in state["activities"].values() if a["status"] in {"running", "interrupted"}]
    payload["confirmed_commitments"] = [c for c in state.get("commitments", []) if c["status"] == "confirmed"]
    try:
        if proposal is None:
            proposal = agenda.cog.calls.ask(f"agenda-reaction:{message_id}:{attempts}", "agenda_reaction", payload)
        # Re-read the clock: model latency cannot authorize edits to the past.
        now = agenda.p.clock.now()
        rules = validate_proposal(proposal, message, validation_body, state, agenda.p.config, now)
        from .coarse_plan import schedule_day
        revised = None
        if rules is not None:
            new_ids = {a['id'] for a in rules['appointments']} - {a['id'] for a in appointments_before}
            validate_future(agenda, rules, now, state, new_ids)
            today_rules = for_day(rules, schedule_day(now))
            before_rules = for_day(validation_body['user_constraints'], schedule_day(now))
            if today_rules != before_rules:
                revised = reflow(body, today_rules, state, agenda.p.config, now)
                from .itinerary_updates import check_result
                check_result(revised, today_rules.get('itinerary', [])[len(before_rules.get('itinerary', [])):], now)
        with agenda.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current_request = db.execute('SELECT request FROM life_received_messages WHERE id=?', (message_id,)).fetchone()
            if current_request and json.loads(current_request[0]) != request:
                raise Conflict('chat reply arrived during message interpretation')
            if agenda._read(db, body["date"]) != body or agenda.store.read(db)["revision"] != state["revision"]:
                raise Conflict("agenda or actual state changed during message interpretation")
            if upcoming(db, utc(payload['now'])) != appointments_before:
                raise Conflict('appointments changed during message interpretation')
            from .coarse_plan import schedule_day
            require(str(schedule_day(now)) == body["date"], "living day changed during interpretation")
            result = {"decision": proposal["decision"], "reason": proposal["reason"], "proposal": proposal,
                      "source_message": message_id, "at": now.isoformat(), "prior_revision": body["revision"]}
            status = "applied" if rules is not None else proposal["decision"]
            if rules is not None:
                save(db, appointments_before, rules['appointments'])
                result['upcoming_appointments'] = rules['appointments']
                result['schedule_changed'] = True
            if revised is not None:
                revision = body["revision"]+1
                revised.update(revision=revision, change_reason="user_message", source_message=message_id,
                               generated_at=now.isoformat(), evidence_id=f"agenda:{body['date']}:r{revision}")
                for index, item in enumerate(revised["items"]):
                    item["id"] = f"agenda:{body['date']}:r{revision}:{index}"
                from .coarse_plan_schema import pack
                db.execute("INSERT INTO life_daily_agendas VALUES(?,?,?)", (body["date"], revision, canonical(pack(revised))))
                result["revision"] = revision
            db.execute("UPDATE life_agenda_messages SET status=?,receipt=?,retry_at=NULL WHERE message_id=?",
                       (status, canonical(result), message_id))
    except Exception as error:
        terminal = attempts >= 3
        clarify_itinerary = bool(proposal and proposal.get('itinerary_changes') and
                                 isinstance(error, ValueError) and not isinstance(error, Conflict))
        with agenda.store.connect() as db:
            db.execute("UPDATE life_agenda_messages SET status=?,receipt=?,retry_at=? WHERE message_id=?",
                ('clarify' if clarify_itinerary else "needs_review" if terminal else "pending", canonical({"type": type(error).__name__,
                 "reason": str(error), 'at': now.isoformat(), 'proposal': proposal, "schedule_changed": False}),
                 None if clarify_itinerary else (now+timedelta(seconds=30)).isoformat(), message_id))
    return True
