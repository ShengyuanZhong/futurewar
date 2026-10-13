"""First-day repair and real occupied-wall relay with all 17 walls permanent."""
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn, distance
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import unit
from tests.test_maintenance import fortified
from tests.test_u_layout import point


def actor(raw, uid):
    return next(u for u in raw['teamOur']['roles'] if u['id'] == uid)


def setup(raw, memory=None):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, Settings(enable_boss_raid=False, enable_tasks=False))
    return Strategy(turn, plan, memory or GameMemory(opening_complete=True)), plan


class ExteriorRepairTests(unittest.TestCase):
    def test_every_wall_has_an_exterior_repair_post_in_both_templates(self):
        for mirrored in (False, True):
            s, _ = setup(fortified(71, mirrored))
            cells = s.guard.duty_cells(s.turn.workers()[0])
            self.assertTrue(cells)
            self.assertFalse(cells & s.guard.inner_cells())
            self.assertNotIn(s.layout.operator_pos, cells)
            self.assertTrue(all(any(distance(p, w.pos) == 1 for p in cells)
                                for w in s.turn.walls()))

    def test_first_night_repairs_an_adjacent_critical_wall_from_outside(self):
        for mirrored in (False, True):
            raw = fortified(71, mirrored)
            wall_pos = point(9, 7, mirrored)
            actor(raw, 501).update(pos=point(10, 7, mirrored).dump(), backpack=['WallFixer'])
            next(w for w in raw['teamOur']['roles']
                 if w['roleType'] == 'wall' and w['pos'] == wall_pos.dump())['health'] = 100
            s, plan = setup(raw)
            self.assertTrue(s.first_defense.worker(s.turn.workers()[0]))
            self.assertEqual(plan.commands['501'], {'action': 'use', 'name': 'WallFixer',
                                                   'targetPos': [wall_pos.dump()]})
            self.assertEqual(plan.rejections, [])

    def test_exactly_thirty_percent_is_not_a_critical_repair(self):
        raw = fortified(71)
        actor(raw, 501).update(pos=point(10, 7).dump(), backpack=['WallFixer'])
        next(w for w in raw['teamOur']['roles']
             if w['roleType'] == 'wall' and w['pos'] == point(9, 7).dump())['health'] = 300
        s, plan = setup(raw)
        self.assertFalse(s.guard.nighttime(s.turn.workers()[0], urgent_only=True))
        self.assertNotIn('501', plan.commands)

    def test_legacy_inside_worker_repairs_locally_without_demolishing_walls(self):
        raw = fortified(71)
        actor(raw, 501).update(pos=point(8, 7).dump(), backpack=['WallFixer'])
        next(w for w in raw['teamOur']['roles']
             if w['roleType'] == 'wall' and w['pos'] == point(9, 7).dump())['health'] = 100
        s, plan = setup(raw)
        worker = s.turn.workers()[0]
        self.assertIn(worker.pos, s.guard.duty_cells(worker))
        self.assertTrue(s.first_defense.worker(worker))
        self.assertEqual(plan.commands['501']['action'], 'use')
        self.assertFalse(any(c['action'] == 'remove' for c in plan.commands.values()))

    def test_first_night_return_does_not_target_the_closed_inner_lane(self):
        for mirrored in (False, True):
            raw = fortified(71, mirrored)
            actor(raw, 501).update(pos=point(2, 7, mirrored).dump(), backpack=['WallFixer'])
            s, plan = setup(raw)
            worker = s.turn.workers()[0]
            self.assertFalse(s.first_defense.home_cells(worker) & s.guard.inner_cells())
            self.assertTrue(s.first_defense.worker(worker))
            command = plan.commands.get('501')
            self.assertTrue(command and command['action'] == 'move')
            self.assertNotIn(Pos.load(command['targetPos'][0]), s.guard.inner_cells())
            self.assertEqual(plan.rejections, [])

    def test_first_day_does_not_reserve_a_return_trip_or_remove_a_wall(self):
        raw = fortified(70)
        actor(raw, 501).update(pos=point(2, 7).dump(), backpack=['WallFixer'])
        s, plan = setup(raw)
        worker = s.turn.workers()[0]
        self.assertFalse(s.guard.daytime(worker))
        self.assertFalse(s.first_defense.return_home(worker))
        self.assertFalse(any(c['action'] == 'remove' for c in plan.commands.values()))

    def test_former_door_camp_is_retained_until_actual_wall_reconstruction(self):
        raw = fortified(40)
        gap = point(5, 9)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                  if u['roleType'] != 'wall' or u['pos'] != gap.dump()]
        raw['teamEnemy']['roles'] = [unit(901, 'worker', gap.x, gap.y, health=500)]
        memory = GameMemory(opening_complete=True)
        first, _ = setup(raw, memory)
        self.assertIn(gap, first.gap_guard.gaps)
        raw['roundNo'] = 41
        raw['teamEnemy']['roles'] = []
        second, _ = setup(raw, memory)
        self.assertIn(gap, second.gap_guard.gaps)
        posts = second.gap_guard.posts(role=second.turn.workers()[0])
        self.assertTrue(posts)
        self.assertFalse(posts & second.guard.inner_cells())

    def test_first_night_worker_enters_the_real_gap_from_outside(self):
        raw = fortified(71)
        gap = point(9, 7)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                  if u['roleType'] != 'wall' or u['pos'] != gap.dump()]
        actor(raw, 501).update(pos=point(10, 7).dump(), backpack=['stone'])
        memory = GameMemory(opening_complete=True)
        memory.wall_gap_defense.update(gaps={gap: {'first_seen': 60}}, worker_id=501)
        s, plan = setup(raw, memory)
        self.assertTrue(s.gap_guard.worker(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501'], {'action': 'move', 'targetPos': [gap.dump()]})
        self.assertEqual(plan.rejections, [])

    def test_first_night_imp_takes_the_gap_after_observed_guard_death(self):
        raw = fortified(71)
        gap = point(9, 7)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                  if u['roleType'] != 'wall' or u['pos'] != gap.dump()]
        actor(raw, 501).update(pos=point(10, 7).dump(), health=0)
        raw['teamOur']['roles'].append(unit(505, 'imp', 10, 8, health=500))
        memory = GameMemory(opening_complete=True)
        memory.wall_gap_defense.update(gaps={gap: {'first_seen': 60}}, worker_id=501, imp_id=505)
        s, plan = setup(raw, memory)
        self.assertTrue(s.gap_guard.imp(s.turn.imps()[0]))
        self.assertEqual(plan.commands['505'], {'action': 'move', 'targetPos': [gap.dump()]})
        self.assertEqual(plan.rejections, [])
