"""Inner sealing and material scheduling from the first-day blockade logs."""
from collections import deque
from types import SimpleNamespace
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn, build_command, distance
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import unit, layout_settings
from tests.test_site_blockade import camped, GAP


INNER = {Pos(8, 6), Pos(8, 7), Pos(8, 8)}


def left(number=61, standing=()):
    raw = camped(number)
    raw['teamOur']['roles'][2].update(pos={'x': 8, 'y': 7}, backpack=['stone'] * 4)
    for uid, cell in enumerate(standing, 52000):
        raw['teamOur']['roles'].append(unit(uid, 'wall', cell.x, cell.y, health=1000))
    return raw


def corner_log4(number=64):
    # The historic horizontal mirror has base (33,7). Translate it to the
    # actual log4 base (30,10); the blocked corner is then exactly (28,7).
    raw = camped(number, mirrored=True, gaps=(Pos(9, 4),))
    for actor in raw['teamOur']['roles'] + raw['teamEnemy']['roles']:
        actor['pos'] = {'x': actor['pos']['x'] - 3, 'y': actor['pos']['y'] + 3}
    for zone in raw['mapInfo']['zones']:
        zone['pos'] = {'x': zone['pos']['x'] - 3, 'y': zone['pos']['y'] + 3}
    raw['teamOur']['roles'][2].update(pos={'x': 29, 'y': 8}, backpack=['stone'] * 2)
    raw['teamOur']['roles'][3].update(pos={'x': 26, 'y': 7}, backpack=['stone'] * 2)
    return raw


def setup(raw, memory=None, run=True, settings=None):
    state = memory if memory is not None else GameMemory(opening_complete=True)
    configured = settings or Settings(enable_boss_raid=False, enable_tasks=False, enable_news=False)
    turn = Turn.load(raw)
    plan = ActionPlan(turn, configured)
    strategy = Strategy(turn, plan, state)
    if run:
        for worker in turn.workers():
            strategy.site_guard.watch(worker)
    return strategy, plan


def confirmed(raw):
    state = GameMemory(opening_complete=True)
    current = raw['roundNo']
    for number in range(current - 5, current + 1):
        raw['roundNo'] = number
        setup(raw, state, run=False)
    return state


def advance(test, raw, strategy, plan):
    """Apply only supplied observations, not an official collision simulator."""
    occupied = strategy.turn.occupied_cells()
    destinations = set()
    for actor_id, command in plan.commands.items():
        actor = next(u for u in raw['teamOur']['roles'] if str(u['id']) == actor_id)
        target = Pos.load(command['targetPos'][0])
        test.assertEqual(distance(Pos.load(actor['pos']), target), 1)
        if command['action'] in ('move', 'build'):
            test.assertNotIn(target, occupied)
            test.assertNotIn(target, destinations)
            destinations.add(target)
        if command['action'] == 'move':
            actor['pos'] = target.dump()
        elif command['action'] == 'build':
            test.assertTrue(strategy.turn.is_day)
            test.assertIn('stone', actor['backpack'])
            actor['backpack'].remove('stone')
            raw['teamOur']['roles'].append(unit(60000 + raw['roundNo'] * 10 + int(actor_id) % 10,
                'wall', target.x, target.y, health=1000))
        elif command['action'] == 'collect':
            actor['backpack'].append(strategy.turn.zones[target])
        elif command['action'] == 'remove':
            raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                      if u['roleType'] != 'wall' or Pos.load(u['pos']) != target]
        else:
            test.fail('unexpected fixture command: ' + repr(command))
    raw['lastRoundRoleActionResults'] = {actor_id: True for actor_id in plan.commands}
    strategy.memory.record(strategy.turn, plan)


class BlockadeLogRegressions(unittest.TestCase):
    def test_default_front_bypass_is_three_inner_cells(self):
        raw = left()
        turn = Turn.load(raw)
        self.assertEqual(set(Settings().wall_detour_cells(turn, GAP)), INNER)
        self.assertEqual(set(Settings().wall_detour_cells(turn, GAP, outward=True)),
                         {Pos(10, 6), Pos(10, 7), Pos(10, 8)})

    def test_log4_corner_maps_to_single_inner_diagonal(self):
        raw = corner_log4()
        turn = Turn.load(raw)
        self.assertEqual(turn.station().pos, Pos(30, 10))
        self.assertEqual(set(Settings().wall_detour_cells(turn, Pos(28, 7))), {Pos(29, 8)})
        self.assertNotIn(Pos(27, 8), Settings().wall_detour_cells(turn, Pos(28, 7)))

    def test_front_corners_and_horizontal_edges_are_inward(self):
        turn = Turn.load(left())
        self.assertEqual(set(Settings().wall_detour_cells(turn, Pos(9, 4))), {Pos(8, 5)})
        self.assertEqual(set(Settings().wall_detour_cells(turn, Pos(9, 9))), {Pos(8, 8)})
        self.assertEqual(set(Settings().wall_detour_cells(turn, Pos(7, 9))),
                         {Pos(6, 8), Pos(7, 8), Pos(8, 8)})
        self.assertEqual(set(Settings().wall_detour_cells(turn, Pos(7, 4))),
                         {Pos(6, 5), Pos(7, 5), Pos(8, 5)})

    def test_geometry_excludes_towers_terrain_and_strict_layouts(self):
        raw = left()
        raw['mapInfo']['zones'].append({'neutralType': 'stone', 'pos': {'x': 8, 'y': 6}})
        raw['teamOur']['roles'].append(unit(52900, 'rocket', 8, 8))
        turn = Turn.load(raw)
        self.assertEqual(set(Settings().wall_detour_cells(turn, GAP)), {Pos(8, 7)})
        self.assertEqual(Settings(allow_base_surroundings=False).wall_detour_cells(turn, GAP), ())
        self.assertEqual(layout_settings().wall_detour_cells(turn, GAP), ())

    def test_original_stone_stash_deadlock_now_clears_and_collects_stone(self):
        raw = left()
        memory = confirmed(raw)
        strategy, plan = setup(raw, memory)
        self.assertEqual(strategy.stone_targets(), {501: 4, 504: 0})
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertNotIn(Pos.load(plan.commands['501']['targetPos'][0]), INNER)
        self.assertEqual(memory.worker_tasks[501]['kind'], 'blockade_clear')
        self.assertEqual(plan.commands['504'], {'action': 'collect', 'targetPos': [{'x': 3, 'y': 5}]})
        self.assertEqual(strategy.site_guard.seal_assignments[504], {Pos(8, 6)})
        self.assertEqual(plan.rejections, [])

    def test_two_workers_finish_inner_seal_and_keep_original_stone(self):
        raw = left()
        memory = confirmed(raw)
        owners = []
        for number in range(61, 71):
            raw['roundNo'] = number
            strategy, plan = setup(raw, memory)
            owners.append(memory.blockade_worker_id)
            advance(self, raw, strategy, plan)
            standing = {Pos.load(u['pos']) for u in raw['teamOur']['roles'] if u['roleType'] == 'wall'}
            if INNER <= standing:
                break
        self.assertTrue(INNER <= standing)
        self.assertEqual(set(owners), {501})
        watcher = next(u for u in raw['teamOur']['roles'] if u['id'] == 501)
        self.assertIn('stone', watcher['backpack'])
        self.assertNotIn(GAP, standing)

    def test_log4_failed_outward_point_records_feedback_then_builds_inner(self):
        raw = corner_log4()
        memory = confirmed(raw)
        memory.blockade_worker_id = 501
        memory.last_round = 63
        memory.last_commands = {'504': build_command(Pos(27, 8), 'wall')}
        raw['lastRoundRoleActionResults'] = {'504': False}
        strategy, plan = setup(raw, memory)
        failed = memory.wall_blockades[Pos(28, 7)]['failed_sites'][Pos(27, 8)]
        self.assertEqual(failed['count'], 1)
        self.assertEqual(failed['round'], 64)
        self.assertEqual(strategy.site_guard.temporary_needed, {Pos(29, 8)})
        self.assertEqual(plan.commands['501']['action'], 'move')
        destination = Pos.load(plan.commands['501']['targetPos'][0])
        self.assertNotEqual(destination, Pos(29, 8))
        self.assertIn(destination, strategy.guard.inner_cells())
        advance(self, raw, strategy, plan)
        raw['roundNo'] = 65
        strategy, plan = setup(raw, memory)
        self.assertEqual(plan.commands['501'], build_command(Pos(29, 8), 'wall'))
        self.assertFalse(any(Pos.load(c['targetPos'][0]) == Pos(27, 8) for c in plan.commands.values()))
        self.assertEqual(plan.rejections, [])

    def test_last_temp_command_is_not_observed_completion(self):
        raw = left(64, standing=INNER - {Pos(8, 6)})
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'])
        raw['teamOur']['roles'][3].update(pos={'x': 7, 'y': 5}, backpack=['stone'])
        memory = confirmed(raw)
        memory.blockade_worker_id = 501
        strategy, plan = setup(raw, memory)
        self.assertEqual(plan.commands['504'], build_command(Pos(8, 6), 'wall'))
        self.assertIn(Pos(8, 6), memory.temporary_wall_sites)
        self.assertEqual(strategy.site_guard.temporary_needed, {Pos(8, 6)})
        self.assertFalse(memory.wall_blockades[GAP]['sealed_observed'])
        memory.record(strategy.turn, plan)
        raw['roundNo'] = 65
        raw['lastRoundRoleActionResults'] = {'504': True}
        strategy, _ = setup(raw, memory, run=False)
        self.assertFalse(memory.wall_blockades[GAP]['sealed_observed'])
        raw['teamOur']['roles'].append(unit(52800, 'wall', 8, 6, health=1000))
        raw['roundNo'] = 66
        strategy, _ = setup(raw, memory, run=False)
        self.assertTrue(memory.wall_blockades[GAP]['sealed_observed'])

    def test_sealed_guard_can_fetch_kits_without_being_marked_used(self):
        raw = left(70, standing=INNER)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'])
        memory = confirmed(raw)
        strategy, plan = setup(raw, memory, run=False)
        strategy.first_defense = SimpleNamespace(worker_id=501, needs_supply=lambda role: True)
        watcher = next(w for w in strategy.turn.workers() if w.unit_id == 501)
        self.assertTrue(strategy.site_guard.sealed(GAP))
        self.assertTrue(strategy.site_guard.sealed())
        self.assertFalse(strategy.site_guard.watch(watcher))
        self.assertNotIn(501, plan.used)
        self.assertNotIn('501', plan.commands)

    def test_unconfirmed_seal_does_not_handoff_to_supply(self):
        raw = left(70, standing=INNER - {Pos(8, 8)})
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'] * 2)
        memory = confirmed(raw)
        strategy, plan = setup(raw, memory, run=False)
        strategy.first_defense = SimpleNamespace(worker_id=501, needs_supply=lambda role: True)
        watcher = next(w for w in strategy.turn.workers() if w.unit_id == 501)
        self.assertFalse(strategy.site_guard.sealed())
        self.assertTrue(strategy.site_guard.watch(watcher))
        self.assertEqual(plan.commands['501'], build_command(Pos(8, 8), 'wall'))
        self.assertFalse(strategy.site_guard.sealed())

    def test_night_guard_handoff_never_builds(self):
        raw = left(71, standing=INNER)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'])
        memory = confirmed(raw)
        strategy, plan = setup(raw, memory, run=False)
        strategy.first_defense = SimpleNamespace(worker_id=501, needs_supply=lambda role: False)
        watcher = next(w for w in strategy.turn.workers() if w.unit_id == 501)
        self.assertFalse(strategy.site_guard.watch(watcher))
        self.assertNotIn(501, plan.used)
        self.assertFalse(any(c['action'] == 'build' for c in plan.commands.values()))

    def test_failed_inner_site_is_not_repeated_or_falsely_sealed(self):
        raw = left(62)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'] * 4)
        raw['teamOur']['roles'][3].update(pos={'x': 7, 'y': 5}, backpack=['stone'])
        memory = confirmed(raw)
        memory.blockade_worker_id = 501
        memory.last_round = 61
        memory.last_commands = {'501': build_command(Pos(8, 7), 'wall')}
        raw['lastRoundRoleActionResults'] = {'501': False}
        for number in range(62, 69):
            raw['roundNo'] = number
            strategy, plan = setup(raw, memory)
            self.assertTrue(strategy.site_guard.failed(Pos(8, 7)))
            self.assertFalse(memory.wall_blockades[GAP]['sealed_observed'])
            self.assertFalse(any(c['action'] == 'build' and c['targetPos'] == [{'x': 8, 'y': 7}]
                                 for c in plan.commands.values()))
            advance(self, raw, strategy, plan)
        self.assertEqual(memory.wall_blockades[GAP]['failed_sites'][Pos(8, 7)]['count'], 1)
        self.assertIn(Pos(8, 7), strategy.site_guard.temporary_needed)

    def test_feedback_missing_stale_or_for_original_does_not_blacklist_temp(self):
        for actor, target, last_round, result in (('501', Pos(8, 7), 61, None),
                ('501', Pos(8, 7), 60, False), ('501', GAP, 61, False)):
            with self.subTest(target=target, result=result):
                raw = left(62)
                memory = confirmed(raw)
                memory.last_round = last_round
                memory.last_commands = {actor: build_command(target, 'wall')}
                raw['lastRoundRoleActionResults'] = {} if result is None else {actor: result}
                strategy, _ = setup(raw, memory, run=False)
                self.assertEqual(memory.wall_blockades[GAP].get('failed_sites', {}), {})

    def test_same_feedback_frame_is_counted_once(self):
        raw = left(62)
        memory = confirmed(raw)
        memory.last_round = 61
        memory.last_commands = {'501': build_command(Pos(8, 7), 'wall')}
        raw['lastRoundRoleActionResults'] = {'501': False}
        for _ in range(3):
            setup(raw, memory, run=False)
        self.assertEqual(memory.wall_blockades[GAP]['failed_sites'][Pos(8, 7)]['count'], 1)

    def test_ordinary_rebuild_entry_also_excludes_a_failed_temp_site(self):
        raw = left(62, standing=INNER - {Pos(8, 7)})
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 5}, backpack=['stone'])
        raw['teamOur']['roles'][3].update(pos={'x': 7, 'y': 8}, backpack=['stone'] * 2)
        memory = confirmed(raw)
        memory.last_round = 61
        memory.last_commands = {'501': build_command(Pos(8, 7), 'wall')}
        raw['lastRoundRoleActionResults'] = {'501': False}
        strategy, plan = setup(raw, memory, run=False)
        teammate = next(w for w in strategy.turn.workers() if w.unit_id == 504)
        self.assertTrue(strategy.site_guard.failed(Pos(8, 7)))
        self.assertFalse(strategy.build_wall(teammate))
        self.assertNotIn('504', plan.commands)

    def test_single_corner_cell_closes_local_eight_way_crossing(self):
        raw = camped(64, gaps=(Pos(9, 4),))
        turn = Turn.load(raw)
        bypass = set(Settings().wall_detour_cells(turn, Pos(9, 4)))
        self.assertEqual(bypass, {Pos(8, 5)})
        permanent = {w.pos for w in turn.walls()}
        local = {Pos(x, y) for x in range(7, 11) for y in range(3, 7)}
        inside = {Pos(7, 5), Pos(7, 6), Pos(8, 6)}
        def reached(blocked):
            seen = {Pos(10, 3)}
            queue = deque(seen)
            while queue:
                for cell in queue.popleft().neighbours():
                    if cell in local and cell not in blocked | seen:
                        seen.add(cell)
                        queue.append(cell)
            return seen
        self.assertTrue(inside & reached(permanent))
        self.assertFalse(inside & reached(permanent | bypass))

    def test_open_original_is_rebuilt_by_routing_out_of_inner_post(self):
        raw = left(131, standing=INNER)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'])
        raw['teamOur']['roles'][3]['health'] = 0
        memory = confirmed(raw)
        memory.temporary_wall_sites = set(INNER)
        raw['teamEnemy']['roles'] = []
        strategy, plan = setup(raw, memory)
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertEqual(memory.worker_tasks[501]['kind'], 'blockade_rebuild')
        rebuilt = False
        for number in range(131, 158):
            raw['roundNo'] = number
            strategy, plan = setup(raw, memory)
            advance(self, raw, strategy, plan)
            if any(c == build_command(GAP, 'wall') for c in plan.commands.values()):
                rebuilt = True
                break
        self.assertTrue(rebuilt)

    def test_original_command_or_false_feedback_never_starts_cleanup(self):
        raw = left(131, standing=INNER)
        raw['teamOur']['roles'][2].update(pos={'x': 10, 'y': 7}, backpack=['stone'])
        raw['teamOur']['roles'][3]['health'] = 0
        memory = confirmed(raw)
        memory.temporary_wall_sites = set(INNER)
        raw['teamEnemy']['roles'] = []
        strategy, plan = setup(raw, memory)
        self.assertEqual(plan.commands['501'], build_command(GAP, 'wall'))
        self.assertEqual(strategy.site_guard.cleanup_sites, set())
        memory.record(strategy.turn, plan)
        raw['roundNo'] = 132
        raw['lastRoundRoleActionResults'] = {'501': False}
        strategy, _ = setup(raw, memory, run=False)
        self.assertEqual(strategy.site_guard.cleanup_sites, set())
        raw['roundNo'] = 133
        raw['teamOur']['roles'].append(unit(52999, 'wall', GAP.x, GAP.y, health=1000))
        strategy, plan = setup(raw, memory, run=False)
        self.assertEqual(strategy.site_guard.cleanup_sites, INNER)
        for worker in strategy.turn.workers():
            strategy.site_guard.cleanup(worker)
        self.assertFalse(any(c.get('targetPos') == [GAP.dump()] for c in plan.commands.values()))

    def test_night_never_builds_and_destroyed_temp_invalidates_observed_seal(self):
        raw = left(70, standing=INNER)
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'])
        memory = confirmed(raw)
        memory.temporary_wall_sites = set(INNER)
        strategy, _ = setup(raw, memory, run=False)
        self.assertTrue(memory.wall_blockades[GAP]['sealed_observed'])
        raw['roundNo'] = 71
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if u['roleType'] != 'wall' or u['pos'] != {'x': 8, 'y': 7}]
        strategy, plan = setup(raw, memory)
        self.assertFalse(memory.wall_blockades[GAP]['sealed_observed'])
        self.assertFalse(any(c['action'] == 'build' for c in plan.commands.values()))

    def test_one_stone_is_reserved_instead_of_spent_on_temporary_wall(self):
        raw = left()
        raw['teamOur']['roles'][2].update(pos={'x': 7, 'y': 8}, backpack=['stone'])
        raw['teamOur']['roles'][3]['health'] = 0
        memory = confirmed(raw)
        strategy, plan = setup(raw, memory)
        self.assertEqual(memory.blockade_worker_id, 501)
        self.assertFalse(any(c['action'] == 'build' for c in plan.commands.values()))
        self.assertEqual(next(w for w in strategy.turn.workers() if w.unit_id == 501).backpack, ('stone',))

    def test_early_reserve_owner_does_not_fall_through_to_spend_last_stone(self):
        raw = left(20)
        raw['teamOur']['roles'][2].update(pos={'x': 15, 'y': 15}, backpack=['stone'])
        raw['teamOur']['roles'][3].update(pos={'x': 7, 'y': 8}, backpack=['stone'] * 4)
        memory = confirmed(raw)
        memory.blockade_worker_id = 501
        strategy, plan = setup(raw, memory, run=False)
        watcher = next(w for w in strategy.turn.workers() if w.unit_id == 501)
        self.assertEqual(strategy.site_guard.seal_assignments[501], set())
        self.assertEqual(strategy.site_guard.seal_assignments[504], INNER)
        self.assertTrue(strategy.site_guard.watch(watcher))
        self.assertEqual(memory.worker_tasks[501]['kind'], 'blockade_reserve')
        self.assertIn(501, plan.used)
        self.assertNotIn('501', plan.commands)

    def test_nominal_home_blocked_by_inner_wall_still_reaches_free_inner_post(self):
        raw = left(71, standing=INNER)
        raw['teamOur']['roles'][2].update(pos={'x': 3, 'y': 4}, backpack=['stone'])
        raw['teamOur']['roles'][3].update(pos={'x': 4, 'y': 3}, backpack=[])
        memory = confirmed(raw)
        arrived = False
        for number in range(71, 79):
            raw['roundNo'] = number
            strategy, plan = setup(raw, memory, run=False)
            watcher = next(w for w in strategy.turn.workers() if w.unit_id == 501)
            self.assertEqual(strategy.guard.home(watcher), Pos(8, 7))
            self.assertNotIn(Pos(8, 7), strategy.route(watcher).cost)
            self.assertTrue(strategy.first_defense.worker(watcher))
            if watcher.pos in strategy.guard.inner_cells():
                arrived = True
                break
            self.assertEqual(plan.commands['501']['action'], 'move')
            self.assertEqual(plan.rejections, [])
            advance(self, raw, strategy, plan)
        self.assertTrue(arrived)

    def test_authorization_keeps_inner_geometry_and_night_rule(self):
        turn = Turn.load(left())
        plan = ActionPlan(turn, Settings())
        plan.authorize_wall_detour(GAP)
        self.assertEqual(plan.temporary_wall_sites, INNER)
        self.assertNotIn(Pos(10, 7), plan.temporary_wall_sites)
        for settings in (Settings(allow_base_surroundings=False), layout_settings()):
            plan = ActionPlan(turn, settings)
            plan.authorize_wall_detour(GAP)
            self.assertEqual(plan.temporary_wall_sites, set())
        raw = left(71)
        raw['teamOur']['roles'][2]['pos'] = {'x': 7, 'y': 8}
        plan = ActionPlan(Turn.load(raw), Settings())
        plan.authorize_wall_detour(GAP)
        self.assertFalse(plan.add(501, build_command(Pos(8, 7), 'wall')))


if __name__ == '__main__':
    unittest.main()
