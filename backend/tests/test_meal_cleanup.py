import unittest
from life_prototype import skill_dining as dining, skill_housework as chores
from life_prototype.coarse_plan_execution import requirement
from life_prototype.coarse_locations import advance
import test_housework_skill as fixture
import test_meal_skill as meal_fixture


class MealCleanupTests(unittest.TestCase):
    setUp = fixture.HouseworkTests.setUp
    command = fixture.HouseworkTests.command
    set_place = fixture.HouseworkTests.set_place
    ticks = fixture.HouseworkTests.ticks
    execute_plan = fixture.HouseworkTests.execute_plan

    def test_home_meal_requires_cleanup_within_same_slot(self):
        for mode in ('cook', 'takeout'):
            with self.subTest(mode=mode):
                self.setUp()
                self.model.mode = mode
                self.set_place('home.f1.dining' if mode == 'takeout' else 'home.f1.kitchen')
                plan = dining.prepare(self.cog)['meal']
                self.command('prep', 'start', activity_id='prep', kind='cooking', target=self.ref)
                meal_fixture.MealSkillTests.ticks(self, plan['prepare_seconds'])
                advance(self.cog)
                self.command('eat', 'start', activity_id='eat', kind='eating', target=self.ref)
                meal_fixture.MealSkillTests.ticks(self, plan['eat_seconds'])
                state = self.p.snapshot()
                self.assertIn('eaten_at', state['meal_plans'][self.ref])
                self.assertNotIn('completed_at', state['meal_plans'][self.ref])
                self.assertEqual(requirement(self.cog)['reason'], 'call_housework_prepare')
                cleanup = chores.prepare(self.cog)['housework']
                self.assertEqual(cleanup['meal_cleanup_ref'], self.ref)
                self.assertEqual(self.item['state_type'], 'eating')
                self.execute_plan(cleanup)
                self.assertIn('cleanup_completed_at', self.p.snapshot()['meal_plans'][self.ref])
                self.assertEqual(requirement(self.cog)['reason'], 'meal_completed')

    def test_daily_chores_do_not_resume_dishwashing(self):
        state = {'housework_plans': {'old': {'routine':'clean_dishes', 'coarse_place':'home.f1.dining'}}}
        item = {'id':'daily', 'intent':'家务', 'activity':'housework', 'place':'home.f1.living'}
        self.assertIsNone(chores.pending_plan(state, item))


if __name__ == '__main__': unittest.main()
