"""V2 owned-robot protocol, attack permissions and first-night BOSS workflow."""
import unittest

from agent.actions import ActionPlan
from agent.combat import choose_targets
from agent.protocol import Pos, Turn, build_command, distance, move_command
from agent.worker_safety import robot_danger
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import robot, unit
from tests.test_maintenance import fortified
from tests.test_worker_safety import strategy


ORDER = 'BossRobotSummonOrder'


def raid_request(number=30, boss=False):
    raw = fortified(number)
    raw['teamOur']['roles'][1]['pos'] = {'x': 3, 'y': 7}
    raw['teamEnemy']['roles'] = [unit(990, 'station', 33, 25),
        unit(991, 'rocket', 35, 25), unit(992, 'pioneer', 36, 25, health=500)]
    raw['teamOur']['summonRobotList'] = []
    raw['weaponShopList'].append({'name': ORDER, 'price': 120})
    raw['teamOur']['goldNum'] = 120
    if boss:
        raw['teamOur']['summonRobotList'] = [robot(30005, 39, 25, health=800, roleType='bossRobot')]
        raw['robot']['roles'] = list(raw['teamOur']['summonRobotList'])
    return raw


def finished_tasks():
    return GameMemory(opening_complete=True, task_points_attempted={(1, 3, 9), (1, 4, 9)})


class SummonControlTests(unittest.TestCase):
    def test_owned_list_is_parsed_and_deduplicated_with_global_robots(self):
        raw = raid_request(71, boss=True)
        turn = Turn.load(raw)
        self.assertEqual([r.robot_id for r in turn.summon_robots], [30005])
        self.assertEqual(len(turn.robots), 1)
        self.assertEqual(turn.hostile_robots(), ())
        raw['robot']['roles'] = []
        turn = Turn.load(raw)
        self.assertEqual(len(turn.robots), 1)
        self.assertIn(Pos(39, 25), turn.blocked(turn.workers()[0]))

    def test_owned_ids_cannot_impersonate_heroes_or_conflict_with_global_positions(self):
        for variant in ('hero_id', 'duplicate', 'conflict'):
            raw = raid_request(71, boss=True)
            if variant == 'hero_id':
                raw['teamOur']['summonRobotList'][0]['id'] = 501
                raw['robot']['roles'] = []
            elif variant == 'duplicate':
                raw['teamOur']['summonRobotList'] *= 2
            else:
                raw['teamOur']['summonRobotList'][0] = dict(raw['teamOur']['summonRobotList'][0], pos={'x': 38, 'y': 25})
            with self.assertRaises(ValueError):
                Turn.load(raw)

    def test_owned_robot_can_attack_without_a_hero_controller_and_cannot_double_act(self):
        raw = raid_request(71, boss=True)
        plan = ActionPlan(Turn.load(raw), Settings())
        command = {'action': 'attack', 'targetPos': [{'x': 36, 'y': 25}]}
        self.assertTrue(plan.add(30005, command), plan.rejections)
        self.assertNotIn(502, plan.used)
        self.assertFalse(plan.add(30005, move_command(Pos(38, 25))))

    def test_owned_robot_movement_uses_shared_reservations(self):
        raw = raid_request(71, boss=True)
        raw['teamOur']['roles'][2]['pos'] = {'x': 37, 'y': 25}
        plan = ActionPlan(Turn.load(raw), Settings())
        self.assertTrue(plan.add(501, move_command(Pos(38, 25))))
        self.assertFalse(plan.add(30005, move_command(Pos(38, 25))))
        self.assertTrue(plan.add(30005, move_command(Pos(38, 24))), plan.rejections)

    def test_night_range_visibility_wall_and_robot_action_limits(self):
        for variant in ('day', 'range', 'unseen', 'wall', 'dizzy', 'collect'):
            raw = raid_request(71, boss=True)
            command = {'action': 'attack', 'targetPos': [{'x': 36, 'y': 25}]}
            if variant == 'day': raw['roundNo'] = 70
            elif variant == 'range': command['targetPos'] = [{'x': 33, 'y': 25}]
            elif variant == 'unseen': raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:2]
            elif variant == 'wall': raw['teamEnemy']['roles'].append(unit(993, 'wall', 38, 25))
            elif variant == 'dizzy':
                raw['teamOur']['summonRobotList'][0]['abnormalState'] = 'dizzy'
            else: command = {'action': 'collect', 'targetPos': [{'x': 38, 'y': 25}]}
            plan = ActionPlan(Turn.load(raw), Settings())
            self.assertFalse(plan.add(30005, command), variant)

    def test_first_intervening_enemy_wall_is_itself_a_valid_attack_target(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'].append(unit(993, 'wall', 38, 25))
        plan = ActionPlan(Turn.load(raw), Settings())
        self.assertTrue(plan.add(30005, {'action': 'attack', 'targetPos': [{'x': 38, 'y': 25}]}), plan.rejections)

    def test_unowned_robot_cannot_receive_commands(self):
        raw = raid_request(71, boss=True); raw['teamOur']['summonRobotList'] = []
        plan = ActionPlan(Turn.load(raw), Settings())
        self.assertFalse(plan.add(30005, move_command(Pos(38, 25))))

    def test_robot_cannot_attack_friendly_units_or_claim_a_hero_controller(self):
        raw = raid_request(71, boss=True)
        raw['teamOur']['roles'][2]['pos'] = {'x': 38, 'y': 25}
        for command in ({'action': 'attack', 'targetPos': [{'x': 38, 'y': 25}]},
                        {'action': 'attack', 'controllerId': '502', 'targetPos': [{'x': 36, 'y': 25}]}):
            plan = ActionPlan(Turn.load(raw), Settings())
            self.assertFalse(plan.add(30005, command))
            self.assertEqual(plan.used, set())

    def test_robot_cannot_shoot_a_second_wall_through_the_first(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'] += [unit(993, 'wall', 38, 25), unit(994, 'wall', 37, 25)]
        plan = ActionPlan(Turn.load(raw), Settings())
        self.assertFalse(plan.add(30005, {'action': 'attack', 'targetPos': [{'x': 37, 'y': 25}]}))
        self.assertTrue(plan.add(30005, {'action': 'attack', 'targetPos': [{'x': 38, 'y': 25}]}), plan.rejections)

    def test_summon_requires_target_and_accepts_dynamic_occupancy(self):
        raw = raid_request()
        raw['teamOur']['roles'][1]['backpack'] = [ORDER]
        for occupied in (False, True):
            raw['robot']['roles'] = [robot(900, 40, 25)] if occupied else []
            plan = ActionPlan(Turn.load(raw), Settings())
            self.assertFalse(plan.add(502, {'action': 'use', 'name': ORDER}))
            self.assertTrue(plan.add(502, {'action': 'use', 'name': ORDER,
                                         'targetPos': [{'x': 40, 'y': 25}]}), plan.rejections)
            self.assertEqual(plan.summon_used, 1)

    def test_summon_rejects_base_construction_areas_npcs_and_duplicate_positions(self):
        raw = raid_request()
        raw['teamOur']['roles'][1]['backpack'] = [ORDER]
        for target in (Pos(6, 7), Pos(5, 8), Pos(33, 25), Pos(35, 25), Pos(2, 7)):
            plan = ActionPlan(Turn.load(raw), Settings())
            self.assertFalse(plan.add(502, {'action': 'use', 'name': ORDER, 'targetPos': [target.dump()]}))
        plan = ActionPlan(Turn.load(raw), Settings(), summon_positions={Pos(40, 25)})
        self.assertFalse(plan.add(502, {'action': 'use', 'name': ORDER, 'targetPos': [{'x': 40, 'y': 25}]}))

    def test_two_tasks_must_end_before_buying_exactly_one_boss_order(self):
        raw = raid_request()
        memory = finished_tasks()
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['502'], {'action': 'buy', 'name': ORDER, 'num': 1})
        raw['phaseTask'] = 'active task'; s, plan = strategy(raw, memory); s.run()
        self.assertNotEqual(plan.commands.get('502', {}).get('action'), 'buy')
        raw['phaseTask'] = ''; memory.task_points_attempted = {(1, 3, 9)}
        s, plan = strategy(raw, memory); s.run()
        self.assertNotEqual(plan.commands.get('502', {}).get('action'), 'buy')

    def test_carried_order_summons_in_the_enemy_rear_then_returns(self):
        raw = raid_request(); raw['teamOur']['roles'][1]['backpack'] = [ORDER]
        memory = finished_tasks(); s, plan = strategy(raw, memory); s.run()
        command = plan.commands['502']
        self.assertEqual(command['action'], 'use')
        self.assertEqual(command['name'], ORDER)
        pos = Pos.load(command['targetPos'][0]); self.assertGreater(pos.x, 34)
        self.assertGreater(min(distance(pos, p) for p in s.turn.footprint(s.turn.enemies[0])), 5)
        memory.record(s.turn, plan)
        raw['roundNo'] = 31; raw['teamOur']['roles'][1]['backpack'] = []
        raw['lastRoundRoleActionResults'] = {'502': True}
        memory.observe(Turn.load(raw))
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['502']['action'], 'move')
        self.assertEqual(plan.commands['502']['targetPos'], [{'x': 4, 'y': 7}])

    def test_insufficient_money_stays_at_shop_and_late_day_does_not_buy(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 119
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertNotIn('502', plan.commands)
        raw['roundNo'] = 70; raw['teamOur']['goldNum'] = 120
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertNotEqual(plan.commands.get('502', {}).get('action'), 'buy')
        raw['roundNo'] = 160
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertNotEqual(plan.commands.get('502', {}).get('name'), ORDER)

    def test_first_night_boss_attacks_controller_independently_of_our_pioneer(self):
        raw = raid_request(71, boss=True)
        raw['teamOur']['roles'][1]['pos'] = {'x': 4, 'y': 7}
        raw['robot']['roles'].append(robot(900, 13, 7))
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertEqual(plan.commands['30005'], {'action': 'attack', 'targetPos': [{'x': 36, 'y': 25}]})
        self.assertTrue(any(c.get('controllerId') == '502' for c in plan.commands.values()))

    def test_owned_boss_is_excluded_from_worker_danger_and_rocket_centres(self):
        raw = raid_request(71, boss=True)
        turn = Turn.load(raw)
        self.assertEqual(robot_danger(turn), {})
        self.assertEqual(choose_targets(turn, turn.weapons()[0], {30005: 800}), [])


if __name__ == '__main__':
    unittest.main()
