"""State-based grading; no exact tool-order matching or model self-scoring."""
from datetime import datetime
import math


def same_time(a, b):
    if a is None or b is None:
        return a is b
    return datetime.fromisoformat(a) == datetime.fromisoformat(b)


def business(snapshot):
    return {'agenda': snapshot['agenda'], 'companionships': snapshot['state'].get('companionships', [])}


def grade_turn(expected, before, after, review, context):
    checks = {}
    statuses = expected['status'] if isinstance(expected['status'], list) else [expected['status']]
    checks['terminal_outcome'] = review.get('status') in statuses
    sessions = [s for s in after['state'].get('companionships', []) if s['status'] != 'ended']
    items = after['agenda']['items']
    if expected.get('unchanged'):
        checks['no_unrequested_write'] = business(before) == business(after)
    if expected.get('no_companion'):
        checks['no_unrequested_companion'] = not sessions
    if 'companion' in expected:
        target = expected['companion']
        checks['exactly_one_companion'] = len(sessions) == 1
        checks['companion_fields'] = len(sessions) == 1 and all(
            same_time(sessions[0].get(k), v) if k.endswith('_at') else sessions[0].get(k) == v
            for k, v in target.items())
    if 'item' in expected:
        target = expected['item']
        matches = [i for i in items if all(
            same_time(i.get(k), v) if k.endswith('_at') else i.get(k) == v for k, v in target.items())]
        checks['requested_item_exactly_once'] = len(matches) == 1
    if 'absent_activity' in expected:
        checks['cancelled_activity_absent'] = not any(i.get('activity') == expected['absent_activity'] for i in items)
    if 'absent_intent' in expected:
        checks['cancelled_intent_absent'] = not any(i.get('intent') == expected['absent_intent'] for i in items)
    if expected.get('preserve_required'):
        def required(rows):
            return {(i['kind'], i.get('activity')): (datetime.fromisoformat(i['end_at']) -
                    datetime.fromisoformat(i['start_at'])).total_seconds()
                    for i in rows if i['kind'] in {'meal', 'shower', 'bedtime'}}
        old, new = required(before['agenda']['items']), required(items)
        checks['required_activities_retained'] = all(k in new and (k[0] == 'bedtime' or new[k] >= duration)
                                                   for k, duration in old.items())
    # This is a context projection check, NOT a natural-language reply check.
    projected = context.get('daily_agenda_review')
    checks['receipt_projection_consistent'] = (review['status'] == 'host_ended' or
        bool(projected and projected['message_id'] == review.get('message_id') and projected['status'] == review['status']))
    if review.get('status') in {'applied', 'clarify'}:
        message_id = review.get('message_id')
        checks['outbox_contains_correlated_result'] = any(
            e.get('id') == 'companion-message:' + str(message_id) or
            e.get('detail', {}).get('source_message') == message_id
            for e in after.get('outbox', []))
    return {'passed': all(checks.values()), 'checks': checks,
            'failed_checks': [key for key, value in checks.items() if not value]}


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)]


def summarize(results, planned):
    evaluated = [r for r in results if r.get('execution_status') == 'evaluated']
    passed = sum(bool(r.get('passed')) for r in results)
    by_category = {}
    for r in results:
        bucket = by_category.setdefault(r['category'], {'runs': 0, 'passed': 0, 'errors': 0})
        bucket['runs'] += 1
        bucket['passed'] += bool(r.get('passed'))
        bucket['errors'] += r.get('execution_status') not in {'evaluated', 'prepared'}
    ids = {r['case_id'] for r in results}
    stable = sum(sum(r['case_id'] == ident for r in results) == planned['repeats'] and
                 all(r.get('passed', False) for r in results if r['case_id'] == ident) for ident in ids)
    no_write = [t for r in evaluated for t in r.get('turns', []) if t['expected'].get('unchanged')]
    durations = [r['duration_seconds'] for r in evaluated]
    return {'planned_runs': planned['runs'], 'finished_runs': len(results), 'passed_runs': passed,
            'success_rate': passed / len(results) if evaluated and all(r['execution_status'] != 'prepared' for r in results) else None,
            'all_repeats_passed_cases': stable, 'planned_cases': planned['cases'],
            'by_category': by_category, 'no_write_turns': len(no_write),
            'wrong_write_turns': sum(not t['grade']['checks']['no_unrequested_write'] for t in no_write),
            'latency_p50_seconds': percentile(durations, .50), 'latency_p95_seconds': percentile(durations, .95),
            'latency_scope': 'whole scenario, including all turns and agent settling; excludes process startup',
            'false_success_reply_rate': None, 'reply_evaluation': 'not_measured: production chat generation excluded',
            'mean_model_calls': sum(r.get('model_calls', 0) for r in evaluated) / len(evaluated) if evaluated else None}
