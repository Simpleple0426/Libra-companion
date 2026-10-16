"""Audited additive isolated configuration, never production migration."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from .config import canonical, digest, validate
from .activity_engine import require


def effective(store):
    with store.connect() as db:
        db.execute('SELECT 1')
        row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'work_extension\') AS work_extension').fetchone()
    if not row: return store.config
    extension = json.loads(row[0])
    require(extension["base_config_hash"] == digest(store.config), "extension base config mismatch")
    validate(extension["config"])
    return extension["config"]


def historical(p, rules_hash):
    for config in (p.config, p.store.config):
        if digest(config) == rules_hash:
            return SimpleNamespace(config=config, _resources=p._resources)
    with p.store.connect() as db:
        exists = db.execute("SELECT 1 FROM life_evidence WHERE category='resource_version' LIMIT 1").fetchone()
        row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "hash","body" AS "body" FROM life_evidence WHERE category=\'resource_version\') AS life_resource_versions WHERE hash=?',(rules_hash,)).fetchone() if exists else None
    if row: return SimpleNamespace(config=json.loads(row[0]), _resources=p._resources)
    raise ValueError("unknown historical world rules")






def edge_seconds(config, start, end):
    return config.get("edge_seconds", {}).get("|".join(sorted([start, end])), config["checkpoint_seconds"])


def duration(config, activity):
    if activity and activity.get('work_mode'):return config['checkpoint_seconds']
    if activity and activity.get("duration_seconds"):
        return activity["duration_seconds"]
    if activity and activity["kind"] in {"moving", "serving"}:
        route, n = activity["route"], activity["progress"]
        return edge_seconds(config, route[n], route[n+1])
    if activity and activity["kind"] == "work":
        return config["work_items"][activity["target"]]["checkpoint_seconds"]
    return config["checkpoint_seconds"]
