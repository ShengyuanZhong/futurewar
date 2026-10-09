"""Level-three allocation and occupied efficiency-maximizing rocket centres."""
from fractions import Fraction
import time
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.combat import choose_targets
from agent.protocol import Pos, Turn, distance
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, unit, robot

POINTS = {'smallRobot':1, 'middleRobot':2, 'largeRobot':4, 'bossRobot':10}


def battlefield(lower=False):
    raw = request(71)
    raw['teamOur']['playerTasks'] = []
    raw['mapInfo']['zones'] = []
    positions = ((30,7),(32,7),(33,7),(28,7),(6,25)) if lower else (
        (10,24),(9,24),(8,24),(12,24),(30,5))
    base, tower, pioneer, own, enemy = positions
    raw['teamOur']['roles'] = [unit(503,'station',*base), unit(601,'rocket',*tower,level=3),
                               unit(502,'pioneer',*pioneer)]
    raw['robot']['roles'] = [robot(900,*own,health=500,roleType='largeRobot'),
                            robot(901,*enemy,health=800,roleType='bossRobot')]
    return raw


def target_list(raw, health=None, deadline=float('inf')):
    turn = Turn.load(raw)
    health = health if health is not None else {r.robot_id:r.health for r in turn.robots}
    return choose_targets(turn, turn.weapons()[0], health, deadline)


def area_score(raw, target):
    return sum(POINTS[r['roleType']] for r in raw['robot']['roles'] if r['health'] > 0
               and distance(Pos.load(r['pos']), target) <= 1)


def area_ratio(raw, target):
    return sum((Fraction(POINTS[r['roleType']],r['health']) for r in raw['robot']['roles']
                if r['health'] > 0 and distance(Pos.load(r['pos']),target) <= 1),Fraction(0))


class RocketSectorTests(unittest.TestCase):
    def test_three_shots_split_two_home_one_enemy_in_both_team_positions(self):
        for lower in (False, True):
            for team in ('challenger','defender'):
                raw = battlefield(lower); raw['teamOur']['type'] = team
                targets = target_list(raw)
                own_sign = -1 if lower else 1
                self.assertEqual(len(targets),3)
                self.assertTrue(all((40*p.y-31*p.x)*own_sign >= 0 for p in targets[:2]))
                self.assertLess((40*targets[2].y-31*targets[2].x)*own_sign,0)
                self.assertEqual(targets[2], Pos.load(raw['robot']['roles'][1]['pos']))

    def test_enemy_efficiency_prefers_eight_small_robots_over_a_full_boss(self):
        raw = battlefield()
        raw['robot']['roles'][1]['pos'] = {'x':23,'y':5}
        raw['robot']['roles'] += [robot(910+i,x,y,health=40)
            for i,(x,y) in enumerate(((29,4),(30,4),(31,4),(29,5),(30,5),(31,5),(29,6),(30,6)))]
        enemy = target_list(raw)[2]
        self.assertIn(enemy,{Pos.load(r['pos']) for r in raw['robot']['roles'] if r['health']>0})
        self.assertEqual(area_ratio(raw,enemy),Fraction(1,5))

    def test_enemy_efficiency_sums_all_robots_not_just_the_centre(self):
        raw = battlefield()
        raw['robot']['roles'][1]['pos'] = {'x':23,'y':5}
        raw['robot']['roles'] += [robot(910+i,x,y,health=60,roleType='middleRobot')
            for i,(x,y) in enumerate(((29,4),(30,4),(31,4),(29,5),(30,5),(31,5)))]
        enemy = target_list(raw)[2]
        self.assertEqual(area_ratio(raw,enemy),Fraction(1,5))
        self.assertIn(enemy,{Pos.load(r['pos']) for r in raw['robot']['roles'] if r['health']>0})

    def test_empty_high_score_centre_is_not_a_legal_enemy_choice(self):
        raw = battlefield()
        raw['robot']['roles'][1]['pos'] = {'x':23,'y':5}
        raw['robot']['roles'] += [robot(910+i,x,y,health=500,roleType='largeRobot')
            for i,(x,y) in enumerate(((28,4),(30,4),(28,6),(30,6)))]
        self.assertEqual(area_score(raw,Pos(29,5)),16)
        self.assertEqual(target_list(raw)[2],Pos(23,5))

    def test_no_enemy_robots_uses_all_three_shots_at_home(self):
        raw = battlefield(); raw['robot']['roles'] = raw['robot']['roles'][:1]
        health = {900:500}
        self.assertEqual(target_list(raw,health), [Pos(12,24)]*3)
        self.assertEqual(health, {900:440})

    def test_dead_enemy_robot_does_not_trigger_the_enemy_allocation(self):
        raw = battlefield(); raw['robot']['roles'][1]['health'] = 0
        self.assertEqual(target_list(raw), [Pos(12,24)]*3)

    def test_no_home_robots_transfers_unused_shots_to_the_enemy(self):
        raw = battlefield(); raw['robot']['roles'] = raw['robot']['roles'][1:]
        health = {901:800}
        self.assertEqual(target_list(raw,health), [Pos(30,5)]*3)
        self.assertEqual(health, {901:740})

    def test_prediction_accounts_for_two_home_hits_and_one_enemy_hit(self):
        raw = battlefield(); health = {900:500,901:800}
        self.assertEqual(target_list(raw,health), [Pos(12,24),Pos(12,24),Pos(30,5)])
        self.assertEqual(health, {900:460,901:780})
        self.assertEqual([r['health'] for r in raw['robot']['roles']], [500,800])

    def test_robot_target_team_does_not_override_coordinate_partition(self):
        raw = battlefield()
        raw['robot']['roles'][0]['targetTeam'] = 'defender'
        raw['robot']['roles'][1]['targetTeam'] = 'challenger'
        self.assertEqual(target_list(raw)[2],Pos(30,5))

    def test_predicted_dead_home_robots_do_not_change_observed_shot_allocation(self):
        raw = battlefield(); health = {900:0,901:800}
        targets = target_list(raw,health)
        self.assertEqual(len(targets),3)
        self.assertTrue(all(40*p.y-31*p.x >= 0 for p in targets[:2]))
        self.assertEqual(targets[2],Pos(30,5))
        self.assertEqual(health,{900:0,901:780})

    def test_both_sector_ratios_include_cross_boundary_splash_robots(self):
        raw = battlefield()
        raw['robot']['roles'] += [robot(902,20,15), robot(903,20,16,health=800,roleType='bossRobot')]
        self.assertEqual(area_ratio(raw,Pos(20,15)),Fraction(3,80))
        self.assertEqual(target_list(raw),[Pos(20,16),Pos(20,16),Pos(20,15)])

    def test_expired_deadline_does_not_commit_partial_predictions(self):
        raw = battlefield(); health = {900:500,901:800}
        self.assertEqual(target_list(raw,health,time.monotonic()-1), [])
        self.assertEqual(health, {900:500,901:800})

    def test_lower_levels_keep_the_existing_range_and_projectile_count(self):
        for level in (1,2):
            raw = battlefield(); raw['teamOur']['roles'][1]['level'] = level
            raw['robot']['roles'] = [robot(900,19,14,health=500)]
            self.assertEqual(target_list(raw), [Pos(19,14)]*level)

    def test_strategy_emits_one_legal_salvo_and_keeps_cooldown(self):
        for cooldown in (0,3):
            raw = battlefield(); raw['teamOur']['roles'][1]['cooldown'] = cooldown
            turn = Turn.load(raw); plan = ActionPlan(turn,Settings(enable_news=False))
            Strategy(turn,plan,GameMemory(opening_complete=True)).run()
            if cooldown == 0:
                self.assertEqual(plan.commands['601']['controllerId'],'502')
                self.assertEqual(plan.commands['601']['targetPos'],
                    [{'x':12,'y':24},{'x':12,'y':24},{'x':30,'y':5}])
                self.assertNotIn('502',plan.commands)
            else:
                self.assertNotIn('601',plan.commands)
            self.assertEqual(plan.rejections, [])


if __name__ == '__main__':
    unittest.main()
