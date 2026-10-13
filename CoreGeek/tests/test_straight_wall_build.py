"""First-day wall sweeps use each exterior straight edge without diagonal skips.

The scenes contain observed buildings and bags only. They do not load user logs
or pretend that a submitted build already exists in the next observation.
"""
import unittest

from agent.grid import Routes, adjacent_cells
from agent.protocol import Pos, Turn, build_command, distance
from tests.fixtures import unit
from tests.test_personal_construction import add_walls, make_strategy, started_scene
from tests.test_wall_schedule import scene, strategy


def actor(raw, uid=501):
    return next(u for u in raw['teamOur']['roles'] if u['id'] == uid)


def side_scene(edge, upper=False, reverse=False):
    raw, memory, settings = scene(upper)
    initial, schedule = strategy(raw, memory, settings)
    walls = set(initial.construction_walls())
    xs, ys = [p.x for p in walls], [p.y for p in walls]
    if edge in ('north', 'south'):
        y = max(ys) if edge == 'north' else min(ys)
        ordered = sorted((p for p in walls if p.y == y), reverse=reverse)
        outward = Pos(0, 1 if edge == 'north' else -1)
    else:
        x = max(xs) if edge == 'east' else min(xs)
        ordered = sorted((p for p in walls if p.x == x), reverse=reverse)
        outward = Pos(1 if edge == 'east' else -1, 0)
    add_walls(raw, walls - set(ordered))
    schedule.state['arcs'] = {501: ordered, 504: []}
    first = ordered[0]
    actor(raw)['pos'] = Pos(first.x + outward.x, first.y + outward.y).dump()
    actor(raw)['backpack'] = ['stone'] * len(ordered)
    actor(raw, 504)['backpack'] = []
    actor(raw, 504)['pos'] = Pos(20, 10).dump()
    return raw, memory, settings, ordered, outward


def apply_frame(case, raw, memory, s, uid=501):
    command = s.plan.commands[str(uid)]
    mover = actor(raw, uid)
    target = Pos.load(command['targetPos'][-1])
    before = next(w for w in s.turn.workers() if w.unit_id == uid)
    case.assertNotIn(target, s.turn.occupied_cells())
    if command['action'] == 'move':
        case.assertEqual(distance(before.pos, target), 1)
        mover['pos'] = target.dump()
    elif command['action'] == 'build':
        case.assertEqual(command['name'], 'wall')
        case.assertIn('stone', mover['backpack'])
        case.assertEqual(distance(before.pos, target), 1)
        mover['backpack'].remove('stone')
        raw['teamOur']['roles'].append(unit(10000 + raw['roundNo'], 'wall', target.x, target.y,
                                           health=1000))
    else:
        case.fail(f'unexpected isolated wall action: {command}')
    memory.record(s.turn, s.plan)
    raw['roundNo'] += 1
    raw['lastRoundRoleActionResults'] = {str(uid): True}
    memory.observe(Turn.load(raw))
    return command, before.pos, target


class StraightWallBuildTests(unittest.TestCase):
    def assert_straight_edge(self, edge):
        for upper in (False, True):
            for reverse in (False, True):
                with self.subTest(edge=edge, upper=upper, reverse=reverse):
                    raw, memory, settings, ordered, outward = side_scene(edge, upper, reverse)
                    built, moves = [], []
                    for _ in range(2 * len(ordered) + 2):
                        s, _ = strategy(raw, memory, settings)
                        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
                        missing = [p for p in ordered if p in s.construction_walls()]
                        if not missing:
                            break
                        self.assertTrue(s.build_wall(worker), f'wall sweep stalled at {missing}')
                        self.assertFalse(s.plan.rejections)
                        command, start, target = apply_frame(self, raw, memory, s)
                        if command['action'] == 'build':
                            self.assertEqual(target, missing[0])
                            self.assertEqual(start, Pos(target.x + outward.x, target.y + outward.y),
                                             'a free straight edge must build from its facing exterior cell')
                            built.append(target)
                        else:
                            self.assertEqual(abs(target.x - start.x) + abs(target.y - start.y), 1,
                                             'a straight construction edge must not jump diagonally')
                            self.assertEqual(target, Pos(missing[0].x + outward.x,
                                                         missing[0].y + outward.y))
                            moves.append(target)
                    else:
                        self.fail(f'wall sweep did not complete: built={built}, moves={moves}')
                    self.assertEqual(built, ordered)
                    self.assertEqual(len(moves), len(ordered) - 1)
                    self.assertEqual(actor(raw)['backpack'], [])
                    finished = Turn.load(raw)
                    self.assertEqual(len(finished.walls()), 17)
                    for worker in finished.workers():
                        self.assertIsNotNone(Routes(finished, worker).nearest(
                            adjacent_cells(finished, [Pos(24, 20)])))

    def test_north_wall_sweeps_straight_in_both_directions(self):
        self.assert_straight_edge('north')

    def test_south_wall_sweeps_straight_in_both_directions(self):
        self.assert_straight_edge('south')

    def test_west_wall_sweeps_straight_in_both_directions(self):
        self.assert_straight_edge('west')

    def test_east_wall_sweeps_straight_in_both_directions(self):
        self.assert_straight_edge('east')

    def test_near_later_wall_cannot_skip_the_first_missing_personal_wall(self):
        raw, memory, settings, ordered, outward = side_scene('south')
        later = ordered[-1]
        actor(raw)['pos'] = Pos(later.x + outward.x, later.y + outward.y).dump()
        s, schedule = strategy(raw, memory, settings)
        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
        self.assertEqual(schedule.targets(worker, s.construction_walls())[0], ordered[0])
        self.assertEqual(schedule.targets(worker, s.construction_walls(), local_only=True), [])

    def test_old_skipped_target_is_reset_to_the_actual_first_gap(self):
        raw, memory, settings, ordered, outward = side_scene('north', reverse=True)
        later = ordered[3]
        post = Pos(later.x + outward.x, later.y + outward.y)
        actor(raw)['pos'] = post.dump()
        memory.worker_tasks[501] = dict(kind='build:wall', target=later, goal=post,
            moving=True, round=raw['roundNo'] - 1, position=Pos(post.x - 1, post.y))
        s, schedule = strategy(raw, memory, settings)
        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
        self.assertEqual(schedule.targets(worker, s.construction_walls())[0], ordered[0])

    def test_materialless_live_peer_does_not_release_its_wall_to_other_builder(self):
        raw, memory, settings = scene()
        s, schedule = strategy(raw, memory, settings)
        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
        own = set(schedule.state['arcs'][501])
        actor(raw, 504)['backpack'] = []
        peer_frontier = schedule.state['arcs'][504][0]
        actor(raw)['pos'] = Pos(peer_frontier.x, peer_frontier.y - 1).dump()
        s, schedule = strategy(raw, memory, settings)
        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
        self.assertTrue(set(schedule.targets(worker, s.construction_walls())) <= own)

    def test_hostile_occupied_frontier_is_temporarily_skipped_then_revisited(self):
        raw, memory, settings, ordered, _ = side_scene('north')
        first = ordered[0]
        raw['teamEnemy']['roles'].append(unit(9900, 'worker', first.x, first.y))
        s, schedule = strategy(raw, memory, settings)
        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
        choices = [p for p in s.construction_walls() if p not in s.turn.blocked(worker)]
        self.assertEqual(schedule.targets(worker, choices)[0], ordered[1])
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['id'] != 9900]
        raw['roundNo'] += 1
        s, schedule = strategy(raw, memory, settings)
        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
        self.assertEqual(schedule.targets(worker, s.construction_walls())[0], first)

    def test_failed_build_keeps_the_same_unbuilt_wall_as_frontier(self):
        raw, memory, settings, ordered, _ = side_scene('south')
        s, _ = strategy(raw, memory, settings)
        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
        self.assertTrue(s.build_wall(worker))
        self.assertEqual(s.plan.commands['501'], build_command(ordered[0], 'wall'))
        # Keep the actual bag and actual structures unchanged. A rejected build
        # is feedback to retry/replan, never evidence that this wall exists.
        memory.record(s.turn, s.plan)
        raw['roundNo'] += 1
        raw['lastRoundRoleActionResults'] = {'501': False}
        memory.observe(Turn.load(raw))
        s, schedule = strategy(raw, memory, settings)
        worker = next(w for w in s.turn.workers() if w.unit_id == 501)
        self.assertEqual(schedule.targets(worker, s.construction_walls())[0], ordered[0])
        self.assertTrue(s.build_wall(worker))
        self.assertEqual(s.plan.commands['501'], build_command(ordered[0], 'wall'))
        self.assertEqual(len(worker.backpack), len(ordered))
        self.assertFalse(s.plan.rejections)

    def test_corner_turn_preserves_the_whole_personal_wall_sequence(self):
        for upper in (False, True):
            with self.subTest(upper=upper):
                transform = lambda p: Pos(40 - p.x, 31 - p.y) if upper else p
                raw, memory, settings = scene(upper)
                initial, schedule = strategy(raw, memory, settings)
                ordered = [transform(p) for p in
                           (Pos(30, 7), Pos(29, 7), Pos(28, 7), Pos(28, 8), Pos(28, 9))]
                add_walls(raw, set(initial.construction_walls()) - set(ordered))
                schedule.state['arcs'] = {501: ordered, 504: []}
                actor(raw)['pos'] = transform(Pos(30, 6)).dump()
                actor(raw)['backpack'] = ['stone'] * len(ordered)
                actor(raw, 504)['backpack'] = []
                actor(raw, 504)['pos'] = Pos(20, 10).dump()
                built = []
                for _ in range(20):
                    s, _ = strategy(raw, memory, settings)
                    missing = [p for p in ordered if p in s.construction_walls()]
                    if not missing:
                        break
                    worker = next(w for w in s.turn.workers() if w.unit_id == 501)
                    self.assertTrue(s.build_wall(worker))
                    self.assertFalse(s.plan.rejections)
                    command, _, target = apply_frame(self, raw, memory, s)
                    if command['action'] == 'build':
                        self.assertEqual(target, missing[0])
                        built.append(target)
                    else:
                        self.assertIn(target, s.sealed_home.outside)
                else:
                    self.fail(f'corner stalled or skipped walls: {built}')
                self.assertEqual(built, ordered)
                self.assertEqual(len(Turn.load(raw).walls()), 17)
                self.assertEqual(actor(raw)['backpack'], [])

    def test_real_exterior_obstacle_allows_a_legal_detour_without_losing_walls(self):
        raw, memory, settings, ordered, outward = side_scene('north')
        blocked = Pos(ordered[1].x + outward.x, ordered[1].y + outward.y)
        raw['teamEnemy']['roles'].append(unit(9900, 'wall', blocked.x, blocked.y, health=1000))
        built = []
        for _ in range(25):
            s, _ = strategy(raw, memory, settings)
            if not s.construction_walls():
                break
            worker = next(w for w in s.turn.workers() if w.unit_id == 501)
            self.assertTrue(s.build_wall(worker), 'a single exterior obstacle must not deadlock the wall sweep')
            self.assertFalse(s.plan.rejections)
            command, _, target = apply_frame(self, raw, memory, s)
            self.assertNotEqual(target, blocked)
            if command['action'] == 'build':
                built.append(target)
        else:
            self.fail(f'legal detour failed to finish: {built}')
        self.assertEqual(built, ordered)

    def test_personal_last_wall_is_not_complete_until_observed_and_then_dispatches(self):
        for mission in ('buyer', 'scout'):
            with self.subTest(mission=mission):
                raw, memory, settings = started_scene()
                buyer_id = memory.boss_raid['buyer_id']
                uid = buyer_id if mission == 'buyer' else next(
                    i for i in memory.sealed_home['wall_schedule']['arcs'] if i != buyer_id)
                own = memory.sealed_home['wall_schedule']['arcs'][uid]
                last = own[-1]
                add_walls(raw, own[:-1])
                s = make_strategy(raw, memory, settings)
                worker = next(w for w in s.turn.workers() if w.unit_id == uid)
                actor(raw, uid)['pos'] = min(s.wall_schedule.posts(worker, last)).dump()
                raw['roundNo'] += 1
                s = make_strategy(raw, memory, settings)
                worker = next(w for w in s.turn.workers() if w.unit_id == uid)
                self.assertTrue(s.plan.add(uid, build_command(last, 'wall')))
                self.assertFalse(s.wall_schedule.construction_ready(worker))
                self.assertNotIn(uid, s.wall_schedule.departed_ids())
                actor(raw, uid)['backpack'].remove('stone')
                add_walls(raw, [last])
                raw['roundNo'] += 1
                s = make_strategy(raw, memory, settings)
                worker = next(w for w in s.turn.workers() if w.unit_id == uid)
                self.assertTrue(s.construction_walls(), 'the peer deliberately remains unfinished')
                self.assertTrue(s.wall_schedule.construction_ready(worker))
                s.run_worker(worker)
                self.assertEqual(s.plan.commands[str(uid)]['action'], 'move')
                self.assertIn(uid, s.wall_schedule.departed_ids())
                self.assertEqual(s.wall_schedule.targets(worker, s.construction_walls()), [])
                self.assertFalse(s.plan.rejections)


if __name__ == '__main__':
    unittest.main()
