"""Real robot commands for the user's scouted layouts, with ordinary sight.

These observations are synthetic unit tests, not a local game simulation or
official match result. Inferred gunner positions never become visible units.
"""
import unittest
from dataclasses import replace

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Robot, Unit, distance
from agent.robot_combat import enemy_at
from agent.summoning import layout_operator_positions, scouted_spawn_position
from app.config import Settings
from app.service.memory import GameMemory
from tests.test_scouted_spawn import OPERATOR, reflect, scene


BOSSES = (30005, 30006)
CREW = 1100


def battle(gap=None, vertical_guns=False, visible_operator=True,
           horizontal=False, vertical=False, two=True):
    layout = scene(gap, vertical_guns, visible_operator, horizontal, vertical)
    settings = Settings(enable_news=False, allow_base_surroundings=False,
                        enable_first_night_defense=False, boss_controller_max_walk=4)
    first = scouted_spawn_position(layout, settings)
    points = [first]
    if two:
        points.append(scouted_spawn_position(layout, settings, pending=points))
    observer = reflect(Pos(14, 18), horizontal, vertical)
    # Ordinary worker sight reaches all three guns and the real gunner. The
    # BOSS itself contributes no sight. Buildings do not obstruct this sight.
    ours = (Unit(503, Pos(1, 30), 'station', 1500, level=1),
            Unit(501, observer, 'worker', 500, capacity=100))
    robots = tuple(Robot(uid, pos, 800, 'bossRobot') for uid, pos in zip(BOSSES, points))
    return replace(layout, round_no=71, is_day=False, ours=ours,
                   robots=robots, summon_robots=robots), settings


def decide(turn, settings, memory=None):
    memory = memory if memory is not None else GameMemory(opening_complete=True)
    # The real day-one summon flow records these only after a scouted-position
    # use has been confirmed. This unit-level fixture starts at that deployment.
    memory.boss_raid.setdefault('scouted_spawns', [r.pos for r in turn.summon_robots])
    plan = ActionPlan(turn, settings)
    strategy = Strategy(turn, plan, memory)
    for robot in turn.summon_robots:
        strategy.raider.decide(robot)
    return strategy, plan


class LayoutRaiderTests(unittest.TestCase):
    def assert_attack(self, strategy, plan, robot, target):
        command = plan.commands.get(str(robot.robot_id))
        self.assertEqual(command, {'action': 'attack', 'targetPos': [target.dump()]})
        self.assertLessEqual(distance(robot.pos, target), 3)
        self.assertGreater(distance(robot.pos, target), 0)
        self.assertIsNotNone(enemy_at(strategy.turn, target))
        self.assertNotIn('controllerId', command)
        self.assertEqual(plan.rejections, [])

    def assert_controller(self, strategy, robot):
        job = strategy.memory.robot_raids[robot.robot_id]
        self.assertEqual(job['pursuit_kind'], 'controller')
        self.assertEqual(job['controller_id'], CREW)

    def test_gap_pictures_and_all_mirrors_attack_real_crew_without_moving(self):
        for horizontal, vertical in ((False, False), (True, False), (False, True), (True, True)):
            for kind in ('worker', 'pioneer'):
                with self.subTest(horizontal=horizontal, vertical=vertical, role=kind):
                    turn, settings = battle(Pos(13, 14), horizontal=horizontal, vertical=vertical)
                    turn = replace(turn, enemies=tuple(replace(u, kind=kind) if u.unit_id == CREW else u
                                                       for u in turn.enemies))
                    target = reflect(OPERATOR, horizontal, vertical)
                    s, plan = decide(turn, settings)
                    self.assertEqual(len(plan.commands), 2)
                    for robot in turn.summon_robots:
                        self.assertTrue(s.raider.seen_cell(target))
                        self.assert_attack(s, plan, robot, target)
                        self.assert_controller(s, robot)

    def test_vertical_gun_picture_and_mirrors_attack_outer_ring_crew(self):
        for horizontal, vertical in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(horizontal=horizontal, vertical=vertical):
                turn, settings = battle(vertical_guns=True, horizontal=horizontal, vertical=vertical)
                target = reflect(Pos(13, 15), horizontal, vertical)
                s, plan = decide(turn, settings)
                for robot in turn.summon_robots:
                    self.assert_attack(s, plan, robot, target)
                    self.assert_controller(s, robot)

    def test_closed_picture_and_mirrors_start_on_same_wall_to_clear_crew(self):
        for horizontal, vertical in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(horizontal=horizontal, vertical=vertical):
                turn, settings = battle(horizontal=horizontal, vertical=vertical)
                wall = reflect(Pos(13, 15), horizontal, vertical)
                s, plan = decide(turn, settings)
                for robot in turn.summon_robots:
                    self.assert_attack(s, plan, robot, wall)
                    self.assert_controller(s, robot)
                    self.assertEqual(s.memory.robot_raids[robot.robot_id]['stage'], 'breach')

    def test_confirmed_damaging_wall_attacks_continue_past_four_rounds_then_hit_crew(self):
        turn, settings = battle()
        memory = GameMemory(opening_complete=True)
        wall = Pos(13, 15)
        for number in range(71, 80):
            # Two BOSS hits per preceding turn: 40+40 damage. No movement or
            # robot-provided vision is simulated, and the wall remains alive.
            hp = 1000-80*(number-71)
            frame = replace(turn, round_no=number, action_results={str(uid): True for uid in BOSSES}
                            if number > 71 else {},
                            enemies=tuple(replace(u, health=hp) if u.pos == wall and u.kind == 'wall' else u
                                          for u in turn.enemies))
            s, plan = decide(frame, settings, memory)
            for robot in frame.summon_robots:
                self.assert_attack(s, plan, robot, wall)
                self.assert_controller(s, robot)
            memory.record(frame, plan)
        # On actual removal the same original spawn immediately sees a clear
        # attack on the live gunner; no chase lock or stale wall remains.
        frame = replace(turn, round_no=80, action_results={str(uid): True for uid in BOSSES},
                        enemies=tuple(u for u in turn.enemies if u.pos != wall))
        s, plan = decide(frame, settings, memory)
        for robot in frame.summon_robots:
            self.assert_attack(s, plan, robot, OPERATOR)
            self.assert_controller(s, robot)
            self.assertEqual(memory.robot_raids[robot.robot_id]['stage'], 'controller')

    def test_actual_wall_damage_without_command_feedback_also_preserves_breach(self):
        turn, settings = battle(two=False)
        memory = GameMemory(opening_complete=True)
        wall = Pos(13, 15)
        for number in range(71, 78):
            frame = replace(turn, round_no=number, action_results={},
                            enemies=tuple(replace(u, health=1000-40*(number-71))
                                          if u.pos == wall and u.kind == 'wall' else u
                                          for u in turn.enemies))
            s, plan = decide(frame, settings, memory)
            self.assert_attack(s, plan, frame.summon_robots[0], wall)
            self.assert_controller(s, frame.summon_robots[0])
            memory.record(frame, plan)

    def test_healed_crew_is_rechecked_and_attacked_every_round(self):
        turn, settings = battle(Pos(13, 14))
        memory = GameMemory(opening_complete=True)
        for number, hp in ((71, 40), (72, 500), (73, 420), (74, 500), (75, 420), (76, 500)):
            frame = replace(turn, round_no=number, action_results={str(uid): True for uid in BOSSES}
                            if number > 71 else {},
                            enemies=tuple(replace(u, health=hp) if u.unit_id == CREW else u
                                          for u in turn.enemies))
            s, plan = decide(frame, settings, memory)
            for robot in frame.summon_robots:
                self.assert_attack(s, plan, robot, OPERATOR)
                self.assert_controller(s, robot)
            memory.record(frame, plan)

    def test_lost_observer_and_hidden_crew_never_fire_at_last_seen_operator(self):
        turn, settings = battle(Pos(13, 14))
        s, plan = decide(turn, settings)
        memory = s.memory
        memory.record(turn, plan)
        hidden = replace(turn, round_no=72, ours=turn.ours[:1],
                         action_results={str(uid): True for uid in BOSSES},
                         enemies=tuple(u for u in turn.enemies if u.kind in ('station', 'wall')))
        s, plan = decide(hidden, settings, memory)
        self.assertFalse(s.raider.seen_cell(OPERATOR))
        self.assertEqual(len(memory.enemy_structures), len(turn.enemies)-1)
        for command in plan.commands.values():
            if command['action'] == 'attack':
                target = Pos.load(command['targetPos'][0])
                self.assertNotEqual(target, OPERATOR)
                self.assertIsNotNone(enemy_at(hidden, target))
        self.assertTrue(all(memory.robot_raids[r.robot_id]['pursuit_kind'] != 'controller'
                            for r in hidden.summon_robots))

    def test_empty_inferred_common_operator_cell_never_becomes_attack_target(self):
        turn, settings = battle(Pos(13, 14), visible_operator=False)
        self.assertEqual(layout_operator_positions(turn), (OPERATOR,))
        self.assertIsNone(enemy_at(turn, OPERATOR))
        s, plan = decide(turn, settings)
        # A teammate's real move may close the sole entry for this frame.
        # Both robots are scheduled, but a coordinated wait emits no command.
        self.assertTrue(set(BOSSES) <= plan.used)
        for command in plan.commands.values():
            if command['action'] == 'attack':
                target = Pos.load(command['targetPos'][0])
                self.assertNotEqual(target, OPERATOR)
                self.assertIsNotNone(enemy_at(turn, target))
        self.assertTrue(all(memory['pursuit_kind'] != 'controller'
                            for memory in s.memory.robot_raids.values()))


if __name__ == '__main__':
    unittest.main()
