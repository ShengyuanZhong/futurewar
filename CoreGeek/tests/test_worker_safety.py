"""Worker threat avoidance, batched shopping, and third-night wall duty."""
import copy
import unittest
from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn, distance, move_command
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import TurnService
from tests.fixtures import request, robot, unit
from tests.test_maintenance import fortified
from tests.test_u_layout import point


def strategy(raw, memory=None, settings=None):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, settings or Settings())
    return Strategy(turn, plan, memory or GameMemory(opening_complete=True)), plan


class WorkerSafetyTests(unittest.TestCase):
    def test_worker_route_detours_outside_robot_range_and_buffer(self):
        raw = request(71)
        raw['mapInfo']['zones'] = []
        raw['teamOur']['roles'] = [unit(501, 'worker', 3, 7)]
        raw['robot']['roles'] = [robot(900, 9, 7)]
        target = Pos(15, 7)
        for _ in range(30):
            s, plan = strategy(raw)
            worker = s.turn.workers()[0]
            if worker.pos == target: break
            step = s.route(worker).step([target])
            self.assertIsNotNone(step)
            self.assertGreater(distance(step, Pos(9, 7)), 4)
            self.assertTrue(plan.add(501, move_command(step)), plan.rejections)
            raw['teamOur']['roles'][0]['pos'] = step.dump()
        else:
            self.fail('safe detour never reached destination')

    def test_threatened_miner_retreats_instead_of_collecting(self):
        raw = request(71)
        raw['teamOur']['roles'] = [unit(501, 'worker', 10, 10)]
        raw['mapInfo']['zones'] = [{'neutralType': 'stone', 'pos': {'x': 10, 'y': 9}}]
        raw['robot']['roles'] = [robot(900, 12, 10)]
        s, plan = strategy(raw)
        s.night_worker(s.turn.workers()[0])
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertGreater(distance(Pos.load(plan.commands['501']['targetPos'][0]), Pos(12, 10)), 2)

    def test_safe_mine_preferred_over_rich_dangerous_mine(self):
        raw = request(71)
        raw['teamOur']['roles'] = [unit(501, 'worker', 10, 10)]
        raw['mapInfo']['zones'] = [{'neutralType': k, 'pos': {'x': x, 'y': y}}
                                   for k, x, y in (('stone', 14, 10), ('copper', 10, 5))]
        raw['vendorShopList'] = [{'name': 'stone', 'price': 100}, {'name': 'copper', 'price': 1}]
        raw['robot']['roles'] = [robot(900, 17, 10)]
        s, plan = strategy(raw)
        s.night_worker(s.turn.workers()[0])
        self.assertLess(plan.commands['501']['targetPos'][0]['y'], 10)

    def test_trapped_worker_waits_without_illegal_move(self):
        raw = request(71)
        raw['teamOur']['roles'] = [unit(501, 'worker', 10, 10)]
        raw['mapInfo']['zones'] = [{'neutralType': 'stone', 'pos': p.dump()} for p in Pos(10, 10).neighbours()]
        raw['robot']['roles'] = [robot(900, 12, 10)]
        s, plan = strategy(raw)
        s.night_worker(s.turn.workers()[0])
        self.assertEqual(plan.commands, {})
        self.assertEqual(plan.rejections, [])

    def test_bulk_purchase_limited_by_demand_budget_and_capacity(self):
        for gold, bag, expected in ((1000, [], 4), (65, [], 3), (1000, ['stone'] * 99, 1)):
            raw = fortified(weapon_level=3)
            for wall in raw['teamOur']['roles']:
                if wall['roleType']=='wall' and wall['pos'] in ({'x':9,'y':7},{'x':9,'y':6}):
                    wall.update(level=3,health=2000)
            raw['teamOur']['goldNum'] = gold
            raw['teamOur']['roles'][2].update(pos={'x': 3, 'y': 7}, backpack=bag)
            s, plan = strategy(raw)
            s.buy_upgrade(s.turn.workers()[0])
            self.assertEqual(plan.commands['501'], {'action': 'buy', 'name': 'WallUpgradeVoucher1', 'num': expected})
            self.assertEqual(plan.gold, gold - expected * 20)

    def test_bulk_wall_purchase_subtracts_team_inventory_and_prevents_double_buy(self):
        raw = fortified(weapon_level=3)
        for wall in raw['teamOur']['roles']:
            if wall['roleType']=='wall' and wall['pos'] in ({'x':9,'y':7},{'x':9,'y':6}):
                wall.update(level=3,health=2000)
        raw['teamOur']['roles'][2].update(pos={'x': 3, 'y': 7}, backpack=['WallUpgradeVoucher1'] * 2)
        raw['teamOur']['roles'][3].update(pos={'x': 3, 'y': 6}, backpack=['WallUpgradeVoucher1'])
        s, plan = strategy(raw)
        for worker in s.turn.workers(): s.buy_upgrade(worker)
        self.assertEqual(plan.commands['501']['num'], 1)
        self.assertNotIn('504', plan.commands)

    def test_guard_buys_five_fixers_from_day_three(self):
        raw = fortified(261)
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        s, plan = strategy(raw)
        s.run()
        self.assertEqual(plan.commands['501'], {'action': 'buy', 'name': 'WallFixer', 'num': 5})
        self.assertEqual(plan.rejections, [])

    def test_guard_repairs_below_thirty_percent_and_other_worker_runs_economy(self):
        for mirrored in (False, True):
            raw = fortified(331, mirrored=mirrored)
            raw['teamOur']['roles'][2].update(pos=point(8, 7, mirrored).dump(), backpack=['WallFixer'] * 5)
            raw['teamOur']['roles'][3]['pos'] = point(4, 9, mirrored).dump()
            wall = next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall' and r['pos'] == point(9, 7, mirrored).dump())
            wall['health'] = 299
            s, plan = strategy(raw)
            s.run()
            self.assertEqual(plan.commands['501'], {'action': 'use', 'name': 'WallFixer', 'targetPos': [wall['pos']]})
            self.assertEqual(plan.commands['504']['action'], 'move')
            self.assertEqual(s.memory.worker_tasks[504]['kind'], 'buy_upgrade')
            self.assertEqual(plan.rejections, [])

    def test_repair_threshold_uses_level_max_health_strictly(self):
        for level, health, should_repair in ((1, 300, False), (1, 299, True), (2, 450, False), (2, 449, True), (3, 600, False), (3, 599, True)):
            raw = fortified(331, wall_level=level)
            raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['WallFixer'])
            wall = next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall' and r['pos'] == {'x': 9, 'y': 7})
            wall['health'] = health
            s, plan = strategy(raw)
            s.run()
            self.assertEqual(plan.commands.get('501', {}).get('name') == 'WallFixer', should_repair, (level, health))

    def test_before_day_three_workers_can_shop_at_night(self):
        raw = fortified(201)
        raw['teamOur']['roles'][2].update(backpack=['WallFixer'] * 5)
        s, plan = strategy(raw)
        s.run()
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertEqual(s.memory.worker_tasks[501]['kind'], 'buy_upgrade')

    def test_guard_stays_inside_without_mining_or_leaving_for_shop(self):
        raw = fortified(331)
        raw['teamOur']['roles'][2]['pos'] = {'x': 8, 'y': 7}
        s, plan = strategy(raw)
        s.run()
        command = plan.commands.get('501')
        if command:
            self.assertEqual(command['action'], 'move')
            self.assertIn(Pos.load(command['targetPos'][0]), {Pos(6, 8), Pos(7, 8), Pos(8, 8), Pos(8, 7), Pos(8, 6), Pos(8, 5), Pos(7, 5), Pos(6, 5)})

    def test_guard_assignment_stable_and_dead_guard_replaced(self):
        raw = fortified(331)
        raw['teamOur']['roles'][3]['backpack'] = ['WallFixer'] * 3
        memory = GameMemory(opening_complete=True)
        s, _ = strategy(raw, memory)
        s.run()
        self.assertEqual(memory.repair_worker_id, 504)
        raw['teamOur']['roles'][3]['backpack'] = []
        raw['teamOur']['roles'][2]['backpack'] = ['WallFixer'] * 5
        s, _ = strategy(raw, memory)
        s.run()
        self.assertEqual(memory.repair_worker_id, 504)
        raw['teamOur']['roles'][3]['health'] = 0
        s, _ = strategy(raw, memory)
        s.run()
        self.assertEqual(memory.repair_worker_id, 501)

    def test_dead_robot_does_not_block_mining_but_dizzy_robot_still_buffered(self):
        raw = request(71)
        raw['teamOur']['roles'] = [unit(501, 'worker', 10, 10)]
        raw['mapInfo']['zones'] = [{'neutralType': 'stone', 'pos': {'x': 10, 'y': 9}}]
        raw['robot']['roles'] = [robot(900, 12, 10, health=0)]
        s, plan = strategy(raw)
        s.night_worker(s.turn.workers()[0])
        self.assertEqual(plan.commands['501']['action'], 'collect')
        raw['robot']['roles'][0].update(health=40, abnormalState='dizzy')
        s, plan = strategy(raw)
        s.night_worker(s.turn.workers()[0])
        self.assertEqual(plan.commands['501']['action'], 'move')

    def test_guard_returns_before_third_night_even_without_kits(self):
        for mirrored in (False, True):
            raw = fortified(318, mirrored=mirrored)
            raw['teamOur']['goldNum'] = 0
            raw['teamOur']['roles'][2]['pos'] = point(3, 7, mirrored).dump()
            memory = GameMemory(opening_complete=True)
            for number in range(318, 332):
                raw['roundNo'] = number
                s, plan = strategy(raw, memory)
                s.run()
                command = plan.commands.get('501', {})
                self.assertNotEqual(command.get('action'), 'buy')
                if command.get('action') == 'move':
                    raw['teamOur']['roles'][2]['pos'] = command['targetPos'][0]
            self.assertIn(Pos.load(raw['teamOur']['roles'][2]['pos']), s.guard.inner_cells())

    def test_guard_patrol_to_far_critical_wall_stays_inside(self):
        for mirrored in (False, True):
            raw = fortified(331, mirrored=mirrored)
            raw['teamOur']['roles'][2].update(pos=point(6, 8, mirrored).dump(), backpack=['WallFixer'] * 5)
            wall = next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall' and r['pos'] == point(6, 4, mirrored).dump())
            wall['health'] = 1
            memory = GameMemory(opening_complete=True)
            for number in range(331, 341):
                raw['roundNo'] = number
                s, plan = strategy(raw, memory)
                s.run()
                cmd = plan.commands['501']
                if cmd['action'] == 'use':
                    self.assertEqual(cmd['targetPos'], [wall['pos']])
                    break
                self.assertEqual(cmd['action'], 'move')
                self.assertIn(Pos.load(cmd['targetPos'][0]), s.guard.inner_cells())
                raw['teamOur']['roles'][2]['pos'] = cmd['targetPos'][0]
            else:
                self.fail('guard never reached far wall')

    def test_guard_does_not_repair_full_or_destroyed_wall(self):
        for health in (0, 1000):
            raw = fortified(331)
            raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['WallFixer'] * 5)
            wall = next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall' and r['pos'] == {'x': 9, 'y': 7})
            wall['health'] = health
            s, plan = strategy(raw)
            s.run()
            self.assertNotEqual(plan.commands.get('501', {}).get('action'), 'use')
            self.assertFalse(any(c['action'] == 'build' for c in plan.commands.values()))

    def test_guard_keeps_emergency_stock_during_daytime_upgrades(self):
        raw = fortified(261)
        raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['WallFixer'] * 5)
        for wall in raw['teamOur']['roles']:
            if wall['roleType'] == 'wall': wall['health'] = 800
        s, plan = strategy(raw)
        s.run()
        self.assertNotEqual(plan.commands.get('501', {}).get('name'), 'WallFixer')

    def test_guard_partial_stock_purchase_budget_capacity_and_free_price(self):
        for gold, bag, price, count in ((20, [], 10, 2), (100, ['stone'] * 99, 10, 1),
                                       (0, [], 0, 5), (100, ['WallFixer'] * 3, 10, 2)):
            raw = fortified(261)
            raw['teamOur']['goldNum'] = gold
            raw['teamOur']['roles'][2].update(pos={'x': 3, 'y': 7}, backpack=bag)
            raw['weaponShopList'][-1]['price'] = price
            s, plan = strategy(raw)
            s.run()
            self.assertEqual(plan.commands['501'], {'action': 'buy', 'name': 'WallFixer', 'num': count})
            self.assertEqual(plan.rejections, [])

    def test_upgrade_batch_reserves_guard_supply_budget(self):
        raw = fortified(261, weapon_level=3)
        raw['teamOur']['goldNum'] = 100
        for wall in raw['teamOur']['roles']:
            if wall['roleType']=='wall' and wall['pos'] in ({'x':9,'y':7},{'x':9,'y':6}):
                wall.update(level=3,health=2000)
        raw['teamOur']['roles'][3]['pos'] = {'x': 3, 'y': 7}
        s, plan = strategy(raw)
        s.buy_upgrade(s.turn.workers()[1])
        self.assertEqual(plan.commands['504']['num'], 2)
        self.assertEqual(plan.gold, 60)

    def test_repair_feedback_cache_failure_retry_and_daytime_restock(self):
        raw = fortified(331)
        raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['WallFixer'] * 2)
        wall = next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall' and r['pos'] == {'x': 9, 'y': 7})
        wall['health'] = 100
        service = TurnService()
        first = service.decide(copy.deepcopy(raw))
        self.assertEqual(first, service.decide(copy.deepcopy(raw)))
        self.assertEqual(first['roleCommandMap']['501']['name'], 'WallFixer')
        raw.update(roundNo=332, lastRoundRoleActionResults={'501': False})
        self.assertEqual(service.decide(copy.deepcopy(raw))['roleCommandMap']['501']['name'], 'WallFixer')
        # Only actual platform feedback consumes inventory and restores health.
        raw.update(roundNo=333, lastRoundRoleActionResults={'501': True})
        wall['health'] = 1000
        raw['teamOur']['roles'][2]['backpack'].pop()
        self.assertNotEqual(service.decide(copy.deepcopy(raw))['roleCommandMap'].get('501', {}).get('name'), 'WallFixer')
        raw['roundNo'] = 391
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        # Day four target is eight, and actual inventory contains one kit.
        self.assertEqual(service.decide(copy.deepcopy(raw))['roleCommandMap']['501'], {'action': 'buy', 'name': 'WallFixer', 'num': 7})
