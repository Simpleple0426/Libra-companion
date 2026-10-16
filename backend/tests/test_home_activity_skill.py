import unittest
from life_prototype.skill_home_activity import routine, _choices
from life_prototype.local_configuration import configurations


class HomeActivitySkillTests(unittest.TestCase):
    def setUp(self):
        self.config=configurations()[0]

    def test_morning_refines_to_care_inside_home(self):
        item={'place':'home.f2.bedroom','intent':'起床及晨间准备'}
        self.assertTrue(routine(item))
        choice=_choices(self.config,item)[0]
        self.assertEqual(choice['choice'],'morning_care')
        self.assertEqual(choice['activity'],'morning_wash')
        self.assertTrue(choice['place'].startswith('home.'))

    def test_refined_item_is_not_dispatched_again(self):
        self.assertFalse(routine({'place':'home.f2.study','intent':'阅读',
                                  'home_activity_choice':'reading'}))


if __name__=='__main__': unittest.main()
