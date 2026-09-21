"""Upgrade purchase/use order and destroyed-wall recovery from observed state."""
import copy
import unittest
from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import TurnService
from tests.fixtures import unit
from tests.test_u_layout import drawing_request, point, WALLS


def fortified(round_no=131, mirrored=False, weapon_level=1, wall_level=1):
    raw = drawing_request(mirrored, built=True, round_no=round_no)
    raw['teamOur']['goldNum'] = 1000
    for tower in raw['teamOur']['roles'][-3:]:
        tower.update(level=weapon_level, health=500 + 500 * weapon_level)
    for uid, (x, y) in enumerate(sorted(WALLS), 701):
        p = point(x, y, mirrored)
        raw['teamOur']['roles'].append(unit(uid, 'wall', p.x, p.y,
                                          level=wall_level, health=500 + 500 * wall_level))
    raw['mapInfo']['zones'] = [
        {'neutralType': name, 'pos': point(x, y, mirrored).dump()}
        for name, x, y in (('weaponShop', 2, 7), ('stone', 3, 9), ('vendor', 3, 8))]
    raw['weaponShopList'] = [{'name': f'{prefix}UpgradeVoucher{level}', 'price': price}
                            for prefix in ('Weapon', 'Wall', 'Station')
                            for level, price in ((1, 20 if prefix == 'Wall' else 100),
                                                 (2, 30 if prefix == 'Wall' else 150))]
    raw['weaponShopList'].append({'name': 'WallFixer', 'price': 10})
    return raw


def setup(raw):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, Settings())
    return Strategy(turn, plan, GameMemory(opening_complete=True)), plan


class MaintenanceTests(unittest.TestCase):
    def test_purchase_delivery_feedback_completes_all_stages(self):
        raw = fortified()
        raw['teamOur']['goldNum'] = 3000
        # One courier isolates maintenance from the separate multi-role path problem.
        raw['teamOur']['roles'] = [r for r in raw['teamOur']['roles'] if r['id'] != 504]
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        raw['teamOur']['roles'][2]['backpack'] = ['WallFixer'] * 5
        service = TurnService()
        purchases = []
        wall_uses = {1: [], 2: []}
        for number in range(131, 1301):
            if (number - 1) % 130 >= 70: continue
            raw['roundNo'] = number
            before = Turn.load(raw)
            response = service.decide(copy.deepcopy(raw))
            for uid, command in response['roleCommandMap'].items():
                actor = next(r for r in raw['teamOur']['roles'] if str(r['id']) == uid)
                action = command['action']
                if action == 'move':
                    target = command['targetPos'][0]
                    self.assertNotIn(Pos.load(target), before.occupied_cells())
                    actor['pos'] = target
                elif action == 'buy':
                    name = command['name']
                    count = command.get('num', 1)
                    purchases.extend([name] * count)
                    raw['teamOur']['goldNum'] -= count * next(i['price'] for i in raw['weaponShopList'] if i['name'] == name)
                    self.assertGreaterEqual(raw['teamOur']['goldNum'], 0)
                    actor['backpack'].extend([name] * count)
                elif action == 'use':
                    name = command['name']
                    target = next(r for r in raw['teamOur']['roles'] if r['pos'] == command['targetPos'][0])
                    self.assertTrue(name.endswith(str(target['level'])))
                    if target['roleType'] == 'wall': wall_uses[target['level']].append(target['pos']['x'])
                    actor['backpack'].remove(name)
                    target['level'] += 1
                    target['health'] = 1500 * target['level'] if target['roleType'] == 'station' else 500 + 500 * target['level']
                elif action == 'collect':
                    actor['backpack'].append(before.zones[Pos.load(command['targetPos'][0])])
                elif action == 'sell':
                    for _ in range(command['num']): actor['backpack'].remove(command['name'])
                    raw['teamOur']['goldNum'] += command['num'] * before.vendor_prices[command['name']]
                else:
                    self.fail(f'unexpected maintenance action: {command}')
            if setup(raw)[0].upgrades_complete(): break
        else:
            self.fail('maintenance courier never completed upgrades')
        self.assertEqual(purchases, ['WeaponUpgradeVoucher1', 'WeaponUpgradeVoucher2']
                         + ['WallUpgradeVoucher1'] * 2 + ['WallUpgradeVoucher2'] * 2
                         + ['WeaponUpgradeVoucher1']
                         + ['WallUpgradeVoucher1'] * 4 + ['WallUpgradeVoucher2'] * 4
                         + ['WeaponUpgradeVoucher2', 'WeaponUpgradeVoucher1', 'WeaponUpgradeVoucher2']
                         + ['WallUpgradeVoucher1'] * 6)
        self.assertEqual(wall_uses[1], [9] * 6 + [8] * 2 + [7] * 2 + [6] * 2)
        self.assertEqual(wall_uses[2], [9] * 6)

    def purchase(self, raw):
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        strategy, plan = setup(raw)
        strategy.buy_upgrade(strategy.turn.workers()[0])
        self.assertEqual(plan.rejections, [])
        return plan.commands.get('501', {}).get('name')

    def test_day_one_only_weapons_even_with_damaged_station(self):
        raw = fortified(20)
        raw['teamOur']['roles'][0]['health'] = 1
        self.assertEqual(self.purchase(raw), 'WeaponUpgradeVoucher1')
        for role in raw['teamOur']['roles']:
            if role['roleType'] == 'rocket': role.update(level=3, health=2000)
        self.assertIsNone(self.purchase(raw))

    def test_day_one_does_not_use_existing_wall_or_station_vouchers(self):
        raw = fortified(20, weapon_level=3)
        raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7},
            backpack=['StationUpgradeVoucher1', 'WallUpgradeVoucher1'])
        strategy, plan = setup(raw)
        self.assertFalse(strategy.consume(strategy.turn.workers()[0]))
        self.assertEqual(plan.commands, {})

    def test_upgrade_stages_and_station_excluded(self):
        for weapons, walls, expected in ((1, 1, 'WeaponUpgradeVoucher1'),
                                         (2, 1, 'WeaponUpgradeVoucher2'),
                                         (2, 2, 'WeaponUpgradeVoucher2'),
                                         (3, 2, 'WallUpgradeVoucher2'),
                                         (3, 3, None)):
            with self.subTest(weapons=weapons, walls=walls):
                self.assertEqual(self.purchase(fortified(weapon_level=weapons, wall_level=walls)), expected)

    def test_day_one_can_continue_weapon_level_three(self):
        self.assertEqual(self.purchase(fortified(20, weapon_level=2)), 'WeaponUpgradeVoucher2')

    def test_wall_columns_advance_only_after_observed_upgrade(self):
        for mirrored in (False, True):
            raw = fortified(mirrored=mirrored, weapon_level=3)
            raw['teamOur']['roles'][2].update(pos=point(7, 8, mirrored).dump(), backpack=['WallUpgradeVoucher1'])
            for role in raw['teamOur']['roles']:
                if role['roleType'] == 'wall' and role['pos']['x'] == point(9, 7, mirrored).x:
                    role.update(level=3, health=2000)
            strategy, plan = setup(raw)
            strategy.consume(strategy.turn.workers()[0])
            self.assertEqual(plan.commands['501']['targetPos'][0]['x'], point(8, 9, mirrored).x)
            self.assertEqual(plan.commands['501']['action'], 'use')

    def test_no_stage_advance_on_unconfirmed_use_and_full_heal_observation(self):
        raw = fortified(weapon_level=3)
        for role in raw['teamOur']['roles']:
            if role['roleType'] == 'wall': role.update(level=2, health=1500)
        last = next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall' and r['pos'] == {'x': 9, 'y': 7})
        last.update(level=1, health=5)
        raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['WallUpgradeVoucher1'])
        raw['teamOur']['roles'][3]['pos'] = {'x': 3, 'y': 7}
        strategy, plan = setup(raw)
        strategy.consume(strategy.turn.workers()[0])
        self.assertEqual(plan.commands['501']['name'], 'WallUpgradeVoucher1')
        strategy.buy_upgrade(strategy.turn.workers()[1])
        self.assertNotIn('504', plan.commands)
        self.assertEqual(last['health'], 5)  # Agent must not fake a successful heal.
        # Failed use: same inventory and building observation keeps the same stage.
        raw['roundNo'] += 1
        raw['lastRoundRoleActionResults'] = {'501': False}
        strategy, plan = setup(raw)
        strategy.consume(strategy.turn.workers()[0])
        self.assertEqual(plan.commands['501']['name'], 'WallUpgradeVoucher1')
        # Successful platform feedback, with level and health restored, advances.
        last.update(level=2, health=1500)
        raw['teamOur']['roles'][2]['backpack'] = []
        raw['roundNo'] += 1
        self.assertEqual(self.purchase(raw), 'WallUpgradeVoucher2')

    def test_rebuilt_level_one_wall_reenters_upgrade_order_before_station(self):
        raw = fortified(weapon_level=3, wall_level=3)
        raw['teamOur']['roles'][-1].update(level=1, health=1000)
        self.assertEqual(self.purchase(raw), 'WallUpgradeVoucher1')
        raw['teamOur']['roles'][-1].update(level=2, health=1500)
        self.assertEqual(self.purchase(raw), 'WallUpgradeVoucher2')

    def test_missing_wall_blocks_station_purchase_even_when_others_maxed(self):
        raw = fortified(weapon_level=3, wall_level=3)
        raw['teamOur']['roles'][-1]['health'] = 0
        self.assertIsNone(self.purchase(raw))

    def test_save_for_current_stage_instead_of_buying_cheaper_wall_or_base(self):
        raw = fortified()
        raw['teamOur']['goldNum'] = 99
        self.assertIsNone(self.purchase(raw))

    def test_wall_use_front_before_nearer_rear_for_both_sides(self):
        for mirrored in (False, True):
            raw = fortified(mirrored=mirrored, weapon_level=3)
            raw['teamOur']['roles'][2].update(pos=point(6, 8, mirrored).dump(), backpack=['WallUpgradeVoucher1'])
            strategy, plan = setup(raw)
            self.assertTrue(strategy.consume(strategy.turn.workers()[0]))
            self.assertEqual(plan.commands['501']['action'], 'move')
            raw['teamOur']['roles'][2]['pos'] = point(8, 7, mirrored).dump()
            strategy, plan = setup(raw)
            self.assertTrue(strategy.consume(strategy.turn.workers()[0]))
            command = plan.commands['501']
            self.assertEqual(command['action'], 'use')
            self.assertEqual(command['targetPos'][0]['x'], point(9, 7, mirrored).x)

    def test_upgrade_precedes_fixer_and_inventory_order(self):
        raw = fortified(weapon_level=3)
        raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['WallFixer', 'WallUpgradeVoucher1'])
        for role in raw['teamOur']['roles']:
            if role['roleType'] == 'wall' and role['pos'] == {'x': 9, 'y': 7}: role['health'] = 50
        strategy, plan = setup(raw)
        strategy.consume(strategy.turn.workers()[0])
        self.assertEqual(plan.commands['501'], {'action': 'use', 'name': 'WallUpgradeVoucher1',
                                               'targetPos': [{'x': 9, 'y': 7}]})

    def test_owned_vouchers_and_same_turn_buys_do_not_overbuy(self):
        raw = fortified()
        raw['teamOur']['roles'][3]['backpack'] = ['WeaponUpgradeVoucher1'] * 3
        self.assertEqual(self.purchase(raw), 'WeaponUpgradeVoucher2')
        raw['teamOur']['roles'][3]['backpack'].append('WeaponUpgradeVoucher2')
        self.assertIsNone(self.purchase(raw))
        raw['teamOur']['roles'][3]['backpack'] = []
        for role in raw['teamOur']['roles']:
            if role['roleType'] == 'rocket' and role['id'] != 601: role['level'] = 2
        raw['teamOur']['roles'][2]['pos'] = {'x': 3, 'y': 7}
        raw['teamOur']['roles'][3]['pos'] = {'x': 3, 'y': 6}
        strategy, plan = setup(raw)
        for worker in strategy.turn.workers(): strategy.buy_upgrade(worker)
        self.assertEqual(sum(c['action'] == 'buy' for c in plan.commands.values()), 1)

    def test_destroyed_wall_rebuilt_before_upgrade_or_trade(self):
        for removed in (False, True):
            raw = fortified()
            raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['stone', 'WeaponUpgradeVoucher1'])
            wall = next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall' and r['pos'] == {'x': 9, 'y': 7})
            if removed: raw['teamOur']['roles'].remove(wall)
            else: wall['health'] = 0
            strategy, plan = setup(raw)
            strategy.worker(strategy.turn.workers()[0])
            self.assertEqual(plan.commands['501'], {'action': 'build', 'name': 'wall', 'targetPos': [{'x': 9, 'y': 7}]})

    def test_missing_wall_without_stone_collects_before_buying(self):
        raw = fortified()
        raw['teamOur']['roles'][-1]['health'] = 0
        strategy, plan = setup(raw)
        strategy.worker(strategy.turn.workers()[0])
        self.assertEqual(plan.commands['501']['action'], 'collect')

    def test_night_preserves_rebuild_stone_after_opening_complete(self):
        raw = fortified(201)
        raw['teamOur']['roles'][-1]['health'] = 0
        raw['teamOur']['roles'][2].update(pos={'x': 4, 'y': 9}, backpack=['stone'] * 12)
        strategy, plan = setup(raw)
        strategy.night_worker(strategy.turn.workers()[0])
        self.assertFalse(any(c['action'] in ('build', 'sell') for c in plan.commands.values()))

    def test_two_workers_do_not_upgrade_same_wall(self):
        raw = fortified(weapon_level=3)
        raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['WallUpgradeVoucher1'])
        raw['teamOur']['roles'][3].update(pos={'x': 8, 'y': 6}, backpack=['WallUpgradeVoucher1'])
        strategy, plan = setup(raw)
        for worker in strategy.turn.workers(): strategy.consume(worker)
        self.assertEqual(plan.rejections, [])
        uses = [c['targetPos'][0] for c in plan.commands.values() if c['action'] == 'use']
        self.assertEqual(len(uses), 2)
        self.assertNotEqual(uses[0], uses[1])
