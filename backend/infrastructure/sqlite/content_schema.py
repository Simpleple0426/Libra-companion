"""Remove legacy foreign keys which cannot cross SQLite shard boundaries."""
import re


def repair_moments(connection):
    row = connection.execute("SELECT sql FROM sqlite_master WHERE name='shared_moments'").fetchone()
    if not row:
        return False
    sql = row[0]
    repaired = re.sub(r',\s*FOREIGN KEY\s*\([^)]*\)\s*REFERENCES\s+(?:messages|world_events)\s*\([^)]*\)', '', sql, flags=re.I)
    if repaired == sql:
        return False
    indexes = [r[0] for r in connection.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name='shared_moments' AND type='index' AND sql IS NOT NULL")]
    sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='shared_moments'").fetchone()
    columns = ','.join('"'+r[1]+'"' for r in connection.execute('PRAGMA table_info(shared_moments)'))
    connection.commit()
    enabled = connection.execute('PRAGMA foreign_keys').fetchone()[0]
    connection.execute('PRAGMA foreign_keys=OFF')
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute(re.sub(r'(CREATE TABLE\s+)(?:"shared_moments"|shared_moments)', r'\1shared_moments_repaired', repaired, count=1, flags=re.I))
        connection.execute(f'INSERT INTO shared_moments_repaired ({columns}) SELECT {columns} FROM shared_moments')
        connection.execute('DROP TABLE shared_moments')
        connection.execute('ALTER TABLE shared_moments_repaired RENAME TO shared_moments')
        for index in indexes:
            connection.execute(index)
        if sequence:
            connection.execute("UPDATE sqlite_sequence SET seq=? WHERE name='shared_moments'", (sequence[0],))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute(f'PRAGMA foreign_keys={enabled}')
    return True
