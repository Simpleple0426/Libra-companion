from datetime import timedelta
import unittest
from unittest.mock import patch

import test_future_appointments as fixture
from life_prototype.memory_service import add_memory, LifeMemory
from life_prototype.config import canonical


class MemoryCandidateTests(unittest.TestCase):
    setUp = fixture.FutureAppointmentTests.setUp

    def add(self, ident, text, actor=None, importance=3):
        with self.p.store.connect() as db:
            add_memory(db, ident, 'event', text, self.clock.now().isoformat(), importance, [], [ident],
                       actor or self.p.config['persona']['id'], 'observed')

    def test_synonym_recall_update_delete_and_restart(self):
        self.add('book', '在书房阅读了一会儿')
        self.add('movie', '昨晚观影后写了几句感想')
        self.cog.memory.candidates.sync()
        with self.p.store.connect() as db:
            candidates = self.cog.memory.candidates.candidates(db, '看书', self.p.config['persona']['id'], self.clock.now().isoformat())
        self.assertIn('book', candidates)
        result = self.cog.memory.retrieve('看书', 'q1')
        self.assertEqual(result[0]['id'], 'book')
        self.cog.memory = LifeMemory(self.p.store, self.cog.config)
        with self.p.store.connect() as db:
            db.execute("UPDATE life_memories SET description='周末在花园散步' WHERE id='book'")
            db.execute("DELETE FROM life_memories WHERE id='movie'")
        result = self.cog.memory.retrieve('走走', 'q2')
        self.assertEqual([r['id'] for r in result], ['book'])
        self.assertEqual(self.cog.memory.retrieve('看书', 'q1'), [])
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM life_memory_fts').fetchone()[0], 1)

    def test_bounded_scoring_and_older_relevant_memory(self):
        self.add('old-book', '读书时想起了你', importance=1)
        self.clock.advance(3600)
        with self.p.store.connect() as db:
            for i in range(1500):
                add_memory(db, 'noise:' + str(i), 'event', '完成日常办公室整理 ' + str(i),
                           self.clock.now().isoformat(), 5, [], ['event:' + str(i)],
                           self.p.config['persona']['id'], 'observed')
        memory = self.cog.memory
        with patch.object(memory.index, 'score', wraps=memory.index.score) as score:
            result = memory.retrieve('看书', 'bounded')
        self.assertLessEqual(len(score.call_args.args[0]), 384)
        self.assertIn('old-book', [r['id'] for r in result])

    def test_revoked_other_actor_and_future_memories_are_excluded(self):
        self.add('valid', '阅读记录')
        self.add('revoked', '阅读记录')
        self.add('other', '阅读记录', actor='someone-else')
        self.add('future', '阅读记录')
        with self.p.store.connect() as db:
            db.execute('UPDATE life_memories SET created_at=? WHERE id=?',
                       ((self.clock.now() + timedelta(days=1)).isoformat(), 'future'))
        self.cog.memory.index.mark('review', 'revoked', effective_at=self.clock.now(), status='revoked', reason='错误记录')
        result = self.cog.memory.retrieve('阅读', 'filtered')
        self.assertEqual([r['id'] for r in result], ['valid'])

    def test_revoked_cluster_cannot_fill_candidate_limit(self):
        self.add('valid-long', '候鸟迁徙 ' + '长篇说明' * 60)
        with self.p.store.connect() as db:
            for i in range(300):
                ident = 'revoked:' + str(i)
                add_memory(db, ident, 'event', '候鸟迁徙', self.clock.now().isoformat(), 5, [], [ident],
                           self.p.config['persona']['id'], 'observed')
                db.execute('INSERT INTO life_memory_validity VALUES(?,?,?)',
                           ('review:' + ident, ident, canonical({'status': 'revoked', 'effective_at': self.clock.now().isoformat()})))
        self.assertEqual([r['id'] for r in self.cog.memory.retrieve('候鸟', 'valid-match')], ['valid-long'])


if __name__ == '__main__':
    unittest.main()
