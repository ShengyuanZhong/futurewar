"""Hand-built siege priorities; these are observations, not official games."""
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn, Unit, station_footprint
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, robot, unit
from tools.validate import independent_base_ray_guns, independent_contract


BOSS, BASE, GUN, HERO = 30005, 990, 991, 992


def scene(base=(12, 11), start=(10, 10), extra=()):
    raw = request(71)
    raw['mapInfo']['zones'] = []
    raw['teamOur']['playerTasks'] = []
    raw['teamOur']['roles'] = [unit(503, 'station', 30, 30),
                               unit(501, 'worker', 10, 13)]
    raw['teamEnemy']['roles'] = [unit(BASE, 'station', *base)] + list(extra)
    born = robot(BOSS, *start, health=800, roleType='bossRobot')
    raw['teamOur']['summonRobotList'] = [born]
    raw['robot']['roles'] = [dict(born)]
    return raw


def decide(raw, memory=None, budget=4):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, Settings(enable_news=False, boss_controller_max_walk=budget))
    state = memory if memory is not None else GameMemory(opening_complete=True)
    strategy = Strategy(turn, plan, state)
    strategy.raider.decide(turn.summon_robots[0])
    return strategy, plan


class SiegeWeaponsTests(unittest.TestCase):
    def assert_attack(self, plan, target):
        self.assertEqual(plan.commands[str(BOSS)],
                         {'action': 'attack', 'targetPos': [Pos(*target).dump()]})
        self.assertEqual(plan.rejections, [])
        self.assertEqual(len(plan.commands), 1)

    def assert_base_attack(self, strategy, plan):
        command = plan.commands[str(BOSS)]
        self.assertEqual(command['action'], 'attack')
        self.assertIn(Pos.load(command['targetPos'][0]),
                      station_footprint(next(u.pos for u in strategy.turn.enemies if u.unit_id == BASE)))
        self.assertEqual(plan.rejections, [])

    def test_no_guns_stationary_base_neighbour_preempts_base_for_both_roles(self):
        for kind in ('worker', 'pioneer'):
            with self.subTest(kind=kind):
                raw = scene(extra=[unit(HERO, kind, 11, 11, health=500)])
                strategy, plan = decide(raw)
                self.assert_attack(plan, (11, 11))
                self.assertEqual(strategy.memory.robot_raids[BOSS]['stage'], 'base_nearby')
                self.assertTrue(strategy.raider.diag.records[BOSS]['direct_base_cells'])

    def test_no_stationary_base_ray_does_not_chase_secondary_neighbour(self):
        # Two walls screen all in-range base cells; the visible adjacent hero
        # (12,12) is clear, but killing it cannot outrank opening a base ray.
        raw = scene(base=(13,11), extra=[unit(HERO,'worker',12,12),
            unit(40001,'wall',11,10,health=1000),unit(40002,'wall',11,11,health=1000)])
        strategy, plan = decide(raw)
        self.assertNotEqual(plan.commands[str(BOSS)],
            {'action':'attack','targetPos':[Pos(12,12).dump()]})
        self.assertNotEqual(strategy.memory.robot_raids[BOSS]['stage'], 'base_nearby')

    def test_out_of_range_neighbour_does_not_cause_a_detour(self):
        raw = scene(extra=[unit(HERO,'worker',14,11)])
        strategy, plan = decide(raw)
        self.assert_base_attack(strategy, plan)

    def test_role_two_cells_from_base_is_not_a_secondary_target(self):
        raw = scene(extra=[unit(HERO,'worker',10,12)])
        strategy, plan = decide(raw)
        self.assert_base_attack(strategy, plan)

    def test_surviving_remote_gun_excludes_non_operator_base_neighbour(self):
        raw = scene(extra=[unit(HERO,'worker',11,11),unit(GUN,'rocket',20,20)])
        strategy, plan = decide(raw)
        self.assert_base_attack(strategy, plan)

    def test_hidden_remembered_gun_is_not_assumed_destroyed(self):
        raw = scene(extra=[unit(HERO,'worker',11,11)])
        state = GameMemory(opening_complete=True)
        state.enemy_structures[GUN] = Unit(GUN,Pos(20,20),'rocket',1000,level=1)
        strategy, plan = decide(raw,state)
        self.assertIn(GUN,state.enemy_structures)
        self.assert_base_attack(strategy, plan)

    def test_gun_absence_under_ordinary_sight_allows_secondary_sweep(self):
        raw = scene(extra=[unit(HERO,'worker',11,11)])
        state = GameMemory(opening_complete=True)
        state.enemy_structures[GUN] = Unit(GUN,Pos(11,12),'rocket',1000,level=1)
        strategy, plan = decide(raw,state)
        self.assertNotIn(GUN,state.enemy_structures)
        self.assert_attack(plan,(11,11))

    def test_first_visible_gun_on_all_available_base_rays_is_attacked(self):
        # Base x=13/14; only x=13 is in range. Both y=10/11 rays pass
        # through the interior of the gun at (11,10).
        for kind in ('gatling','railgun','rocket'):
            with self.subTest(kind=kind):
                raw = scene(base=(13,11),extra=[unit(GUN,kind,11,10,health=1000)])
                strategy, plan = decide(raw)
                self.assert_attack(plan,(11,10))
                self.assertEqual(strategy.memory.robot_raids[BOSS]['stage'],'weapon')
                self.assertEqual(strategy.memory.robot_raids[BOSS]['pursuit_kind'],'base')

    def test_an_exposed_base_cell_preempts_blocking_gun_on_other_ray(self):
        raw = scene(base=(12,12),extra=[unit(GUN,'rocket',11,10)])
        strategy, plan = decide(raw)
        self.assert_base_attack(strategy, plan)
        self.assertEqual(plan.commands[str(BOSS)]['targetPos'],[Pos(12,12).dump()])

    def test_wall_in_front_of_blocking_gun_is_hit_first(self):
        raw = scene(base=(13,10),extra=[unit(GUN,'rocket',12,10),
                                       unit(40001,'wall',11,10,health=1000)])
        strategy, plan = decide(raw)
        self.assert_attack(plan,(11,10))
        self.assertEqual(strategy.memory.robot_raids[BOSS]['stage'],'breach')
        self.assertEqual(strategy.memory.robot_raids[BOSS]['pursuit_kind'],'base')

    def test_hidden_blocking_gun_never_becomes_an_attack_target(self):
        raw = scene(base=(13,11))
        raw['teamOur']['roles'] = raw['teamOur']['roles'][:1]
        state = GameMemory(opening_complete=True)
        state.enemy_structures[GUN] = Unit(GUN,Pos(11,10),'rocket',1000,level=1)
        strategy, plan = decide(raw,state)
        self.assertIn(GUN,state.enemy_structures)
        for command in plan.commands.values():
            if command['action']=='attack':
                self.assertNotEqual(command['targetPos'],[Pos(11,10).dump()])

    def test_actual_gun_removal_releases_base_attack_next_round(self):
        raw = scene(base=(13,11),extra=[unit(GUN,'rocket',11,10,health=40)])
        strategy, plan = decide(raw)
        self.assert_attack(plan,(11,10))
        state = strategy.memory
        state.record(strategy.turn,plan)
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS):True}
        raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:1]
        strategy, plan = decide(raw,state)
        self.assert_base_attack(strategy,plan)
        self.assertNotIn(GUN,state.enemy_structures)

    def test_failed_weapon_shot_is_cached_and_not_repeated_from_same_post(self):
        raw = scene(base=(13,11),extra=[unit(GUN,'rocket',11,10)])
        strategy, plan = decide(raw)
        self.assert_attack(plan,(11,10))
        state = strategy.memory
        state.record(strategy.turn,plan)
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS):False}
        strategy, plan = decide(raw,state)
        self.assertNotEqual(plan.commands[str(BOSS)],
            {'action':'attack','targetPos':[Pos(11,10).dump()]})
        self.assertIn((GUN,Pos(11,10),Pos(10,10)),state.robot_raids[BOSS]['failed_firing'])

    def test_live_cannon_operator_preempts_weapon_base_and_neighbour(self):
        raw = scene(base=(13,11),extra=[unit(GUN,'rocket',11,10),
                                       unit(HERO,'worker',11,11,health=500)])
        strategy, plan = decide(raw)
        self.assert_attack(plan,(11,11))
        self.assertEqual(strategy.memory.robot_raids[BOSS]['stage'],'controller')

    def test_diagonal_side_wall_does_not_block_secondary_direct_role(self):
        raw = scene(base=(12,11),extra=[unit(HERO,'worker',11,11),
            unit(40002,'wall',10,11)])
        strategy, plan = decide(raw)
        self.assert_attack(plan,(11,11))

    def test_stationary_clear_base_ray_preempts_old_verified_walk_goal(self):
        raw = scene(base=(12,11))
        state = GameMemory(opening_complete=True)
        state.robot_raids[BOSS] = dict(verified_base_post=Pos(11,12),
                                       verified_base_target=Pos(12,11))
        strategy, plan = decide(raw,state)
        self.assert_base_attack(strategy,plan)

    def test_healed_secondary_role_is_rechecked_until_actually_dead(self):
        state = GameMemory(opening_complete=True)
        for number,hp in ((71,40),(72,500),(73,420)):
            raw = scene(extra=[unit(HERO,'worker',11,11,health=hp)])
            raw['roundNo'] = number
            raw['lastRoundRoleActionResults'] = {str(BOSS):True} if number>71 else {}
            strategy, plan = decide(raw,state)
            self.assert_attack(plan,(11,11))
            state.record(strategy.turn,plan)
        raw['roundNo'] = 74
        raw['teamEnemy']['roles'][-1]['health'] = 0
        strategy, plan = decide(raw,state)
        self.assert_base_attack(strategy,plan)

    @staticmethod
    def audit_response(target):
        return {'roleCommandMap':{str(BOSS):{'action':'attack','targetPos':[Pos(*target).dump()]}},
                'prompt':'','executeCmd':''}

    def test_independent_audit_accepts_visible_first_base_ray_gun(self):
        for kind in ('gatling','railgun','rocket'):
            with self.subTest(kind=kind):
                raw = scene(base=(13,11),extra=[unit(GUN,kind,11,10)])
                self.assertEqual(independent_base_ray_guns(raw,Pos(10,10)),{Pos(11,10)})
                independent_contract(raw,self.audit_response((11,10)))

    def test_independent_audit_45_degree_base_ray_ignores_side_corner_walls(self):
        raw = scene(base=(13,13),extra=[unit(GUN,'rocket',11,11),
            unit(40001,'wall',11,10),unit(40002,'wall',10,11)])
        self.assertEqual(independent_base_ray_guns(raw,Pos(10,10)),{Pos(11,11)})
        independent_contract(raw,self.audit_response((11,11)))

    def test_independent_audit_rejects_unrelated_visible_gun(self):
        raw = scene(base=(13,11),extra=[unit(GUN,'rocket',11,10),
                                      unit(993,'gatling',11,12)])
        with self.assertRaisesRegex(AssertionError,'first obstacle'):
            independent_contract(raw,self.audit_response((11,12)))

    def test_independent_audit_rejects_any_gun_when_base_has_clear_cell(self):
        raw = scene(base=(12,12),extra=[unit(GUN,'rocket',11,10)])
        self.assertEqual(independent_base_ray_guns(raw,Pos(10,10)),set())
        with self.assertRaisesRegex(AssertionError,'first obstacle'):
            independent_contract(raw,self.audit_response((11,10)))

    def test_independent_audit_rejects_gun_when_all_base_cells_are_out_of_range(self):
        raw = scene(base=(17,10),extra=[unit(GUN,'rocket',11,10)])
        with self.assertRaisesRegex(AssertionError,'first obstacle'):
            independent_contract(raw,self.audit_response((11,10)))

    def test_independent_audit_requires_wall_before_gun_to_be_attacked_first(self):
        raw = scene(base=(13,10),extra=[unit(GUN,'rocket',12,10),
                                      unit(40001,'wall',11,10)])
        self.assertEqual(independent_base_ray_guns(raw,Pos(10,10)),set())
        with self.assertRaisesRegex(AssertionError,'first obstacle'):
            independent_contract(raw,self.audit_response((12,10)))
        independent_contract(raw,self.audit_response((11,10)))

    def test_independent_audit_cannot_skip_first_gun_to_hit_second(self):
        raw = scene(base=(13,11),extra=[unit(GUN,'rocket',11,10),
                                      unit(993,'gatling',12,10)])
        self.assertEqual(independent_base_ray_guns(raw,Pos(10,10)),{Pos(11,10)})
        with self.assertRaisesRegex(AssertionError,'first obstacle'):
            independent_contract(raw,self.audit_response((12,10)))

    def test_independent_audit_direct_cannon_operator_still_preempts_gun(self):
        raw = scene(base=(13,11),extra=[unit(GUN,'rocket',11,10),
                                      unit(HERO,'worker',11,11,health=40)])
        with self.assertRaisesRegex(AssertionError,'lowest-current-HP'):
            independent_contract(raw,self.audit_response((11,10)))
        independent_contract(raw,self.audit_response((11,11)))

    def test_independent_audit_short_walk_cannon_operator_still_preempts_gun(self):
        raw = scene(base=(13,11),extra=[unit(GUN,'rocket',11,10),
            unit(994,'railgun',16,15),unit(HERO,'worker',16,14,health=40)])
        # No direct range-three crew shot, but an ordinary shortest path reaches
        # a crew firing post within four moves, so fresh siege is forbidden.
        with self.assertRaisesRegex(AssertionError,'access exceeds its budget'):
            independent_contract(raw,self.audit_response((11,10)))

    def test_independent_audit_unreachable_cannon_operator_allows_first_gun(self):
        raw = scene(base=(13,11),extra=[unit(GUN,'rocket',11,10),
            unit(994,'railgun',20,21),unit(HERO,'worker',20,20,health=40)])
        independent_contract(raw,self.audit_response((11,10)))


if __name__ == '__main__':
    unittest.main()
