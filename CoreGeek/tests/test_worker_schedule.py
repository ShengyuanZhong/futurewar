"""A worker's economic job survives dusk/dawn, subject to defense and safety."""
import unittest

from agent.protocol import Pos
from app.service.memory import GameMemory
from tests.fixtures import robot
from tests.test_maintenance import fortified
from tests.test_worker_safety import strategy
from tests.test_u_layout import point


class WorkerScheduleTests(unittest.TestCase):
    def courier(self, number, mirrored=False):
        raw = fortified(number, mirrored=mirrored)
        raw['teamOur']['roles'] = [r for r in raw['teamOur']['roles'] if r['id'] != 504]
        return raw

    def test_night_uses_adjacent_rocket_voucher(self):
        for mirrored in (False, True):
            raw = self.courier(201, mirrored)
            raw['teamOur']['roles'][2].update(pos=point(4, 6, mirrored).dump(), backpack=['WeaponUpgradeVoucher1'])
            s, plan = strategy(raw); s.run()
            self.assertEqual(plan.commands['501']['action'], 'use')
            self.assertEqual(plan.commands['501']['name'], 'WeaponUpgradeVoucher1')
            self.assertEqual(plan.rejections, [])

    def test_delivery_continues_through_dusk_and_dawn(self):
        for start in (200, 260):
            raw = self.courier(start)
            raw['teamOur']['goldNum'] = 0
            raw['teamOur']['roles'][2].update(pos={'x': 1, 'y': 5}, backpack=['WeaponUpgradeVoucher1'])
            # Disable assignment of this courier as the third-day repairer.
            from app.config import Settings
            memory = GameMemory(opening_complete=True)
            targets = []
            for n in range(start, start+8):
                raw['roundNo'] = n
                s, plan = strategy(raw, memory, Settings(repair_start_day=10)); s.run()
                cmd = plan.commands['501']
                if cmd['action'] == 'use':
                    self.assertEqual(cmd['name'], 'WeaponUpgradeVoucher1')
                    break
                self.assertEqual(cmd['action'], 'move')
                job = memory.worker_tasks[501]
                self.assertEqual(job['kind'], 'use:WeaponUpgradeVoucher1')
                targets.append(job['target'])
                raw['teamOur']['roles'][2]['pos'] = cmd['targetPos'][0]
                memory.record(s.turn, plan)
            else:
                self.fail('courier abandoned its voucher delivery')
            self.assertTrue(targets)
            self.assertTrue(all(t == targets[0] for t in targets))

    def test_shop_trip_does_not_stop_at_sunset(self):
        for number in (200, 201):
            raw = self.courier(number)
            raw['teamOur']['roles'][2]['pos'] = {'x': 1, 'y': 3}
            s, plan = strategy(raw); s.run()
            self.assertEqual(plan.commands['501']['action'], 'move')
            self.assertEqual(s.memory.worker_tasks[501]['kind'], 'buy_upgrade')
            self.assertEqual(plan.rejections, [])

    def test_night_shop_buy_uses_same_stage_and_bulk_count(self):
        raw = self.courier(201)
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        s, plan = strategy(raw); s.run()
        self.assertEqual(plan.commands['501'], {'action': 'buy', 'name': 'WeaponUpgradeVoucher1', 'num': 1})

    def test_unsafe_upgrade_route_is_not_followed(self):
        raw = self.courier(201)
        raw['teamOur']['goldNum'] = 0
        raw['teamOur']['roles'][2].update(pos={'x': 1, 'y': 5}, backpack=['WeaponUpgradeVoucher1'])
        raw['robot']['roles'] = [robot(900, 4, 8)]
        s, plan = strategy(raw); s.run()
        cmd = plan.commands.get('501', {})
        self.assertNotEqual(cmd.get('action'), 'use')
        if cmd.get('action') == 'move':
            self.assertLessEqual(s.danger.get(Pos.load(cmd['targetPos'][0]), 0), s.danger.get(Pos(1, 5), 0))
        self.assertEqual(plan.rejections, [])

    def test_night_never_builds_even_with_missing_buildings(self):
        for kind in ('wall', 'rocket'):
            raw = self.courier(201)
            building = next(r for r in raw['teamOur']['roles'] if r['roleType'] == kind)
            building['health'] = 0
            raw['teamOur']['roles'][2]['backpack'] = ['stone'] * 12
            s, plan = strategy(raw, GameMemory()); s.run()
            self.assertFalse(any(c['action'] == 'build' for c in plan.commands.values()))
            self.assertEqual(plan.rejections, [])

    def test_guard_upgrades_inside_but_does_not_leave_post_for_rocket(self):
        for mirrored in (False, True):
            raw = fortified(331, mirrored=mirrored, weapon_level=3)
            raw['teamOur']['roles'][2].update(pos=point(8, 7, mirrored).dump(), backpack=['WallFixer']*5 + ['WallUpgradeVoucher1'])
            s, plan = strategy(raw); s.run()
            self.assertEqual(plan.commands['501']['name'], 'WallUpgradeVoucher1')
            raw = fortified(331, mirrored=mirrored)
            raw['teamOur']['roles'][2].update(pos=point(8, 7, mirrored).dump(), backpack=['WallFixer']*5 + ['WeaponUpgradeVoucher1'])
            s, plan = strategy(raw); s.run()
            cmd = plan.commands.get('501', {})
            if cmd.get('action') == 'move':
                self.assertIn(Pos.load(cmd['targetPos'][0]), s.guard.inner_cells())
            self.assertNotEqual(cmd.get('name'), 'WeaponUpgradeVoucher1')

    def test_urgent_repair_preempts_guard_upgrade(self):
        raw = fortified(331, weapon_level=3)
        raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['WallFixer']*5 + ['WallUpgradeVoucher1'])
        wall = next(r for r in raw['teamOur']['roles'] if r['roleType']=='wall' and r['pos']=={'x': 9, 'y': 7})
        wall['health'] = 100
        s, plan = strategy(raw); s.run()
        self.assertEqual(plan.commands['501']['name'], 'WallFixer')

    def test_mining_target_is_stable_across_dusk(self):
        raw = self.courier(200); raw['teamOur']['goldNum'] = 0
        raw['teamOur']['roles'][2]['pos'] = {'x': 4, 'y': 9}
        memory = GameMemory(opening_complete=True)
        for n in (200, 201):
            raw['roundNo'] = n
            s, plan = strategy(raw, memory); s.run()
            self.assertEqual(plan.commands['501'], {'action': 'collect', 'targetPos': [{'x': 3, 'y': 9}]})
            memory.record(s.turn, plan)

    def test_sales_continue_across_both_transitions(self):
        from app.config import Settings
        for start in (200, 260):
            raw = self.courier(start); raw['teamOur']['goldNum'] = 0
            raw['teamOur']['roles'][2].update(pos={'x': 1, 'y': 4}, backpack=['copper']*20)
            raw['vendorShopList'] = [{'name':'copper', 'price':5}]
            memory = GameMemory(opening_complete=True)
            for n in range(start, start+8):
                raw['roundNo'] = n
                s, plan = strategy(raw, memory, Settings(repair_start_day=10)); s.run()
                cmd = plan.commands['501']
                if cmd['action'] == 'sell':
                    self.assertEqual(cmd['num'], 20)
                    break
                self.assertEqual(cmd['action'], 'move')
                self.assertEqual(memory.worker_tasks[501]['kind'], 'sell')
                raw['teamOur']['roles'][2]['pos'] = cmd['targetPos'][0]
                memory.record(s.turn, plan)
            else:
                self.fail('worker abandoned sale at phase boundary')

    def test_guard_can_walk_inner_lane_to_upgrade_at_night(self):
        raw = fortified(331, weapon_level=3)
        raw['teamOur']['goldNum'] = 0
        raw['teamOur']['roles'][2].update(pos={'x': 6, 'y': 8}, backpack=['WallFixer']*5 + ['WallUpgradeVoucher1'])
        raw['robot']['roles'] = [robot(900, 11, 7)]
        memory = GameMemory(opening_complete=True)
        for n in range(331, 339):
            raw['roundNo'] = n
            s, plan = strategy(raw, memory); s.run()
            cmd = plan.commands['501']
            if cmd['action'] == 'use':
                self.assertEqual(cmd['name'], 'WallUpgradeVoucher1')
                break
            self.assertIn(Pos.load(cmd['targetPos'][0]), s.guard.inner_cells())
            self.assertEqual(memory.worker_tasks[501]['kind'], 'use:WallUpgradeVoucher1')
            raw['teamOur']['roles'][2]['pos'] = cmd['targetPos'][0]
            memory.record(s.turn, plan)
        else:
            self.fail('guard never delivered wall voucher')

    def test_guard_finishes_safe_shop_stop_at_dusk_then_returns(self):
        raw = fortified(331)
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        memory = GameMemory(opening_complete=True)
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501'], {'action':'buy', 'name':'WallFixer', 'num':5})
        raw['roundNo'] += 1
        raw['teamOur']['roles'][2]['backpack'] = ['WallFixer']*5
        memory.record(s.turn, plan)
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertIn(memory.worker_tasks[501]['kind'], ('guard_post', 'return_guard'))

    def test_guard_does_not_shop_from_exposed_position(self):
        raw = fortified(331)
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        raw['robot']['roles'] = [robot(900, 1, 7)]
        s, plan = strategy(raw); s.run()
        self.assertNotEqual(plan.commands.get('501', {}).get('action'), 'buy')

    def test_night_safe_worker_does_not_cross_danger_for_shop(self):
        raw = self.courier(201)
        raw['teamOur']['roles'][2]['pos'] = {'x': 1, 'y': 1}
        raw['robot']['roles'] = [robot(900, 2, 7)]
        s, plan = strategy(raw); s.run()
        self.assertEqual(s.danger.get(Pos(1, 1), 0), 0)
        cmd = plan.commands.get('501', {})
        if cmd.get('action') == 'move':
            self.assertEqual(s.danger.get(Pos.load(cmd['targetPos'][0]), 0), 0)
        self.assertNotEqual(s.memory.worker_tasks[501]['kind'], 'buy_upgrade')
        self.assertEqual(plan.rejections, [])

    def test_night_batch_wall_purchase_and_day_one_restriction(self):
        raw = self.courier(201)
        for r in raw['teamOur']['roles']:
            if r['roleType'] == 'rocket':
                r.update(level=3, health=2000)
        raw['teamOur']['roles'][2]['pos'] = {'x':3, 'y':7}
        s, plan = strategy(raw); s.run()
        self.assertEqual(plan.commands['501'], {'action':'buy', 'name':'WallUpgradeVoucher1', 'num':2})
        raw['roundNo'] = 71
        s, plan = strategy(raw); s.run()
        self.assertFalse(any(c.get('name', '').startswith('WallUpgrade') for c in plan.commands.values()))

    def test_rocket_upgrade_waits_for_observed_level_and_retries_failure(self):
        raw = self.courier(201)
        raw['teamOur']['goldNum'] = 0
        raw['teamOur']['roles'][2].update(pos={'x':4, 'y':6}, backpack=['WeaponUpgradeVoucher1', 'WeaponUpgradeVoucher2'])
        from app.service.turn_service import TurnService
        import copy
        service = TurnService()
        self.assertEqual(service.decide(copy.deepcopy(raw))['roleCommandMap']['501']['name'], 'WeaponUpgradeVoucher1')
        raw.update(roundNo=202, lastRoundRoleActionResults={'501':False})
        self.assertEqual(service.decide(copy.deepcopy(raw))['roleCommandMap']['501']['name'], 'WeaponUpgradeVoucher1')
        raw.update(roundNo=203, lastRoundRoleActionResults={'501':True})
        raw['teamOur']['roles'][2]['backpack'].remove('WeaponUpgradeVoucher1')
        next(r for r in raw['teamOur']['roles'] if r['id']==601).update(level=2, health=1500)
        self.assertEqual(service.decide(copy.deepcopy(raw))['roleCommandMap']['501']['name'], 'WeaponUpgradeVoucher2')
