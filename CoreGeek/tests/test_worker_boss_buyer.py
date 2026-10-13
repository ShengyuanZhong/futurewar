"""First-day BOSS purchases belong to a worker, independent of task travel.

These observations enforce the actual shop position, three settled task
attempts, actor-specific bags and next-round feedback. They are local policy
regressions; they do not simulate official opponents or later game days.
"""
import unittest
from dataclasses import replace

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.first_day_tasks import finish_attempt, record_attempt
from agent.protocol import Pos, Turn, distance
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, unit


ORDER = 'BossRobotSummonOrder'
SHOP = Pos(18, 13)
BUYER = 501
SCOUT = 504
PIONEER = 502


def worker_raid_scene(round_no=40, lower_right=False, finished=3, successes=2):
    """Keep the shop fixed when changing the base; do not mirror its distance."""
    raw = request(round_no)
    base = Pos(31, 8) if lower_right else Pos(8, 24)
    enemy = Pos(8, 24) if lower_right else Pos(31, 8)
    settings = Settings(enable_news=False, enable_first_night_defense=False)
    raw['teamOur'].update(playerTasks=[], goldNum=360)
    raw['mapInfo']['zones'] = [
        dict(neutralType='weaponShop', pos=SHOP.dump()),
        dict(neutralType='vendor', pos=Pos(20, 13).dump()),
        dict(neutralType='stone', pos=Pos(17, 15).dump()),
    ]
    raw['weaponShopList'] = [dict(name=ORDER, price=120),
                            dict(name='WeaponUpgradeVoucher1', price=100),
                            dict(name='WallFixer', price=10)]
    raw['teamOur']['roles'] = [
        unit(503, 'station', base.x, base.y, health=2000),
        unit(BUYER, 'worker', 17, 13, health=500, backpack=['stone']),
        unit(PIONEER, 'pioneer', 16, 14, health=500),
        unit(SCOUT, 'worker', enemy.x + (-2 if lower_right else 3), enemy.y - 2,
             health=500),
    ]
    turn = Turn.load(raw)
    operator = settings.default_operator_position(turn)
    raw['teamOur']['roles'][2]['pos'] = operator.dump()
    for uid, p in enumerate(settings.build_cells(turn, 'rocket'), 600):
        raw['teamOur']['roles'].append(unit(uid, 'rocket', p.x, p.y, health=1000))
    gate = Pos(base.x + (2 if lower_right else -1), base.y + 2)
    for uid, p in enumerate(settings.build_cells(turn, 'wall'), 700):
        if p != gate:
            raw['teamOur']['roles'].append(unit(uid, 'wall', p.x, p.y, health=1000))
    gun_x = enemy.x + (-1 if lower_right else 2)
    raw['teamEnemy']['roles'] = [unit(990, 'station', enemy.x, enemy.y, health=2000)]
    raw['teamEnemy']['roles'] += [unit(991 + i, 'rocket', gun_x, enemy.y + dy, health=1000)
                                 for i, dy in enumerate((1, 0, -1))]
    memory = GameMemory(opening_complete=True)
    memory.raid_scouts.update(worker_id=SCOUT, home_worker_id=BUYER)
    memory.boss_raid['buyer_id'] = BUYER
    memory.day_gate['worker_id'] = BUYER
    for index, (accepted, ended, point, kind) in enumerate((
            (1, 4, (15, 14), '自进化类2'),
            (8, 11, (13, 14), '自进化类1'),
            (34, 37, (15, 14), '自进化类2'))[:finished]):
        key = record_attempt(memory, 1, accepted, point, kind, origin='isolated_fixture')
        finish_attempt(memory, key, ended, succeeded=index < successes)
    memory.task_active_attempt = None
    return raw, memory, settings


def load_strategy(raw, memory, settings):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, settings)
    return Strategy(turn, plan, memory), plan


def role(strategy, uid=BUYER):
    return next(u for u in strategy.turn.ours if u.unit_id == uid)


def actor(raw, uid=BUYER):
    return next(u for u in raw['teamOur']['roles'] if u['id'] == uid)


def advance(raw, memory, strategy, plan, results=None):
    """Record commands, then expose their explicit next-round acknowledgements."""
    memory.record(strategy.turn, plan)
    raw['roundNo'] += 1
    raw['lastRoundRoleActionResults'] = results or {uid: True for uid in plan.commands}
    memory.observe(Turn.load(raw))


class WorkerBossBuyerTests(unittest.TestCase):
    def test_departed_buyer_and_scout_keep_missions_when_camper_leaves(self):
        raw,memory,settings = worker_raid_scene(successes=1)
        gap = Pos(11,24)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not(u['roleType']=='wall' and u['pos']==gap.dump())]
        raw['teamEnemy']['roles'].append(unit(905,'worker',gap.x,gap.y,health=500))
        actor(raw)['backpack'] += ['stone']
        s,plan = load_strategy(raw,memory,settings)
        self.assertTrue(s.boss_raid.dispatch_ready())
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertEqual(plan.commands[str(BUYER)],dict(action='buy',name=ORDER,num=1))
        self.assertTrue(memory.boss_raid['buyer_departed'])
        actor(raw)['backpack'].append(ORDER)
        advance(raw,memory,s,plan)
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['id']!=905]
        s,plan = load_strategy(raw,memory,settings)
        self.assertFalse(s.boss_raid.dispatch_ready())  # Never pretend the hole was built.
        self.assertTrue(s.boss_raid.worker_mission_active(role(s)))
        self.assertTrue(s.raid_scouts.is_worker(role(s,SCOUT)))
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertEqual(plan.commands[str(BUYER)]['action'],'use')
        self.assertEqual(plan.commands[str(BUYER)]['name'],ORDER)
        self.assertEqual(plan.rejections,[])

    def test_two_departing_workers_yield_at_the_actual_single_entrance(self):
        raw,memory,settings = worker_raid_scene(finished=2)
        base = Pos(8,24)
        gate = Pos(7,26)
        actor(raw)['pos'] = Pos(base.x,base.y+1).dump()
        actor(raw,SCOUT)['pos'] = gate.dump()
        # Neither worker is near the enemy yet: no hidden gun may be supplied
        # as current sight, and a homeward scout may safely yield one step.
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['roleType']=='station']
        s,plan = load_strategy(raw,memory,settings)
        s.run()
        self.assertEqual(plan.commands[str(SCOUT)]['action'],'move')
        self.assertNotEqual(plan.commands[str(SCOUT)]['targetPos'],[actor(raw)['pos']])
        self.assertIn(BUYER,plan.used)
        self.assertNotIn(str(BUYER),plan.commands)
        self.assertFalse(plan.rejections)
        next_pos = plan.commands[str(SCOUT)]['targetPos'][-1]
        advance(raw,memory,s,plan)
        actor(raw,SCOUT)['pos'] = next_pos
        s,plan = load_strategy(raw,memory,settings)
        s.run()
        self.assertEqual(plan.commands[str(BUYER)],dict(action='move',targetPos=[gate.dump()]))
        self.assertFalse(plan.rejections)

    def test_initial_dispatch_roles_remain_distinct_and_stable(self):
        raw, memory, settings = worker_raid_scene(successes=1)
        memory.boss_raid.clear()
        memory.raid_scouts.clear()
        s, _ = load_strategy(raw, memory, settings)
        self.assertEqual(s.boss_raid.buyer_id, BUYER)
        self.assertEqual(memory.raid_scouts.get('worker_id'), SCOUT)
        buyer_pos = actor(raw)['pos']
        actor(raw)['pos'] = actor(raw, SCOUT)['pos']
        actor(raw, SCOUT)['pos'] = buyer_pos
        raw['roundNo'] += 1
        s, _ = load_strategy(raw, memory, settings)
        self.assertEqual(s.boss_raid.buyer_id, BUYER)
        self.assertEqual(memory.raid_scouts.get('worker_id'), SCOUT)

    def test_midday_restart_does_not_invent_known_purchase_history(self):
        raw, _, settings = worker_raid_scene()
        memory = GameMemory(opening_complete=True)
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(memory.boss_raid.get('history_known'))
        self.assertTrue(memory.boss_raid.get('purchase_closed'))
        s.boss_raid.worker(role(s))
        self.assertFalse(any(c.get('action') in ('buy', 'use') and c.get('name') == ORDER
                             for c in plan.commands.values()))

    def test_batch_quantity_follows_zero_to_three_successful_tasks(self):
        for successes in range(4):
            with self.subTest(successes=successes):
                raw, memory, settings = worker_raid_scene(successes=successes)
                s, plan = load_strategy(raw, memory, settings)
                s.boss_raid.worker(role(s))
                command = plan.commands.get(str(BUYER), {})
                if successes:
                    self.assertEqual(command, dict(action='buy', name=ORDER, num=successes))
                    self.assertEqual(plan.gold, 360 - successes * 120)
                    self.assertEqual(memory.boss_raid['pending_buy']['actor_id'], BUYER)
                else:
                    self.assertFalse(command.get('action') == 'buy' and command.get('name') == ORDER)
                self.assertNotIn(str(PIONEER), plan.commands)
                self.assertEqual(plan.rejections, [])

    def test_non_symmetric_shop_does_not_require_pioneer_travel(self):
        for lower_right in (False, True):
            with self.subTest(lower_right=lower_right):
                raw, memory, settings = worker_raid_scene(lower_right=lower_right, successes=3)
                s, plan = load_strategy(raw, memory, settings)
                self.assertTrue(s.boss_raid.worker(role(s)))
                self.assertEqual(plan.commands[str(BUYER)], dict(action='buy', name=ORDER, num=3))
                self.assertNotIn(str(PIONEER), plan.commands)
                self.assertEqual(next(p for p, kind in s.turn.zones.items() if kind == 'weaponShop'), SHOP)

    def test_worker_waits_at_shop_until_third_attempt_is_settled(self):
        raw, memory, settings = worker_raid_scene(finished=2, successes=2)
        s, plan = load_strategy(raw, memory, settings)
        s.boss_raid.worker(role(s))
        self.assertFalse(any(c.get('action') == 'buy' and c.get('name') == ORDER
                             for c in plan.commands.values()))
        self.assertNotIn('order_decision_round', memory.boss_raid)
        # A third accepted attempt with no ending is also insufficient.
        record_attempt(memory, 1, 34, (15, 14), '自进化类2')
        s, plan = load_strategy(raw, memory, settings)
        s.boss_raid.worker(role(s))
        self.assertFalse(any(c.get('action') == 'buy' and c.get('name') == ORDER
                             for c in plan.commands.values()))
        self.assertNotIn('order_decision_round', memory.boss_raid)

    def test_builder_prepositions_before_task_outcomes_are_known(self):
        raw, memory, settings = worker_raid_scene(round_no=20, finished=1, successes=1)
        actor(raw)['pos'] = Pos(16, 13).dump()
        s, plan = load_strategy(raw, memory, settings)
        self.assertTrue(s.boss_raid.worker(role(s)))
        command = plan.commands[str(BUYER)]
        self.assertEqual(command['action'], 'move')
        target = Pos.load(command['targetPos'][-1])
        self.assertEqual(distance(target, SHOP), 1)
        self.assertFalse(any(c.get('action') == 'buy' for c in plan.commands.values()))

    def test_interior_buyer_really_removes_closed_gate_before_exiting(self):
        raw, memory, settings = worker_raid_scene(round_no=20, finished=1)
        base = Pos.load(actor(raw, 503)['pos'])
        gate = Pos(base.x - 1, base.y + 2)
        raw['teamOur']['roles'].append(unit(800, 'wall', gate.x, gate.y, health=1000))
        actor(raw)['pos'] = Pos(base.x, base.y + 1).dump()
        s, plan = load_strategy(raw, memory, settings)
        self.assertEqual(len(s.turn.walls()), 17)
        s.run()
        self.assertEqual(plan.commands[str(BUYER)], dict(action='remove', targetPos=[gate.dump()]))
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['id'] != 800]
        advance(raw, memory, s, plan)
        s, plan = load_strategy(raw, memory, settings)
        s.run()
        self.assertEqual(plan.commands[str(BUYER)], dict(action='move', targetPos=[gate.dump()]))
        self.assertEqual(len(s.turn.walls()), 16)
        self.assertEqual(plan.rejections, [])

    def test_unbuilt_unoccupied_wall_keeps_buyer_on_construction(self):
        raw, memory, settings = worker_raid_scene(finished=1)
        wall = next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'wall')
        raw['teamOur']['roles'].remove(wall)
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(s.boss_raid.worker(role(s)))
        self.assertNotIn(str(BUYER), plan.commands)

    def test_occupied_wall_is_ignored_without_stealing_scout(self):
        raw, memory, settings = worker_raid_scene(finished=1)
        wall = next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'wall')
        raw['teamOur']['roles'].remove(wall)
        p = Pos.load(wall['pos'])
        raw['teamEnemy']['roles'].append(unit(1100, 'worker', p.x, p.y, health=500))
        actor(raw)['pos'] = Pos(16, 13).dump()
        s, plan = load_strategy(raw, memory, settings)
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertEqual(plan.commands[str(BUYER)]['action'], 'move')
        self.assertFalse(s.boss_raid.worker(role(s, SCOUT)))
        self.assertNotIn(str(SCOUT), plan.commands)

    def test_buy_confirmation_and_three_uses_read_only_worker_bag(self):
        raw, memory, settings = worker_raid_scene(successes=3)
        s, plan = load_strategy(raw, memory, settings)
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertEqual(plan.commands[str(BUYER)]['action'], 'buy')
        actor(raw)['backpack'] += [ORDER] * 3
        raw['teamOur']['goldNum'] = 0
        # A coupon in the pioneer bag must not inflate this worker's inventory.
        actor(raw, PIONEER)['backpack'] = [ORDER]
        advance(raw, memory, s, plan)
        used = []
        for _ in range(3):
            s, plan = load_strategy(raw, memory, settings)
            self.assertTrue(s.boss_raid.worker(role(s)))
            command = plan.commands[str(BUYER)]
            self.assertEqual((command['action'], command['name']), ('use', ORDER))
            self.assertEqual(memory.boss_raid['pending_use']['actor_id'], BUYER)
            self.assertNotIn(str(PIONEER), plan.commands)
            used.append(Pos.load(command['targetPos'][0]))
            actor(raw)['backpack'].remove(ORDER)
            advance(raw, memory, s, plan)
        s, plan = load_strategy(raw, memory, settings)
        self.assertEqual(memory.boss_raid['deployed_count'], 3)
        self.assertEqual(memory.boss_raid['acquired_count'], 3)
        self.assertEqual(len(set(used)), 3)
        s.boss_raid.worker(role(s))
        self.assertFalse(any(c.get('action') == 'buy' and c.get('name') == ORDER
                             for c in plan.commands.values()))
        self.assertEqual(actor(raw, PIONEER)['backpack'], [ORDER])

    def test_explicit_failed_buy_retries_without_fake_inventory(self):
        raw, memory, settings = worker_raid_scene(successes=2)
        s, plan = load_strategy(raw, memory, settings)
        s.boss_raid.worker(role(s))
        advance(raw, memory, s, plan, {str(BUYER): False, str(PIONEER): True})
        s, plan = load_strategy(raw, memory, settings)
        self.assertEqual(memory.boss_raid['acquired_count'], 0)
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertEqual(plan.commands[str(BUYER)], dict(action='buy', name=ORDER, num=2))

    def test_failed_use_changes_spawn_without_buying_again(self):
        raw, memory, settings = worker_raid_scene(successes=1)
        actor(raw)['backpack'] += [ORDER]
        raw['teamOur']['goldNum'] = 0
        s, plan = load_strategy(raw, memory, settings)
        s.boss_raid.worker(role(s))
        before = Pos.load(plan.commands[str(BUYER)]['targetPos'][0])
        advance(raw, memory, s, plan, {str(BUYER): False, str(PIONEER): True})
        s, plan = load_strategy(raw, memory, settings)
        self.assertEqual(memory.boss_raid['deployed_count'], 0)
        self.assertTrue(s.boss_raid.worker(role(s)))
        command = plan.commands[str(BUYER)]
        self.assertEqual((command['action'], command['name']), ('use', ORDER))
        self.assertNotEqual(Pos.load(command['targetPos'][0]), before)
        self.assertEqual(memory.boss_raid['acquired_count'], 1)

    def test_stale_success_feedback_cannot_resummon_same_coupon(self):
        raw, memory, settings = worker_raid_scene(successes=1)
        actor(raw)['backpack'] += [ORDER]
        raw['teamOur']['goldNum'] = 0
        s, plan = load_strategy(raw, memory, settings)
        s.boss_raid.worker(role(s))
        # Feedback reports successful use but bag remains stale: close purchases.
        advance(raw, memory, s, plan)
        s, plan = load_strategy(raw, memory, settings)
        s.boss_raid.worker(role(s))
        self.assertEqual(memory.boss_raid['deployed_count'], 1)
        self.assertTrue(memory.boss_raid['purchase_closed'])
        self.assertFalse(any(c.get('action') == 'use' and c.get('name') == ORDER
                             for c in plan.commands.values()))

    def test_full_mineral_bag_never_sends_illegal_purchase(self):
        raw, memory, settings = worker_raid_scene(successes=3)
        actor(raw)['backpack'] = ['stone'] + ['iron'] * 99
        freed = 0
        for _ in range(4):
            s, plan = load_strategy(raw, memory, settings)
            self.assertTrue(s.boss_raid.worker(role(s)))
            command = plan.commands.get(str(BUYER), {})
            self.assertEqual(plan.rejections, [])
            if command.get('action') == 'buy':
                self.assertEqual(command, dict(action='buy', name=ORDER, num=3))
                self.assertEqual(freed, 3)
                self.assertLessEqual(len(actor(raw)['backpack']) + 3, 100)
                break
            # Capacity is freed with actual commands/feedback, not just an
            # optimistic counter. The one gate stone must remain available.
            self.assertEqual(command.get('action'), 'drop')
            self.assertEqual(command['name'], 'iron')
            actor(raw)['backpack'].remove(command['name'])
            self.assertEqual(actor(raw)['backpack'].count('stone'), 1)
            freed += 1
            advance(raw, memory, s, plan)
        else:
            self.fail('full mineral bag never freed three slots for the actual batch')

    def test_worker_holds_orders_until_current_shared_sight_is_reliable(self):
        raw, memory, settings = worker_raid_scene(successes=1)
        s, _ = load_strategy(raw, memory, settings)  # Observe real three guns.
        actor(raw, SCOUT)['pos'] = Pos(16, 12).dump()
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles']
                                    if u['roleType'] == 'station']
        actor(raw)['backpack'] += [ORDER]
        raw['teamOur']['goldNum'] = 0
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(s.raid_scouts.summon_ready())
        s.boss_raid.worker(role(s))
        self.assertFalse(any(c.get('action') == 'use' and c.get('name') == ORDER
                             for c in plan.commands.values()))
        self.assertEqual(actor(raw)['backpack'].count(ORDER), 1)

    def test_pioneer_goes_home_after_third_task_never_claims_coupons(self):
        raw, memory, settings = worker_raid_scene(successes=2)
        actor(raw, PIONEER)['pos'] = Pos(16, 14).dump()
        s, plan = load_strategy(raw, memory, settings)
        s.run()
        command = plan.commands.get(str(PIONEER), {})
        self.assertEqual(command.get('action'), 'move')
        self.assertNotEqual(command.get('name'), ORDER)
        self.assertEqual(plan.commands[str(BUYER)], dict(action='buy', name=ORDER, num=2))
        self.assertEqual(plan.rejections, [])

    def test_late_day_purchase_is_not_preempted_by_gate_or_supply_return(self):
        raw, memory, settings = worker_raid_scene(round_no=67, successes=1)
        settings = replace(settings, enable_first_night_defense=True)
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(s.day_gate.closing())
        self.assertEqual(s.first_defense.worker_id, BUYER)
        s.run()
        self.assertEqual(plan.commands[str(BUYER)], dict(action='buy', name=ORDER, num=1))
        self.assertNotIn(str(PIONEER), plan.commands)
        self.assertEqual(plan.rejections, [])

    def test_night_never_buys_or_uses_daytime_summon_order(self):
        raw, memory, settings = worker_raid_scene(round_no=71, successes=2)
        actor(raw)['backpack'] += [ORDER] * 2
        settings = replace(settings, enable_first_night_defense=True)
        s, plan = load_strategy(raw, memory, settings)
        s.run()
        self.assertFalse(any(c.get('action') in ('buy', 'use') and c.get('name') == ORDER
                             for c in plan.commands.values()))
        self.assertEqual(plan.commands[str(BUYER)]['action'], 'move')


if __name__ == '__main__':
    unittest.main()
