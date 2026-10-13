"""First-night coordinated BOSS siege using explicit, observed geometry.

The damaged-wall settlement below is a small command regression, not an
official duel simulation. No robot supplies vision or fabricates live heroes.
All moves retain actual simultaneous occupancy and each attack is checked
against the observed range-three line before local damage is settled.
"""
import copy
import unittest
from dataclasses import replace

from agent.protocol import Pos, Turn, distance
from app.service.memory import GameMemory
from tests.fixtures import request, robot, unit
from tests.test_boss_formation import (BASE, FRONT, REAR, GAP, OPERATOR,
    formation_arena, reflected, reflected_cell)
from tests.test_raid_efficiency import decide


THIRD = 31037
WALL = 42000
WALL_POS = Pos(14, 22)
CREW = 43000
PROTECTED_POST = Pos(14, 18)


def siege_arena(wall_hp=120, positions=None, visible_crew=True):
    """Image-one geometry translated to a safe interior map coordinate."""
    raw = request(71)
    raw['mapInfo']['zones'] = []
    raw['teamOur']['playerTasks'] = []
    raw['teamOur']['roles'] = [unit(503, 'station', 30, 8),
                              unit(501, 'worker', 18, 19)]
    raw['teamEnemy']['roles'] = [unit(BASE, 'station', 14, 20),
        unit(991, 'rocket', 13, 19, health=1000),
        unit(993, 'rocket', 13, 18, health=1000),
        unit(994, 'rocket', 15, 18, health=1000)]
    ring = {Pos(x, y) for x in range(12, 18) for y in range(17, 23)
            if x in (12, 17) or y in (17, 22)}
    raw['teamEnemy']['roles'] += [unit(WALL if p == WALL_POS else 44000+i,
        'wall', p.x, p.y, health=wall_hp if p == WALL_POS else 1000)
        for i, p in enumerate(sorted(ring))]
    if visible_crew:
        raw['teamEnemy']['roles'].append(unit(CREW, 'worker', 14, 18, health=220))
    positions = positions or (Pos(14, 23), Pos(14, 24), Pos(14, 25))
    raw['teamOur']['summonRobotList'] = [robot(uid, p.x, p.y,
        health=800, roleType='bossRobot') for uid, p in zip((FRONT, REAR, THIRD), positions)]
    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
    return raw


def committed_state(raw, horizontal=False, vertical=False):
    wall = reflected_cell(WALL_POS, horizontal, vertical)
    return GameMemory(opening_complete=True, boss_raid={'wall_assault': {
        'wall_id': WALL, 'wall_pos': wall,
        'side': 'south' if vertical else 'north',
        'spawns': [Pos.load(u['pos']) for u in raw['teamOur']['summonRobotList']]}})


class WallAssaultControlTests(unittest.TestCase):
    def assert_actual_commands(self, strategy, plan):
        occupied = strategy.turn.occupied_cells()
        destinations = set()
        for boss in strategy.turn.summon_robots:
            command = plan.commands.get(str(boss.robot_id), {})
            self.assertLessEqual(len(command.get('targetPos', [])), 1)
            if command.get('action') == 'move':
                target = Pos.load(command['targetPos'][0])
                self.assertEqual(distance(boss.pos, target), 1)
                self.assertNotIn(target, occupied, 'ally movement has not yet settled')
                self.assertNotIn(target, destinations)
                destinations.add(target)
            elif command.get('action') == 'attack':
                target = Pos.load(command['targetPos'][0])
                self.assertGreater(distance(boss.pos, target), 0)
                self.assertLessEqual(distance(boss.pos, target), 3)
                self.assertTrue(strategy.raider.clear_shot(boss, target))
        self.assertEqual(plan.rejections, [])

    def settle(self, raw, strategy, plan):
        """Accumulate legal attacks together; do not optimistically remove walls."""
        self.assert_actual_commands(strategy, plan)
        damage = {}
        for boss in strategy.turn.summon_robots:
            command = plan.commands.get(str(boss.robot_id), {})
            if command.get('action') == 'attack':
                target = Pos.load(command['targetPos'][0])
                victim = next(u for u in strategy.turn.enemies
                              if target in strategy.turn.footprint(u) and u.health > 0)
                damage[victim.unit_id] = damage.get(victim.unit_id, 0) + boss.attack_power
        for unit_raw in raw['teamEnemy']['roles']:
            unit_raw['health'] -= damage.get(unit_raw['id'], 0)
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['health'] > 0]
        for boss in raw['teamOur']['summonRobotList']:
            command = plan.commands.get(str(boss['id']), {})
            if command.get('action') == 'move':
                boss['pos'] = copy.deepcopy(command['targetPos'][0])
        raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
        raw['roundNo'] += 1
        raw['lastRoundRoleActionResults'] = {uid: True for uid in plan.commands}

    def assert_base_attack(self, strategy, plan, uid):
        command = plan.commands[str(uid)]
        self.assertEqual(command['action'], 'attack')
        base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
        self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(base))

    def test_three_in_range_bosses_focus_one_committed_wall(self):
        raw = siege_arena()
        strategy, plan = decide(raw, committed_state(raw))
        for uid in (FRONT, REAR, THIRD):
            self.assertEqual(plan.commands[str(uid)],
                             {'action': 'attack', 'targetPos': [WALL_POS.dump()]})
        self.assert_actual_commands(strategy, plan)

    def test_north_and_south_mirrors_focus_the_same_real_wall(self):
        for horizontal, vertical in ((False, False), (True, False),
                                     (False, True), (True, True)):
            with self.subTest(horizontal=horizontal, vertical=vertical):
                raw = reflected(siege_arena(), horizontal, vertical)
                strategy, plan = decide(raw, committed_state(raw, horizontal, vertical))
                target = reflected_cell(WALL_POS, horizontal, vertical)
                for uid in (FRONT, REAR, THIRD):
                    self.assertEqual(plan.commands[str(uid)],
                                     {'action': 'attack', 'targetPos': [target.dump()]})
                self.assert_actual_commands(strategy, plan)

    def test_west_protected_operator_uses_the_committed_south_wall(self):
        # Image two: crew to the left of the base, robots below it. This is
        # intentionally a different gun orientation, not a vertical mirror.
        raw = siege_arena()
        positions = {991: Pos(13, 21), 993: Pos(14, 21), 994: Pos(13, 19),
                     CREW: Pos(13, 20)}
        south = Pos(15, 17)
        for observed in raw['teamEnemy']['roles']:
            if observed['id'] in positions:
                observed['pos'] = positions[observed['id']].dump()
            elif observed['id'] == WALL:
                observed['id'], observed['health'] = 45000, 1000
            elif observed['roleType'] == 'wall' and Pos.load(observed['pos']) == south:
                observed['id'], observed['health'] = WALL, 120
        for observed, post in zip(raw['teamOur']['summonRobotList'],
                                   (Pos(15, 16), Pos(15, 15), Pos(15, 14))):
            observed['pos'] = post.dump()
        raw['teamOur']['roles'][1]['pos'] = Pos(16, 18).dump()
        raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
        state = committed_state(raw)
        state.boss_raid['wall_assault'].update(wall_pos=south, side='south')
        strategy, plan = decide(raw, state)
        for uid in (FRONT, REAR, THIRD):
            self.assertEqual(plan.commands[str(uid)],
                             {'action': 'attack', 'targetPos': [south.dump()]})
        self.assert_actual_commands(strategy, plan)

    def test_wall_stays_target_until_actual_destruction_not_planned_damage(self):
        raw = siege_arena(wall_hp=80)
        memory = committed_state(raw)
        strategy, plan = decide(raw, memory)
        # Two shots suffice locally, but all three decide against the same
        # actual positive-health wall before end-of-round damage settlement.
        for uid in (FRONT, REAR, THIRD):
            self.assertEqual(plan.commands[str(uid)]['targetPos'], [WALL_POS.dump()])
        self.assertEqual(next(u for u in raw['teamEnemy']['roles'] if u['id'] == WALL)['health'], 80)
        self.settle(raw, strategy, plan)
        self.assertNotIn(WALL, [u['id'] for u in raw['teamEnemy']['roles']])
        strategy, plan = decide(raw, memory)
        for command in plan.commands.values():
            if command.get('action') == 'attack':
                self.assertNotEqual(command['targetPos'], [WALL_POS.dump()])
                self.assertNotEqual(command['targetPos'], [PROTECTED_POST.dump()])
        self.assert_actual_commands(strategy, plan)

    def test_failed_wall_shot_does_not_pretend_breach_was_completed(self):
        raw = siege_arena(wall_hp=120)
        memory = committed_state(raw)
        strategy, plan = decide(raw, memory)
        # Next authoritative observation still contains the undamaged wall.
        raw['roundNo'] += 1
        raw['lastRoundRoleActionResults'] = {uid: False for uid in plan.commands}
        strategy, plan = decide(raw, memory)
        for command in plan.commands.values():
            if command.get('action') == 'attack':
                self.assertEqual(command['targetPos'], [WALL_POS.dump()])
        self.assert_actual_commands(strategy, plan)

    def test_observed_zero_health_wall_opens_the_base_phase(self):
        raw = siege_arena()
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == WALL)['health'] = 0
        strategy, plan = decide(raw, committed_state(raw))
        for command in plan.commands.values():
            if command.get('action') == 'attack':
                self.assertNotEqual(command['targetPos'], [WALL_POS.dump()])
                self.assertNotEqual(command['targetPos'], [PROTECTED_POST.dump()])
        self.assert_actual_commands(strategy, plan)

    def test_out_of_range_rear_moves_before_it_can_attack_the_common_wall(self):
        raw = siege_arena(positions=(Pos(14, 23), Pos(14, 24), Pos(14, 26)))
        strategy, plan = decide(raw, committed_state(raw))
        self.assertEqual(plan.commands[str(THIRD)]['action'], 'move')
        self.assertNotEqual(plan.commands[str(THIRD)].get('targetPos'), [WALL_POS.dump()])
        self.assert_actual_commands(strategy, plan)

    def test_breached_wall_leads_all_three_bosses_to_base_fire_without_crew_chase(self):
        for hp in (80, 120):
            with self.subTest(wall_health=hp):
                raw = siege_arena(wall_hp=hp)
                memory = committed_state(raw)
                all_firing = False
                for _ in range(25):
                    strategy, plan = decide(raw, memory)
                    self.assert_actual_commands(strategy, plan)
                    if not any(u['id'] == WALL for u in raw['teamEnemy']['roles']):
                        for command in plan.commands.values():
                            if command.get('action') == 'attack':
                                base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
                                self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(base))
                        if all(plan.commands.get(str(uid), {}).get('action') == 'attack'
                               for uid in (FRONT, REAR, THIRD)):
                            for uid in (FRONT, REAR, THIRD):
                                self.assert_base_attack(strategy, plan, uid)
                            all_firing = True
                            break
                    self.settle(raw, strategy, plan)
                    self.assertLessEqual(raw['roundNo'], 100)
                self.assertTrue(all_firing, 'the front must release a firing lane for following BOSSes')

    def test_hidden_crew_memory_is_geometry_not_an_attack_target_after_breach(self):
        raw = siege_arena(visible_crew=False)
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['id'] != WALL]
        raw['teamOur']['roles'][1]['pos'] = Pos(30, 7).dump()
        memory = committed_state(raw)
        memory.robot_raids[FRONT] = dict(controller_id=CREW,
            controller_pos=PROTECTED_POST, controller_health=40,
            action='attack', target=PROTECTED_POST, position=Pos(14, 23), round=70)
        strategy, plan = decide(raw, memory)
        self.assertFalse(strategy.raider.seen_cell(PROTECTED_POST))
        for command in plan.commands.values():
            if command.get('action') == 'attack':
                self.assertNotEqual(command['targetPos'], [PROTECTED_POST.dump()])
        self.assert_actual_commands(strategy, plan)

    def test_dizzy_boss_does_not_attack_and_remains_a_real_obstacle(self):
        raw = siege_arena()
        raw['teamOur']['summonRobotList'][0]['abnormalState'] = 'dizzy'
        raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
        strategy, plan = decide(raw, committed_state(raw))
        self.assertNotIn(str(FRONT), plan.commands)
        self.assert_actual_commands(strategy, plan)

    def test_group_base_lock_overrides_a_visible_partial_operator(self):
        raw = formation_arena(front=OPERATOR, rear=GAP, mixed=True)
        raw['teamEnemy']['roles'].append(unit(CREW, 'worker', 13, 21, health=1))
        strategy, plan = decide(raw)
        self.assertTrue(strategy.raider.group_base_ready())
        for uid in (FRONT, REAR):
            self.assert_base_attack(strategy, plan, uid)
        self.assert_actual_commands(strategy, plan)

    def test_group_base_lock_requires_an_actual_occupied_best_control_post(self):
        raw = formation_arena(front=GAP, rear=Pos(11, 19), mixed=True)
        strategy, _ = decide(raw)
        self.assertFalse(strategy.raider.group_base_ready())

    def test_group_base_lock_requires_all_living_bosses_currently_in_range(self):
        raw = formation_arena(front=OPERATOR, rear=Pos(2, 19), mixed=True)
        strategy, _ = decide(raw)
        self.assertFalse(strategy.raider.group_base_ready())

    def test_group_base_lock_requires_every_living_boss_to_be_able_to_act(self):
        raw = formation_arena(front=OPERATOR, rear=GAP, mixed=True)
        raw['teamOur']['summonRobotList'][1]['abnormalState'] = 'dizzy'
        raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
        strategy, _ = decide(raw)
        self.assertFalse(strategy.raider.group_base_ready())

    def test_group_base_lock_rejects_a_real_wall_blocking_one_boss(self):
        raw = formation_arena(front=OPERATOR, rear=Pos(11, 19), mixed=True)
        raw['teamEnemy']['roles'].append(unit(WALL, 'wall', GAP.x, GAP.y, health=1000))
        strategy, _ = decide(raw)
        self.assertFalse(strategy.raider.group_base_ready())

    def test_dead_extra_boss_does_not_veto_the_live_group_base_lock(self):
        raw = formation_arena(front=OPERATOR, rear=GAP, mixed=True)
        raw['teamOur']['summonRobotList'].append(robot(THIRD, 2, 19,
            health=0, roleType='bossRobot'))
        raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
        strategy, plan = decide(raw)
        self.assertTrue(strategy.raider.group_base_ready())
        for uid in (FRONT, REAR):
            self.assert_base_attack(strategy, plan, uid)
        self.assertNotIn(str(THIRD), plan.commands)
        self.assert_actual_commands(strategy, plan)


if __name__ == '__main__':
    unittest.main()
