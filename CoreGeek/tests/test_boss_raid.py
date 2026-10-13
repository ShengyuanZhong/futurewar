"""Stateful purchase/summon feedback and wall-aware first-night robot tactics."""
import copy
import time
import unittest

from agent.protocol import Pos, Turn, distance, station_footprint
from agent.summoning import rear_spawn_position, scouted_spawn_position, summon_cell_legal
from app.config import Settings
from app.service.turn_service import Session, TurnService
from tests.fixtures import robot, unit
from tests.test_summon_control import ORDER, finished_tasks, provide_scout, raid_request
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
            raw['teamOur']['roles'][2].update(pos={'x':own_x+(4 if own_x>20 else -3),'y':own_y},
                backpack=['stone']+['WallFixer']*5+[ORDER])
            raw['teamOur']['goldNum'] = 0  # Isolate a carried single order from affordable top-up.
            raw['teamEnemy']['roles'] = [unit(990, 'station', enemy_x, enemy_y)]
            raw['teamOur']['roles'] = raw['teamOur']['roles'][:4]
            # Supply the actual completed defense, independently of raid orders.
            for i in range(3):
                raw['teamOur']['roles'].append(unit(600+i, 'rocket', own_x+(2 if own_x > 20 else -1), own_y+i-1))
            for uid,pos in enumerate(Settings().build_cells(Turn.load(raw),'wall'),1701):
                raw['teamOur']['roles'].append(unit(uid,'wall',pos.x,pos.y,health=1000))
            memory = finished_tasks(); provide_scout(raw,memory)
            s, plan = strategy(raw, memory); s.run()
            command = plan.commands['501']; self.assertEqual(command['name'], ORDER)
            spawn = Pos.load(command['targetPos'][0])
            self.assertEqual(min(distance(spawn,p) for p in station_footprint(Pos(enemy_x,enemy_y))),3)
            self.assertEqual(spawn,Pos(enemy_x+(4 if enemy_x>20 else -3),enemy_y))
            self.assertTrue(spawn.x > enemy_x+1 if enemy_x > 20 else spawn.x < enemy_x)
            self.assertLess(abs(spawn.y-enemy_y), 3)

    def test_missing_enemy_base_keeps_mirror_geometry_but_waits_for_scout(self):
        raw = raid_request(); raw['teamEnemy']['roles'] = []
        raw['teamOur']['roles'][2]['backpack'] += [ORDER]
        raw['teamOur']['goldNum'] = 0
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertEqual(rear_spawn_position(s.turn,s.settings),Pos(37,25))
        self.assertNotEqual(plan.commands.get('501',{}).get('action'),'use')
        self.assertFalse(s.raid_scouts.summon_ready())

    def test_buy_uses_observed_price_capacity_and_actual_gold(self):
        for gold, price, full, buys in ((130, 130, False, True), (129, 130, False, False),
                                       (120, 120, True, False)):
            raw = raid_request(); raw['teamOur']['goldNum'] = gold
            raw['weaponShopList'][-1]['price'] = price
            if full: raw['teamOur']['roles'][2]['backpack'] = ['stone']+['iron']*99
            s, plan = strategy(raw, finished_tasks()); s.run()
            self.assertEqual(plan.commands.get('501', {}).get('name') == ORDER, buys)
        raw = raid_request(); raw['weaponShopList'] = []
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertNotEqual(plan.commands.get('501', {}).get('name'), ORDER)

    def test_purchase_budget_is_reserved_while_worker_walks_to_the_shop(self):
        raw = raid_request(); raw['teamOur']['roles'][1]['pos'] = {'x': 4, 'y': 7}
        raw['teamOur']['roles'][2]['pos'] = {'x': 4, 'y': 8}
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertFalse(any(c['action'] == 'buy' for c in plan.commands.values()))
        self.assertEqual(plan.gold, 120)

    def test_failed_purchase_can_retry_but_carried_coupon_is_not_bought_twice(self):
        raw = raid_request(); memory = finished_tasks()
        provide_scout(raw,memory)
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] += 1; raw['lastRoundRoleActionResults'] = {'501': False}
        memory.observe(Turn.load(raw)); s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501']['action'], 'buy')
        memory.record(s.turn, plan)
        raw['roundNo'] += 1; raw['lastRoundRoleActionResults'] = {'501': True}
        raw['teamOur']['roles'][2]['backpack'] += [ORDER]
        raw['teamOur']['goldNum'] = 0  # The successful purchase consumed the 120-gold balance.
        memory.observe(Turn.load(raw)); s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501']['action'], 'use')
        self.assertFalse(any(c.get('name') == ORDER and c['action'] == 'buy' for c in plan.commands.values()))

    def test_failed_summon_keeps_order_and_tries_a_different_rear_position(self):
        raw = raid_request(); raw['teamOur']['roles'][2]['backpack'] += [ORDER]
        raw['teamOur']['goldNum'] = 0
        memory = finished_tasks(); provide_scout(raw,memory)
        s, plan = strategy(raw, memory); s.run()
        first = plan.commands['501']['targetPos'][0]; memory.record(s.turn, plan)
        raw['roundNo'] += 1; raw['lastRoundRoleActionResults'] = {'501': False}
        memory.observe(Turn.load(raw)); s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501']['action'], 'use')
        self.assertNotEqual(plan.commands['501']['targetPos'][0], first)
        self.assertNotEqual(memory.boss_raid['status'], 'deployed')

    def test_disabled_strategy_preserves_daytime_pioneer_and_stops_robot_ai(self):
        raw = raid_request(); s, plan = strategy(raw, finished_tasks(), Settings(enable_boss_raid=False)); s.run()
        self.assertNotEqual(plan.commands.get('501', {}).get('name'), ORDER)
        raw = raid_request(71, boss=True)
        s, plan = strategy(raw, finished_tasks(), Settings(enable_boss_raid=False)); s.run()
        self.assertNotIn('30005', plan.commands)

    def test_blocked_rear_still_allows_purchase_when_other_legal_positions_exist(self):
        raw = raid_request(); raw['teamEnemy']['roles'][0]['pos'] = {'x': 38, 'y': 25}
        s, plan = strategy(raw, finished_tasks()); s.run()
        self.assertIsNone(rear_spawn_position(s.turn,s.settings))
        self.assertEqual(plan.commands['501'],{'action':'buy','name':ORDER,'num':1})

    def test_no_legal_spawn_anywhere_skips_buy_and_budget_reservation(self):
        raw = raid_request()
        turn,settings = Turn.load(raw),Settings()
        # Synthetic NPC coverage leaves paths in the building zones intact,
        # while every otherwise legal summon tile becomes an NPC tile.
        raw['mapInfo']['zones'].extend({'neutralType':'vendor','pos':p.dump()}
            for x in range(turn.width) for y in range(turn.height)
            if summon_cell_legal(turn,settings,p:=Pos(x,y)))
        s,plan = strategy(raw,finished_tasks());s.run()
        self.assertFalse(any(summon_cell_legal(s.turn,settings,Pos(x,y))
                             for x in range(turn.width) for y in range(turn.height)))
        self.assertNotEqual(plan.commands.get('501', {}).get('name'), ORDER)
        self.assertEqual(s.boss_raid.budget_reserve(), 0)

    def test_missing_already_acquired_order_never_triggers_a_second_purchase(self):
        raw = raid_request(); raw['teamOur']['roles'][2]['backpack'] += [ORDER]
        memory = finished_tasks(); provide_scout(raw,memory)
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] += 1; raw['teamOur']['roles'][2]['backpack'] = ['stone']+['WallFixer']*5
        raw['lastRoundRoleActionResults'] = {'501': False}
        memory.observe(Turn.load(raw)); s, plan = strategy(raw, memory); s.run()
        self.assertNotEqual(plan.commands.get('501', {}).get('name'), ORDER)
        self.assertEqual(memory.boss_raid['status'], 'order_missing')

    def test_failed_summon_releases_its_daily_attempt_and_pending_position(self):
        raw = raid_request(); raw['teamOur']['roles'][2]['backpack'] += [ORDER]
        raw['teamOur']['goldNum'] = 0
        memory = finished_tasks(); provide_scout(raw,memory)
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        self.assertEqual(memory.summon_attempts, 1)
        spawn = Pos.load(plan.commands['501']['targetPos'][0])
        self.assertIn(spawn, memory.pending_summon_positions)
        raw['roundNo'] += 1; raw['lastRoundRoleActionResults'] = {'501': False}
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

    def test_completely_screened_controller_causes_shared_flank_breach_then_base_attack(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'] = [unit(990, 'station', 33, 25),
                                   unit(991, 'rocket', 32, 24),
                                   unit(995, 'rocket', 32, 23),
                                   unit(996, 'rocket', 34, 23),
                                   unit(992, 'pioneer', 33, 23, health=500)]
        base_cells = station_footprint(Pos(33, 25))
        for i, pos in enumerate(sorted(Pos(x, y) for x in range(31, 37) for y in range(22, 28)
                if min(distance(Pos(x, y), cell) for cell in base_cells) == 2), 1001):
            raw['teamEnemy']['roles'].append(unit(i, 'wall', pos.x, pos.y,
                                                   health=40 if pos == Pos(33, 27) else 1000))
        # Ordinary friendly sight covers the real cannon crew. Deploy using
        # the public planner at the opposite north flank, outside build zones.
        observer = next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'worker')
        observer['pos'] = Pos(33, 21).dump()
        spawn = scouted_spawn_position(Turn.load(raw), Settings())
        self.assertEqual(spawn, Pos(33, 28))
        update_robot(raw, spawn.dump())
        memory = finished_tasks(); s, plan = strategy(raw, memory); s.run()
        command = plan.commands['30005']
        self.assertEqual(command['action'], 'attack')
        self.assertEqual(command['targetPos'], [{'x': 33, 'y': 27}])
        self.assertTrue(s.raider.clear_shot(s.turn.summon_robots[0], Pos(33, 27)))
        self.assertEqual(memory.boss_raid['wall_assault']['wall_pos'], Pos(33, 27))
        self.assertEqual(memory.boss_raid['wall_assault']['observed_wall_health'], 40)
        self.assertNotIn('controller_id', memory.robot_raids[30005])
        self.assertEqual(next(u.health for u in s.turn.enemies if u.unit_id == 992), 500)
        memory.record(s.turn, plan)
        next(u for u in raw['teamEnemy']['roles'] if u['pos'] == {'x': 33, 'y': 27})['health'] = 0
        raw['roundNo'] = 72; raw['lastRoundRoleActionResults'] = {'30005': True}
        s, plan = strategy(raw, memory); s.run()
        command = plan.commands['30005']
        self.assertEqual(command['action'], 'attack')
        target = Pos.load(command['targetPos'][0])
        self.assertIn(target, base_cells)
        self.assertTrue(s.raider.clear_shot(s.turn.summon_robots[0], target))
        self.assertEqual(memory.boss_raid['wall_assault']['phase'], 'base')
        self.assertEqual(memory.robot_raids[30005]['pursuit_kind'], 'base')
        self.assertEqual(next(u.health for u in s.turn.enemies if u.unit_id == 992), 500)
        self.assertEqual(plan.rejections, [])

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
        memory = finished_tasks(); provide_scout(raw,memory)
        service.sessions[key] = Session(memory=memory)
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
