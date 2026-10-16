"""Read user-editable sticker meanings alongside the image files."""
from pathlib import Path


def descriptions(directory: Path) -> dict[str, str]:
    path = directory / '表情包描述.md'
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        cells = [cell.strip().strip('`') for cell in line.strip().strip('|').split('|')]
        if len(cells) == 2 and Path(cells[0]).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
            result[cells[0]] = cells[1]
    return result


def sticker_event(directory: Path, filename: str) -> str:
    name = Path(filename.replace('\\', '/')).name or '表情'
    meaning = descriptions(directory).get(name, '')
    text = f'用户发来一个表情包，名字：{Path(name).stem}'
    if meaning:
        text += f'；含义：{meaning}'
    return text
