"""Build the reviewed household catalog from the explicit document space tree.

Developer utility only; runtime loads the checked-in JSON, not changing prose.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'docs/character/左然家庭空间与物品清单.md'
OUTPUT = ROOT / 'backend/life_prototype/home_catalog.json'
ROOMS = {
    ('一层', '玄关'): 'home.f1.entry', ('一层', '客厅'): 'home.f1.living',
    ('一层', '厨房'): 'home.f1.kitchen', ('一层', '餐厅'): 'home.f1.dining',
    ('一层', '卫生间'): 'home.f1.bathroom', ('一层', '阳台'): 'home.f1.balcony',
    ('二层', '卧室'): 'home.f2.bedroom', ('二层', '梳妆区'): 'home.f2.vanity',
    ('二层', '影音区'): 'home.f2.media', ('二层', '衣帽间'): 'home.f2.dressing',
    ('二层', '卫生间'): 'home.f2.bathroom', ('二层', '书房'): 'home.f2.study',
}


def build():
    document = SOURCE.read_text(encoding='utf8')
    tree = document.split('```text\n', 1)[1].split('```', 1)[0]
    places = {'home': {'name': '家', 'parent': None},
              'home.f1': {'name': '一层', 'parent': 'home'},
              'home.f2': {'name': '二层', 'parent': 'home'},
              'home.stairs': {'name': '楼梯', 'parent': 'home'}}
    for (floor, name), ident in ROOMS.items():
        places[ident] = {'name': floor + name if name == '卫生间' else name,
                         'parent': 'home.f1' if floor == '一层' else 'home.f2'}
    objects, lines = {}, []
    floor, room = None, 'home'

    def add(name, source_line, container=None, **extra):
        ident = room + '.object.' + hashlib.sha256(name.encode()).hexdigest()[:12]
        if ident in objects:
            raise ValueError('Duplicate household identity: ' + ident)
        objects[ident] = {'name': name, 'parent': room, 'source_line': source_line,
                          'container_id': container, 'quantity': None,
                          'dynamic_state': {'power': None, 'cleanliness': None, 'in_use': None},
                          **extra}
        return ident

    for raw in tree.splitlines():
        if not re.search('[├└]─ ', raw):
            continue
        text = re.split('[├└]─ ', raw, maxsplit=1)[1].strip()
        if text in ('一层', '二层'):
            floor = text
            continue
        if (floor, text) in ROOMS:
            room = ROOMS[(floor, text)]
            continue
        if text.startswith('楼梯：'):
            room = 'home.stairs'
            continue
        if text == '家庭网络':
            room = 'home'
            continue
        lines.append(text)
        if text.startswith('Wi-Fi：'):
            add('家庭 Wi-Fi', text, ssid='律狮的专属频道', coverage=['home.f1', 'home.f2'],
                connection_rule='device_wifi_enabled_and_network_available_then_auto_connect; disconnect_outside_coverage',
                availability=None, kind='network')
            continue
        clean = re.sub(r'（[^）]*）', '', text)
        head, sep, children = clean.partition('：')
        container = add(head, text, kind='group' if head in {'个人物品', '纪念物品', '清洁用品', '调料收纳'} else 'fixture') if sep else None
        for name in (children if sep else head).split('、'):
            add(name.strip(), text, container)

    def named(name):
        return next(obj for obj in objects.values() if obj['name'] == name)

    named('小熊公仔').update(owner='user', background={
        'provenance': 'user_provided_setting', 'origin': '左然送给用户的生日礼物',
        'interaction': '触碰右手开关播放预先录入的声音', 'known_recording': '左然录制的摇篮曲',
        'unknown': ['赠送日期', '具体生日场景', '完整录音列表', '曲名', '录音内容'],
        'boundary': '播放录音不是左然现场唱歌，不生成台词'})
    named('大雁戒托').update(background={
        'provenance': 'user_provided_setting', 'purpose': '用于放置用户与左然的婚戒',
        'relationship': '婚姻关系', 'current_contents': None,
        'unknown': ['购买或赠送经过', '婚礼日期'], 'boundary': '不表示婚戒当前在戒托上'})
    named('红豆项链').update(owner='user', worn=None, background={
        'provenance': 'user_provided_setting', 'origin': '左然告白时送给用户的礼物',
        'associated_poem': '玲珑骰子安红豆，入骨相思知不知',
        'unknown': ['告白日期', '地点', '完整对话', '项链具体造型'],
        'boundary': '诗句不等于刻字或当时逐字台词'})
    named('跑步机')['placement'] = '客厅右侧靠窗、接近阳台，避开通行路线'
    named('路由器')['placement'] = '客厅电视柜处；清单建议位置'
    named('充电座')['placement'] = '客厅角落；清单建议位置'
    named('扫地机器人').update(cleaning_scope=None, activation_method=None, movable=True)
    for name in ('书籍', '工作资料', '家庭文件'):
        named(name).update(kind='collection', content=None, progress=None)
    room = 'home'
    for name, owner in [('左然的婚戒', 'zuoran'), ('用户的婚戒', 'user')]:
        add(name, '纪念物品背景：两人的婚戒；当前佩戴或存放状态未知', owner=owner,
            location_status='unknown; parent is catalog scope only', worn=None)
    add('手机', '家庭网络连接规则：手机保存家庭网络并开启自动连接',
        location_status='unknown; parent is catalog scope only', owner=None,
        network_preferences={'saved_ssid': '律狮的专属频道', 'auto_connect': True},
        current_connection=None)
    edges = [[ident, value['parent']] for ident, value in places.items()
             if ident not in {'home', 'home.f1', 'home.f2', 'home.stairs', 'home.f1.balcony', 'home.f2.vanity'}]
    edges += [['home.f1.living', 'home.f1.balcony'], ['home.f2.bedroom', 'home.f2.vanity'],
              ['home.f1', 'home.stairs'], ['home.stairs', 'home.f2']]
    return {'version': 'confirmed-household-catalog-v1',
            'source_document': str(SOURCE.relative_to(ROOT)).replace('\\', '/'),
            'authorization': 'user_requested_all_household_spaces_and_items_2026-09-27',
            'source_tree_sha256': hashlib.sha256(tree.encode()).hexdigest(),
            'covered_tree_lines': lines, 'places': places, 'objects': objects, 'edges': edges,
            'boundary': 'Configuration only; unknown quantities, device states and contents are not fabricated. No events or memories are generated.'}


if __name__ == '__main__':
    catalog = build()
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'places': len(catalog['places']), 'objects': len(catalog['objects']),
                      'tree_lines': len(catalog['covered_tree_lines'])}))
