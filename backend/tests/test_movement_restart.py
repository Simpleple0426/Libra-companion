"""Retired movement commands cannot be revived by a process restart."""
import unittest
import test_meal_skill as fixture
from life_prototype.config import canonical
from life_prototype.coarse_locations import advance


class MovementRetirementTests(unittest.TestCase):
    setUp = fixture.MealSkillTests.setUp
    command = fixture.MealSkillTests.command

    def seed_legacy(self, status):
        with self.p.store.connect() as db:
            state=self.p.store.read(db)
            state['activities']['old']={'id':'old','kind':'moving','status':status,
                'target':'home.f1.living','place':state['place'],'route':[state['place'],'home.f1.living'],
                'progress':0,'revision':1,'started_at':self.clock.now().isoformat(),
                'last_progress_at':self.clock.now().isoformat(),'next_due_at':None}
            state['active']='old' if status=='running' else None
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))

    def test_old_interrupted_movement_cannot_resume(self):
        self.seed_legacy('interrupted')
        with self.assertRaisesRegex(ValueError,'independent movement removed'):
            self.command('resume','resume',activity_id='old')

    def test_running_legacy_movement_is_closed_without_progress(self):
        self.seed_legacy('running')
        advance(self.cog)
        state=self.p.snapshot()
        self.assertEqual(state['activities']['old']['status'],'failed')
        self.assertEqual(state['activities']['old']['progress'],0)
        self.assertIsNone(state['active'])

    def test_new_movement_and_serving_cannot_start(self):
        for kind in ('moving','serving'):
            with self.assertRaisesRegex(ValueError,'independent movement removed'):
                self.command(kind,'start',activity_id=kind,kind=kind,target='home.f1.living')
