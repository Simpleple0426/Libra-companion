"""Read-only need assessment for scheduled check-ins; never emits events."""
from __future__ import annotations

import json
import math
from pathlib import Path

THRESHOLDS = json.loads((Path(__file__).resolve().parents[2] / 'config' / 'need_contact.json').read_text(encoding='utf-8'))['thresholds']


def detect_trigger(previous: dict | None, state: dict) -> dict | None:
    """Pick the largest normalized threshold excess, regardless of prior reviews."""
    candidates = []
    for key, threshold in THRESHOLDS.items():
        item = (state.get('needs') or {}).get(key) or {}
        value = item.get('value')
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 or value <= threshold:
            continue
        candidates.append({'dominant_need': key, 'need_value': value,
                           'need_threshold': threshold,
                           'need_strength': (value-threshold)/(1-threshold)})
    return max(candidates, key=lambda item: item['need_strength'], default=None)


def checkin_assessment(state: dict, snapshot: dict) -> dict:
    needs = {}
    for key, threshold in THRESHOLDS.items():
        value = (state.get('needs', {}).get(key) or {}).get('value')
        valid = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
        needs[key] = {'value': value if valid else None, 'threshold': threshold,
                      'above_threshold': bool(valid and value > threshold),
                      'excess_strength': max(0, (value - threshold) / (1 - threshold)) if valid else 0}
    return {'needs': needs, 'fatigue': snapshot.get('libra', {}).get('fatigue'),
            'fatigue_scale': '0..1; missing or unknown is not zero',
            'mood': dict(state.get('mood', {})),
            'emotions': dict(state.get('aggregated_emotions', {}))}
