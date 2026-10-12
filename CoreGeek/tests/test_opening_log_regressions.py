"""Log-derived opening geometry, with local deterministic action feedback.

The supplied logs contain worker/base/mine positions, not full observations.
These fixtures reproduce those known positions; the off-site pioneer and
stationary unlimited test mines isolate construction routing, not a match.
"""
import unittest

from agent.protocol import Pos
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, unit
from tests.test_worker_safety import strategy


def opening_geometry(log_name):
    raw = request()
    raw['teamOur'].update(type='defender', playerTasks=[], goldNum=75)
    raw['teamOur']['roles'] = [unit(20013, 'station', 30, 10),
                               unit(20010, 'worker', 30, 8),
                               unit(20012, 'worker', 31, 8),
                               unit(20011, 'pioneer', 25, 13)]
    minerals = ((34, 16), (21, 2)) if log_name == 'bug_log1' else ((30, 6), (21, 13))
    raw['mapInfo']['zones'] = [dict(neutralType='stone', pos=Pos(x, y).dump())
                              for x, y in minerals]
    return raw


def feedback(test, raw, s, plan):
    roles = {str(r['id']): r for r in raw['teamOur']['roles']}
    destinations = set()
    for uid, command in plan.commands.items():
        actor = roles[uid]
        action = command['action']
        if action in ('move', 'build'):
            point = Pos.load(command['targetPos'][0])
            test.assertNotIn(point, s.turn.occupied_cells())
            test.assertNotIn(point, destinations)
            destinations.add(point)
        if action == 'move':
            actor['pos'] = point.dump()
        elif action == 'collect':
            actor['backpack'].append('stone')
        elif action == 'build':
            if command['name'] == 'rocket':
                raw['teamOur']['goldNum'] -= 25
            else:
                actor['backpack'].remove('stone')
            raw['teamOur']['roles'].append(unit(100000 + len(raw['teamOur']['roles']),
                                               command['name'], point.x, point.y))
        elif action == 'remove':
            raw['teamOur']['roles'] = [r for r in raw['teamOur']['roles']
                                      if not (r['roleType'] == 'wall'
                                              and r['pos'] == command['targetPos'][0])]
    raw['lastRoundRoleActionResults'] = {uid: True for uid in plan.commands}


class OpeningLogRegressionTests(unittest.TestCase):
    def test_actual_worker_spawn_positions_do_not_idle_or_mine_via_virtual_enclosure(self):
        for log_name in ('bug_log1', 'bug_log2'):
            with self.subTest(log=log_name):
                raw = opening_geometry(log_name)
                memory = GameMemory()
                settings = Settings(enable_tasks=False, enable_boss_raid=False,
                                    enable_first_night_defense=False)
                first_collect = {}
                third_rocket_round = None
                idle = {20010: 0, 20012: 0}
                for number in range(1, 27):
                    raw['roundNo'] = number
                    s, plan = strategy(raw, memory, settings=settings)
                    s.run()
                    for uid in idle:
                        command = plan.commands.get(str(uid), {})
                        idle[uid] = 0 if command else idle[uid] + 1
                        self.assertLess(idle[uid], 4, f'{uid} opening idle at R{number}')
                        if command.get('action') == 'collect':
                            first_collect.setdefault(uid, number)
                    self.assertEqual(plan.rejections, [])
                    feedback(self, raw, s, plan)
                    memory.record(s.turn, plan)
                    if len([r for r in raw['teamOur']['roles'] if r['roleType'] == 'rocket']) == 3:
                        third_rocket_round = third_rocket_round or number
                    if len(first_collect) == 2 and third_rocket_round is not None:
                        break
                self.assertEqual(set(first_collect), {20010, 20012})
                self.assertIsNotNone(third_rocket_round, 'active miners must not leave the third gun unbuilt')
                self.assertLessEqual(third_rocket_round, 10)
                if log_name == 'bug_log2':
                    self.assertLessEqual(min(first_collect.values()), 10)
                    # One builder finishes the third rocket, then reaches its
                    # distinct ore near (21,13); those actions still take time.
                    self.assertLessEqual(max(first_collect.values()), 26)

    def test_transit_over_missing_wall_does_not_force_miner_to_reverse_next_turn(self):
        raw = opening_geometry('bug_log2')
        raw['teamOur']['roles'] = [r for r in raw['teamOur']['roles'] if r['id'] != 20012]
        raw['teamOur']['roles'][1]['pos'] = Pos(30, 7).dump()
        for uid, y in enumerate((9, 10, 11), 800):
            raw['teamOur']['roles'].append(unit(uid, 'rocket', 32, y))
        raw['teamOur']['goldNum'] = 0
        s, plan = strategy(raw, GameMemory(), settings=Settings(enable_tasks=False,
                          enable_boss_raid=False, enable_first_night_defense=False))
        s.run()
        command = plan.commands['20010']
        self.assertEqual(command['action'], 'collect')
        self.assertEqual(command['targetPos'], [Pos(30, 6).dump()])
        self.assertEqual(s.coordinator.job(s.turn.workers()[0])['kind'], 'collect:stone')
