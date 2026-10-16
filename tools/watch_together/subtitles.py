"""Parse SRT/WebVTT locally; the full subtitle file never reaches Libra."""
import html
import re


def timestamp(value):
    match = re.fullmatch(r'(?:(\d{1,3}):)?(\d{2}):(\d{2})[.,](\d{3})', value)
    if not match:
        raise ValueError('字幕时间格式无效')
    hours, minutes, seconds, millis = match.groups()
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise ValueError('字幕时间超出范围')
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_subtitles(content):
    if not isinstance(content, str) or len(content) > 500_000:
        raise ValueError('字幕文件过大')
    content = content.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    for block in re.split(r'\n\s*\n', content.strip()):
        lines = block.splitlines()
        if not lines or lines[0].startswith(('NOTE', 'STYLE', 'REGION')):
            continue
        for index, line in enumerate(lines):
            if '-->' not in line:
                continue
            match = re.fullmatch(r'\s*(\S+)\s+-->\s+(\S+)(?:\s+.*)?', line)
            if not match:
                raise ValueError('字幕时间行无效')
            start, end = map(timestamp, match.groups())
            if end <= start:
                raise ValueError('字幕结束时间必须晚于开始时间')
            text = html.unescape(re.sub(r'<[^>]*>|\{\\[^}]*\}', '', '\n'.join(lines[index + 1:])))
            text = text.strip()
            if text:
                cues.append({'start': start, 'end': end, 'text': text[:2000]})
            break
    if not cues or len(cues) > 10000:
        raise ValueError('未找到有效字幕，或字幕条数超过10000')
    return sorted(cues, key=lambda cue: (cue['start'], cue['end']))
