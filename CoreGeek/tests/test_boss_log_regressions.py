"""Rule-level regressions from the hidden guns and failed shots in BOSS logs."""
import unittest

from agent.protocol import Pos, Unit, distance
from app.service.memory import GameMemory
from tests.fixtures import request, robot, unit
from tests.test_worker_safety import strategy


BOSS_ID, SECOND_ID, BASE_ID = 31035, 31036, 10013


def log_world(number=71, pos=Pos(6, 21), second=False):
    raw = request(number)
    raw['teamOur'].update(type='defender', teamId='boss-log-regression', playerTasks=[], goldNum=0)
    raw['mapInfo']['zones'] = []
    raw['teamOur']['roles'] = [unit(20013, 'station', 30, 10), unit(20010, 'worker', 32, 7),
        unit(20011, 'pioneer', 34, 10), unit(20012, 'worker', 32, 12),
        unit(20020, 'rocket', 32, 9), unit(20030, 'rocket', 32, 10), unit(20040, 'rocket', 32, 11)]
    raw['teamEnemy']['roles'] = [unit(BASE_ID, 'station', 9, 22)]
    bosses = [robot(BOSS_ID, pos.x, pos.y, health=800, roleType='bossRobot', targetTeam='challenger')]
    if second:
        bosses.append(robot(SECOND_ID, 6, 22, health=800, roleType='bossRobot', targetTeam='challenger'))
    raw['teamOur']['summonRobotList'] = bosses
    raw['robot']['roles'] = list(bosses)
    return raw


def log_memory(structures=()):
    memory = GameMemory(opening_complete=True, day=1)
    memory.enemy_structures = {u['id']: Unit.load(u) for u in structures}
    return memory


def raid_step(raw, memory):
    s, plan = strategy(raw, memory)
    for boss in s.turn.summon_robots:
        s.raider.decide(boss)
    summary, records = s.raider.diag.finish()
    memory.record(s.turn, plan)
    return s, plan, {r['robot']['id']: r for r in records}


def apply_moves(raw, plan):
    feedback = {}
    for actor in raw['teamOur']['summonRobotList']:
        command = plan.commands.get(str(actor['id']), {})
        if command.get('action') == 'move':
            actor['pos'] = command['targetPos'][0]
            feedback[str(actor['id'])] = True
        elif command.get('action') == 'attack':
            # A local negative feedback fixture, not an official damage model.
            feedback[str(actor['id'])] = False
    raw['lastRoundRoleActionResults'] = feedback
    raw['roundNo'] += 1


class BossLogRegressionTests(unittest.TestCase):
    def test_log3_hidden_known_guns_still_block_planning_without_becoming_targets(self):
        guns = [unit(10020, 'gatling', 8, 20, health=1000),
                unit(10030, 'railgun', 9, 20, health=1000),
                unit(10040, 'rocket', 8, 22, health=1000)]
        memory = log_memory(guns)
        raw = log_world(85, Pos(7, 21))
        s, plan, traces = raid_step(raw, memory)
        self.assertEqual({u.unit_id for u in s.turn.enemies}, {BASE_ID})
        self.assertFalse(s.raider.clear_shot(s.turn.summon_robots[0], Pos(9, 22)))
        self.assertTrue({10020, 10030, 10040} <= set(memory.enemy_structures))
        adjacent = traces[BOSS_ID]['route']['adjacent']
        for cell in (Pos(8, 20), Pos(8, 22)):
            self.assertFalse(next(p for p in adjacent if p['pos'] == cell.dump())['reachable'])
        command = plan.commands[str(BOSS_ID)]
        self.assertNotIn(Pos.load(command['targetPos'][0]), {Pos(8,20), Pos(9,20), Pos(8,22)})
        self.assertTrue(traces[BOSS_ID]['remembered_structures'])

    def test_visible_structure_update_replaces_its_previous_position(self):
        old = unit(10020, 'gatling', 8, 20, health=1000)
        memory = log_memory([old])
        raw = log_world()
        raw['teamEnemy']['roles'].append(unit(10020, 'gatling', 8, 19, health=900))
        s, _ = strategy(raw, memory)
        self.assertEqual(memory.enemy_structures[10020].pos, Pos(8, 19))
        self.assertEqual(memory.enemy_structures[10020].health, 900)
        self.assertIsInstance(memory.enemy_structures[10020], Unit)

    def test_explicit_dead_structure_removes_memory(self):
        memory = log_memory([unit(10020, 'gatling', 8, 20, health=1000)])
        raw = log_world()
        raw['teamEnemy']['roles'].append(unit(10020, 'gatling', 8, 20, health=0))
        strategy(raw, memory)
        self.assertNotIn(10020, memory.enemy_structures)

    def test_real_hero_sight_confirms_empty_static_position(self):
        memory = log_memory([unit(10020, 'gatling', 8, 20, health=1000)])
        raw = log_world()
        next(u for u in raw['teamOur']['roles'] if u['id'] == 20010)['pos'] = {'x': 5, 'y': 20}
        strategy(raw, memory)
        self.assertNotIn(10020, memory.enemy_structures)

    def test_robot_nearby_does_not_confirm_a_hidden_gun_empty(self):
        memory = log_memory([unit(10020, 'gatling', 8, 20, health=1000)])
        raw = log_world(pos=Pos(7, 20))
        strategy(raw, memory)
        self.assertEqual(memory.enemy_structures[10020].pos, Pos(8, 20))

    def test_absent_globally_visible_wall_is_removed_without_nearby_hero_sight(self):
        vanished = Pos(7, 21)
        memory = log_memory([unit(10070, 'wall', vanished.x, vanished.y, health=40)])
        raw = log_world()
        s, plan, traces = raid_step(raw, memory)
        self.assertNotIn(10070, memory.enemy_structures)
        self.assertTrue(s.raider.clear_shot(s.turn.summon_robots[0], Pos(9, 21)))
        cell = next(p for p in traces[BOSS_ID]['route']['adjacent'] if p['pos'] == vanished.dump())
        self.assertTrue(cell['reachable'])

    def test_only_own_building_sight_can_confirm_hidden_gun_position_empty(self):
        memory = log_memory([unit(10020, 'gatling', 33, 11, health=1000)])
        raw = log_world()
        for actor in raw['teamOur']['roles']:
            if actor['roleType'] in ('worker', 'pioneer'):
                actor['pos'] = {'x': 5, 'y': actor['id'] % 3 + 1}
        s, _ = strategy(raw, memory)
        self.assertTrue(all(distance(u.pos,Pos(33,11)) > 4 for u in s.turn.controllable()))
        self.assertNotIn(10020, memory.enemy_structures)

    def test_regular_role_blocks_interior_line_but_not_corner_contact(self):
        raw = log_world(pos=Pos(6, 21))
        raw['teamEnemy']['roles'] += [unit(10010, 'worker', 7, 20, health=500),
                                     unit(10070, 'wall', 7, 19, health=1000)]
        s, plan = strategy(raw, log_memory())
        boss = s.turn.summon_robots[0]
        self.assertFalse(s.raider.clear_shot(boss, Pos(7, 19)))
        # This remains a planning restriction, not an expanded official action gate.
        self.assertTrue(plan.add(BOSS_ID, {'action':'attack', 'targetPos':[Pos(7,19).dump()]}))
        raw = log_world(pos=Pos(6, 20))
        raw['teamEnemy']['roles'] += [unit(10010, 'worker', 7, 20, health=500),
                                     unit(10070, 'wall', 7, 19, health=1000)]
        s, _ = strategy(raw, log_memory())
        self.assertTrue(s.raider.clear_shot(s.turn.summon_robots[0], Pos(7, 19)))

    def test_static_failed_shot_is_not_recycled_after_four_rounds(self):
        raw, memory = log_world(), log_memory()
        s, plan, _ = raid_step(raw, memory)
        command = plan.commands[str(BOSS_ID)]
        self.assertEqual(command['action'], 'attack')
        origin, target = Pos.load(raw['teamOur']['summonRobotList'][0]['pos']), Pos.load(command['targetPos'][0])
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): False}
        raid_step(raw, memory)
        key = (BASE_ID, target, origin)
        self.assertGreaterEqual(memory.robot_raids[BOSS_ID]['failed_firing'][key], 131)
        raw['roundNo'] = 78
        raw['lastRoundRoleActionResults'] = {}
        s, plan, _ = raid_step(raw, memory)
        self.assertIn(key, memory.robot_raids[BOSS_ID]['failed_firing'])
        self.assertFalse(plan.commands[str(BOSS_ID)] == command)

    def test_two_negative_base_attacks_switch_to_close_recovery_without_range_change(self):
        raw, memory = log_world(), log_memory()
        rejected = 0
        close_seen = False
        for _ in range(8):
            s, plan, traces = raid_step(raw, memory)
            trace = traces[BOSS_ID]
            command = plan.commands[str(BOSS_ID)]
            if rejected >= 2:
                self.assertGreaterEqual(trace['base_attack_failures'], 2)
                self.assertTrue(trace['base_close_required'])
                self.assertEqual(trace['robot']['attack_range'], 3)
                if command['action'] == 'attack':
                    self.assertLessEqual(distance(s.turn.summon_robots[0].pos, Pos.load(command['targetPos'][0])), 1)
                    close_seen = True
                    break
                self.assertLessEqual(min(distance(Pos.load(trace['goal']), p)
                                         for p in s.turn.footprint(s.turn.enemies[0])), 1)
            if command['action'] == 'attack':
                rejected += 1
            apply_moves(raw, plan)
        self.assertGreaterEqual(rejected, 2)
        self.assertTrue(close_seen)

    def test_legal_close_attack_clears_failure_streak_and_stays_at_working_position(self):
        raw, memory = log_world(pos=Pos(8, 21)), log_memory()
        s, plan, _ = raid_step(raw, memory)
        self.assertEqual(plan.commands[str(BOSS_ID)]['action'], 'attack')
        target = Pos.load(plan.commands[str(BOSS_ID)]['targetPos'][0])
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): True}
        raw['teamEnemy']['roles'][0]['health'] -= 40
        s, plan, traces = raid_step(raw, memory)
        self.assertEqual(traces[BOSS_ID]['base_attack_failures'], 0)
        self.assertFalse(traces[BOSS_ID]['base_close_required'])
        self.assertEqual(plan.commands[str(BOSS_ID)]['action'], 'attack')
        self.assertEqual(plan.commands[str(BOSS_ID)]['targetPos'], [target.dump()])
        self.assertEqual(s.turn.summon_robots[0].pos, Pos(8, 21))
        self.assertEqual(memory.robot_raids[BOSS_ID]['verified_base_post'], Pos(8, 21))
        self.assertEqual(memory.robot_raids[BOSS_ID]['verified_base_target'], target)

    def test_verified_base_shot_is_not_repeated_after_new_negative_feedback(self):
        raw, memory = log_world(pos=Pos(8, 21)), log_memory()
        s, plan, _ = raid_step(raw, memory)
        working = plan.commands[str(BOSS_ID)]
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): True}
        raw['teamEnemy']['roles'][0]['health'] -= 40
        s, plan, _ = raid_step(raw, memory)
        self.assertEqual(plan.commands[str(BOSS_ID)], working)
        self.assertEqual(memory.robot_raids[BOSS_ID]['verified_base_post'], Pos(8, 21))
        raw['roundNo'] = 73
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): False}
        s, plan, traces = raid_step(raw, memory)
        self.assertNotEqual(plan.commands[str(BOSS_ID)], working)
        self.assertGreaterEqual(traces[BOSS_ID]['base_attack_failures'], 1)
        self.assertIsNone(memory.robot_raids[BOSS_ID].get('verified_base_post'))

    def test_working_base_position_can_be_recovered_after_controller_detour(self):
        raw, memory = log_world(pos=Pos(8, 21)), log_memory()
        s, plan, _ = raid_step(raw, memory)
        self.assertEqual(plan.commands[str(BOSS_ID)]['action'], 'attack')
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): True}
        raw['teamEnemy']['roles'][0]['health'] -= 40
        raw['teamEnemy']['roles'] += [unit(10090, 'rocket', 2, 20, health=1000),
                                     unit(10091, 'worker', 3, 20, health=40)]
        s, plan, _ = raid_step(raw, memory)
        self.assertEqual(plan.commands[str(BOSS_ID)]['action'], 'move')
        moved = plan.commands[str(BOSS_ID)]['targetPos'][0]
        raw['teamOur']['summonRobotList'][0]['pos'] = moved
        raw['roundNo'] = 73
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): True}
        raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:1]
        s, plan, _ = raid_step(raw, memory)
        self.assertEqual(plan.commands[str(BOSS_ID)],
                         {'action':'move', 'targetPos':[Pos(8,21).dump()]})

    def test_two_boss_recovery_moves_have_distinct_next_cells(self):
        raw, memory = log_world(second=True), log_memory()
        rejected = {BOSS_ID:0, SECOND_ID:0}
        observed = False
        for _ in range(8):
            s, plan, traces = raid_step(raw, memory)
            if all(rejected[uid] >= 2 for uid in rejected):
                moves = [Pos.load(plan.commands[str(uid)]['targetPos'][0])
                         for uid in rejected if plan.commands[str(uid)]['action'] == 'move']
                if len(moves) == 2:
                    self.assertEqual(len(set(moves)), 2)
                    for uid, destination in zip(rejected, moves):
                        actor = next(r for r in s.turn.summon_robots if r.robot_id == uid)
                        self.assertEqual(distance(actor.pos, destination), 1)
                        self.assertNotIn(destination, s.turn.blocked(actor))
                    observed = True
                    break
            for uid in rejected:
                if plan.commands[str(uid)]['action'] == 'attack':
                    rejected[uid] += 1
            apply_moves(raw, plan)
        self.assertTrue(observed)

    def test_failed_move_avoids_that_step_without_inventing_a_unit(self):
        raw = log_world(72)
        memory = log_memory()
        failed = Pos(7, 20)
        memory.last_round = 71
        memory.last_commands = {str(BOSS_ID): {'action':'move', 'targetPos':[failed.dump()]}}
        memory.robot_raids[BOSS_ID] = {'round':71, 'stage':'base', 'pursuit_kind':'base',
            'action':'move', 'position':Pos(6,21), 'target':failed, 'goal':failed}
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): False}
        s, plan, traces = raid_step(raw, memory)
        self.assertTrue(traces[BOSS_ID]['blocked_steps'])
        self.assertGreaterEqual(memory.robot_raids[BOSS_ID]['blocked_steps'][failed], 75)
        command = plan.commands[str(BOSS_ID)]
        self.assertFalse(command['action'] == 'move' and command['targetPos'] == [failed.dump()])
        self.assertNotIn(failed, {u.pos for u in s.turn.enemies})
        self.assertTrue(all(isinstance(u, Unit) for u in memory.enemy_structures.values()))

    def test_new_hero_observation_releases_a_temporary_empty_step(self):
        raw, memory = log_world(72), log_memory()
        failed = Pos(7, 20)
        memory.last_round = 71
        memory.last_commands = {str(BOSS_ID): {'action':'move', 'targetPos':[failed.dump()]}}
        memory.robot_raids[BOSS_ID] = {'round':71, 'stage':'base', 'pursuit_kind':'base',
            'action':'move', 'position':Pos(6,21), 'target':failed, 'goal':failed}
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): False}
        s, plan, traces = raid_step(raw, memory)
        self.assertTrue(traces[BOSS_ID]['blocked_steps'])
        raw['roundNo'] = 73
        raw['lastRoundRoleActionResults'] = {}
        next(u for u in raw['teamOur']['roles'] if u['id'] == 20010)['pos'] = {'x': 4, 'y': 20}
        s, plan, traces = raid_step(raw, memory)
        self.assertFalse(traces[BOSS_ID]['blocked_steps'])
        self.assertNotIn(failed, memory.robot_raids[BOSS_ID].get('blocked_steps', {}))


if __name__ == '__main__':
    unittest.main()
