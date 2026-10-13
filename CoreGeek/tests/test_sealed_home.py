"""First-day enclosure tests using the two user drawings and real observations.

The command applier below is a small, explicit local construction fixture. It
does not model enemies, official mine respawns, or subsequent days.
"""
import copy
import unittest
from dataclasses import replace

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.grid import Routes, adjacent_cells
from agent.protocol import Pos, Turn, build_command, distance, move_command, station_footprint
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, unit


# Written directly from the drawing, independent of Settings' offset generator.
WALLS = {(5, 9), (6, 9), (7, 9), (8, 9), (9, 9), (9, 8), (9, 7),
         (9, 6), (9, 5), (9, 4), (8, 4), (7, 4), (6, 4), (5, 4),
         (4, 4), (4, 5), (4, 6)}
GUNS = {(5, 8), (5, 7), (5, 6)}
GATE = (5, 9)
INNER = (6, 8)


def position(x, y, mirrored=False):
    return Pos(40 - x if mirrored else x, y)


def scene(mirrored=False, missing=(), inside_worker=False, round_no=40):
    raw = request(round_no)
    raw['teamOur'].update(playerTasks=[], goldNum=0)
    raw['teamOur']['roles'] = [unit(503, 'station', 33 if mirrored else 6, 7, health=2000)]
    for uid, kind, x, y in ((502, 'pioneer', 3, 7),
                            (501, 'worker', *(INNER if inside_worker else (4, 9))),
                            (504, 'worker', 3, 6)):
        p = position(x, y, mirrored)
        raw['teamOur']['roles'].append(unit(uid, kind, p.x, p.y,
                                            health=500, backpack=['stone'] if kind == 'worker' else []))
    for uid, (x, y) in enumerate(sorted(GUNS), 601):
        p = position(x, y, mirrored)
        raw['teamOur']['roles'].append(unit(uid, 'rocket', p.x, p.y, health=1000))
    for uid, (x, y) in enumerate(sorted(WALLS - set(missing)), 701):
        p = position(x, y, mirrored)
        raw['teamOur']['roles'].append(unit(uid, 'wall', p.x, p.y, health=1000))
    raw['teamEnemy']['roles'] = []
    raw['mapInfo']['zones'] = [dict(neutralType=kind, pos=position(x, y, mirrored).dump())
                               for kind, x, y in (('vendor', 2, 7), ('weaponShop', 2, 8),
                                                 ('stone', 3, 9))]
    raw['weaponShopList'] = []
    settings = Settings(enable_tasks=False, enable_boss_raid=False,
                        enable_first_night_defense=False, enable_news=False)
    return raw, GameMemory(), settings


def strategy(raw, memory, settings):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, settings)
    return Strategy(turn, plan, memory), plan


def actor(raw, uid):
    return next(u for u in raw['teamOur']['roles'] if u['id'] == uid)


def upgrade_scene(mirrored=False, round_no=40):
    raw, memory, settings = scene(mirrored, round_no=round_no)
    settings = replace(settings, enable_first_night_defense=True)
    actor(raw, 502)['pos'] = position(4, 7, mirrored).dump()
    actor(raw, 501).update(pos=position(3, 6, mirrored).dump(),
                           backpack=['WeaponUpgradeVoucher2'] + ['WallFixer'] * 5)
    actor(raw, 504).update(pos=position(2, 5, mirrored).dump(), backpack=[])
    gun = next(u for u in raw['teamOur']['roles']
               if u['roleType'] == 'rocket' and u['pos'] == position(5, 6, mirrored).dump())
    gun.update(level=2, health=1500)
    return raw, memory, settings, gun['id']


def apply_upgrade_frame(raw, memory, s, plan):
    """Expose movement/use results only in the following observed frame."""
    before = s.turn
    destinations = set()
    for uid, command in plan.commands.items():
        if command['action'] == 'move':
            for point in command['targetPos']:
                target = Pos.load(point)
                assert target not in before.occupied_cells()
                assert target not in destinations
                destinations.add(target)
        elif command['action'] == 'use':
            holder = actor(raw, int(uid))
            assert command['name'] in holder['backpack']
    for uid, command in plan.commands.items():
        holder = actor(raw, int(uid))
        if command['action'] == 'move':
            holder['pos'] = command['targetPos'][-1]
        elif command['action'] == 'use':
            holder['backpack'].remove(command['name'])
            gun = next(u for u in raw['teamOur']['roles'] if u['pos'] == command['targetPos'][0])
            assert command['name'] == f"WeaponUpgradeVoucher{gun['level']}"
            gun.update(level=gun['level'] + 1, health=500 + 500 * (gun['level'] + 1))
        elif command['action'] == 'collect':
            holder['backpack'].append(before.zones[Pos.load(command['targetPos'][0])])
        elif command['action'] == 'sell':
            for _ in range(command['num']):
                holder['backpack'].remove(command['name'])
        else:
            raise AssertionError(f'unexpected isolated upgrade frame: {command}')
    memory.record(before, plan)
    raw['roundNo'] += 1
    raw['lastRoundRoleActionResults'] = {uid: True for uid in plan.commands}
    memory.observe(Turn.load(raw))


class SealedHomeTests(unittest.TestCase):
    def test_drawings_have_seventeen_walls_and_operator_remains_outside_reachable(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                raw, memory, settings = scene(mirrored)
                s, _ = strategy(raw, memory, settings)
                walls = {position(x, y, mirrored) for x, y in WALLS}
                guns = {position(x, y, mirrored) for x, y in GUNS}
                self.assertEqual(set(settings.build_cells(s.turn, 'wall')), walls)
                self.assertEqual(set(settings.build_cells(s.turn, 'rocket')), guns)
                base = station_footprint(s.turn.station().pos)
                self.assertTrue(all(min(distance(p, b) for b in base) == 2 for p in walls))
                self.assertTrue(all(min(distance(p, b) for b in base) == 1 for p in guns))
                pioneer = next(u for u in s.turn.controllable() if u.kind == 'pioneer')
                self.assertIn(s.layout.operator_pos, Routes(s.turn, pioneer).cost)
                self.assertTrue(all(distance(s.layout.operator_pos, p) == 1 for p in guns))
                # Workers remain outside; the interior repair lane is sealed.
                inner = position(*INNER, mirrored)
                self.assertTrue(all(inner not in Routes(s.turn, w).cost for w in s.turn.workers()))

    def test_former_entrance_is_an_ordinary_missing_wall_and_needs_no_extra_stone(self):
        raw, memory, settings = scene(missing=WALLS)
        for w in (actor(raw, 501), actor(raw, 504)):
            w['backpack'] = []
        s, _ = strategy(raw, memory, settings)
        self.assertEqual(set(s.missing_walls()), {Pos(x, y) for x, y in WALLS})
        self.assertEqual(set(s.construction_walls()), set(s.missing_walls()))
        self.assertEqual(sum(s.stone_targets().values()), 17)
        self.assertTrue(all(s.day_gate.reserve_stone(w) == 0 for w in s.turn.workers()))

    def test_outside_worker_builds_the_last_wall_then_never_reopens_it(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                raw, memory, settings = scene(mirrored, missing={GATE})
                s, plan = strategy(raw, memory, settings)
                builder = next(w for w in s.turn.workers() if w.unit_id == 501)
                target = position(*GATE, mirrored)
                self.assertTrue(s.build_wall(builder))
                self.assertEqual(plan.commands['501'], build_command(target, 'wall'))
                self.assertFalse(plan.rejections)
                actor(raw, 501)['backpack'].remove('stone')
                raw['teamOur']['roles'].append(unit(900, 'wall', target.x, target.y, health=1000))
                memory.record(s.turn, plan)
                raw['roundNo'] += 1
                memory.observe(Turn.load(raw))
                s, plan = strategy(raw, memory, settings)
                self.assertEqual(len(s.turn.walls()), 17)
                self.assertFalse(s.missing_walls())
                for worker in s.turn.workers():
                    self.assertFalse(s.day_gate.worker(worker))
                    self.assertNotIn(position(*INNER, mirrored), Routes(s.turn, worker).cost)
                    self.assertIsNotNone(Routes(s.turn, worker).nearest(
                        adjacent_cells(s.turn, [position(2, 8, mirrored)])))
                s.run()
                self.assertFalse(any(c['action'] == 'remove' for c in plan.commands.values()))

    def test_last_wall_cannot_trap_the_other_actual_inside_worker(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                raw, memory, settings = scene(mirrored, missing={GATE}, inside_worker=True)
                actor(raw, 504)['pos'] = position(4, 9, mirrored).dump()
                s, plan = strategy(raw, memory, settings)
                builder = next(w for w in s.turn.workers() if w.unit_id == 504)
                self.assertFalse(s.wall_keeps_exit(builder, position(*GATE, mirrored)))
                s.build_wall(builder)
                self.assertFalse(any(c.get('action') == 'build' and c.get('name') == 'wall'
                                     for c in plan.commands.values()))
                self.assertFalse(plan.rejections)

    def test_planned_move_is_not_evidence_that_inside_worker_has_left(self):
        raw, memory, settings = scene(missing={GATE}, inside_worker=True)
        actor(raw, 504)['pos'] = position(4, 9).dump()
        s, plan = strategy(raw, memory, settings)
        inside = next(w for w in s.turn.workers() if w.unit_id == 501)
        builder = next(w for w in s.turn.workers() if w.unit_id == 504)
        # Even a legal accepted movement command is only a future reservation;
        # the worker's current observed position still requires a real exit.
        self.assertTrue(plan.add(inside.unit_id, move_command(position(7, 8))))
        self.assertFalse(s.wall_keeps_exit(builder, position(*GATE)))
        self.assertEqual(inside.pos, position(*INNER))

    def test_two_individually_safe_builds_cannot_jointly_close_both_exits(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                second = (5, 4)
                raw, memory, settings = scene(mirrored, missing={GATE, second}, inside_worker=True)
                actor(raw, 504)['pos'] = position(4, 3, mirrored).dump()
                s, plan = strategy(raw, memory, settings)
                inside = next(w for w in s.turn.workers() if w.unit_id == 501)
                outside = next(w for w in s.turn.workers() if w.unit_id == 504)
                top, bottom = position(*GATE, mirrored), position(*second, mirrored)
                self.assertTrue(s.wall_keeps_exit(inside, top))
                self.assertTrue(s.wall_keeps_exit(outside, bottom))
                self.assertTrue(plan.add(inside.unit_id, build_command(top, 'wall')))
                self.assertIn(top, plan.build_targets)
                self.assertFalse(s.wall_keeps_exit(outside, bottom))
                s.build_wall(outside)
                self.assertNotEqual(plan.commands.get('504'), build_command(bottom, 'wall'))
                self.assertFalse(plan.rejections)

    def test_inside_worker_evacuates_before_a_real_next_observation_can_seal(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                raw, memory, settings = scene(mirrored, missing={GATE}, inside_worker=True)
                # The outside builder waits near the final cell; the inside
                # worker carries the material but must leave before sealing.
                actor(raw, 504)['pos'] = position(3, 8, mirrored).dump()
                commands = []
                for number in range(40, 56):
                    raw['roundNo'] = number
                    s, plan = strategy(raw, memory, settings)
                    if len(s.turn.walls()) == 17:
                        break
                    before = s.turn
                    s.run()
                    self.assertFalse(plan.rejections)
                    self.assertTrue(plan.commands, 'unfinished enclosure must make progress')
                    # Validate all commands against the same pre-action state
                    # before applying any result, rather than serially freeing
                    # positions for a simultaneous teammate command.
                    destinations = set()
                    for uid, command in plan.commands.items():
                        action = command['action']
                        self.assertNotEqual(action, 'remove')
                        if action in ('move', 'build'):
                            target = Pos.load(command['targetPos'][-1])
                            self.assertNotIn(target, before.occupied_cells())
                            self.assertNotIn(target, destinations)
                            destinations.add(target)
                        if action == 'build' and command['name'] == 'wall':
                            trial = copy.deepcopy(raw)
                            p = Pos.load(command['targetPos'][0])
                            trial['teamOur']['roles'].append(unit(950, 'wall', p.x, p.y, health=1000))
                            trial_turn = Turn.load(trial)
                            for w in trial_turn.workers():
                                self.assertIsNotNone(Routes(trial_turn, w).nearest(
                                    adjacent_cells(trial_turn, [position(2, 8, mirrored)])))
                    for uid, command in plan.commands.items():
                        mover = actor(raw, int(uid))
                        if command['action'] == 'move':
                            mover['pos'] = command['targetPos'][-1]
                        elif command['action'] == 'build':
                            p = Pos.load(command['targetPos'][0])
                            self.assertEqual(command['name'], 'wall')
                            mover['backpack'].remove('stone')
                            raw['teamOur']['roles'].append(unit(1000 + number, 'wall', p.x, p.y, health=1000))
                        elif command['action'] == 'collect':
                            mover['backpack'].append(before.zones[Pos.load(command['targetPos'][0])])
                        elif command['action'] == 'sell':
                            for _ in range(command['num']):
                                mover['backpack'].remove(command['name'])
                        else:
                            self.fail(f'unexpected isolated construction command: {command}')
                        commands.append(command)
                    memory.record(before, plan)
                    raw['roundNo'] += 1
                    raw['lastRoundRoleActionResults'] = {uid: True for uid in plan.commands}
                    memory.observe(Turn.load(raw))
                else:
                    self.fail(f'enclosure failed to finish after evacuation: {commands}')
                final = Turn.load(raw)
                self.assertEqual(len(final.walls()), 17)
                self.assertTrue(all(position(*INNER, mirrored) not in Routes(final, w).cost
                                    for w in final.workers()))

    def test_enemy_on_former_gate_keeps_existing_gap_exception_without_extra_stone(self):
        raw, memory, settings = scene(missing={GATE})
        p = position(*GATE)
        raw['teamEnemy']['roles'].append(unit(900, 'worker', p.x, p.y, health=500))
        actor(raw, 501)['backpack'] = []
        s, _ = strategy(raw, memory, settings)
        self.assertIn(p, s.missing_walls())
        self.assertTrue(s.day_gate.dispatch_ready({p}))
        self.assertEqual(s.day_gate.reserve_stone(s.turn.workers()[0]), 0)

    def test_shop_deadline_still_preempts_unfinished_sealed_house(self):
        from tests.test_buyer_deadline import unfinished_scene, shop_steps
        from tests.test_worker_boss_buyer import BUYER, load_strategy, role
        raw, memory, settings = unfinished_scene()
        travel = shop_steps(raw, settings)
        raw['roundNo'] = 71 - (travel + 1 + 3)
        s, plan = load_strategy(raw, memory, settings)
        self.assertTrue(s.construction_walls())
        self.assertTrue(s.boss_raid.worker_mission_active(role(s)))
        s.run_worker(role(s))
        self.assertEqual(plan.commands[str(BUYER)]['action'], 'move')
        self.assertFalse(any(c.get('action') == 'build' for c in plan.commands.values()))
        self.assertFalse(plan.rejections)

    def test_pioneer_yields_only_on_real_daytime_upgrade_then_returns_after_worker_leaves(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                raw, memory, settings, gun_id = upgrade_scene(mirrored)
                post = position(4, 7, mirrored)
                s, plan = strategy(raw, memory, settings)
                buyer = next(w for w in s.turn.workers() if w.unit_id == 501)
                self.assertTrue(s.first_defense.prepared())
                self.assertTrue(s.sealed_home.needs_operator(buyer))
                self.assertNotIn(position(*INNER, mirrored), Routes(s.turn, buyer).cost)
                s.run()
                self.assertFalse(plan.rejections)
                self.assertEqual(plan.commands['502']['action'], 'move')
                vacated_to = Pos.load(plan.commands['502']['targetPos'][-1])
                self.assertIn(vacated_to, s.sealed_home.outside)
                self.assertEqual(distance(vacated_to, post), 1)
                # The pioneer still occupies post in this observation. A
                # teammate cannot enter until movement actually settles.
                self.assertFalse(any(post.dump() in command.get('targetPos', [])
                                     for uid, command in plan.commands.items() if uid != '502'))
                apply_upgrade_frame(raw, memory, s, plan)

                s, plan = strategy(raw, memory, settings)
                s.run()
                self.assertFalse(plan.rejections)
                self.assertEqual(plan.commands['501'], move_command(post))
                self.assertNotEqual(plan.commands.get('502'), move_command(post))
                apply_upgrade_frame(raw, memory, s, plan)

                s, plan = strategy(raw, memory, settings)
                s.run()
                self.assertFalse(plan.rejections)
                self.assertEqual(plan.commands['501'], dict(action='use', name='WeaponUpgradeVoucher2',
                    targetPos=[actor(raw, gun_id)['pos']]))
                self.assertNotEqual(plan.commands.get('502'), move_command(post))
                apply_upgrade_frame(raw, memory, s, plan)
                self.assertEqual(actor(raw, gun_id)['level'], 3)

                s, plan = strategy(raw, memory, settings)
                s.run()
                self.assertFalse(plan.rejections)
                self.assertEqual(plan.commands['501']['action'], 'move')
                self.assertNotEqual(plan.commands['501']['targetPos'][-1], post.dump())
                self.assertNotEqual(plan.commands.get('502'), move_command(post))
                apply_upgrade_frame(raw, memory, s, plan)

                s, plan = strategy(raw, memory, settings)
                s.run()
                self.assertFalse(plan.rejections)
                self.assertEqual(plan.commands['502'], move_command(post))
                self.assertFalse(any(c.get('action') == 'remove' for c in plan.commands.values()))

    def test_pioneer_never_yields_without_matching_carried_voucher_or_before_tasks_finish(self):
        for reason in ('missing_voucher', 'wrong_level_voucher', 'tasks_unfinished'):
            with self.subTest(reason=reason):
                raw, memory, settings, _ = upgrade_scene()
                if reason == 'missing_voucher':
                    actor(raw, 501)['backpack'] = ['WallFixer'] * 5
                elif reason == 'wrong_level_voucher':
                    actor(raw, 501)['backpack'] = ['WeaponUpgradeVoucher1'] + ['WallFixer'] * 5
                else:
                    settings = replace(settings, enable_tasks=True)
                s, plan = strategy(raw, memory, settings)
                pioneer = next(u for u in s.turn.controllable() if u.kind == 'pioneer')
                self.assertFalse(s.sealed_home.pioneer_yield(pioneer))
                self.assertNotIn('502', plan.commands)
                self.assertFalse(plan.rejections)

    def test_nighttime_pioneer_keeps_control_post_despite_waiting_upgrade_worker(self):
        raw, memory, settings, _ = upgrade_scene(round_no=71)
        s, plan = strategy(raw, memory, settings)
        pioneer = next(u for u in s.turn.controllable() if u.kind == 'pioneer')
        self.assertFalse(s.sealed_home.pioneer_yield(pioneer))
        self.assertNotIn('502', plan.commands)
        s.run()
        self.assertFalse(plan.rejections)
        self.assertFalse(plan.commands.get('502', {}).get('action') == 'move')
        self.assertEqual(pioneer.pos, position(4, 7))


if __name__ == '__main__':
    unittest.main()
