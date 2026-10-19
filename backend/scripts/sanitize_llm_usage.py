"""Remove impossible historical provider usage counters from reports."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from infrastructure.paths import COGNITION_DATABASE_PATH
from infrastructure.sqlite.connection import connect


def run(max_input=2_000_000, max_output=200_000):
    with connect(COGNITION_DATABASE_PATH, attach_shards=False) as connection:
        cursor = connection.execute(
            'DELETE FROM llm_usage_events WHERE input_tokens>? OR output_tokens>? '
            'OR cached_input_tokens>input_tokens OR reasoning_output_tokens>? '
            'OR total_tokens>?',
            (max_input, max_output, max_output, max_input + max_output),
        )
        return cursor.rowcount


if __name__ == '__main__':
    print({'removed_invalid_usage_events': run()})
