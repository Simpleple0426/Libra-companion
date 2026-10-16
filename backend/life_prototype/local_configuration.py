"""Confirmed first-run configuration for the local single-user App.

This module creates an empty state anchor, not a synthetic history.  It reuses
the P1-P4 storage and execution contracts while excluding every test fixture,
book, recipe, work item, message and prior activity.
"""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from .clock import RealClock
from .activity_engine import Prototype
from .cognition import Cognition
from .interaction import Interaction
from .scheduler import Scheduler




def configurations(daily_routines_activated_at=None):
    activation = daily_routines_activated_at or "2026-09-25T00:00:00+08:00"
    activation = datetime.fromisoformat(activation).astimezone(ZoneInfo("Asia/Shanghai"))
    source = "docs/左然家庭空间与物品清单.md confirmed space tree"
    world = {
        "schema_version": 1,
        "mode": "local_single_user",
        "display_timezone": "Asia/Shanghai",
        "checkpoint_seconds": 300,
        "max_gap_seconds": 3600,
        "timing_source": "project_adaptation_scheduler_limits; not need-change rates",
        "persona": {
            "id": "zuoran", "version": "confirmed-local-v1", "status": "confirmed",
            "source": "docs/左然生活启动设定.md confirmed character boundary",
            "description": "左然；固定人物设定由 P2 人设文档提供。",
            "boundary": "不生成用户的行动、位置、对话或决定；沉默不表示拒绝或离开。",
        },
        "places": {
            "home": {"name": "家", "parent": None, "status": "confirmed", "source": source},
            "home.f1": {"name": "一层", "parent": "home", "status": "confirmed", "source": source},
            "home.f1.living": {"name": "客厅", "parent": "home.f1", "status": "confirmed",
                               "source": source + "; user-confirmed first-run location"},
            "home.f1.kitchen": {"name": "厨房", "parent": "home.f1", "status": "confirmed", "source": source},
            "home.f1.dining": {"name": "餐厅", "parent": "home.f1", "status": "confirmed", "source": source},
            "home.f2": {"name": "二层", "parent": "home", "status": "confirmed", "source": source},
            "home.f2.study": {"name": "书房", "parent": "home.f2", "status": "confirmed", "source": source},
            "home.f2.bedroom": {"name": "卧室", "parent": "home.f2", "status": "confirmed", "source": source},
            "home.f2.dressing": {"name": "衣帽间", "parent": "home.f2", "status": "confirmed", "source": source},
            "home.stairs": {"name": "楼梯", "parent": "home", "status": "confirmed", "source": source},
            "home.f2.bathroom": {"name": "二层卫生间", "parent": "home.f2", "status": "confirmed", "source": source},
        },
        "objects": {}, "books": {}, "recipes": {},
        "initial": {"source": "user_confirmed", "place": "home.f1.living",
                    "inventory": {}, "available_tools": [], "hunger": 5},
        "unknown": {"user_location": None, "production_book": None,
                    "production_start": None, "commitments": None},
        "not_enabled": ["passive need rates", "offline backfill", "special sleep schedules"],
        "household_world": {"source": "user_confirmed_local_single_user", "rules": "discrete_household_v1",
            "edges": [["home.f1.living", "home.f1"], ["home.f1.kitchen", "home.f1"],
                      ["home.f1.dining", "home.f1"], ["home.f1", "home.stairs"],
                      ["home.stairs", "home.f2"], ["home.f2", "home.f2.bathroom"],
                      ["home.f2", "home.f2.study"], ["home.f2", "home.f2.bedroom"],
                      ["home.f2", "home.f2.dressing"]],
            "connectivity_status": "confirmed_space_tree; 60s edge timing is project adaptation",
            "dining_place": "home.f1.dining", "portion_per_checkpoint": 0.5,
            "step_rule": "one passage or actual routine checkpoint; no offline catchup"},
        "edge_seconds": {"home.f1|home.f1.living": 60, "home.f1|home.f1.kitchen": 60,
            "home.f1|home.f1.dining": 60, "home.f1|home.stairs": 60,
            "home.f2|home.stairs": 60, "home.f2|home.f2.bathroom": 60,
            "home.f2|home.f2.study": 60, "home.f2|home.f2.bedroom": 60,
            "home.f2|home.f2.dressing": 60},
        "daily_routines": {"version": "user-confirmed-daily-routines-v1",
            "source": "user_confirmed_2026-09-24; project adaptation not D2A",
            "effective_from": activation.date().isoformat(),
            "activation_at": activation.isoformat(),
            "activation_policy": "first_day_past_meal_windows_not_backfilled",
            "meal_resource_model": "general_meal_available_at_valid_dining_place; food identity and inventory intentionally abstracted",
            "meal_windows": {
                "workday": {"breakfast": ["07:35", "08:10"], "lunch": ["11:45", "12:30"], "dinner": ["18:00", "20:00"]},
                "rest_day": {"breakfast": ["08:50", "09:45"], "lunch": ["11:45", "12:30"], "dinner": ["18:00", "20:00"]}},
            "meal_units": {"breakfast": 1.0, "lunch": 3.0, "dinner": 3.0},
            "shower": {"available_after": "18:00", "place": "home.f2.bathroom",
                       "duration_seconds": 1200, "deadline": "before_sleep", "flexible_after_home_arrival": True}},
    }
    from .planning_reference import apply_to_world
    world = apply_to_world(world)
    from .home_catalog import apply_to_world as apply_household
    world = apply_household(world)
    cognition = {
        "version": "p2-local-single-user-v1", "source": "user_confirmed_local_single_user",
        "reflection_threshold": 8, "retrieval_count": 8,
        "recency_decay_per_hour": 0.995,
        "retrieval_weights": {"recency": 1, "importance": 1, "relevance": 1},
        "embedding": "lexical_bigram_cosine_local_fallback",
        "plan_horizon_seconds": 14400, "near_window_seconds": 900,
        "reading_chunk_chars": 24, "commitments": [],
        "commitments_source": "user_confirmed_empty_at_first_initialization",
        "production_commitments": [],
    }
    sleep = {
        "version": "p3-local-single-user-v1", "source": "user_confirmed_local_single_user",
        "timezone": "Asia/Shanghai",
        "wake_minutes": {"workday": 420, "swimming": 390, "weekend": 450},
        "wake_source": "docs/左然生活启动设定.md confirmed wake references",
        "wake_jitter_minutes": 0,
        "wake_jitter_source": "project adaptation: exact confirmed reference until configured otherwise",
        "normal_sleep_windows": [], "calendar": {},
        "special_schedule_policy": None, "late_sleep_policy": None,
        "offline_sleep_policy": None,
        "goodnight_recognition": "host_explicit_intent_single_reply_path",
    }
    scheduler = {"source": "project_adaptation_local_single_user", "poll_seconds": 1,
                 "sleep_checkpoint_seconds": 1800, "idle_check_seconds": 900,
                 "max_attempts": 3, "retry_seconds": 5}
    return world, cognition, sleep, scheduler


def provision(root, run_id, model):
    activated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    world, cognition, sleep, scheduler = configurations(activated_at)
    prototype = Prototype(run_id, world, RealClock(), root=root)
    system = Scheduler(Interaction(Cognition(prototype, model, cognition), sleep), scheduler)
    return system
