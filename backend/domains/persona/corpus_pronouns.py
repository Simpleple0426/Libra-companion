"""Make the user explicit without rewriting characters' dialogue."""
import re


def normalize_narration(text):
    # Preserve quoted speech, work titles, plurals and lexical uses such as 自我.
    parts = re.split(r'(“[^”]*”|「[^」]*」|《[^》]*》|"[^"\n]*")', text)
    return ''.join(part if i % 2 else re.sub(r'(?<![自忘无故敌])我(?!们)', '用户', part.replace('来自我', '来自用户'))
                   for i, part in enumerate(parts))


def normalize_excerpt(text):
    result = []
    for line in text.split('\n'):
        dialogue = re.match(r'^(\s*(?:\*\*)?)([^：:\n]{1,20})([：:])(.*)$', line)
        if dialogue:
            prefix, speaker, colon, body = dialogue.groups()
            result.append(prefix + ('用户' if speaker == '我' else speaker) + colon + body)
        else:
            result.append(normalize_narration(line))
    return '\n'.join(result)
