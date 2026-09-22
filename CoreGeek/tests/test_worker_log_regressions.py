"""Reconstruct the log1/log2 clear-site/path conflicts; not full match replays."""
import unittest

from agent.protocol import Pos
from app.service.memory import GameMemory
from tests.fixtures import unit
from tests.test_worker_safety import strategy
from tests.test_u_layout import drawing_request, point


def log_layout(round_no=15):
    # Mirrored reference shifted to base (30,10), consistent with logged sites.
    raw = drawing_request(True, built=True, round_no=round_no)
    for r in raw['teamOur']['roles']:
        r['pos']['x'] -= 3
        r['pos']['y'] += 3
    raw['teamOur']['roles'] = [r for r in raw['teamOur']['roles'] if r['id'] != 504]
    raw['teamOur']['roles'][2]['pos'] = {'x':30, 'y':6}
    raw['mapInfo']['zones'] = [{'neutralType':'stone', 'pos':{'x':34, 'y':10}}]
    return raw


def move_feedback(raw, s, plan):
    destinations = []
    for uid, cmd in plan.commands.items():
        if cmd['action'] != 'move':
            continue
        p = Pos.load(cmd['targetPos'][0])
        if p in s.turn.occupied_cells() or p in destinations:
            raise AssertionError('illegal occupied/simultaneous destination')
        destinations.append(p)
        next(r for r in raw['teamOur']['roles'] if str(r['id'])==uid)['pos'] = p.dump()


class WorkerLogRegressionTests(unittest.TestCase):
    def test_log2_miner_passes_bottom_wall_sites_and_reaches_mine(self):
        raw = log_layout(); memory = GameMemory()
        visited = []
        for n in range(15, 32):
            raw['roundNo'] = n
            s, plan = strategy(raw, memory); s.run()
            visited.append(s.turn.workers()[0].pos)
            cmd = plan.commands.get('501', {})
            if cmd.get('action') == 'collect':
                self.assertEqual(cmd['targetPos'], [{'x':34, 'y':10}])
                break
            self.assertEqual(plan.rejections, [])
            move_feedback(raw, s, plan); memory.record(s.turn, plan)
        else:
            self.fail(f'log2-style mine/clear-site loop: {visited}')

    def test_log1_guard_supply_crosses_missing_upper_wall_without_bouncing(self):
        raw = log_layout(522)
        raw['teamOur']['goldNum'] = 1000
        raw['teamOur']['roles'][2]['pos'] = {'x':29, 'y':11}
        raw['mapInfo']['zones'] = [{'neutralType':'weaponShop', 'pos':{'x':24, 'y':20}}]
        raw['weaponShopList'] = [{'name':'WallFixer', 'price':10}]
        memory = GameMemory(opening_complete=True, repair_worker_id=501)
        initial, _ = strategy(raw, memory)
        for uid, p in enumerate(initial.settings.build_cells(initial.turn, 'wall'), 701):
            if p != Pos(30,12):
                raw['teamOur']['roles'].append(unit(uid, 'wall', p.x, p.y))
        visited = []
        for n in range(522, 550):
            raw['roundNo'] = n
            s, plan = strategy(raw, memory)
            w = s.turn.workers()[0]; visited.append(w.pos)
            s.run()
            if plan.commands.get('501', {}).get('action') == 'buy':
                self.assertEqual(plan.commands['501']['name'], 'WallFixer')
                break
            self.assertEqual(plan.rejections, [])
            move_feedback(raw, s, plan); memory.record(s.turn, plan)
        else:
            self.fail(f'log1-style supply/clear-site loop: {visited}')

    def test_build_route_never_uses_another_missing_wall_as_a_stand(self):
        for mirrored in (False, True):
            raw = drawing_request(mirrored, built=True, round_no=25)
            raw['teamOur']['roles'][2].update(pos=point(10, 5, mirrored).dump(), backpack=['stone']*6)
            raw['teamOur']['roles'][3].update(pos=point(8, 10, mirrored).dump(), backpack=['stone']*6)
            s, plan = strategy(raw, GameMemory())
            s.run()
            sites = set(s.missing_walls()) | set(s.layout.tower_sites)
            for w in s.turn.workers():
                self.assertFalse((set(s.route(w).cost) - {w.pos}) & sites)
            for uid in (501, 504):
                cmd = plan.commands.get(str(uid), {})
                if cmd.get('action') == 'move':
                    self.assertNotIn(Pos.load(cmd['targetPos'][0]), sites)

    def test_spawn_on_planned_site_can_leave_then_finish_delivery(self):
        raw = log_layout();raw['teamOur']['roles'][2]['pos'] = {'x':31, 'y':7}
        memory = GameMemory()
        for n in range(15, 33):
            raw['roundNo'] = n
            s, plan = strategy(raw, memory); s.run()
            if plan.commands.get('501', {}).get('action') == 'collect':
                break
            self.assertEqual(plan.rejections, [])
            move_feedback(raw, s, plan); memory.record(s.turn, plan)
        else:
            self.fail('worker spawning on wall site never reached resource')

    def test_two_builders_finish_walls_without_clear_site_ping_pong(self):
        for mirrored in (False, True):
            raw = drawing_request(mirrored, built=True, round_no=25)
            raw['mapInfo']['zones'] = [{'neutralType':'vendor', 'pos':point(2, 12, mirrored).dump()}]
            for r, p in zip(raw['teamOur']['roles'][2:4], ((10, 6), (7, 10))):
                r.update(pos=point(*p, mirrored).dump(), backpack=['stone']*6)
            memory = GameMemory()
            for n in range(25, 71):
                raw['roundNo'] = n
                s, plan = strategy(raw, memory); s.run()
                if not s.missing_walls():
                    break
                move_feedback(raw, s, plan)
                for uid, cmd in plan.commands.items():
                    if cmd['action']=='build':
                        self.assertEqual(cmd['name'], 'wall')
                        p = Pos.load(cmd['targetPos'][0])
                        raw['teamOur']['roles'].append(unit(1000+len(raw['teamOur']['roles']), 'wall', p.x, p.y))
                        next(r for r in raw['teamOur']['roles'] if str(r['id'])==uid)['backpack'].remove('stone')
                self.assertEqual(plan.rejections, [])
                memory.record(s.turn, plan)
            else:
                self.fail('two builders failed to finish the U wall before night')

    def test_diagnostic_routes_keep_planned_sites_blocked(self):
        raw = log_layout()
        s, _ = strategy(raw)
        worker = s.turn.workers()[0]
        reserved = set(s.missing_walls()) | set(s.layout.tower_sites) | {s.layout.operator_pos}
        self.assertFalse((set(s.coordinator.diagnostic_route(worker).cost)-{worker.pos}) & reserved)
        self.assertEqual(s.coordinator.reserved(), s.movement_reserved(worker))

    def test_oscillation_is_detected_separately_from_no_movement(self):
        raw = log_layout(); memory = GameMemory()
        detected = []
        for n, p in enumerate((Pos(30,6), Pos(31,7), Pos(30,6), Pos(31,7)), 15):
            raw['roundNo'] = n; raw['teamOur']['roles'][2]['pos'] = p.dump()
            s, _ = strategy(raw, memory)
            w = s.turn.workers()[0]
            s.coordinator.assign(w, 'diagnostic', Pos(34,10), Pos(33,9), moving=True)
            job = memory.worker_tasks[501]
            detected.append(job.get('oscillating', False))
            self.assertEqual(job['stalled'], 0)
            self.assertLessEqual(len(job['recent_positions']), 4)
        self.assertEqual(detected, [False, False, False, True])
        raw['roundNo'] = 25
        s, _ = strategy(raw, memory)
        self.assertNotIn(501, memory.worker_tasks)

    def test_clear_site_logs_actual_destination_and_movement_state(self):
        raw = log_layout();raw['teamOur']['roles'][2]['pos']={'x':31,'y':7}
        s, plan = strategy(raw); s.run()
        job = s.memory.worker_tasks[501]
        self.assertEqual(job['kind'], 'clear_site')
        self.assertTrue(job['moving'])
        self.assertEqual(job['goal'], Pos.load(plan.commands['501']['targetPos'][0]))
        self.assertEqual(job['position'], Pos(31,7))

    def test_service_log_separates_position_goal_command_and_feedback(self):
        from app.service.turn_service import TurnService
        raw = log_layout();raw['lastRoundRoleActionResults'] = {'501': False}
        with self.assertLogs('app.service.turn_service', level='INFO') as captured:
            TurnService().decide(raw)
        line = next(line for line in captured.output if 'worker_motion' in line)
        for field in ("'position':", "'target':", "'goal':", "'command':", "'last_action_ok': False", "'oscillating':"):
            self.assertIn(field, line)
