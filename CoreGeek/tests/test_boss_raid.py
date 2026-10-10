"""Stateful purchase/summon feedback and wall-aware first-night robot tactics."""
import copy
import time
import unittest

from agent.protocol import Pos, Turn, distance, station_footprint
from app.config import Settings
from app.service.turn_service import Session, TurnService
from tests.fixtures import robot, unit
from tests.test_summon_control import ORDER, finished_tasks, raid_request
from tests.test_worker_safety import strategy


def update_robot(raw, pos):
    raw['teamOur']['summonRobotList'][0]['pos'] = pos
    raw['robot']['roles'][0]['pos'] = pos


class BossRaidTests(unittest.TestCase):
    def test_actual_enemy_base_overrides_mirror_and_both_rear_orientations_work(self):
        for own_x, own_y, enemy_x, enemy_y in ((6, 7, 29, 10), (33, 25, 6, 7)):
            raw = raid_request()
            raw['teamOur']['roles'][0].update(pos={'x': own_x, 'y': own_y})
            raw['teamOur']['roles'][1]['pos'] = {'x': own_x + (3 if own_x > 20 else -2), 'y': own_y}
            raw['teamOur']['roles'][1]['backpack'] = [ORDER]
            raw['teamOur']['goldNum'] = 0  # Isolate a carried single order from affordable top-up.
            raw['teamEnemy']['roles'] = [unit(990, 'station', enemy_x, enemy_y)]
            raw['teamOur']['roles'] = raw['teamOur']['roles'][:4]
            # Add guns beside the current controller to make its return budget real.
            for i in range(3):
                raw['teamOur']['roles'].append(unit(600+i, 'rocket', own_x+(2 if own_x > 20 else -1), own_y+i-1))
            s, plan = strategy(raw, finished_tasks()); s.run()
            command = plan.commands['502']; self.assertEqual(command['name'], ORDER)
            spawn = Pos.load(command['targetPos'][0])
            self.assertEqual(min(distance(spawn,p) for p in station_footprint(Pos(enemy_x,enemy_y))),3)
            self.assertEqual(spawn,Pos(enemy_x+(4 if enemy_x>20 else -3),enemy_y))
            self.assertTrue(spawn.x > enemy_x+1 if enemy_x > 20 else spawn.x < enemy_x)
            self.assertLess(abs(spawn.y-enemy_y), 3)

    def test_missing_enemy_base_uses_full_two_by_two_mirror(self):
        raw = raid_request(); raw['teamEnemy']['roles'] = []
        raw['teamOur']['roles'][1]['backpack'] = [ORDER]
        raw['teamOur']['goldNum'] = 0
        s, plan = strategy(raw, finished_tasks()); s.run()
        pos = Pos.load(plan.commands['502']['targetPos'][0])
        self.assertEqual(pos,Pos(37,25))

    def test_buy_uses_observed_price_capacity_and_actual_gold(self):
        for gold, price, full, buys in ((130, 130, False, True), (129, 130, False, False),
                                       (120, 120, True, False)):
            raw = raid_request(); raw['teamOur']['goldNum'] = gold
            raw['weaponShopList'][-1]['price'] = price
            if full: raw['teamOur']['roles'][1]['backpack'] = ['iron']*40
            s, plan = strategy(raw, finished_tasks()); s.run()
            self.assertEqual(plan.commands.get('502', {}).get('name') == ORDER, buys)
        raw = raid_request(); raw['weaponShopList'] = []
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertNotEqual(plan.commands.get('502', {}).get('name'), ORDER)

    def test_purchase_budget_is_reserved_while_pioneer_walks_to_the_shop(self):
        raw = raid_request(); raw['teamOur']['roles'][1]['pos'] = {'x': 4, 'y': 7}
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertEqual(plan.commands['502']['action'], 'move')
        self.assertFalse(any(c['action'] == 'buy' for c in plan.commands.values()))
        self.assertEqual(plan.gold, 120)

    def test_failed_purchase_can_retry_but_carried_coupon_is_not_bought_twice(self):
        raw = raid_request(); memory = finished_tasks()
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] += 1; raw['lastRoundRoleActionResults'] = {'502': False}
        memory.observe(Turn.load(raw)); s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['502']['action'], 'buy')
        memory.record(s.turn, plan)
        raw['roundNo'] += 1; raw['lastRoundRoleActionResults'] = {'502': True}
        raw['teamOur']['roles'][1]['backpack'] = [ORDER]
        raw['teamOur']['goldNum'] = 0  # The successful purchase consumed the 120-gold balance.
        memory.observe(Turn.load(raw)); s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['502']['action'], 'use')
        self.assertFalse(any(c.get('name') == ORDER and c['action'] == 'buy' for c in plan.commands.values()))

    def test_failed_summon_keeps_order_and_tries_a_different_rear_position(self):
        raw = raid_request(); raw['teamOur']['roles'][1]['backpack'] = [ORDER]
        raw['teamOur']['goldNum'] = 0
        memory = finished_tasks(); s, plan = strategy(raw, memory); s.run()
        first = plan.commands['502']['targetPos'][0]; memory.record(s.turn, plan)
        raw['roundNo'] += 1; raw['lastRoundRoleActionResults'] = {'502': False}
        memory.observe(Turn.load(raw)); s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['502']['action'], 'use')
        self.assertNotEqual(plan.commands['502']['targetPos'][0], first)
        self.assertNotEqual(memory.boss_raid['status'], 'deployed')

    def test_disabled_strategy_preserves_daytime_pioneer_and_stops_robot_ai(self):
        raw = raid_request(); s, plan = strategy(raw, finished_tasks(), Settings(enable_boss_raid=False)); s.run()
        self.assertNotEqual(plan.commands.get('502', {}).get('name'), ORDER)
        raw = raid_request(71, boss=True)
        s, plan = strategy(raw, finished_tasks(), Settings(enable_boss_raid=False)); s.run()
        self.assertNotIn('30005', plan.commands)

    def test_no_legal_rear_spawn_skips_buy_and_budget_reservation(self):
        raw = raid_request(); raw['teamEnemy']['roles'][0]['pos'] = {'x': 38, 'y': 25}
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertNotEqual(plan.commands.get('502', {}).get('name'), ORDER)
        self.assertEqual(s.boss_raid.budget_reserve(), 0)

    def test_missing_already_acquired_order_never_triggers_a_second_purchase(self):
        raw = raid_request(); raw['teamOur']['roles'][1]['backpack'] = [ORDER]
        memory = finished_tasks(); s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] += 1; raw['teamOur']['roles'][1]['backpack'] = []
        raw['lastRoundRoleActionResults'] = {'502': False}
        memory.observe(Turn.load(raw)); s, plan = strategy(raw, memory); s.run()
        self.assertNotEqual(plan.commands.get('502', {}).get('name'), ORDER)
        self.assertEqual(memory.boss_raid['status'], 'order_missing')

    def test_failed_summon_releases_its_daily_attempt_and_pending_position(self):
        raw = raid_request(); raw['teamOur']['roles'][1]['backpack'] = [ORDER]
        raw['teamOur']['goldNum'] = 0
        memory = finished_tasks(); s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        self.assertEqual(memory.summon_attempts, 1)
        spawn = Pos.load(plan.commands['502']['targetPos'][0])
        self.assertIn(spawn, memory.pending_summon_positions)
        raw['roundNo'] += 1; raw['lastRoundRoleActionResults'] = {'502': False}
        memory.observe(Turn.load(raw))
        self.assertEqual(memory.summon_attempts, 0)
        self.assertNotIn(spawn, memory.pending_summon_positions)

    def test_clear_reposition_is_preferred_to_firing_through_a_wall(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'].append(unit(993, 'wall', 38, 25))
        s, plan = strategy(raw, finished_tasks()); s.run()
        command = plan.commands['30005']
        self.assertEqual(command['action'], 'move')
        self.assertNotEqual(command['targetPos'], [{'x': 38, 'y': 25}])

    def test_completely_screened_controller_causes_breach_then_resumes_attack(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'] = [unit(990, 'station', 33, 25),
                                   unit(991,'rocket',35,25),unit(992,'pioneer',36,25,health=500)]
        # The whole ring blocks every firing line to the controller.
        for i, pos in enumerate(Pos(36, 25).neighbours(), 1001):
            if pos != Pos(35,25):  # Cannon occupies one ring cell; other cells are walls.
                raw['teamEnemy']['roles'].append(unit(i, 'wall', pos.x, pos.y, health=40))
        memory = finished_tasks(); s, plan = strategy(raw, memory); s.run()
        command = plan.commands['30005']
        self.assertEqual(command['action'], 'attack')
        self.assertEqual(command['targetPos'], [{'x': 37, 'y': 25}])
        memory.record(s.turn, plan)
        next(u for u in raw['teamEnemy']['roles'] if u['pos'] == {'x': 37, 'y': 25})['health'] = 0
        raw['roundNo'] = 72; s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['30005']['targetPos'], [{'x': 36, 'y': 25}])

    def test_departed_controller_releases_priority_and_returns_to_base(self):
        raw = raid_request(71, boss=True); memory = finished_tasks()
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] = 72
        raw['teamEnemy']['roles'][2]['pos'] = {'x': 36, 'y': 20}
        s, plan = strategy(raw, memory); s.run()
        self.assertNotIn('controller_id',memory.robot_raids[30005])
        self.assertEqual(memory.robot_raids[30005]['stage'],'base')
        self.assertEqual(plan.commands['30005']['action'], 'move')

    def test_no_visible_controller_attempts_base_without_attacking_empty_coordinate(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:2]
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertEqual(plan.commands['30005']['action'], 'move')
        self.assertEqual(s.memory.robot_raids[30005]['stage'], 'base')

    def test_stun_death_new_day_and_deadline_stop_robot_orders(self):
        for mode in ('stun', 'death', 'day', 'later', 'deadline'):
            raw = raid_request(71, boss=True)
            if mode == 'stun': raw['teamOur']['summonRobotList'][0]['abnormalState'] = 'dizzy'
            elif mode == 'death': raw['teamOur']['summonRobotList'][0]['health'] = 0
            elif mode == 'day': raw['roundNo'] = 131
            elif mode == 'later': raw['roundNo'] = 201
            s, plan = strategy(raw, finished_tasks())
            if mode == 'deadline': s.deadline = time.monotonic()-1
            s.run(); self.assertNotIn('30005', plan.commands, mode)

    def test_explicit_failed_robot_attack_tries_a_different_firing_post(self):
        raw = raid_request(71, boss=True); memory = finished_tasks()
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        self.assertEqual(plan.commands['30005']['action'], 'attack')
        raw['roundNo'] = 72; raw['lastRoundRoleActionResults'] = {'30005': False}
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['30005']['action'], 'move')
        self.assertNotEqual(plan.commands['30005']['targetPos'], [{'x': 39, 'y': 25}])
        self.assertEqual(plan.rejections, [])

    def test_confirmed_controller_death_switches_to_the_observed_enemy_base(self):
        raw = raid_request(71, boss=True); memory = finished_tasks()
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] = 72; raw['teamEnemy']['roles'][2]['health'] = 0
        update_robot(raw, {'x': 36, 'y': 24})
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['30005'], {'action': 'attack', 'targetPos': [{'x': 34, 'y': 24}]})
        self.assertEqual(memory.robot_raids[30005]['stage'], 'base')

    def test_multiple_owned_bosses_never_reserve_the_same_step(self):
        raw = raid_request(71, boss=True)
        second = robot(32009, 39, 26, health=800, roleType='bossRobot')
        raw['teamOur']['summonRobotList'].append(second); raw['robot']['roles'].append(second)
        # Force both robots to move towards the same distant controller.
        raw['teamEnemy']['roles'][2]['pos'] = {'x': 35, 'y': 25}
        s, plan = strategy(raw, finished_tasks()); s.run()
        moves = [tuple(c['targetPos'][0].values()) for uid, c in plan.commands.items()
                 if uid in ('30005', '32009') and c['action'] == 'move']
        self.assertEqual(len(moves), 2)
        self.assertEqual(len(set(moves)), 2)
        self.assertEqual(plan.rejections, [])

    def test_api_sequence_buys_once_summons_then_kills_controller_before_base(self):
        raw = raid_request(); service = TurnService(Settings(enable_news=False,enable_first_night_defense=False))
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        service.sessions[key] = Session(memory=finished_tasks())
        births, buys, uses, attacks = [], [], [], []
        boss_id = 32768
        for number in list(range(30, 38)) + list(range(71, 131)):
            raw['roundNo'] = number
            if number == 71:
                self.assertEqual(len(births), 1)
                pos = births[0]
                born = robot(boss_id, pos['x'], pos['y'], health=800, roleType='bossRobot')
                raw['teamOur']['summonRobotList'] = [born]
                raw['robot']['roles'] = [born, robot(900, 13, 7)]
            before = Turn.load(raw)
            response = service.decide(copy.deepcopy(raw))
            destinations = set()
            cost = sum(before.shop_prices[c['name']]*c.get('num', 1)
                       for c in response['roleCommandMap'].values() if c['action'] == 'buy')
            self.assertLessEqual(cost, before.gold)
            for uid, command in response['roleCommandMap'].items():
                actor = next((u for u in raw['teamOur']['roles'] + raw['teamOur']['summonRobotList']
                              if str(u['id']) == uid), None)
                action = command['action']
                if action == 'move':
                    target = Pos.load(command['targetPos'][0])
                    self.assertEqual(distance(Pos.load(actor['pos']), target), 1)
                    self.assertNotIn(target, before.blocked(next(u for u in before.ours + before.summon_robots if u.unit_id == int(uid))))
                    self.assertNotIn(target, destinations); destinations.add(target)
                    actor['pos'] = target.dump()
                elif action == 'buy':
                    name, num = command['name'], command.get('num', 1)
                    actor['backpack'] += [name]*num
                    raw['teamOur']['goldNum'] -= before.shop_prices[name]*num
                    if name == ORDER: buys.append(command)
                elif action == 'use':
                    name = command['name']; actor['backpack'].remove(name)
                    if name == ORDER:
                        births.append(command['targetPos'][0]); uses.append(command)
                elif action == 'collect':
                    actor['backpack'].append(before.zones[Pos.load(command['targetPos'][0])])
                elif action == 'sell':
                    for _ in range(command['num']): actor['backpack'].remove(command['name'])
                    raw['teamOur']['goldNum'] += command['num']*before.vendor_prices[command['name']]
                elif action == 'attack' and uid == str(boss_id):
                    target = Pos.load(command['targetPos'][0])
                    self.assertLessEqual(distance(Pos.load(actor['pos']), target), 3)
                    enemy = next(u for u in raw['teamEnemy']['roles'] if u['health'] > 0 and target in
                        (station_footprint(Pos.load(u['pos'])) if u['roleType']=='station' else (Pos.load(u['pos']),)))
                    enemy['health'] = max(0, enemy['health']-40)
                    attacks.append(enemy['roleType'])
            raw['lastRoundRoleActionResults'] = {uid: True for uid in response['roleCommandMap']}
        self.assertEqual(len(buys), 1); self.assertEqual(buys[0]['num'], 1)
        self.assertEqual(len(uses), 1)
        self.assertIn('pioneer', attacks); self.assertIn('station', attacks)
        self.assertLess(attacks.index('pioneer'), attacks.index('station'))
        self.assertEqual(raw['teamEnemy']['roles'][2]['health'], 0)
        self.assertEqual(raw['teamEnemy']['roles'][0]['health'], 0)
        self.assertEqual(service.sessions[key].memory.boss_raid['status'], 'deployed')
        raw['roundNo'] = 131; raw['teamOur']['summonRobotList'] = []; raw['robot']['roles'] = []
        response = service.decide(raw)
        self.assertNotIn(str(boss_id), response['roleCommandMap'])
        self.assertEqual(service.sessions[key].memory.robot_raids, {})


if __name__ == '__main__':
    unittest.main()
