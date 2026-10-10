"""Hand-counted first-night routes, conservative LOS, and bounded crew pursuit."""
import json
import unittest
from unittest.mock import patch

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn, distance, station_footprint
from agent.robot_combat import clear_attack, planning_building_blocker
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, robot, unit


BOSS = 30005
BASE = 990
CREW = 992


def arena(position=Pos(10, 10), base=Pos(8, 10)):
    """Only explicit observed units; no fabricated enemy vision or local engine."""
    raw = request(71)
    raw['mapInfo']['zones'] = []
    raw['teamOur']['playerTasks'] = []
    raw['teamOur']['roles'] = [unit(503, 'station', 1, 30)]
    raw['teamEnemy']['roles'] = [unit(BASE, 'station', base.x, base.y)]
    born = robot(BOSS, position.x, position.y, health=800, roleType='bossRobot')
    raw['teamOur']['summonRobotList'] = [born]
    raw['robot']['roles'] = [dict(born)]
    return raw


def crew(raw, uid, x, y, hp=40, gun_x=None, gun_y=None):
    raw['teamEnemy']['roles'] += [
        unit(uid + 100, 'rocket', x if gun_x is None else gun_x,
             y + 1 if gun_y is None else gun_y, health=1000),
        unit(uid, 'worker', x, y, health=hp)]


def decide(raw, memory=None, budget=4):
    turn = Turn.load(raw)
    settings = Settings(enable_news=False, allow_base_surroundings=False,
                        boss_controller_max_walk=budget)
    plan = ActionPlan(turn, settings)
    state = memory if memory is not None else GameMemory(opening_complete=True)
    strategy = Strategy(turn, plan, state)
    for owned in turn.summon_robots:
        strategy.raider.decide(owned)
    return strategy, plan


def previous_chase(memory, raw, action='move', effort=3, target=CREW):
    memory.robot_raids[BOSS] = dict(round=raw['roundNo'] - 1, stage='controller',
        pursuit_kind='controller', action=action, position=Pos(10, 10),
        target=Pos(12, 10), goal=Pos(11, 11), attack_target_id=target,
        controller_id=target, pursuit_rounds=effort)


def screened_crew(wall_hp):
    raw = arena()
    raw['teamEnemy']['roles'] += [unit(1092, 'rocket', 13, 11, health=1000),
                                  unit(CREW, 'worker', 12, 10, health=40)]
    # Eight neighbours are occupied: seven damaged walls and one real gun.
    # No two entities share a cell and the crew has an adjacent weapon.
    for i, cell in enumerate(Pos(12, 10).neighbours()):
        if cell != Pos(13, 11):
            raw['teamEnemy']['roles'].append(unit(40000 + i, 'wall',
                                                cell.x, cell.y, health=wall_hp))
    return raw


class RaidEfficiencyTests(unittest.TestCase):
    def assert_base(self, strategy, plan):
        self.assertEqual(strategy.memory.robot_raids[BOSS]['pursuit_kind'], 'base')
        command = plan.commands[str(BOSS)]
        self.assertEqual(command['action'], 'attack')
        target = Pos.load(command['targetPos'][0])
        base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
        self.assertIn(target, station_footprint(base.pos))
        self.assertEqual(plan.rejections, [])

    def test_near_direct_operator_preempts_far_low_hp_and_base(self):
        raw = arena()
        crew(raw, CREW, 18, 10, hp=1)
        crew(raw, 993, 12, 12, hp=500)
        strategy, plan = decide(raw)
        self.assertEqual(plan.commands[str(BOSS)],
            {'action': 'attack', 'targetPos': [{'x': 12, 'y': 12}]})
        self.assertEqual(strategy.memory.robot_raids[BOSS]['controller_id'], 993)
        self.assertEqual(plan.rejections, [])

    def test_far_low_hp_is_filtered_before_short_higher_hp_rank(self):
        raw = arena()
        crew(raw, CREW, 18, 10, hp=1)
        crew(raw, 993, 14, 10, hp=80)
        strategy, plan = decide(raw)
        self.assertEqual(strategy.memory.robot_raids[BOSS]['controller_id'], 993)
        self.assertEqual(plan.commands[str(BOSS)]['action'], 'move')
        self.assertEqual(distance(Pos(10, 10), Pos.load(plan.commands[str(BOSS)]['targetPos'][0])), 1)

    def test_two_step_wall_detour_keeps_operator_priority(self):
        raw = arena()
        crew(raw, CREW, 12, 10)
        raw['teamEnemy']['roles'].append(unit(40000, 'wall', 11, 10, health=1000))
        # (10,9)->(11,8) is two moves. One-move posts either cross the wall
        # or the visible gun at (12,11), so this is a genuine short detour.
        strategy, plan = decide(raw, budget=2)
        self.assertEqual(plan.commands[str(BOSS)],
            {'action': 'move', 'targetPos': [{'x': 10, 'y': 9}]})
        self.assertEqual(strategy.memory.robot_raids[BOSS]['controller_id'], CREW)
        self.assertEqual(strategy.memory.robot_raids[BOSS]['goal'], Pos(11, 8))
        self.assertEqual(plan.rejections, [])

    def test_single_shot_wall_beats_two_step_detour_with_one_round_budget(self):
        raw = arena()
        crew(raw, CREW, 12, 10)
        raw['teamEnemy']['roles'].append(unit(40000, 'wall', 11, 10, health=40))
        strategy, plan = decide(raw, budget=1)
        self.assertEqual(plan.commands[str(BOSS)],
            {'action': 'attack', 'targetPos': [{'x': 11, 'y': 10}]})
        self.assertEqual(strategy.memory.robot_raids[BOSS]['pursuit_kind'], 'controller')
        self.assertEqual(strategy.memory.robot_raids[BOSS]['stage'], 'breach')
        memory = strategy.memory
        memory.record(strategy.turn, plan)
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS): True}
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == 40000)['health'] = 0
        strategy, plan = decide(raw, memory, budget=1)
        self.assertEqual(plan.commands[str(BOSS)],
            {'action': 'attack', 'targetPos': [{'x': 12, 'y': 10}]})
        self.assertEqual(memory.robot_raids[BOSS]['stage'], 'controller')
        # The one-round chase budget is spent, but a new direct shot still wins.
        self.assertEqual(strategy.raider.diag.records[BOSS]['pursuit_rounds'], 1)

    def test_fully_screened_crew_uses_cheap_wall_then_actual_opening(self):
        raw = screened_crew(40)
        memory = GameMemory(opening_complete=True)
        strategy, plan = decide(raw, memory)
        self.assertEqual(plan.commands[str(BOSS)],
            {'action': 'attack', 'targetPos': [{'x': 11, 'y': 10}]})
        self.assertEqual(memory.robot_raids[BOSS]['pursuit_kind'], 'controller')
        memory.record(strategy.turn, plan)
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS): True}
        next(u for u in raw['teamEnemy']['roles'] if u['pos'] == {'x': 11, 'y': 10})['health'] = 0
        strategy, plan = decide(raw, memory)
        self.assertEqual(plan.commands[str(BOSS)],
            {'action': 'attack', 'targetPos': [{'x': 12, 'y': 10}]})
        self.assertEqual(memory.robot_raids[BOSS]['controller_id'], CREW)

    def test_thousand_hp_screen_is_not_a_quick_breach(self):
        raw = screened_crew(1000)
        strategy, plan = decide(raw)
        self.assert_base(strategy, plan)
        self.assertEqual(strategy.raider.diag.records[BOSS]['fallback_reason'], 'controller_unreachable')
        # 1000/40 = 25 wall hits, greater than the four-round pursuit budget.
        self.assertEqual(strategy.raider.diag.records[BOSS]['controller_budget'], 4)

    def test_five_move_minimum_route_falls_back_at_four(self):
        raw = arena()
        crew(raw, CREW, 18, 10)
        strategy, plan = decide(raw)
        self.assert_base(strategy, plan)
        record = strategy.raider.diag.records[BOSS]
        self.assertEqual(record['fallback_reason'], 'controller_detour_too_long')
        candidate = next(e for e in record['events'] if e['kind'] == 'candidate')
        # Distance eight minus range three is five; an unobstructed five-move
        # route exists, so this assertion does not derive cost from the policy.
        self.assertEqual(candidate['firing']['cost'], 5)
        self.assertFalse(candidate['efficient'])

    def test_route_at_configured_five_step_limit_is_eligible(self):
        raw = arena()
        crew(raw, CREW, 18, 10)
        strategy, plan = decide(raw, budget=5)
        self.assertEqual(strategy.memory.robot_raids[BOSS]['pursuit_kind'], 'controller')
        self.assertEqual(strategy.memory.robot_raids[BOSS]['controller_id'], CREW)
        self.assertEqual(plan.commands[str(BOSS)]['action'], 'move')
        candidate = next(e for e in strategy.raider.diag.records[BOSS]['events']
                         if e['kind'] == 'candidate')
        self.assertEqual(candidate['firing']['cost'], 5)
        self.assertTrue(candidate['efficient'])

    def test_unreachable_operator_does_not_forbid_an_attackable_base(self):
        raw = arena()
        crew(raw, CREW, 20, 20)
        raw['mapInfo']['zones'] = [{'neutralType': 'vendor', 'pos': p.dump()}
                                   for p in Pos(10, 10).neighbours()]
        strategy, plan = decide(raw)
        self.assert_base(strategy, plan)
        self.assertEqual(strategy.raider.diag.records[BOSS]['fallback_reason'], 'controller_unreachable')

    def test_visible_gun_screen_is_planning_only_not_new_rule_gate(self):
        raw = arena()
        crew(raw, CREW, 12, 10, gun_x=11, gun_y=10)
        turn = Turn.load(raw)
        owned = turn.summon_robots[0]
        self.assertTrue(clear_attack(turn, owned, Pos(12, 10)))
        blocker = planning_building_blocker(turn, owned.pos, Pos(12, 10))
        self.assertEqual(blocker[0], Pos(11, 10))
        self.assertEqual(blocker[1].kind, 'rocket')
        plan = ActionPlan(turn, Settings())
        self.assertTrue(plan.add(BOSS, {'action': 'attack', 'targetPos': [{'x': 12, 'y': 10}]}),
                        plan.rejections)
        # Local planning can choose efficiency over an unverified shooting line,
        # without declaring it an official illegal robot command.
        strategy, plan = decide(raw, budget=0)
        self.assert_base(strategy, plan)

    def test_base_anchor_through_other_cell_uses_exposed_footprint(self):
        raw = arena(Pos(33, 9), Pos(30, 10))
        strategy, plan = decide(raw)
        self.assert_base(strategy, plan)
        self.assertEqual(plan.commands[str(BOSS)],
            {'action': 'attack', 'targetPos': [{'x': 31, 'y': 9}]})
        blocker = planning_building_blocker(strategy.turn, Pos(33, 9), Pos(30, 10))
        self.assertIsNotNone(blocker)
        self.assertEqual(blocker[1].unit_id, BASE)

    def test_diagonal_base_corner_contact_does_not_block_plan(self):
        raw = arena(Pos(29, 9), Pos(30, 10))
        strategy, plan = decide(raw)
        # The segment touches (30,9) only at (29.5,9.5), not its interior.
        self.assertIsNone(planning_building_blocker(strategy.turn, Pos(29, 9), Pos(30, 10)))
        self.assertTrue(strategy.raider.clear_shot(strategy.turn.summon_robots[0], Pos(30, 10)))
        self.assert_base(strategy, plan)

    def test_failed_base_cell_can_use_another_visible_cell(self):
        raw = arena(Pos(33, 9), Pos(30, 10))
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS): False}
        memory = GameMemory(opening_complete=True)
        memory.robot_raids[BOSS] = dict(round=71, stage='base', pursuit_kind='base',
            action='attack', position=Pos(33, 9), target=Pos(31, 9), goal=Pos(33, 9),
            attack_target_id=BASE)
        strategy, plan = decide(raw, memory)
        self.assert_base(strategy, plan)
        self.assertEqual(plan.commands[str(BOSS)]['targetPos'], [{'x': 31, 'y': 10}])

    def test_chase_budget_is_carried_when_controller_identity_changes(self):
        raw = arena()
        raw['roundNo'] = 72
        crew(raw, 993, 14, 14)
        memory = GameMemory(opening_complete=True)
        previous_chase(memory, raw, effort=3, target=CREW)
        strategy, plan = decide(raw, memory)
        self.assert_base(strategy, plan)
        self.assertEqual(strategy.raider.diag.records[BOSS]['pursuit_rounds'], 4)
        self.assertEqual(strategy.raider.diag.records[BOSS]['fallback_reason'], 'controller_chase_budget')
        self.assertNotIn('controller_id', memory.robot_raids[BOSS])

    def test_two_step_detour_is_rejected_when_only_one_step_budget_remains(self):
        raw = arena()
        raw['roundNo'] = 72
        crew(raw, CREW, 12, 10)
        raw['teamEnemy']['roles'].append(unit(40000, 'wall', 11, 10, health=1000))
        memory = GameMemory(opening_complete=True)
        previous_chase(memory, raw, effort=2)
        strategy, plan = decide(raw, memory, budget=4)
        self.assert_base(strategy, plan)
        record = strategy.raider.diag.records[BOSS]
        self.assertEqual(record['pursuit_rounds'], 3)
        self.assertEqual(record['controller_budget_remaining'], 1)
        self.assertEqual(record['fallback_reason'], 'controller_detour_too_long')
        candidate = next(e for e in record['events'] if e['kind'] == 'candidate')
        self.assertEqual(candidate['firing']['cost'], 2)
        self.assertFalse(candidate['efficient'])

    def test_failed_or_missing_controller_attack_does_not_clear_effort(self):
        for feedback in (False, None):
            with self.subTest(feedback=feedback):
                raw = arena()
                raw['roundNo'] = 72
                crew(raw, CREW, 14, 14)
                if feedback is not None:
                    raw['lastRoundRoleActionResults'] = {str(BOSS): feedback}
                memory = GameMemory(opening_complete=True)
                previous_chase(memory, raw, action='attack', effort=3)
                strategy, plan = decide(raw, memory)
                self.assert_base(strategy, plan)
                self.assertEqual(strategy.raider.diag.records[BOSS]['pursuit_rounds'], 4)
                self.assertEqual(strategy.raider.diag.records[BOSS]['fallback_reason'], 'controller_chase_budget')

    def test_previous_legal_controller_attack_resets_effort_without_claiming_hit(self):
        raw = arena()
        raw['roundNo'] = 72
        crew(raw, CREW, 14, 14, hp=500)
        raw['lastRoundRoleActionResults'] = {str(BOSS): True}
        memory = GameMemory(opening_complete=True)
        previous_chase(memory, raw, action='attack', effort=3)
        strategy, plan = decide(raw, memory)
        self.assertEqual(memory.robot_raids[BOSS]['pursuit_kind'], 'controller')
        self.assertEqual(memory.robot_raids[BOSS]['pursuit_rounds'], 0)
        self.assertEqual(plan.commands[str(BOSS)]['action'], 'move')
        self.assertEqual(next(u.health for u in strategy.turn.enemies if u.unit_id == CREW), 500)

    def test_siege_focus_prevents_short_retarget_but_direct_crew_preempts_it(self):
        raw = arena()
        crew(raw, CREW, 18, 10)
        memory = GameMemory(opening_complete=True)
        strategy, plan = decide(raw, memory)
        self.assert_base(strategy, plan)
        self.assertEqual(memory.robot_raids[BOSS]['siege_until'], 75)
        memory.record(strategy.turn, plan)
        raw['roundNo'] = 72
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == CREW)['pos'] = {'x': 14, 'y': 14}
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == CREW + 100)['pos'] = {'x': 14, 'y': 15}
        strategy, plan = decide(raw, memory)
        self.assert_base(strategy, plan)
        self.assertEqual(memory.robot_raids[BOSS]['fallback_reason'], 'siege_focus')
        self.assertEqual(memory.robot_raids[BOSS]['siege_until'], 75)
        memory.record(strategy.turn, plan)
        raw['roundNo'] = 73
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == CREW)['pos'] = {'x': 12, 'y': 12}
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == CREW + 100)['pos'] = {'x': 12, 'y': 13}
        strategy, plan = decide(raw, memory)
        self.assertEqual(plan.commands[str(BOSS)]['targetPos'], [{'x': 12, 'y': 12}])
        self.assertEqual(memory.robot_raids[BOSS]['pursuit_kind'], 'controller')
        self.assertNotIn('siege_until', memory.robot_raids[BOSS])
        self.assertNotIn('fallback_reason', memory.robot_raids[BOSS])

    def test_siege_expiry_reconsiders_short_non_direct_operator(self):
        raw = arena()
        crew(raw, CREW, 18, 10)
        memory = GameMemory(opening_complete=True)
        strategy, plan = decide(raw, memory)
        memory.record(strategy.turn, plan)
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == CREW)['pos'] = {'x': 14, 'y': 14}
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == CREW + 100)['pos'] = {'x': 14, 'y': 15}
        for number in (72, 73, 74):
            raw['roundNo'] = number
            strategy, plan = decide(raw, memory)
            self.assert_base(strategy, plan)
            memory.record(strategy.turn, plan)
        raw['roundNo'] = 75
        strategy, plan = decide(raw, memory)
        self.assertEqual(memory.robot_raids[BOSS]['pursuit_kind'], 'controller')
        self.assertEqual(plan.commands[str(BOSS)]['action'], 'move')

    def test_two_bosses_reserve_different_single_steps(self):
        raw = arena(base=Pos(25, 10))
        other = robot(30006, 10, 11, health=800, roleType='bossRobot')
        raw['teamOur']['summonRobotList'].append(other)
        raw['robot']['roles'].append(dict(other))
        strategy, plan = decide(raw)
        targets = []
        for owned in strategy.turn.summon_robots:
            command = plan.commands[str(owned.robot_id)]
            self.assertEqual(command['action'], 'move')
            destination = Pos.load(command['targetPos'][0])
            self.assertEqual(distance(owned.pos, destination), 1)
            targets.append(destination)
        self.assertEqual(len(set(targets)), 2)
        self.assertEqual(plan.reserved, set(targets))
        self.assertEqual(plan.rejections, [])

    def test_zero_budget_means_direct_only_and_never_hides_direct_priority(self):
        raw = arena()
        crew(raw, CREW, 14, 14)
        strategy, plan = decide(raw, budget=0)
        self.assert_base(strategy, plan)
        raw = arena()
        crew(raw, CREW, 12, 12, hp=500)
        strategy, plan = decide(raw, budget=0)
        self.assertEqual(plan.commands[str(BOSS)]['targetPos'], [{'x': 12, 'y': 12}])
        self.assertEqual(strategy.memory.robot_raids[BOSS]['pursuit_kind'], 'controller')

    def test_hidden_cannon_crew_is_not_invented_to_fill_a_priority(self):
        raw = arena()
        raw['teamEnemy']['roles'].append(unit(1092, 'rocket', 12, 11, health=1000))
        strategy, plan = decide(raw)
        self.assert_base(strategy, plan)
        self.assertEqual(strategy.raider.diag.records[BOSS]['operator_count'], 0)
        self.assertIsNone(strategy.raider.diag.records[BOSS]['fallback_reason'])
        self.assertNotIn('controller_id', strategy.memory.robot_raids[BOSS])

    def test_budget_config_validates_type_and_bounds(self):
        for value in (0, 4, 30):
            with patch('app.config.Path.read_text', return_value=json.dumps({'boss_controller_max_walk': value})):
                self.assertEqual(Settings.load('synthetic.json').boss_controller_max_walk, value)
        for value in (-1, 31, True, 4.0, '4'):
            with self.subTest(value=value), patch('app.config.Path.read_text',
                    return_value=json.dumps({'boss_controller_max_walk': value})):
                with self.assertRaises(ValueError):
                    Settings.load('synthetic.json')


if __name__ == '__main__':
    unittest.main()
