"""Memory backup, health, inspection and invalidation operations."""
from .base import *  # shared domain primitives
from infrastructure.paths import BACKUP_ROOT, COGNITION_DATABASE_PATH


class MemoryAdminMixin:
    def create_backup(self, destination=None):
        """Create and verify a consistent online SQLite backup."""
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = BACKUP_ROOT if self.path.resolve() == COGNITION_DATABASE_PATH else self.path.parent / 'backups'
        destination = Path(destination) if destination else backup_dir / f'{self.path.stem}_{stamp}.db'
        destination = destination.resolve()
        if destination == self.path.resolve():
            raise ValidationError('backup_destination_is_source')
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + '.tmp')
        if temporary.exists():
            temporary.unlink()
        from infrastructure.sqlite.connection import connect
        source = connect(self.path, timeout=30)
        target = connect(temporary, attach_shards=False)
        try:
            source.backup(target)
            target.commit()
            check = target.execute('PRAGMA integrity_check').fetchone()[0]
            if check != 'ok':
                raise ValidationError('backup_integrity_failed')
        finally:
            target.close()
            source.close()
        os.replace(temporary, destination)
        with self.connect(True) as c:
            c.execute("INSERT INTO memory_config VALUES ('last_backup_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (utc(),))
            c.execute("INSERT INTO memory_config VALUES ('last_backup_path',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(destination),))
        return {'path':str(destination), 'size_bytes':destination.stat().st_size, 'integrity':'ok'}
    def maybe_create_backup(self, interval_hours=24, keep=14):
        """Create a scheduled backup at most once per interval and rotate only owned files."""
        with self.connect() as c:
            row=c.execute("SELECT value FROM memory_config WHERE key='last_backup_at'").fetchone()
        if row:
            age=datetime.now(timezone.utc)-datetime.fromisoformat(utc(row[0]))
            if age < timedelta(hours=max(1,int(interval_hours))):
                return None
        result=self.create_backup()
        backup_dir=(BACKUP_ROOT if self.path.resolve() == COGNITION_DATABASE_PATH else self.path.parent/'backups').resolve()
        owned=sorted(backup_dir.glob(f'{self.path.stem}_*.db'),key=lambda p:p.stat().st_mtime,reverse=True)
        for old in owned[max(1,int(keep)):]:
            resolved=old.resolve()
            if resolved.parent==backup_dir and resolved!=Path(result['path']).resolve():
                resolved.unlink()
        return result
    def quality_audit(self, limit=500):
        """Read-only audit of LMC lifecycle, evidence and relation integrity."""
        from .lmc_maintenance import patrol
        return patrol(self, limit=limit)
    def health(self):
        cutoff=utc(datetime.now(timezone.utc)-timedelta(days=7))
        with self.connect() as c:
            counts={table:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in
                    ('raw_experiences','lmc_candidates','lmc_memories','lmc_embeddings','memory_jobs')}
            jobs={r['job_status']:r['n'] for r in c.execute('SELECT job_status,COUNT(*) n FROM memory_jobs GROUP BY job_status')}
            decisions={r['segment_state']:r['n'] for r in c.execute('SELECT segment_state,COUNT(*) n FROM experience_segments GROUP BY segment_state')}
            config={r['key']:r['value'] for r in c.execute("SELECT key,value FROM memory_config WHERE key IN ('schema_version','last_backup_at','last_backup_path')")}
            config['memory_engine'] = 'lmc5-native-v2'
            config['dream_jobs'] = {r['status']: r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM lmc_dream_jobs GROUP BY status')}
            config['dream_pages'] = c.execute('SELECT COUNT(*) FROM lmc_dream_pages').fetchone()[0]
            config['relation_jobs'] = {r['status']: r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM lmc_relation_jobs GROUP BY status')}
            config['coordinate_statuses'] = {r['status']: r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM lmc_memory_coordinates GROUP BY status')}
            journal=c.execute('PRAGMA journal_mode').fetchone()[0]
            integrity=c.execute('PRAGMA quick_check').fetchone()[0]
            retention={'discard':0,'recent_only':0,'long_term':0}
            for row in c.execute("SELECT result_json FROM memory_jobs WHERE job_kind='lmc' AND job_status='committed' AND updated_at>=?",(cutoff,)):
                for item in json.loads(row[0] or '[]'):
                    decision=item.get('retention')
                    if decision in retention:retention[decision]+=1
            latencies=[]
            for row in c.execute('SELECT trace_json FROM lmc_recall_logs WHERE created_at>=?',(cutoff,)):
                value=json.loads(row[0] or '{}').get('latency_ms')
                if isinstance(value,(int,float)):latencies.append(float(value))
            latencies.sort()
            percentile=lambda p: latencies[min(len(latencies)-1,int((len(latencies)-1)*p))] if latencies else None
        return {'database_size_bytes':self.path.stat().st_size if self.path.exists() else 0,
                'journal_mode':journal,'integrity':integrity,'counts':counts,
                'jobs_by_status':jobs,'segments_by_state':decisions,
                'retention_decisions_7d':retention,
                'recall_latency_ms_7d':{'samples':len(latencies),'p50':percentile(.5),'p95':percentile(.95)},
                **config}
    def inspect(self, limit=50):
        with self.connect() as c:
            return {'fts_available':self.fts_available,'embedding_enabled':self.embedding_adapter is not None,'policy_version':POLICY_VERSION,
                    'health':self.health(),
                    'memories':[dict(r) for r in c.execute('SELECT memory_id,title,memory_kind,revision,record_status,sensitivity FROM lmc_memories ORDER BY updated_at DESC LIMIT ?',(max(1,min(limit,100)),))],
                    'jobs':[dict(r) for r in c.execute('SELECT job_id,segment_id,job_kind,job_status,attempts,error_code FROM memory_jobs ORDER BY created_at DESC LIMIT 50')]}
    def detail(self, memory_id):
        with self.connect() as c:
            record=c.execute('SELECT * FROM lmc_memories WHERE memory_id=?',(memory_id,)).fetchone()
            if not record:
                return None
            detail=c.execute('SELECT * FROM lmc_event_context WHERE memory_id=?',(memory_id,)).fetchone()
            return {'record':dict(record),
                    'coordinates':dict(row) if (row := c.execute('SELECT * FROM lmc_memory_coordinates WHERE memory_id=?',(memory_id,)).fetchone()) else None,
                    'relations':[dict(r) for r in c.execute('SELECT * FROM lmc_memory_relations WHERE source_id=? OR target_id=?',(memory_id,memory_id))],
                    'detail':dict(detail) if detail else {},
                    'revisions':[dict(r) for r in c.execute('SELECT * FROM lmc_revisions WHERE memory_id=? ORDER BY revision',(memory_id,))],
                    'sources':[dict(r) for r in c.execute('''SELECT s.*,r.actor,r.occurred_at,r.source_status
                        FROM lmc_sources s JOIN raw_experiences r USING(experience_id) WHERE memory_id=?''',(memory_id,))]}
    def invalidate(self, memory_id):
        """User-requested invalidation preserves the complete audit trail."""
        with self.connect(True) as c:
            row=c.execute("SELECT * FROM lmc_memories WHERE memory_id=? AND record_status='active'",(memory_id,)).fetchone()
            if not row:
                return False
            now=utc()
            c.execute("UPDATE lmc_memories SET record_status='invalid',revision=revision+1,updated_at=? WHERE memory_id=?",(now,memory_id))
            snapshot=dict(c.execute('SELECT * FROM lmc_memories WHERE memory_id=?',(memory_id,)).fetchone())
            snapshot['detail']=dict(c.execute('SELECT * FROM lmc_event_context WHERE memory_id=?',(memory_id,)).fetchone())
            snapshot['sources']=[dict(r) for r in c.execute('SELECT * FROM lmc_sources WHERE memory_id=?',(memory_id,))]
            c.execute('INSERT INTO lmc_revisions VALUES (?,?,?,?,?,?)',(memory_id,snapshot['revision'],'invalidate',dumps(snapshot),'explicit_user_invalidation',now))
            c.execute("UPDATE lmc_memory_coordinates SET status='archived',active_fact=0,source_revision=? WHERE memory_id=?", (snapshot['revision'], memory_id))
            c.execute("UPDATE lmc_memory_relations SET status='invalid' WHERE source_id=? OR target_id=?", (memory_id, memory_id))
            c.execute("UPDATE lmc_relation_jobs SET status='obsolete',lease_token=NULL,lease_until=NULL WHERE memory_id=? AND status IN ('pending','processing','retryable')", (memory_id,))
            return True
