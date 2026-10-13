"""First-day outbound purchase deadlines, independently derived from real paths.

These local observations cover R1--R70 only. Construction is deliberately
unfinished in deadline cases: it must not consume the actions needed for the
shop trip, one batch purchase, and up to three separate confirmed uses.
"""
import unittest
from dataclasses import replace

from agent.first_day_tasks import finish_attempt, record_attempt
from agent.grid import Routes, adjacent_cells
from agent.protocol import Pos, Turn, distance
from tests.fixtures import unit
from tests.test_worker_boss_buyer import (
    BUYER, ORDER, PIONEER, SCOUT, SHOP, actor, advance, load_strategy,
    role, worker_raid_scene,
)


def unfinished_scene(round_no=1, lower_right=False, full_bag=False, driving=False):
    raw, memory, settings = worker_raid_scene(
        round_no=round_no, lower_right=lower_right, finished=2, successes=2)
    # A globally visible, ordinary unoccupied missing wall, not a gate or an
    # enemy-occupied site. The buyer is already outside so the reference path
    # is independently searchable without forecasting a remove action.
    missing = next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'wall')
    raw['teamOur']['roles'].remove(missing)
    actor(raw)['pos'] = Pos(6, 27).dump() if not lower_right else Pos(33, 6).dump()
    actor(raw)['isDriving'] = driving
    actor(raw)['backpack'] = ['stone'] + ['iron'] * 99 if full_bag else ['stone']
    return raw, memory, settings


def shop_steps(raw, settings):
    turn = Turn.load(raw)
    buyer = next(u for u in turn.workers() if u.unit_id == BUYER)
    route = Routes(turn, buyer)
    post = route.nearest(adjacent_cells(turn, [SHOP]))
    assert post is not None, 'fixture requires an actual unblocked outbound route'
    return route.cost[post]


class BuyerDeadlineTests(unittest.TestCase):
    def test_dispatched_buyers_carried_stone_is_not_counted_as_other_builders_material(self):
        raw, memory, settings = worker_raid_scene(round_no=66, finished=2, successes=2)
        removed = [u for u in raw['teamOur']['roles'] if u['roleType'] == 'wall'][:7]
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u not in removed]
        actor(raw)['backpack'] = ['stone']*8
        actor(raw, SCOUT).update(pos=Pos(17, 14).dump(), backpack=[])
        raw['mapInfo']['zones'].append(dict(neutralType='copper', pos=Pos(16, 14).dump()))
        memory.opening_complete = False
        s, plan = load_strategy(raw, memory, settings)
        s.run_worker(role(s))
        self.assertTrue(memory.boss_raid.get('departure_authorized'))
        self.assertIn(BUYER, plan.used)
        advance(raw, memory, s, plan)
        s, plan = load_strategy(raw, memory, settings)
        self.assertEqual(len(s.construction_walls()), 7)
        quotas = s.stone_targets()
        self.assertEqual(quotas[BUYER], s.day_gate.reserve_stone(role(s)))
        self.assertEqual(quotas[BUYER], 0)
        self.assertEqual(quotas[SCOUT], 7)
        self.assertGreater(s.turn.vendor_prices['copper'], s.turn.vendor_prices['stone'])
        s.run_worker(role(s, SCOUT))
        self.assertEqual(plan.commands[str(SCOUT)],
                         dict(action='collect', targetPos=[Pos(17, 15).dump()]))
        self.assertEqual(memory.worker_tasks[SCOUT]['kind'], 'collect:stone')
        self.assertFalse(plan.rejections)
        self.assertEqual(actor(raw)['backpack'].count('stone'), 8)

    def test_driving_inside_already_sealed_home_does_not_invent_a_remove_route(self):
        raw, memory, settings = worker_raid_scene(round_no=1, finished=2)
        actor(raw).update(pos=Pos(8, 22).dump(), isDriving=True)
        s, plan = load_strategy(raw, memory, settings)
        buyer = role(s)
        before = Routes(s.turn, buyer)
        self.assertIsNone(before.nearest(adjacent_cells(s.turn, [SHOP])))
        self.assertIsNone(s.boss_raid.departure_budget(buyer))
        s.boss_raid.worker(buyer)
        self.assertFalse(any(c.get('action') == 'remove' for c in plan.commands.values()))
        self.assertTrue(buyer.is_driving)
        self.assertEqual(len(s.turn.walls()), 17)
        self.assertEqual(plan.rejections, [])

    def test_authorized_buyer_stays_on_real_shop_route_through_final_three_task_settlement(self):
        for lower_right in (False, True):
            with self.subTest(lower_right=lower_right):
                raw, memory, settings = unfinished_scene(lower_right=lower_right)
                s, _ = load_strategy(raw, memory, settings)
                budget = s.boss_raid.departure_budget(role(s))
                raw['roundNo'] = budget['latest_departure']
                third = record_attempt(memory, 1, raw['roundNo'], (15, 14), '自进化类2')
                arrival, bought, used = None, None, []
                for number in range(raw['roundNo'], 71):
                    self.assertEqual(raw['roundNo'], number)
                    if number == 67:
                        finish_attempt(memory, third, number, succeeded=True)
                        memory.task_active_attempt = None
                    s, plan = load_strategy(raw, memory, settings)
                    self.assertFalse(s.boss_raid.dispatch_ready())
                    s.run_worker(role(s))
                    self.assertTrue(memory.boss_raid.get('departure_authorized'))
                    command = plan.commands.get(str(BUYER), {})
                    self.assertNotIn(command.get('action'), ('build', 'collect', 'sell'))
                    if plan.near_zone(role(s), 'weaponShop') and arrival is None:
                        arrival = number
                    if number < 67 and plan.near_zone(role(s), 'weaponShop'):
                        self.assertNotIn(str(BUYER), plan.commands)
                        self.assertIn(BUYER, plan.used)
                    if command.get('action') == 'move':
                        here = role(s).pos
                        for point in command['targetPos']:
                            there = Pos.load(point)
                            self.assertEqual(distance(here, there), 1)
                            self.assertNotIn(there, s.turn.occupied_cells())
                            here = there
                        actor(raw)['pos'] = here.dump()
                    elif command.get('action') == 'buy':
                        self.assertEqual(command, dict(action='buy', name=ORDER, num=3))
                        self.assertEqual(number, 67)
                        self.assertIsNone(bought)
                        bought = number
                        actor(raw)['backpack'] += [ORDER] * 3
                        raw['teamOur']['goldNum'] -= 360
                    elif command.get('action') == 'use':
                        self.assertEqual(command['name'], ORDER)
                        self.assertIn(ORDER, actor(raw)['backpack'])
                        used.append(Pos.load(command['targetPos'][0]))
                        actor(raw)['backpack'].remove(ORDER)
                    else:
                        self.assertFalse(command)
                    self.assertFalse(plan.rejections)
                    if number < 70:
                        advance(raw, memory, s, plan)
                self.assertIsNotNone(arrival)
                self.assertLessEqual(arrival, 66)
                self.assertEqual(bought, 67)
                self.assertEqual(len(set(used)), 3)
                self.assertNotIn(ORDER, actor(raw)['backpack'])

    def test_departure_deadline_does_not_dispatch_unfinished_wall_scout_but_live_imp_can_supply_sight(self):
        raw, memory, settings = unfinished_scene(round_no=66)
        actor(raw)['pos'] = Pos(17, 13).dump()
        actor(raw, SCOUT)['pos'] = Pos(9, 25).dump()
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles']
                                    if u['roleType'] == 'station']
        s, plan = load_strategy(raw, memory, settings)
        s.run_worker(role(s))
        self.assertTrue(memory.boss_raid.get('departure_authorized'))
        self.assertFalse(s.raid_scouts.dispatch_granted())
        self.assertFalse(s.raid_scouts.is_worker(role(s, SCOUT)))
        self.assertFalse(s.raid_scouts.summon_ready())
        advance(raw, memory, s, plan)
        third = record_attempt(memory, 1, 64, (15, 14), '自进化类2')
        finish_attempt(memory, third, 67, succeeded=False)
        memory.task_active_attempt = None
        # These are current ordinary IMP observations, not remembered guns or
        # robot sight. The full cap of three observed guns fixes the layout.
        raw['teamOur']['roles'].append(unit(505, 'imp', 35, 7, health=500))
        raw['teamEnemy']['roles'] += [unit(991+i, 'rocket', 33, y, health=1000)
                                     for i, y in enumerate((9, 8, 7))]
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(s.raid_scouts.dispatch_granted())
        self.assertFalse(s.raid_scouts.is_worker(role(s, SCOUT)))
        self.assertTrue(s.raid_scouts.summon_ready())
        self.assertTrue(s.raid_scouts.state['imp_ready'])
        s.run_worker(role(s))
        self.assertEqual(plan.commands[str(BUYER)], dict(action='buy', name=ORDER, num=2))
        actor(raw)['backpack'] += [ORDER]*2
        raw['teamOur']['goldNum'] -= 240
        advance(raw, memory, s, plan)
        s, plan = load_strategy(raw, memory, settings)
        s.run_worker(role(s))
        self.assertEqual((plan.commands[str(BUYER)]['action'],
                          plan.commands[str(BUYER)]['name']), ('use', ORDER))
        self.assertFalse(s.raid_scouts.dispatch_granted())
        self.assertFalse(s.raid_scouts.is_worker(role(s, SCOUT)))
        self.assertFalse(plan.rejections)

    def test_completed_zero_or_one_order_does_not_resume_early_defence(self):
        forbidden = {'first_night_guard', 'return_guard', 'gap_wait'}
        for successes in (0, 1):
            with self.subTest(successes=successes):
                raw, memory, settings = worker_raid_scene(round_no=67, successes=successes)
                settings = replace(settings, enable_first_night_defense=True)
                if successes:
                    s, plan = load_strategy(raw, memory, settings)
                    s.run_worker(role(s))
                    self.assertEqual(plan.commands[str(BUYER)], dict(action='buy', name=ORDER, num=1))
                    actor(raw)['backpack'].append(ORDER)
                    raw['teamOur']['goldNum'] -= 120
                    advance(raw, memory, s, plan)
                    s, plan = load_strategy(raw, memory, settings)
                    s.run_worker(role(s))
                    self.assertEqual((plan.commands[str(BUYER)]['action'],
                                      plan.commands[str(BUYER)]['name']), ('use', ORDER))
                    actor(raw)['backpack'].remove(ORDER)
                    advance(raw, memory, s, plan)
                else:
                    raw['roundNo'] = 69
                for number in (69, 70):
                    self.assertEqual(raw['roundNo'], number)
                    s, plan = load_strategy(raw, memory, settings)
                    s.run_worker(role(s))
                    self.assertNotIn(memory.worker_tasks.get(BUYER, {}).get('kind'), forbidden)
                    self.assertNotIn(memory.first_night_defense.get('status'),
                                     {'returning', 'prepared_guard', 'waiting_for_supply', 'night_guard'})
                    self.assertFalse(s.day_gate.closing())
                    command = plan.commands.get(str(BUYER), {})
                    self.assertFalse(command.get('name') == ORDER and
                                     command.get('action') in ('buy', 'use'))
                    self.assertFalse(plan.rejections)
                    # Expose purchases/uses/moves instead of letting a stale
                    # bag optimistically authorize repeated transactions.
                    if command.get('action') == 'buy':
                        actor(raw)['backpack'] += [command['name']]*command.get('num', 1)
                        raw['teamOur']['goldNum'] -= s.turn.shop_prices[command['name']]*command.get('num', 1)
                    elif command.get('action') == 'use':
                        actor(raw)['backpack'].remove(command['name'])
                    elif command.get('action') == 'move':
                        actor(raw)['pos'] = command['targetPos'][-1]
                    if number < 70:
                        advance(raw, memory, s, plan)

    def test_first_night_still_repairs_actual_damage_without_daytime_summon_actions(self):
        raw, memory, settings = worker_raid_scene(round_no=71, successes=1)
        settings = replace(settings, enable_first_night_defense=True)
        actor(raw)['pos'] = Pos(10, 24).dump()
        actor(raw)['backpack'] += ['WallFixer', ORDER]
        wall = next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'wall'
                    and u['pos'] == Pos(11, 24).dump())
        wall['health'] = 100
        s, plan = load_strategy(raw, memory, settings)
        s.run_worker(role(s))
        self.assertEqual(plan.commands[str(BUYER)],
                         dict(action='use', name='WallFixer', targetPos=[wall['pos']]))
        self.assertFalse(any(c.get('action') == 'build' or
                             c.get('name') == ORDER and c.get('action') in ('buy', 'use')
                             for c in plan.commands.values()))
        self.assertFalse(plan.rejections)

    def test_first_night_actual_vacated_gap_retains_body_guard_without_night_build(self):
        from tests.test_gap_defense import GAP, occupied
        from app.config import Settings
        from app.service.memory import GameMemory
        raw = occupied(70)
        memory = GameMemory(opening_complete=True, boss_raid={'buyer_id': BUYER})
        settings = Settings(enable_news=False, enable_first_night_defense=True)
        s, plan = load_strategy(raw, memory, settings)
        self.assertIn(GAP, s.gap_guard.gaps)
        memory.record(s.turn, plan)
        raw['roundNo'] = 71
        raw['teamEnemy']['roles'] = []
        actor(raw)['backpack'] += [ORDER]
        memory.observe(Turn.load(raw))
        s, plan = load_strategy(raw, memory, settings)
        s.run_worker(role(s))
        self.assertEqual(plan.commands[str(BUYER)], dict(action='move', targetPos=[GAP.dump()]))
        self.assertNotIn(GAP, s.turn.occupied_cells())
        self.assertFalse(any(c.get('action') == 'build' or
                             c.get('name') == ORDER and c.get('action') in ('buy', 'use')
                             for c in plan.commands.values()))
        self.assertFalse(plan.rejections)

    def test_departure_budget_has_no_home_margin_and_counts_actual_drop_rounds(self):
        for full_bag in (False, True):
            with self.subTest(full_bag=full_bag):
                raw, memory, settings = unfinished_scene(full_bag=full_bag)
                settings = replace(settings, return_margin=100)
                outbound = shop_steps(raw, settings)
                s, _ = load_strategy(raw, memory, settings)
                budget = s.boss_raid.departure_budget(role(s))
                self.assertIsNotNone(budget)
                self.assertEqual(budget['travel'], outbound)
                self.assertEqual(budget['drop'], 3 if full_bag else 0)
                self.assertEqual(budget['buy'], 1)
                self.assertEqual(budget['use'], 3)
                self.assertEqual(budget['opening'], 0)
                self.assertEqual(budget['total'], budget['travel'] + budget['drop']
                                 + budget['buy'] + budget['use'] + budget['opening']
                                 + budget['slack'])
                self.assertLess(budget['total'], 50)
                self.assertEqual(budget['latest_departure'], 71 - budget['total'])

    def test_early_unfinished_walls_still_allow_worker_construction(self):
        raw, memory, settings = unfinished_scene()
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(s.boss_raid.dispatch_ready())
        self.assertFalse(s.boss_raid.worker_mission_active(role(s)))
        self.assertFalse(s.boss_raid.worker(role(s)))
        self.assertNotIn(str(BUYER), plan.commands)

    def test_last_outbound_deadline_preempts_unfinished_wall_in_both_corners(self):
        for lower_right in (False, True):
            with self.subTest(lower_right=lower_right):
                raw, memory, settings = unfinished_scene(lower_right=lower_right)
                outbound = shop_steps(raw, settings)
                raw['roundNo'] = 71 - (outbound + 1 + 3)
                s, plan = load_strategy(raw, memory, settings)
                self.assertEqual(s.turn.daylight_left, outbound + 4)
                self.assertFalse(s.boss_raid.dispatch_ready())
                self.assertTrue(s.boss_raid.worker_mission_active(role(s)))
                self.assertTrue(s.boss_raid.worker(role(s)))
                command = plan.commands[str(BUYER)]
                self.assertEqual(command['action'], 'move')
                self.assertLess(distance(Pos.load(command['targetPos'][-1]), SHOP),
                                distance(role(s).pos, SHOP))
                self.assertFalse(any(c.get('action') == 'buy' for c in plan.commands.values()))
                self.assertFalse(plan.rejections)

    def test_full_bag_deadline_reserves_each_actual_drop_action(self):
        raw, memory, settings = unfinished_scene(full_bag=True)
        outbound = shop_steps(raw, settings)
        raw['roundNo'] = 71 - (outbound + 3 + 1 + 3)
        s, plan = load_strategy(raw, memory, settings)
        self.assertEqual(s.turn.daylight_left, outbound + 7)
        self.assertTrue(s.boss_raid.worker_mission_active(role(s)))
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertIn(plan.commands[str(BUYER)]['action'], ('move', 'drop'))
        self.assertFalse(plan.rejections)
        # Dispatch alone does not free capacity or invent a bought coupon.
        self.assertEqual(len(actor(raw)['backpack']), 100)
        self.assertNotIn(ORDER, actor(raw)['backpack'])

    def test_driving_deadline_uses_two_real_steps_per_action(self):
        raw, memory, settings = unfinished_scene(driving=True)
        outbound = shop_steps(raw, settings)
        self.assertGreater(outbound, 4)
        travel = (outbound + 1) // 2
        raw['roundNo'] = 71 - (travel + 1 + 3)
        s, plan = load_strategy(raw, memory, settings)
        self.assertTrue(s.boss_raid.worker_mission_active(role(s)))
        self.assertTrue(s.boss_raid.worker(role(s)))
        command = plan.commands[str(BUYER)]
        self.assertEqual(command['action'], 'move')
        self.assertEqual(len(command['targetPos']), 2)
        first, second = map(Pos.load, command['targetPos'])
        self.assertEqual(distance(role(s).pos, first), 1)
        self.assertEqual(distance(first, second), 1)
        self.assertFalse(plan.rejections)

    def test_shop_waits_through_unfinished_third_task_without_refunding_wall_time(self):
        raw, memory, settings = unfinished_scene(round_no=67)
        actor(raw)['pos'] = Pos(17, 13).dump()
        s, plan = load_strategy(raw, memory, settings)
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertIn(BUYER, plan.used)
        self.assertNotIn(str(BUYER), plan.commands)
        self.assertNotIn('order_decision_round', memory.boss_raid)
        self.assertFalse(plan.rejections)

    def test_shop_purchase_and_three_uses_fit_final_four_daytime_actions(self):
        raw, memory, settings = worker_raid_scene(round_no=67, successes=3)
        actor(raw, PIONEER)['pos'] = Pos(40, 0).dump()
        used = []
        for index in range(4):
            s, plan = load_strategy(raw, memory, settings)
            self.assertTrue(s.boss_raid.worker(role(s)))
            command = plan.commands[str(BUYER)]
            if index == 0:
                self.assertEqual(command, dict(action='buy', name=ORDER, num=3))
                actor(raw)['backpack'] += [ORDER] * 3
                raw['teamOur']['goldNum'] = 0
            else:
                self.assertEqual((command['action'], command['name']), ('use', ORDER))
                used.append(Pos.load(command['targetPos'][0]))
                actor(raw)['backpack'].remove(ORDER)
            self.assertFalse(plan.rejections)
            if index < 3:
                advance(raw, memory, s, plan)
        self.assertEqual(raw['roundNo'], 70)
        self.assertEqual(len(set(used)), 3)
        self.assertNotIn(ORDER, actor(raw)['backpack'])

    def test_no_sight_still_never_uses_coupon_even_at_the_deadline(self):
        raw, memory, settings = worker_raid_scene(round_no=70, successes=1)
        actor(raw)['backpack'] += [ORDER]
        raw['teamOur']['goldNum'] = 0
        actor(raw, SCOUT)['pos'] = Pos(16, 12).dump()
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles']
                                    if u['roleType'] == 'station']
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(s.raid_scouts.summon_ready())
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertNotIn(str(BUYER), plan.commands)
        self.assertIn(BUYER, plan.used)
        self.assertEqual(actor(raw)['backpack'].count(ORDER), 1)

    def test_existing_sealed_home_does_not_send_an_unrequested_remove_action(self):
        raw, memory, settings = worker_raid_scene(round_no=60, finished=2)
        actor(raw)['pos'] = Pos(8, 25).dump()
        s, plan = load_strategy(raw, memory, settings)
        self.assertIsNone(s.boss_raid.departure_budget(role(s)))
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertFalse(any(c.get('action') == 'remove' for c in plan.commands.values()))
        self.assertIsNone(s.route(role(s)).nearest(adjacent_cells(s.turn, [SHOP])))
        self.assertEqual(len(s.turn.walls()), 17)
        self.assertEqual(plan.rejections, [])

    def test_sealed_home_deadline_budget_does_not_forecast_a_demolished_wall(self):
        raw, memory, settings = worker_raid_scene(round_no=1, finished=2)
        actor(raw)['pos'] = Pos(8, 25).dump()
        s, _ = load_strategy(raw, memory, settings)
        self.assertIsNone(s.boss_raid.departure_budget(role(s)))
        # Forecasting never mutates the actual permanent fortification.
        self.assertEqual(len(s.turn.walls()), 17)
        self.assertIsNone(s.day_gate.pos)
        self.assertFalse(s.day_gate.enabled)

    def test_first_day_supply_trip_ignores_return_margin_at_the_actual_shop(self):
        raw, memory, settings = worker_raid_scene(round_no=70, successes=0)
        settings = replace(settings, enable_first_night_defense=True, return_margin=100)
        s, _ = load_strategy(raw, memory, settings)
        buyer = role(s)
        trip = s.first_defense.trip(buyer, {buyer.pos}, interactions=1)
        self.assertIsNotNone(trip)
        self.assertEqual(trip[0], 1)
        self.assertEqual(trip[2], buyer.pos)

    def test_first_day_gate_never_reserves_worker_return_time(self):
        for round_no in (69, 70):
            with self.subTest(round_no=round_no):
                raw, memory, settings = worker_raid_scene(round_no=round_no, successes=0)
                settings = replace(settings, enable_first_night_defense=True)
                s, plan = load_strategy(raw, memory, settings)
                self.assertFalse(s.day_gate.closing())
                self.assertFalse(s.day_gate.worker(role(s)))
                self.assertNotIn(str(BUYER), plan.commands)


if __name__ == '__main__':
    unittest.main()
