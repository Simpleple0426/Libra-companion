"""Repair the identified legacy sticker trace, preserving original diagnostics."""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infrastructure.sqlite.database import get_connection

TURN_ID = 'turn_60edfede8f69322c1b2c85a88621c9b1'
MESSAGE_ID = 6442


def main():
    connection = get_connection()
    try:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT * FROM cognition_turns WHERE turn_id=?', (TURN_ID,)).fetchone()
        if not row:
            raise ValueError('identified trace not found')
        context = json.loads(row['context_json'])
        if context.get('sticker_event_repair'):
            print('Already repaired')
            return
        assert row['source'] == 'user_sticker'
        assert context['unified_event']['event_id'] == 'evt_94cb24b5570c24b60ce9d25bc1647708'
        match = re.search(r'表情含义是：([^。\n]+)。', context['current_event']['content'])
        if not match:
            raise ValueError('cannot recover sticker meaning from original trace')
        message = connection.execute('SELECT * FROM messages WHERE id=?', (MESSAGE_ID,)).fetchone()
        assert message and message['message_type'] == 'sticker' and message['role'] == 'user'
        revisions = connection.execute('SELECT * FROM cognition_context_revisions WHERE turn_id=?', (TURN_ID,)).fetchall()
        backup = Path(__file__).resolve().parents[2] / 'output' / f'sticker_trace_before_repair_{datetime.now():%Y%m%d_%H%M%S}.json'
        backup.write_text(json.dumps({'turn': dict(row), 'revisions': [dict(r) for r in revisions]}, ensure_ascii=False, indent=2), encoding='utf-8')
        meaning = match.group(1)
        def repair(value):
            value['current_event']['content'] = f'[表情：{meaning}]'
            value['current_event']['message_id'] = MESSAGE_ID
            value['current_event']['explicit_boundaries'] = []
            if value.get('unified_event'):
                value['unified_event']['description'] = f'用户发送了一个表情包（表情含义：{meaning}）。'
            value['sticker_event_repair'] = {
                'message_id': MESSAGE_ID, 'reason': 'legacy_prompt_used_as_event_content',
                'repaired_at': datetime.now().isoformat(),
                'historical_reasoning_recomputed': False,
            }
            return json.dumps(value, ensure_ascii=False)
        connection.execute('UPDATE cognition_turns SET context_json=? WHERE turn_id=?', (repair(context), TURN_ID))
        for revision in revisions:
            connection.execute('UPDATE cognition_context_revisions SET snapshot_json=? WHERE turn_id=? AND revision=?', (repair(json.loads(revision['snapshot_json'])), TURN_ID, revision['revision']))
        connection.commit()
        print(json.dumps({'repaired_turns': 1, 'repaired_revisions': len(revisions), 'backup': str(backup)}, ensure_ascii=True))
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == '__main__':
    main()
