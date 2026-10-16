"""Offline control for the default-off local life integration.

Stop the App before rollback. This command never starts the life engine or a
model and never sends a message.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from application.local_life import EnablePolicy, LifeModeControl, activation_preflight
from infrastructure.paths import (
    BACKUP_ROOT, COGNITION_DATABASE_PATH, CONTENT_DATABASE_PATH, DATABASE_PATH, RUNTIME_ROOT,
)


def _get(key, default=""):
    with sqlite3.connect(DATABASE_PATH) as db:
        row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _set(key, value):
    with sqlite3.connect(DATABASE_PATH) as db:
        db.execute("""INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            (key, value, datetime.now(timezone.utc).isoformat()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("status", "preflight", "configure", "provision", "reference-workday", "daily-routines", "enable", "disable", "rollback"))
    parser.add_argument("--backup-id")
    parser.add_argument("--run-id")
    parser.add_argument("--initial-state-version")
    parser.add_argument("--need-rates-version")
    parser.add_argument("--offline-policy-version")
    parser.add_argument("--special-sleep-policy-version")
    parser.add_argument("--reason", default="offline operator request")
    parser.add_argument("--confirm-app-stopped", action="store_true")
    args = parser.parse_args()
    control = LifeModeControl(_get, _set,
        (DATABASE_PATH, CONTENT_DATABASE_PATH, COGNITION_DATABASE_PATH), BACKUP_ROOT)
    if args.operation == "status":
        result = {"mode": _get("life_system_mode", "disabled"),
                  "run_id": _get("life_system_run_id", "") or None,
                  "backup_id": _get("life_system_backup_id", "") or None,
                  "policy": json.loads(_get("life_system_policy", "{}") or "{}")}
    elif args.operation == "preflight":
        try:
            from life_prototype.cli_model import preflight as cli_preflight
            cli_settings = {key: value for key in ("LIBRA_CODEX_COMMAND", "LIBRA_CODEX_HOME", "LIBRA_LLM_MODEL")
                            if (value := os.getenv(key))}
            cli_status = cli_preflight(cli_settings)
        except Exception as error:
            cli_status = {"error": f"{type(error).__name__}: {error}",
                          "credential_contents_read": False, "model_calls": 0}
        result = activation_preflight(_get, RUNTIME_ROOT / "life", BACKUP_ROOT,
                                      cli_status=cli_status)
    elif args.operation == "configure":
        if not args.confirm_app_stopped:
            parser.error("configure requires --confirm-app-stopped")
        required = (args.run_id, args.initial_state_version, args.need_rates_version,
                    args.offline_policy_version, args.special_sleep_policy_version)
        if not all(required):
            parser.error("configure requires run and all four confirmed policy versions")
        result = control.stage_configuration(args.run_id, EnablePolicy(
            args.initial_state_version, args.need_rates_version,
            args.offline_policy_version, args.special_sleep_policy_version))
    elif args.operation == "provision":
        if not args.confirm_app_stopped:
            parser.error("provision requires --confirm-app-stopped")
        required = (args.run_id, args.initial_state_version, args.need_rates_version,
                    args.offline_policy_version, args.special_sleep_policy_version)
        if not all(required):
            parser.error("provision requires run and all four confirmed policy versions")
        result = control.provision(RUNTIME_ROOT / "life", args.run_id, EnablePolicy(
            args.initial_state_version, args.need_rates_version,
            args.offline_policy_version, args.special_sleep_policy_version))
    elif args.operation == "reference-workday":
        if not args.confirm_app_stopped or not args.run_id:
            parser.error("reference-workday requires --confirm-app-stopped and --run-id")
        result = control.add_workday_planning_reference(
            RUNTIME_ROOT / "life", args.run_id, app_stopped=True)
    elif args.operation == "daily-routines":
        if not args.confirm_app_stopped or not args.run_id:
            parser.error("daily-routines requires --confirm-app-stopped and --run-id")
        result = control.add_confirmed_daily_routines(
            RUNTIME_ROOT / "life", args.run_id, app_stopped=True)
    elif args.operation == "enable":
        if not args.confirm_app_stopped:
            parser.error("enable requires --confirm-app-stopped")
        required = (args.backup_id, args.run_id, args.initial_state_version, args.need_rates_version,
                    args.offline_policy_version, args.special_sleep_policy_version)
        if not all(required):
            parser.error("enable requires backup, run and all four confirmed policy versions")
        result = control.enable(args.backup_id, args.run_id, EnablePolicy(
            args.initial_state_version, args.need_rates_version,
            args.offline_policy_version, args.special_sleep_policy_version))
    elif args.operation == "disable":
        result = control.disable(args.reason)
    else:
        if not args.backup_id:
            parser.error("rollback requires --backup-id")
        result = control.rollback(args.backup_id, app_stopped=args.confirm_app_stopped)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
