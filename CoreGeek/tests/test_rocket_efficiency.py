"""Occupied rocket centres maximizing sum(points/current HP) in either sector."""
from fractions import Fraction
import unittest

from agent.protocol import Pos, distance
from tests.fixtures import robot
from tests.test_rocket_sectors import POINTS, battlefield, target_list


def area_ratio(raw, centre):
    return sum((Fraction(POINTS[r['roleType']],r['health'])
        for r in raw['robot']['roles'] if r['health'] > 0
        and distance(Pos.load(r['pos']),centre) <= 1), Fraction(0))


class RocketEfficiencyTests(unittest.TestCase):
    def test_home_shots_use_efficiency_instead_of_base_distance_damage(self):
        raw = battlefield()
        raw['robot']['roles'].append(robot(902,20,25,health=60,roleType='middleRobot'))
        self.assertEqual(target_list(raw)[:2],[Pos(20,25)]*2)

    def test_full_health_document_parameters_prefer_the_medium_robot(self):
        raw = battlefield()
        raw['robot']['roles'] = raw['robot']['roles'][:1] + [
            robot(901,22,5,health=40,roleType='smallRobot'),
            robot(902,25,5,health=60,roleType='middleRobot'),
            robot(903,28,5,health=500,roleType='largeRobot'),
            robot(904,31,5,health=800,roleType='bossRobot')]
        self.assertEqual(target_list(raw)[2],Pos(25,5))
        self.assertEqual(area_ratio(raw,Pos(25,5)),Fraction(1,30))

    def test_current_health_changes_the_enemy_target(self):
        raw = battlefield()
        raw['robot']['roles'].append(robot(902,23,5,health=40))
        self.assertEqual(target_list(raw)[2],Pos(23,5))
        raw['robot']['roles'][1]['health'] = 10
        self.assertEqual(target_list(raw)[2],Pos(30,5))

    def test_sum_of_individual_ratios_is_not_ratio_of_totals_or_inverse_sum(self):
        raw = battlefield()
        raw['robot']['roles'] = raw['robot']['roles'][:1] + [
            robot(901,23,5,health=40),robot(902,24,5,health=40),
            robot(903,30,5,health=50,roleType='middleRobot')]
        chosen = target_list(raw)[2]
        self.assertIn(chosen,{Pos(23,5),Pos(24,5)})
        self.assertEqual(area_ratio(raw,chosen),Fraction(1,20))
        self.assertGreater(area_ratio(raw,chosen),area_ratio(raw,Pos(30,5)))

    def test_empty_high_ratio_home_centre_is_excluded(self):
        raw = battlefield()
        raw['robot']['roles'] += [robot(910+i,x,y,health=60,roleType='middleRobot')
            for i,(x,y) in enumerate(((14,22),(16,22),(14,24),(16,24)))]
        raw['robot']['roles'].append(robot(920,20,26,health=100,roleType='bossRobot'))
        self.assertEqual(area_ratio(raw,Pos(15,23)),Fraction(2,15))
        self.assertEqual(target_list(raw)[:2],[Pos(20,26)]*2)

    def test_all_rocket_levels_use_occupied_centres_and_skip_zero_health(self):
        for level in (1,2,3):
            raw = battlefield(); raw['teamOur']['roles'][1]['level'] = level
            raw['robot']['roles'] += [robot(902,14,24,health=1,roleType='largeRobot'),
                                     robot(903,13,24,health=0,roleType='bossRobot')]
            targets = target_list(raw)
            self.assertEqual(targets[:min(level,2)],[Pos(14,24)]*min(level,2))
            occupied = {Pos.load(r['pos']) for r in raw['robot']['roles'] if r['health'] > 0}
            self.assertTrue(all(p in occupied for p in targets))

    def test_out_of_range_robot_cannot_be_hit_via_an_empty_splash_centre(self):
        raw = battlefield(); raw['teamOur']['roles'][1]['level'] = 1
        raw['robot']['roles'] = [robot(900,20,24,health=40)]
        health = {900:40}
        self.assertEqual(target_list(raw,health),[])
        self.assertEqual(health,{900:40})

    def test_exact_ratio_ties_are_independent_of_robot_order(self):
        raw = battlefield()
        raw['robot']['roles'] = raw['robot']['roles'][:1] + [
            robot(901,23,5,health=4),robot(902,24,5,health=20),
            robot(903,29,5,health=10),robot(904,30,5,health=10),robot(905,31,5,health=10)]
        self.assertEqual(area_ratio(raw,Pos(24,5)),Fraction(3,10))
        self.assertEqual(area_ratio(raw,Pos(30,5)),Fraction(3,10))
        self.assertEqual(target_list(raw)[2],Pos(24,5))
        raw['robot']['roles'].reverse()
        self.assertEqual(target_list(raw)[2],Pos(24,5))


if __name__ == '__main__':
    unittest.main()
