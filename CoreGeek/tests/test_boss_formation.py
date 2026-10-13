"""First-night BOSS formation regressions using observed, hand-built geometry.

These fixtures exercise decisions and simultaneous occupancy, not official
damage settlement. They contain no private simulator state or unseen crew.
"""
import copy
import unittest
from dataclasses import replace

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn, distance
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, robot, unit
from tests.test_raid_efficiency import decide


BASE = 990
FRONT = 31035
REAR = 31036
OPERATOR = Pos(13, 19)
GAP = Pos(12, 19)


def formation_arena(front=Pos(11, 19), rear=Pos(10, 19), mixed=False):
    """A left-facing gap and three guns with exactly one shared control cell."""
    raw = request(78)
    raw['mapInfo']['zones'] = []
    raw['teamOur']['playerTasks'] = []
    raw['teamOur']['roles'] = [unit(503, 'station', 2, 5),
                              unit(501, 'worker', 16, 17)]
    raw['teamEnemy']['roles'] = [unit(BASE, 'station', 14, 20),
        unit(991, 'rocket', 13, 20, health=1000),
        unit(993, 'rocket', 13, 18, health=1000),
        unit(994, 'railgun' if mixed else 'rocket', 14, 18, health=1000)]
    ring = {Pos(x, y) for x in range(12, 18) for y in range(17, 23)
            if x in (12, 17) or y in (17, 22)} - {GAP}
    raw['teamEnemy']['roles'] += [unit(2000+i, 'wall', p.x, p.y, health=1000)
                                  for i, p in enumerate(sorted(ring))]
    positions = [(FRONT, front)] + ([(REAR, rear)] if rear is not None else [])
    raw['teamOur']['summonRobotList'] = [robot(uid, p.x, p.y, health=800,
        roleType='bossRobot') for uid, p in positions]
    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
    return raw


def reflected(raw, horizontal=False, vertical=False):
    """Reflect footprints rather than treating a base anchor as a single cell."""
    raw = copy.deepcopy(raw)
    for group in (raw['teamOur']['roles'], raw['teamEnemy']['roles'],
                  raw['teamOur']['summonRobotList'], raw['robot']['roles']):
        for u in group:
            x, y = u['pos']['x'], u['pos']['y']
            base = u['roleType'] == 'station'
            u['pos'] = {'x': 40-x-int(base) if horizontal else x,
                        'y': 31-y+int(base) if vertical else y}
    return raw


def reflected_cell(p, horizontal, vertical):
    return Pos(40-p.x if horizontal else p.x, 31-p.y if vertical else p.y)


def decide_subset(raw, actor_ids, memory=None):
    """Isolate a real rear decision before any leader reservation this frame."""
    turn = Turn.load(raw)
    settings = Settings(enable_news=False, allow_base_surroundings=False,
                        boss_controller_max_walk=4)
    plan = ActionPlan(turn, settings)
    strategy = Strategy(turn, plan, memory or GameMemory(opening_complete=True))
    for boss in turn.summon_robots:
        if boss.robot_id in actor_ids:
            strategy.raider.decide(boss)
    return strategy, plan


class BossFormationTests(unittest.TestCase):
    def assert_moves_are_actual(self, strategy, plan):
        occupied = strategy.turn.occupied_cells()
        destinations = set()
        for boss in strategy.turn.summon_robots:
            command = plan.commands.get(str(boss.robot_id), {})
            if command.get('action') != 'move':
                continue
            target = Pos.load(command['targetPos'][0])
            self.assertEqual(distance(boss.pos, target), 1)
            self.assertNotIn(target, occupied, 'same-frame departure is not empty space')
            self.assertNotIn(target, destinations)
            destinations.add(target)
        self.assertEqual(plan.rejections, [])

    def assert_direct_base(self, strategy, boss, post):
        projected = replace(boss, pos=post)
        base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
        self.assertTrue(any(strategy.raider.clear_shot(projected, p)
                            for p in strategy.turn.footprint(base)), post)

    def settle(self, raw, strategy, plan):
        self.assert_moves_are_actual(strategy, plan)
        results = {}
        for actor in raw['teamOur']['summonRobotList']:
            command = plan.commands.get(str(actor['id']), {})
            if command.get('action') == 'move':
                actor['pos'] = copy.deepcopy(command['targetPos'][0])
            if command:
                results[str(actor['id'])] = True
        # The global and owned lists describe the same real positions.
        raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
        raw['roundNo'] += 1
        raw['lastRoundRoleActionResults'] = results

    def test_front_advances_through_gap_without_spending_a_shot_on_wall(self):
        raw = formation_arena()
        strategy, plan = decide(raw)
        command = plan.commands.get(str(FRONT), {})
        self.assertEqual(command, {'action': 'move', 'targetPos': [GAP.dump()]})
        self.assert_moves_are_actual(strategy, plan)
        front = next(r for r in strategy.turn.summon_robots if r.robot_id == FRONT)
        self.assert_direct_base(strategy, front, GAP)
        # The rear cannot move into the front's still-occupied starting cell.
        rear = plan.commands.get(str(REAR), {})
        if rear.get('action') == 'move':
            self.assertNotEqual(rear['targetPos'][0], front.pos.dump())

    def test_gap_entry_can_reach_common_operator_post_and_stay_there(self):
        raw = formation_arena()
        memory = GameMemory(opening_complete=True)
        reached = False
        for _ in range(7):
            strategy, plan = decide(raw, memory)
            self.assert_moves_are_actual(strategy, plan)
            front = next(r for r in strategy.turn.summon_robots if r.robot_id == FRONT)
            command = plan.commands.get(str(FRONT), {})
            if command.get('action') == 'move':
                self.assert_direct_base(strategy, front, Pos.load(command['targetPos'][0]))
            if front.pos == OPERATOR:
                reached = True
                self.assertEqual(command.get('action'), 'attack')
                base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
                self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(base))
            self.settle(raw, strategy, plan)
        self.assertTrue(reached, 'the lead BOSS must claim the shared control post')

    def test_all_reflections_advance_toward_the_actual_common_control_post(self):
        for horizontal, vertical in ((False, False), (True, False),
                                     (False, True), (True, True)):
            with self.subTest(horizontal=horizontal, vertical=vertical):
                raw = reflected(formation_arena(), horizontal, vertical)
                memory = GameMemory(opening_complete=True)
                target = reflected_cell(OPERATOR, horizontal, vertical)
                found = False
                for _ in range(7):
                    strategy, plan = decide(raw, memory)
                    self.assert_moves_are_actual(strategy, plan)
                    front = next(r for r in strategy.turn.summon_robots if r.robot_id == FRONT)
                    command = plan.commands.get(str(FRONT), {})
                    if command.get('action') == 'move':
                        self.assert_direct_base(strategy, front, Pos.load(command['targetPos'][0]))
                    found |= front.pos == target
                    self.settle(raw, strategy, plan)
                self.assertTrue(found)

    def test_reversed_robot_observation_order_does_not_create_swaps(self):
        raw = formation_arena()
        raw['teamOur']['summonRobotList'].reverse()
        raw['robot']['roles'].reverse()
        strategy, plan = decide(raw)
        self.assert_moves_are_actual(strategy, plan)
        self.assertEqual(plan.commands.get(str(FRONT)),
                         {'action': 'move', 'targetPos': [GAP.dump()]})

    def test_mixed_layout_single_robot_keeps_direct_base_fire(self):
        raw = formation_arena(rear=None,mixed=True)
        strategy, plan = decide(raw)
        command = plan.commands[str(FRONT)]
        self.assertEqual(command['action'], 'attack')
        base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
        self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(base))
        self.assertEqual(plan.rejections, [])

    def test_mixed_layout_faraway_second_robot_keeps_direct_base_fire(self):
        raw = formation_arena(rear=Pos(2, 19),mixed=True)
        strategy, plan = decide(raw)
        command = plan.commands[str(FRONT)]
        self.assertEqual(command['action'], 'attack')
        base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
        self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(base))
        self.assert_moves_are_actual(strategy, plan)

    def test_three_robots_do_not_share_a_destination_or_swap_observed_cells(self):
        raw = formation_arena()
        raw['teamOur']['summonRobotList'].append(robot(31037, 9, 19,
            health=800, roleType='bossRobot'))
        raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
        memory = GameMemory(opening_complete=True)
        found = False
        for _ in range(7):
            strategy, plan = decide(raw, memory)
            self.assert_moves_are_actual(strategy, plan)
            front = next(r for r in strategy.turn.summon_robots if r.robot_id == FRONT)
            found |= front.pos == OPERATOR
            self.settle(raw, strategy, plan)
        self.assertTrue(found)

    def test_mixed_layout_remembered_weapons_do_not_invent_control_post_vision(self):
        raw = formation_arena(mixed=True)
        memory = GameMemory(opening_complete=True)
        memory.enemy_structures.update((u.unit_id, u) for u in Turn.load(raw).enemies)
        memory.enemy_weapon_sites.update((u.pos, u.kind) for u in Turn.load(raw).enemies
                                        if u.kind in ('rocket','railgun','gatling'))
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles']
                                    if u['roleType'] not in ('rocket','railgun','gatling')]
        raw['teamOur']['roles'][1]['pos'] = Pos(2, 6).dump()
        strategy, plan = decide(raw, memory)
        # Buildings are remembered routing obstacles; they provide no allied sight.
        self.assertFalse(strategy.raider.seen_cell(OPERATOR))
        command = plan.commands[str(FRONT)]
        self.assertNotEqual(memory.robot_raids[FRONT].get('formation_action'),
                            'occupy_operator_post')
        self.assertEqual(command['action'], 'attack')
        base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
        self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(base))
        self.assert_moves_are_actual(strategy, plan)

    def test_dizzy_front_robot_is_still_an_actual_occupied_cell(self):
        raw = formation_arena()
        raw['teamOur']['summonRobotList'][0]['abnormalState'] = 'dizzy'
        raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
        strategy, plan = decide(raw)
        self.assertNotIn(str(FRONT), plan.commands)
        self.assert_moves_are_actual(strategy, plan)

    def test_front_already_at_operator_post_does_not_wander_from_direct_fire(self):
        raw = formation_arena(front=OPERATOR, rear=GAP)
        strategy, plan = decide(raw)
        for boss in strategy.turn.summon_robots:
            command = plan.commands[str(boss.robot_id)]
            self.assertEqual(command['action'], 'attack')
            base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
            self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(base))
        self.assertEqual(plan.rejections, [])

    def test_current_visible_operator_still_preempts_forward_formation(self):
        raw = formation_arena(front=GAP, rear=Pos(11, 19))
        raw['teamEnemy']['roles'].append(unit(992, 'worker', OPERATOR.x, OPERATOR.y, health=100))
        strategy, plan = decide(raw)
        self.assertEqual(plan.commands[str(FRONT)],
                         {'action': 'attack', 'targetPos': [OPERATOR.dump()]})
        self.assertEqual(strategy.memory.robot_raids[FRONT]['controller_id'], 992)
        self.assert_moves_are_actual(strategy, plan)

    def test_mixed_layout_new_live_operator_breaks_previous_base_focus(self):
        raw = formation_arena(front=OPERATOR, rear=Pos(10, 19),mixed=True)
        memory = GameMemory(opening_complete=True)
        strategy, plan = decide(raw, memory)
        self.settle(raw, strategy, plan)
        target = GAP
        raw['teamEnemy']['roles'].append(unit(992, 'pioneer', target.x, target.y, health=500))
        strategy, plan = decide(raw, memory)
        self.assertEqual(plan.commands[str(FRONT)],
                         {'action': 'attack', 'targetPos': [target.dump()]})
        self.assertEqual(strategy.memory.robot_raids[FRONT]['controller_id'], 992)
        self.assert_moves_are_actual(strategy, plan)

    def test_rear_uses_reachable_base_post_before_an_unrelated_wall(self):
        # R79 counterpart: the original front still occupies its real cell,
        # while GAP is actually free and not reserved by its own new command.
        raw = formation_arena(front=Pos(11, 19), rear=Pos(11, 18))
        strategy, plan = decide_subset(raw, {REAR})
        command = plan.commands.get(str(REAR), {})
        self.assertNotEqual(command.get('action'), 'attack')
        self.assertEqual(command.get('action'), 'move')
        self.assert_moves_are_actual(strategy, plan)
        rear = next(r for r in strategy.turn.summon_robots if r.robot_id == REAR)
        post = Pos.load(command['targetPos'][0])
        self.assert_direct_base(strategy, rear, post)

    def test_rear_waits_for_reserved_front_gap_then_uses_observed_empty_post(self):
        raw = formation_arena(front=Pos(11, 19), rear=Pos(11, 18))
        memory = GameMemory(opening_complete=True)
        strategy, plan = decide(raw, memory)
        self.assertEqual(plan.commands.get(str(FRONT)),
                         {'action': 'move', 'targetPos': [GAP.dump()]})
        self.assertNotEqual(plan.commands.get(str(REAR), {}).get('action'), 'attack')
        self.assert_moves_are_actual(strategy, plan)
        # Settle the actual front move, rather than pretending its old position
        # was available in the same simultaneous decision frame.
        self.settle(raw, strategy, plan)
        strategy, plan = decide(raw, memory)
        self.assert_moves_are_actual(strategy, plan)
        command = plan.commands[str(REAR)]
        self.assertEqual(command['action'], 'move')
        self.assertEqual(Pos.load(command['targetPos'][0]), Pos(11, 19))
        rear = next(r for r in strategy.turn.summon_robots if r.robot_id == REAR)
        self.assert_direct_base(strategy, rear, Pos.load(command['targetPos'][0]))

    def test_actual_occupied_or_reserved_control_post_is_never_entered(self):
        for occupant in ('visible_enemy', 'reserved'):
            with self.subTest(occupant=occupant):
                raw = formation_arena(front=GAP, rear=Pos(11, 19))
                if occupant == 'visible_enemy':
                    raw['teamEnemy']['roles'].append(unit(996, 'imp', OPERATOR.x, OPERATOR.y))
                strategy, plan = decide(raw)
                if occupant == 'reserved':
                    # Replan the same official frame with a prior ally reservation.
                    plan.commands.clear(); plan.used.clear(); plan.reserved.clear()
                    plan.reserved.add(OPERATOR)
                    for boss in strategy.turn.summon_robots:
                        strategy.raider.decide(boss)
                self.assert_moves_are_actual(strategy, plan)
                command = plan.commands.get(str(FRONT), {})
                if command.get('action') == 'move':
                    self.assertNotEqual(Pos.load(command['targetPos'][0]), OPERATOR)

    def test_45_degree_corner_walls_do_not_hide_a_clear_base_cell(self):
        raw = formation_arena(front=Pos(11, 19), rear=None)
        raw['teamEnemy']['roles'] = [unit(BASE, 'station', 14, 22),
            unit(2001, 'wall', 12, 19), unit(2002, 'wall', 11, 20)]
        strategy, plan = decide(raw)
        boss = strategy.turn.summon_robots[0]
        self.assertTrue(strategy.raider.clear_shot(boss, Pos(14, 22)))
        command = plan.commands[str(FRONT)]
        self.assertEqual(command['action'], 'attack')
        self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(strategy.turn.enemies[0]))

    def test_diagonal_wall_on_the_ray_still_blocks_base_fire(self):
        raw = formation_arena(front=Pos(11, 19), rear=None)
        raw['teamEnemy']['roles'] = [unit(BASE, 'station', 14, 22), unit(2001, 'wall', 12, 20)]
        strategy, plan = decide(raw)
        self.assertFalse(strategy.raider.clear_shot(strategy.turn.summon_robots[0], Pos(14, 22)))
        self.assert_moves_are_actual(strategy, plan)

    def test_failed_old_base_ray_does_not_suppress_new_clear_45_degree_ray(self):
        raw = formation_arena(front=Pos(11, 19), rear=None)
        raw['roundNo'] = 125
        raw['teamEnemy']['roles'] = [unit(BASE, 'station', 14, 22),
            unit(2001, 'wall', 12, 19), unit(2002, 'wall', 11, 20)]
        memory = GameMemory(opening_complete=True)
        memory.enemy_structures.update((u.unit_id, u) for u in Turn.load(raw).enemies)
        failed_key = (BASE, Pos(14, 21), Pos(11, 18))
        memory.robot_raids[FRONT] = dict(base_attack_failures=2,
            failed_firing={failed_key: 131}, verified_base_post=Pos(11, 18),
            verified_base_target=Pos(14, 21))
        strategy, plan = decide(raw, memory)
        self.assertTrue(strategy.raider.clear_shot(strategy.turn.summon_robots[0], Pos(14, 22)))
        command = plan.commands[str(FRONT)]
        self.assertEqual(command['action'], 'attack')
        self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(strategy.turn.enemies[0]))
        self.assertIn(failed_key, memory.robot_raids[FRONT]['failed_firing'])

    def test_an_exact_failed_ray_keeps_its_failure_cache(self):
        raw = formation_arena(front=Pos(11, 19), rear=None)
        raw['roundNo'] = 125
        raw['teamEnemy']['roles'] = [unit(BASE, 'station', 14, 22),
            unit(2001, 'wall', 12, 19), unit(2002, 'wall', 11, 20)]
        memory = GameMemory(opening_complete=True)
        memory.enemy_structures.update((u.unit_id, u) for u in Turn.load(raw).enemies)
        blocked_target = Pos(14, 22)
        failed_key = (BASE, blocked_target, Pos(11, 19))
        memory.robot_raids[FRONT] = dict(base_attack_failures=2,
                                       failed_firing={failed_key: 131})
        strategy, plan = decide(raw, memory)
        command = plan.commands.get(str(FRONT), {})
        if command.get('action') == 'attack':
            self.assertNotEqual(Pos.load(command['targetPos'][0]), blocked_target)
        self.assertIn(failed_key, memory.robot_raids[FRONT]['failed_firing'])


if __name__ == '__main__':
    unittest.main()
