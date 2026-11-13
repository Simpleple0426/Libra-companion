"""Small optional menu pool and evidence-aware recent dining context."""
from datetime import timedelta, timezone

from .clock import utc

MENU_POOL = {
    'breakfast_combinations': [
        ['鸡蛋三明治', '牛奶'], ['南瓜粥', '香菇包'], ['鲜肉馄饨'],
        ['酸奶水果燕麦'], ['番茄鸡蛋面'], ['小米粥', '蒸饺'],
        ['全麦吐司', '煎蛋', '豆浆'], ['葱花鸡蛋饼', '牛奶'],
        ['玉米', '水煮蛋', '酸奶'], ['芝士可颂', '咖啡'],
    ],
    'main_dishes': [
        '糖醋排骨', '香菇滑鸡', '清蒸鲈鱼', '番茄炖牛腩', '虾仁滑蛋',
        '照烧鸡腿', '土豆炖牛肉', '葱烧豆腐', '香煎三文鱼', '肉末蒸蛋',
        '冬瓜肉丸', '山药炖鸡',
    ],
    'vegetables': [
        '清炒上海青', '手撕包菜（不放辣椒）', '香菇油菜', '蚝油生菜',
        '清炒芦笋', '蒸南瓜', '荷塘小炒', '番茄炒蛋', '清炒丝瓜',
        '蒜香菠菜', '醋溜土豆丝（不放辣椒）', '清炒西葫芦',
    ],
    'staples': ['米饭', '杂粮饭', '香菇鸡肉焖饭', '番茄意面', '鸡丝面', '蔬菜炒饭', '红薯'],
    'soups': ['冬瓜汤', '菌菇汤', '紫菜蛋花汤', '莲藕排骨汤', '玉米胡萝卜汤', '番茄豆腐汤'],
    'occasional_desserts': ['酒酿圆子', '银耳羹', '牛奶布丁', '桂花藕粉', '红豆汤', '酸奶水果杯'],
}

INGREDIENT_ALIASES = {
    '西兰花': ('西兰花', '西蓝花'), '鸡肉': ('鸡肉', '鸡腿', '鸡胸', '鸡丝', '滑鸡', '炖鸡'),
    '牛肉': ('牛肉', '牛腩', '牛排'), '排骨': ('排骨',), '虾': ('虾',),
    '鱼': ('鲈鱼', '鳕鱼', '三文鱼', '鲫鱼'), '鸡蛋': ('鸡蛋', '煎蛋', '水煮蛋', '滑蛋', '蒸蛋'),
    '上海青/油菜': ('上海青', '油菜', '小青菜'), '生菜': ('生菜',), '包菜': ('包菜', '圆白菜'),
    '芦笋': ('芦笋',), '南瓜': ('南瓜',), '菠菜': ('菠菜',), '丝瓜': ('丝瓜',),
    '西葫芦': ('西葫芦',), '土豆': ('土豆',), '豆腐': ('豆腐',),
    '莲藕': ('莲藕', '藕片'), '燕麦': ('燕麦',),
}


def ingredients(dishes):
    text = '、'.join(dishes)
    return [name for name, aliases in INGREDIENT_ALIASES.items() if any(x in text for x in aliases)]


def recent_meals(state, now):
    """Meals eaten in seven days, plus today's committed plans, never fake completion."""
    now = utc(now)
    cutoff = now - timedelta(days=7)
    local_today = now.astimezone(timezone(timedelta(hours=8))).date()
    result = []
    for ref, plan in state.get('meal_plans', {}).items():
        eaten = plan.get('eaten_at') or plan.get('completed_at')
        stamp = eaten or plan.get('created_at')
        if not stamp:
            continue
        try:
            at = utc(stamp)
        except (ValueError, TypeError):
            continue
        if not cutoff <= at <= now:
            continue
        if not eaten and at.astimezone(timezone(timedelta(hours=8))).date() != local_today:
            continue
        result.append({
            'id': ref, 'at': at.isoformat(), 'dishes': plan.get('dishes', []),
            'ingredients': ingredients(plan.get('dishes', [])),
            'mode': plan.get('mode'), 'place_name': plan.get('place_name'),
            'status': 'eaten' if eaten else 'planned_not_eaten',
        })
    return sorted(result, key=lambda row: row['at'])[-24:]
