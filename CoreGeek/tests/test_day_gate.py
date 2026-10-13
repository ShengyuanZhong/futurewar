"""First-day compatibility facade for retired automatic entrance behavior."""
import unittest

from agent.protocol import Pos, Turn
from agent.grid import Routes
from app.config import Settings
from tests.test_maintenance import fortified, setup
from tests.test_u_layout import point, WALLS, LANE
from app.service.memory import GameMemory
from agent.actions import ActionPlan
from agent.brain import Strategy
from app.config import Settings
from tests.fixtures import unit


def gate_request(round_no=150, mirrored=False, closed=False, final=False):
    raw = fortified(round_no, mirrored=mirrored, weapon_level=3 if final else 1,
                    wall_level=2 if final else 1)
    if final:
        for wall in raw['teamOur']['roles']:
            if wall['roleType'] == 'wall' and wall['pos']['x'] == point(9, 7, mirrored).x:
                wall.update(level=3, health=2000)
    if not closed:
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                  if not (u['roleType'] == 'wall' and u['pos'] == point(5, 9, mirrored).dump())]
    return raw


class DayGateTests(unittest.TestCase):
    def test_facade_retires_old_state_and_never_reopens_complete_daytime_walls(self):
        for mirrored in (False, True):
            raw = gate_request(round_no=40, mirrored=mirrored, closed=True)
            raw['teamOur']['roles'][2]['pos'] = point(4, 9, mirrored).dump()
            memory = GameMemory(opening_complete=True, day_gate={
                'worker_id': 501, 'pos': point(5, 9, mirrored).dump(),
                'status': 'opening', 'coupon_pending': True})
            turn = Turn.load(raw)
            plan = ActionPlan(turn, Settings(enable_boss_raid=False))
            s = Strategy(turn, plan, memory)
            facade = s.day_gate
            self.assertFalse(facade.enabled)
            self.assertIsNone(facade.worker_id)
            self.assertIsNone(facade.pos)
            self.assertNotIn('coupon_pending', memory.day_gate)
            self.assertEqual(memory.day_gate['status'], 'retired_permanent_walls')
            worker = turn.workers()[0]
            self.assertFalse(facade.worker(worker))
            self.assertFalse(facade.closing())
            self.assertFalse(facade.can_seal(worker))
            self.assertFalse(facade.prepare_coupon(worker))
            self.assertEqual(facade.reserve_stone(worker), 0)
            self.assertEqual(len(turn.walls()), 17)
            self.assertEqual(plan.commands, {})
            self.assertEqual(plan.used, set())

    def test_former_gate_requires_a_real_wall_before_construction_dispatch(self):
        raw = gate_request(round_no=40)
        raw['teamOur']['roles'][2].update(pos=point(4, 9).dump(), backpack=['stone'])
        s, plan = setup(raw)
        worker = s.turn.workers()[0]
        gate = point(5, 9)
        self.assertIn(gate, s.missing_walls())
        self.assertIn(gate, s.construction_walls())
        self.assertFalse(s.day_gate.day_ready())
        self.assertFalse(s.day_gate.dispatch_ready())
        self.assertTrue(plan.add(worker.unit_id, {'action': 'build', 'name': 'wall',
                                                  'targetPos': [gate.dump()]}))
        # A reservation is not an observed seventeenth wall.
        self.assertFalse(s.day_gate.dispatch_ready())
        raw['roundNo'] += 1
        raw['teamOur']['roles'].append(unit(900, 'wall', gate.x, gate.y, health=1000))
        s, plan = setup(raw)
        self.assertTrue(s.day_gate.day_ready())
        self.assertTrue(s.day_gate.dispatch_ready())
        self.assertFalse(s.missing_walls())
        self.assertFalse(plan.rejections)

    def test_dispatch_ignores_only_a_current_living_enemy_controllable_occupant(self):
        gate = point(5, 9)
        for kind, hp, expected in (('worker', 500, True), ('pioneer', 500, True),
                                   ('worker', 0, False), ('rocket', 1000, False)):
            with self.subTest(kind=kind, hp=hp):
                raw = gate_request(round_no=40)
                raw['teamEnemy']['roles'] = [unit(900, kind, gate.x, gate.y, health=hp)]
                s, _ = setup(raw)
                self.assertFalse(s.day_gate.dispatch_ready())
                self.assertEqual(s.day_gate.dispatch_ready({gate}), expected)
                self.assertFalse(s.day_gate.diagnostic()['all_planned_walls_present'])
        raw = gate_request(round_no=40)
        s, _ = setup(raw)
        # A coordinate remembered from an earlier enemy occupation is not enough.
        self.assertFalse(s.day_gate.dispatch_ready({gate}))

    def test_complete_first_day_facade_never_reserves_an_extra_stone_for_selling(self):
        raw = gate_request(round_no=40, closed=True)
        raw['teamOur']['roles'][2].update(pos=point(3, 7).dump(), backpack=['stone'] * 4)
        s, plan = setup(raw)
        worker = s.turn.workers()[0]
        self.assertEqual(s.day_gate.reserve_stone(worker), 0)
        self.assertTrue(s.sell(worker))
        self.assertEqual(plan.commands['501'], {'action': 'sell', 'name': 'stone', 'num': 4})
        self.assertFalse(plan.rejections)

    def test_first_night_facade_keeps_the_exact_seventeen_wall_template(self):
        for mirrored in (False, True):
            raw = gate_request(round_no=71, mirrored=mirrored, closed=True)
            raw['teamOur']['roles'][2].update(pos=point(4, 9, mirrored).dump(), backpack=['stone'])
            s, plan = setup(raw)
            self.assertFalse(s.day_gate.worker(s.turn.workers()[0]))
            self.assertFalse(s.day_gate.can_seal(s.turn.workers()[0]))
            self.assertEqual({(w.pos.x, w.pos.y) for w in s.turn.walls()},
                             {(point(x, y, mirrored).x, y) for x, y in WALLS})
            s.run()
            self.assertFalse(any(c['action'] in ('remove', 'build') for c in plan.commands.values()))
            self.assertFalse(plan.rejections)

    def test_closed_template_leaves_outside_worker_access_to_shop_but_not_inside_lane(self):
        for mirrored in (False, True):
            raw = gate_request(round_no=40, mirrored=mirrored, closed=True)
            raw['teamOur']['roles'][2]['pos'] = point(4, 9, mirrored).dump()
            s, _ = setup(raw)
            worker = s.turn.workers()[0]
            route = s.day_gate.access_route(worker)
            self.assertIsNone(route.nearest({point(x, y, mirrored) for x, y in LANE}))
            self.assertIsNotNone(route.nearest({point(3, 7, mirrored)}))


if __name__ == '__main__':
    unittest.main()
