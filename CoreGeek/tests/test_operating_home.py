"""Day-one/day-two boundary and v1.1.2 operation, without an official simulator."""
import copy
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.grid import Routes
from agent.protocol import Pos, Turn
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import TurnService
from tests.fixtures import unit, layout_settings
from tests.test_maintenance import fortified
from tests.test_u_layout import point


# These coordinates are copied from v1.1.2, independent of the new generator.
OPERATING = {(6, 9), (7, 9), (8, 9), (9, 9), (9, 8), (9, 7),
             (9, 6), (9, 5), (9, 4), (8, 4), (7, 4), (6, 4)}
CLOSURES = {(5, 9), (5, 4), (4, 4), (4, 5), (4, 6)}


def actor(raw, uid):
    return next(u for u in raw['teamOur']['roles'] if u['id'] == uid)


def scene(round_no=131, mirrored=False, closed=False, complete=False):
    raw = fortified(round_no, mirrored, weapon_level=3 if complete else 1,
                    wall_level=2 if complete else 1, closed=closed)
    if not closed:
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if u['roleType'] != 'wall' or Pos.load(u['pos']) not in
            {point(x, y, mirrored) for x, y in CLOSURES}]
    if complete:
        for wall in raw['teamOur']['roles']:
            if wall['roleType'] == 'wall' and wall['pos']['x'] == point(9, 7, mirrored).x:
                wall.update(level=3, health=2000)
    raw['weaponShopList'].append({'name': 'BossRobotSummonOrder', 'price': 120})
    return raw


def strategy(raw, memory=None, settings=None):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, settings or Settings(enable_tasks=False, enable_news=False))
    return Strategy(turn, plan, memory or GameMemory(opening_complete=True)), plan


class OperatingHomeTests(unittest.TestCase):
    def test_day_one_closed_then_exact_v112_u_on_day_two_both_mirrors_and_teams(self):
        for mirrored in (False, True):
            for team in ('challenger', 'defender'):
                raw = scene(130, mirrored, closed=True)
                raw['teamOur']['type'] = team
                settings = Settings()
                expected = {point(x, y, mirrored) for x, y in OPERATING}
                self.assertEqual(set(settings.build_cells(Turn.load(raw), 'wall')),
                                 expected | {point(x, y, mirrored) for x, y in CLOSURES})
                raw['roundNo'] = 131
                self.assertEqual(set(settings.build_cells(Turn.load(raw), 'wall')), expected)
                self.assertEqual(set(settings.build_cells(Turn.load(raw), 'rocket')),
                                 {point(5, y, mirrored) for y in (6, 7, 8)})

    def test_no_first_night_removal_and_closures_never_become_rebuild_targets(self):
        raw = scene(130, closed=True)
        s, plan = strategy(raw)
        self.assertFalse(s.operating_home.enabled)
        self.assertTrue(s.sealed_home.enabled)
        self.assertFalse(s.operating_home.worker(s.turn.workers()[0]))
        raw['roundNo'] = 131
        s, _ = strategy(raw)
        self.assertFalse(s.sealed_home.enabled)
        self.assertEqual(s.missing_walls(), [])
        self.assertEqual(s.construction_walls(), [])
        self.assertFalse(s.day_gate.enabled)

    def test_dawn_releases_opening_jobs_but_preserves_static_layout_and_task_evidence(self):
        raw = scene(closed=True)
        memory = GameMemory(day=1, opening_complete=True)
        memory.worker_tasks = {
            501: dict(kind='boss_shop_wait', round=130, position=Pos(4, 9), goal=Pos(20, 15), yield_until=150),
            504: dict(kind='first_night_guard', round=130, position=Pos(3, 6), goal=Pos(4, 9), yield_until=150)}
        memory.raid_scouts.update(worker_id=504, home_worker_id=501, opening_scout_complete=True)
        memory.boss_raid.update(buyer_id=501, mission_started=True, pending_buy={'round': 130},
                                target_count=3, acquired_count=0, summon_window_closed=True)
        memory.wall_gap_defense['gaps'] = {Pos(9, 7): {'first_seen': 4}}
        memory.enemy_weapon_sites[Pos(34, 23)] = 'rocket'
        memory.task_points_finished.add((1, 17, 17))
        raw['teamOur']['goldNum'] = 0
        raw['mapInfo']['zones'].append({'neutralType': 'iron', 'pos': {'x': 2, 'y': 6}})
        raw['vendorShopList'] = [{'name': 'iron', 'price': 3}]
        memory.observe(Turn.load(raw))
        s, plan = strategy(raw, memory)
        s.run()
        self.assertEqual(plan.commands['501']['action'], 'remove')
        self.assertEqual(plan.commands['504']['action'], 'collect')
        self.assertFalse(s.raid_scouts.active)
        self.assertFalse(s.gap_guard.gaps)
        self.assertFalse(s.first_defense.enabled)
        self.assertEqual(s.boss_raid.budget_reserve(), 0)
        self.assertEqual(memory.enemy_weapon_sites, {Pos(34, 23): 'rocket'})
        self.assertIn((1, 17, 17), memory.task_points_finished)
        self.assertEqual(plan.rejections, [])

    def test_removal_waits_for_real_feedback_and_finishes_five_closures_with_mirror(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                raw = scene(mirrored=mirrored, closed=True)
                raw['teamOur']['goldNum'] = 0
                raw['mapInfo']['zones'] = []
                memory = GameMemory(opening_complete=True)
                removed, failed = set(), None
                for number in range(131, 171):
                    raw['roundNo'] = number
                    memory.observe(Turn.load(raw))
                    s, plan = strategy(raw, memory)
                    if not s.operating_home.extra:
                        break
                    s.run()
                    self.assertEqual(plan.rejections, [])
                    raw['lastRoundRoleActionResults'] = {}
                    for uid, command in plan.commands.items():
                        if command['action'] == 'move':
                            actor(raw, int(uid))['pos'] = command['targetPos'][-1]
                        if command['action'] == 'remove':
                            target = Pos.load(command['targetPos'][0])
                            self.assertNotIn(target, {point(x, y, mirrored) for x, y in OPERATING})
                            if failed is None:
                                failed = target
                                raw['lastRoundRoleActionResults'][uid] = False
                                self.assertIn(target, {w.pos for w in s.operating_home.extra})
                                continue  # Command issuance does not change the observed geometry.
                            raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                if not (u['roleType'] == 'wall' and Pos.load(u['pos']) == target)]
                            removed.add(target)
                            raw['lastRoundRoleActionResults'][uid] = True
                        self.assertNotEqual(command.get('name'), 'BossRobotSummonOrder')
                    memory.record(s.turn, plan)
                else:
                    self.fail('repair lane not restored within forty local rounds')
                self.assertEqual(removed, {point(x, y, mirrored) for x, y in CLOSURES})
                self.assertEqual({w.pos for w in s.turn.walls()}, {point(x, y, mirrored) for x, y in OPERATING})
                for worker in s.turn.workers():
                    self.assertIn(point(8, 7, mirrored), Routes(s.turn, worker).cost)
                self.assertEqual(s.guard.duty_cells(), s.guard.inner_cells())

    def test_dead_restorer_is_replaced_using_current_reachable_worker(self):
        raw = scene(closed=True)
        memory = GameMemory(opening_complete=True, operating_home={'worker_id': 501})
        actor(raw, 501)['health'] = 0
        s, plan = strategy(raw, memory)
        self.assertEqual(s.operating_home.worker_id, 504)
        self.assertTrue(s.operating_home.worker(s.turn.workers()[0]))
        self.assertNotIn('501', plan.commands)

    def test_custom_verified_layout_is_never_automatically_dismantled(self):
        raw = scene(closed=True)
        s, _ = strategy(raw, settings=layout_settings())
        self.assertEqual(s.operating_home.extra, [])

    def test_day_two_breach_uses_observed_stone_and_no_body_guard(self):
        raw = scene()
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType'] == 'wall' and u['pos'] == Pos(9, 7).dump())]
        actor(raw, 501).update(pos={'x': 8, 'y': 7}, backpack=['stone'])
        memory = GameMemory(opening_complete=True)
        memory.wall_gap_defense['gaps'] = {Pos(9, 7): {'first_seen': 4}}
        s, plan = strategy(raw, memory)
        s.run_worker(next(w for w in s.turn.workers() if w.unit_id == 501))
        self.assertEqual(plan.commands['501'], dict(action='build', name='wall', targetPos=[{'x': 9, 'y': 7}]))
        self.assertEqual(sum(s.stone_targets().values()), 1)

    def test_day_two_catch_does_not_preempt_an_adjacent_upgrade(self):
        raw = scene()
        actor(raw, 501).update(pos={'x': 4, 'y': 5}, backpack=['WeaponUpgradeVoucher1'])
        raw['teamEnemy']['roles'].append(unit(900, 'imp', 3, 5, health=100))
        s, plan = strategy(raw)
        s.run_worker(next(w for w in s.turn.workers() if w.unit_id == 501))
        self.assertEqual(plan.commands['501']['action'], 'use')
        self.assertEqual(plan.commands['501']['name'], 'WeaponUpgradeVoucher1')

    def test_extra_closures_do_not_consume_upgrade_budget_or_block_final_stage(self):
        raw = scene(closed=True, complete=True)
        for wall in raw['teamOur']['roles']:
            if wall['roleType'] == 'wall' and Pos.load(wall['pos']) in {Pos(x, y) for x, y in CLOSURES}:
                wall.update(level=1, health=100)
        s, _ = strategy(raw)
        self.assertTrue(s.upgrades_complete())
        self.assertEqual(s.upgrade_candidates(), [])

    def test_final_daytime_still_mines_sells_and_buys_bulk_kits_then_returns_at_dusk(self):
        raw = scene(261, complete=True)
        raw['teamOur']['goldNum'] = 0
        actor(raw, 501).update(pos={'x': 2, 'y': 2}, backpack=['WallFixer'] * 5)
        actor(raw, 504).update(pos={'x': 3, 'y': 6}, backpack=['WallFixer'] * 5)
        raw['mapInfo']['zones'].append({'neutralType': 'iron', 'pos': {'x': 2, 'y': 1}})
        raw['vendorShopList'] = [{'name': 'iron', 'price': 3}]
        s, plan = strategy(raw)
        s.run_worker(next(w for w in s.turn.workers() if w.unit_id == 501))
        self.assertEqual(plan.commands['501']['action'], 'collect')
        actor(raw, 501).update(pos={'x': 2, 'y': 8}, backpack=['iron'] * 12)
        s, plan = strategy(raw)
        s.run_worker(next(w for w in s.turn.workers() if w.unit_id == 501))
        self.assertEqual(plan.commands['501']['action'], 'sell')
        actor(raw, 501).update(pos={'x': 2, 'y': 6}, backpack=[])
        raw['teamOur']['goldNum'] = 200
        raw['weaponShopList'] = [{'name': 'WallFixer', 'price': 15}]
        s, plan = strategy(raw)
        s.run_worker(next(w for w in s.turn.workers() if w.unit_id == 501))
        self.assertEqual(plan.commands['501']['name'], 'WallFixer')
        self.assertGreater(plan.commands['501']['num'], 1)
        raw['roundNo'] = 330  # Day 3's last daytime turn: normal return budget restored.
        actor(raw, 501).update(pos={'x': 4, 'y': 8}, backpack=['WallFixer'] * 5)
        s, plan = strategy(raw)
        s.run_worker(next(w for w in s.turn.workers() if w.unit_id == 501))
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertIn(s.memory.worker_tasks[501]['kind'], ('guard_post', 'return_guard'))

    def test_two_night_repairers_use_distinct_inner_walls_below_thirty_percent(self):
        raw = scene(331, complete=True)
        for uid, y in ((501, 7), (504, 6)):
            actor(raw, uid).update(pos={'x': 8, 'y': y}, backpack=['WallFixer'] * 10)
            wall = next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'wall'
                        and u['pos'] == Pos(9, y).dump())
            wall['health'] = 599  # L3 max HP 2000, strict less-than-30% trigger.
        s, plan = strategy(raw)
        s.run()
        self.assertEqual({tuple(c['targetPos'][0].values()) for uid, c in plan.commands.items()
                          if uid in ('501', '504')}, {(9, 7), (9, 6)})
        self.assertTrue(all(plan.commands[uid]['name'] == 'WallFixer' for uid in ('501', '504')))
        self.assertEqual(plan.rejections, [])

    def test_restoring_is_observable_through_real_turn_service(self):
        raw = scene(closed=True)
        service = TurnService(Settings(enable_tasks=False, enable_news=False))
        response = service.decide(copy.deepcopy(raw))
        self.assertEqual(response['roleCommandMap']['501']['action'], 'remove')
        state = next(iter(service.sessions.values())).memory.operating_home
        self.assertEqual(state['enabled'], True)
        self.assertEqual(len(state['pending']), 5)
