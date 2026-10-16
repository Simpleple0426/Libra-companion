"""Shared state, evidence and receipt schemas for the single life database."""

# old name: (destination, discriminator column/value, old column -> new column)
GROUPS = {}
for old, name, value_column in (
    ('snapshot', 'current', 'body'),
    ('prototype_meta', 'world', 'config'),
    ('life_cognition_state', 'cognition', 'body'),
    ('life_interaction_config', 'interaction', 'config'),
    ('life_scheduler_state', 'scheduler', 'body'),
    ('life_encoder', 'encoder', 'body'),
    ('life_resources', 'resources', 'body'),
    ('work_extension', 'work_extension', 'body'),
):
    GROUPS[old] = ('life_state', 'name', name, {'id': 'id', value_column: 'body'})
for old, name, columns in (
    ('home_world_checks', 'world_check', {'id': 'id', 'body': 'body'}),
    ('life_memory_retrievals', 'memory_retrieval', {'id': 'id', 'body': 'body'}),
    ('life_observation_updates', 'observation_update', {'observation_id': 'id', 'body': 'body'}),
    ('life_resource_versions', 'resource_version', {'hash': 'id', 'body': 'body'}),
    ('reading_records', 'reading', {'result_id': 'id', 'body': 'body'}),
    ('life_cognition_artifacts', 'cognition', {'id': 'id', 'kind': 'kind', 'body': 'body'}),
    ('proposals', 'proposal', {'id': 'id', 'kind': 'kind', 'body': 'body'}),
    ('life_message_archive', 'message', {'message_id': 'id', 'source_event': 'source_id', 'body': 'body'}),
):
    GROUPS[old] = ('life_evidence', 'category', name, columns)
for old, name in (
    ('life_sleep_ticks', 'sleep_tick'),
    ('life_agent_effects', 'agent_effect'),
    ('result_reviews', 'result_review'),
):
    GROUPS[old] = ('life_receipts', 'category', name,
                   {'id': 'id', 'request': 'request', 'receipt': 'receipt'})

SCHEMA = '''
CREATE TABLE IF NOT EXISTS life_state (
    name TEXT PRIMARY KEY, id INTEGER NOT NULL DEFAULT 1 CHECK(id=1), body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS life_evidence (
    category TEXT NOT NULL, id TEXT NOT NULL, kind TEXT, source_id TEXT, body TEXT NOT NULL,
    PRIMARY KEY(category,id)
);
CREATE INDEX IF NOT EXISTS life_evidence_kind ON life_evidence(category,kind);
CREATE TABLE IF NOT EXISTS life_receipts (
    category TEXT NOT NULL, id TEXT NOT NULL, request TEXT NOT NULL, receipt TEXT NOT NULL,
    PRIMARY KEY(category,id)
);
'''


def projection(table, *, rowid=False):
    """Projection used only to preserve old audit report shapes, not old tables."""
    if table not in GROUPS:
        return f'SELECT * FROM "{table}"'
    destination, key, value, columns = GROUPS[table]
    fields = [f'"{new}" AS "{old}"' for old, new in columns.items()]
    if rowid:
        fields.insert(0, 'rowid')
    return f'SELECT {",".join(fields)} FROM {destination} WHERE {key}=\'{value}\''


def audit_cursor(db, table):
    if table not in GROUPS:
        return db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
    return db.execute(projection(table) + ' ORDER BY rowid')


def catalog(db):
    """Logical groups for historical audit/report readers."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    tables.update(r[0] for r in db.execute("SELECT name FROM sqlite_temp_master WHERE type='view'"))
    for old,(target,key,value,_) in GROUPS.items():
        if target in tables and (target != 'life_state' or db.execute(f'SELECT 1 FROM {target} WHERE {key}=?',(value,)).fetchone()):
            tables.add(old)
    return tables


def migrate_groups(db):
    """Copy each group in row order and verify values before dropping old tables."""
    for statement in SCHEMA.split(';'):
        if statement.strip():
            db.execute(statement)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    moved = {}
    for old, (destination, key, value, columns) in GROUPS.items():
        if old not in tables:
            continue
        if db.execute(f'SELECT 1 FROM {destination} WHERE {key}=? LIMIT 1', (value,)).fetchone():
            raise ValueError(f'conflicting storage group: {old}')
        fields = ','.join(columns)
        rows = db.execute(f'SELECT {fields} FROM "{old}" ORDER BY rowid').fetchall()
        targets = ','.join(columns.values())
        db.executemany(f'INSERT INTO {destination}({key},{targets}) VALUES ({",".join("?" for _ in range(len(columns)+1))})',
                       [(value, *row) for row in rows])
        if rows != db.execute(projection(old)+' ORDER BY rowid').fetchall():
            raise ValueError(f'storage migration mismatch: {old}')
        db.execute(f'DROP TABLE "{old}"')
        moved[old] = len(rows)
    return moved
