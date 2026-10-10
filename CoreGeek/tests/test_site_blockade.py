"""Hostile occupation, outward detours, dawn races and observed-state cleanup."""
import copy
import unittest

from agent.actions import ActionPlan
from agent.protocol import Pos, Turn, build_command, distance
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import TurnService
from tests.fixtures import unit, robot, layout_settings
from tests.test_maintenance import fortified
from tests.test_u_layout import WALLS, point
from tests.test_worker_safety import strategy


GAP = Pos(9, 7)
DETOUR = {Pos(8, 6), Pos(8, 7), Pos(8, 8)}


def camped(round_no=6, mirrored=False, gaps=(GAP,), detour=False):
    raw = fortified(round_no, mirrored, weapon_level=3, wall_level=3)
    gaps = {point(p.x, p.y, mirrored) for p in gaps}
    raw['teamOur']['roles'] = [r for r in raw['teamOur']['roles']
                             if r['roleType'] != 'wall' or Pos.load(r['pos']) not in gaps]
    raw['teamOur']['goldNum'] = 0
    raw['weaponShopList'] = []
    raw['teamOur']['roles'][2].update(pos=point(10, 5, mirrored).dump(), backpack=['stone'] * 4)
    raw['teamOur']['roles'][3].update(pos=point(3, 4, mirrored).dump(), backpack=[])
    raw['teamEnemy']['roles'] = [unit(901+i, 'worker', p.x, p.y, health=500)
                               for i, p in enumerate(sorted(gaps))]
    raw['mapInfo']['zones'] = [{'neutralType': kind, 'pos': point(x, y, mirrored).dump()}
                             for kind, x, y in (('stone', 3, 5), ('iron', 3, 3), ('iron', 11, 5))]
    raw['vendorShopList'] = [{'name': 'stone', 'price': 1}, {'name': 'iron', 'price': 3}]
    if detour:
        for uid, pos in enumerate(sorted(DETOUR), 2001):
            p = point(pos.x, pos.y, mirrored)
            raw['teamOur']['roles'].append(unit(uid, 'wall', p.x, p.y))
    return raw


def confirm(raw, memory=None):
    memory = memory or GameMemory(opening_complete=True)
    current = raw['roundNo']
    for number in range(current - 5, current + 1):
        raw['roundNo'] = number
        strategy(raw, memory)
    return memory


def apply_commands(test, raw, response):
    """Small observation fixture; not a simulator of official simultaneous turns."""
    before = Turn.load(raw)
    destinations = set()
    for uid, command in response['roleCommandMap'].items():
        actor = next(r for r in raw['teamOur']['roles'] if str(r['id']) == uid)
        action = command['action']
        if action in ('move', 'build'):
            target = Pos.load(command['targetPos'][0])
            test.assertEqual(distance(Pos.load(actor['pos']), target), 1)
            test.assertNotIn(target, before.occupied_cells())
            test.assertNotIn(target, destinations)
            destinations.add(target)
            if action == 'move':
                actor['pos'] = target.dump()
            else:
                test.assertTrue(before.is_day)
                test.assertEqual(command['name'], 'wall')
                test.assertIn('stone', actor['backpack'])
                actor['backpack'].remove('stone')
                raw['teamOur']['roles'].append(unit(3000 + raw['roundNo'] * 10 + int(uid) % 10,
                                                    'wall', target.x, target.y))
        elif action == 'collect':
            target = Pos.load(command['targetPos'][0])
            test.assertEqual(distance(Pos.load(actor['pos']), target), 1)
            actor['backpack'].append(before.zones[target])
        elif action == 'remove':
            target = Pos.load(command['targetPos'][0])
            test.assertEqual(distance(Pos.load(actor['pos']), target), 1)
            raw['teamOur']['roles'] = [r for r in raw['teamOur']['roles']
                if r['roleType'] != 'wall' or Pos.load(r['pos']) != target]
        elif action == 'use' and command['name'] == 'WallFixer':
            actor['backpack'].remove('WallFixer')
    raw['lastRoundRoleActionResults'] = {uid: True for uid in response['roleCommandMap']}


class SiteBlockadeTests(unittest.TestCase):
    def test_six_consecutive_rounds_confirm_camping_but_five_do_not(self):
        raw, memory = camped(), GameMemory(opening_complete=True)
        for number in range(1, 7):
            raw['roundNo'] = number
            s, _ = strategy(raw, memory)
            self.assertEqual(memory.site_occupations[GAP]['count'], number)
            self.assertEqual(bool(memory.wall_blockades), number > 5)
            self.assertEqual(s.site_guard.temporary_needed, DETOUR if number > 5 else set())

    def test_same_round_does_not_increment_and_missing_round_or_changed_id_resets(self):
        raw, memory = camped(), GameMemory(opening_complete=True)
        for number in (1, 2, 2):
            raw['roundNo'] = number; strategy(raw, memory)
        self.assertEqual(memory.site_occupations[GAP]['count'], 2)
        raw['roundNo'] = 4; strategy(raw, memory)
        self.assertEqual(memory.site_occupations[GAP]['count'], 1)
        raw['roundNo'] = 5; raw['teamEnemy']['roles'][0]['id'] = 902; strategy(raw, memory)
        self.assertEqual(memory.site_occupations[GAP]['count'], 1)
        raw['roundNo'] = 6; raw['teamEnemy']['roles'] = []; strategy(raw, memory)
        self.assertEqual(memory.site_occupations, {})
        self.assertEqual(memory.wall_blockades, {})

    def test_departure_does_not_drop_the_breach_before_observed_rebuild(self):
        raw = camped(); memory = confirm(raw)
        raw['roundNo'] = 7; raw['teamEnemy']['roles'] = []
        strategy(raw, memory)
        self.assertIn(GAP, memory.wall_blockades)
        raw['roundNo'] = 8; raw['teamOur']['roles'].append(unit(2500, 'wall', 9, 7))
        strategy(raw, memory)
        self.assertNotIn(GAP, memory.wall_blockades)

    def test_only_live_enemy_roles_on_unbuilt_facilities_count(self):
        for kind, health, counted in (('worker', 500, True), ('pioneer', 500, True),
                                     ('imp', 500, True), ('worker', 0, False), ('wall', 1000, False)):
            raw = camped(); raw['teamEnemy']['roles'][0].update(roleType=kind, health=health)
            memory = confirm(raw)
            self.assertEqual(bool(memory.wall_blockades), counted)
        raw = camped(); raw['teamEnemy']['roles'] = []
        raw['robot']['roles'] = [robot(901, 9, 7)]
        self.assertEqual(confirm(raw).wall_blockades, {})

    def test_detour_geometry_front_corner_and_mirror_leave_inner_posts_free(self):
        for mirrored in (False, True):
            raw = camped(mirrored=mirrored)
            turn = Turn.load(raw); settings = Settings()
            gap = point(9, 7, mirrored)
            self.assertEqual(set(settings.wall_detour_cells(turn, gap)),
                             {point(p.x, p.y, mirrored) for p in DETOUR})
            corner = {Pos(8, 8)}
            self.assertEqual(set(settings.wall_detour_cells(turn, point(9, 9, mirrored))),
                             {point(p.x, p.y, mirrored) for p in corner})
            self.assertEqual(set(settings.wall_detour_cells(turn, point(7, 4, mirrored))),
                             {point(x, 5, mirrored) for x in (6, 7, 8)})

    def test_detour_gate_keeps_night_and_strict_layout_limits(self):
        raw = camped(); raw['teamOur']['roles'][2]['pos'] = {'x': 7, 'y': 8}
        turn = Turn.load(raw); target = Pos(8, 7)
        plan = ActionPlan(turn, Settings())
        self.assertFalse(plan.add(501, build_command(target, 'wall')))
        plan.authorize_wall_detour(GAP)
        self.assertTrue(plan.add(501, build_command(target, 'wall')), plan.rejections)
        for settings in (Settings(allow_base_surroundings=False), layout_settings()):
            plan = ActionPlan(turn, settings); plan.authorize_wall_detour(GAP)
            self.assertFalse(plan.add(501, build_command(target, 'wall')))
        raw['roundNo'] = 71
        plan = ActionPlan(Turn.load(raw), Settings()); plan.authorize_wall_detour(GAP)
        self.assertFalse(plan.add(501, build_command(target, 'wall')))

    def test_both_sides_wrap_wait_rebuild_on_dawn_and_then_remove_detours(self):
        for mirrored in (False, True):
            raw = camped(round_no=1, mirrored=mirrored)
            service = TurnService(Settings(enable_tasks=False, enable_news=False))
            gap = point(9, 7, mirrored)
            detour = {point(p.x, p.y, mirrored) for p in DETOUR}
            for number in range(1, 71):
                raw['roundNo'] = number
                response = service.decide(copy.deepcopy(raw))
                apply_commands(self, raw, response)
            standing = {Pos.load(r['pos']) for r in raw['teamOur']['roles'] if r['roleType'] == 'wall'}
            self.assertTrue(detour <= standing)
            self.assertNotIn(gap, standing)
            raw['teamEnemy']['roles'][0]['pos'] = point(14, 14, mirrored).dump()
            for number in (71, 100, 130):
                raw['roundNo'] = number
                response = service.decide(copy.deepcopy(raw))
                self.assertFalse(any(c['action'] == 'build' for c in response['roleCommandMap'].values()))
                memory = next(iter(service.sessions.values())).memory
                owner = next(r for r in raw['teamOur']['roles'] if r['id'] == memory.blockade_worker_id)
                self.assertTrue(any(distance(Pos.load(owner['pos']), p) == 1 for p in detour))
                self.assertIn('stone', owner['backpack'])
                apply_commands(self, raw, response)
            rebuilt_at = None
            # An inner seal may require walking around the U to an exposed
            # original-wall neighbour. No temporary wall is removed first.
            for number in range(131, 171):
                raw['roundNo'] = number
                response = service.decide(copy.deepcopy(raw))
                self.assertFalse(any(c['action'] == 'remove' for c in response['roleCommandMap'].values()))
                apply_commands(self, raw, response)
                if build_command(gap, 'wall') in response['roleCommandMap'].values():
                    rebuilt_at = number
                    break
            self.assertIsNotNone(rebuilt_at)
            for number in range(rebuilt_at + 1, 210):
                raw['roundNo'] = number
                response = service.decide(copy.deepcopy(raw))
                for command in response['roleCommandMap'].values():
                    if command['action'] == 'remove':
                        self.assertIn(Pos.load(command['targetPos'][0]), detour)
                apply_commands(self, raw, response)
                standing = {Pos.load(r['pos']) for r in raw['teamOur']['roles'] if r['roleType'] == 'wall'}
                if not detour & standing:
                    break
            self.assertFalse(detour & standing)
            self.assertTrue({point(x, y, mirrored) for x, y in WALLS} <= standing)

    def test_one_worker_watches_while_the_other_keeps_mining(self):
        raw = camped(70, detour=True)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'])
        memory = confirm(raw); s, plan = strategy(raw, memory); s.run()
        self.assertEqual(memory.worker_tasks[501]['kind'], 'blockade_watch')
        self.assertNotIn('501', plan.commands)
        self.assertEqual(plan.commands['504']['action'], 'collect')
        self.assertEqual(plan.rejections, [])

    def test_failed_or_recaptured_rebuild_never_triggers_early_removal(self):
        raw = camped(130, detour=True)
        raw['teamOur']['roles'][2].update(pos={'x': 10, 'y': 7}, backpack=['stone'])
        memory = confirm(raw); memory.temporary_wall_sites = set(DETOUR)
        raw['teamEnemy']['roles'] = []; raw['roundNo'] = 131
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501'], build_command(GAP, 'wall'))
        memory.record(s.turn, plan)
        raw['roundNo'] = 132; raw['lastRoundRoleActionResults'] = {'501': False}
        raw['teamEnemy']['roles'] = [unit(901, 'worker', 9, 7)]
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(s.site_guard.cleanup_sites, set())
        self.assertFalse(any(c['action'] == 'remove' for c in plan.commands.values()))
        self.assertIn(GAP, memory.wall_blockades)

    def test_temporary_walls_are_excluded_from_upgrade_goals(self):
        raw = camped(131, detour=True)
        raw['teamEnemy']['roles'] = []
        raw['teamOur']['roles'].append(unit(2500, 'wall', 9, 7, level=3, health=2000))
        memory = GameMemory(opening_complete=True, temporary_wall_sites=set(DETOUR))
        s, _ = strategy(raw, memory)
        self.assertTrue(s.upgrades_complete())
        self.assertEqual(s.upgrade_candidates(), [])

    def test_shared_detour_stays_until_all_supported_gaps_are_filled(self):
        raw = camped(131, gaps=(GAP, Pos(9, 6)))
        memory = confirm(raw)
        all_detours = DETOUR | {Pos(8, 5)}
        memory.temporary_wall_sites = all_detours.copy()
        for uid, p in enumerate(sorted(all_detours), 2001):
            raw['teamOur']['roles'].append(unit(uid, 'wall', p.x, p.y))
        raw['teamOur']['roles'].append(unit(2500, 'wall', 9, 6))
        raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][1:]
        raw['roundNo'] = 132
        s, _ = strategy(raw, memory)
        self.assertEqual(s.site_guard.cleanup_sites, {Pos(8, 5)})

    def test_standby_can_repair_an_adjacent_critical_wall_without_losing_stone(self):
        raw = camped(70, detour=True)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone', 'WallFixer'])
        next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall'
             and r['pos'] == {'x': 8, 'y': 8})['health'] = 1
        memory = confirm(raw); s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501']['name'], 'WallFixer')
        self.assertEqual(plan.commands['501']['targetPos'], [{'x': 8, 'y': 8}])
        self.assertEqual(memory.worker_tasks[501]['kind'], 'blockade_repair')

    def test_dead_watcher_is_reassigned_and_revival_does_not_steal_current_post(self):
        raw = camped(70, detour=True)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'])
        memory = confirm(raw)
        raw['roundNo'] = 71; raw['teamOur']['roles'][2]['health'] = 0
        raw['teamOur']['roles'][3].update(pos={'x': 7, 'y': 5}, backpack=['stone'])
        s, _ = strategy(raw, memory)
        self.assertEqual(s.site_guard.worker_id, 504)
        raw['roundNo'] = 131; raw['teamOur']['roles'][2]['health'] = 220
        s, _ = strategy(raw, memory)
        self.assertEqual(memory.blockade_worker_id, 504)

    def test_empty_bag_watcher_collects_a_stone_and_returns_before_night(self):
        raw = camped(50, detour=True)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=[])
        raw['teamOur']['roles'][3]['health'] = 0
        memory = confirm(raw)
        memory.temporary_wall_sites = set(DETOUR)
        collected = False
        for number in range(50, 71):
            raw['roundNo'] = number
            s, plan = strategy(raw, memory); s.run()
            collected |= plan.commands.get('501', {}).get('action') == 'collect'
            apply_commands(self, raw, {'roleCommandMap': plan.commands})
            memory.record(s.turn, plan)
        self.assertTrue(collected)
        worker = raw['teamOur']['roles'][2]
        self.assertIn('stone', worker['backpack'])
        self.assertTrue(any(distance(Pos.load(worker['pos']), p) == 1 for p in DETOUR))

    def test_preexisting_detour_position_wall_is_not_marked_for_removal(self):
        raw = camped(detour=True)
        memory = confirm(raw)
        self.assertEqual(memory.temporary_wall_sites, set())
        raw['roundNo'] = 7
        raw['teamEnemy']['roles'] = []
        raw['teamOur']['roles'].append(unit(2500, 'wall', 9, 7))
        s, _ = strategy(raw, memory)
        self.assertEqual(s.site_guard.cleanup_sites, set())

    def test_cached_service_request_does_not_count_another_round(self):
        raw = camped(round_no=1)
        service = TurnService(Settings(enable_news=False, enable_tasks=False))
        for number in range(1, 6):
            raw['roundNo'] = number
            first = service.decide(copy.deepcopy(raw))
            self.assertEqual(first, service.decide(copy.deepcopy(raw)))
        memory = next(iter(service.sessions.values())).memory
        self.assertEqual(memory.site_occupations[GAP]['count'], 5)
        self.assertEqual(memory.wall_blockades, {})


if __name__ == '__main__':
    unittest.main()
