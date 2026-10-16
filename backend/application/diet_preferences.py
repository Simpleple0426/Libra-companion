"""User-authored dietary preferences; one app-setting record, never inferred."""
import json

KEY = 'user_diet_preferences'
FIELDS = ('likes', 'avoid', 'taste', 'notes')


def normalize(value):
    if not isinstance(value, dict) or set(value)-set(FIELDS):
        raise ValueError('invalid dietary preferences')
    result = {}
    for key in FIELDS:
        text = value.get(key, '')
        if not isinstance(text,str) or len(text)>500:
            raise ValueError('dietary preference text must be at most 500 characters')
        result[key] = text.strip()
    return result


def read(get_setting):
    try: return normalize(json.loads(get_setting(KEY,'{}') or '{}'))
    except (ValueError, TypeError): return normalize({})


def save(value, set_setting):
    value = normalize(value)
    set_setting(KEY,json.dumps(value,ensure_ascii=False))
    return value
