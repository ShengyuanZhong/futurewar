"""First-day material/path regressions on explicit local synthetic geometry."""
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn
from agent.stone_planner import StonePlanner
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, unit


def scene(number=12, first=None, second=None, mines=None, missing=17, memory=None, remaining=None):
    raw = request(number)
    raw['teamOur']['roles'] = [unit(503, 'station', 10, 24),
        unit(501, 'worker', 3, 8, **(first or {})),
        unit(504, 'worker', 5, 8, **(second or {}))]
    raw['mapInfo']['zones'] = [dict(neutralType=kind, pos=pos.dump())
        for kind, pos in (mines if mines is not None else [('stone', Pos(4, 8))])]
    for zone in raw['mapInfo']['zones']:
        pos=Pos.load(zone['pos'])
        if remaining is not None and pos in remaining:
            zone['remain']=remaining[pos]
    turn = Turn.load(raw)
    settings = Settings(enable_tasks=False, enable_boss_raid=False,
                        enable_first_night_defense=False, enable_news=False)
    plan = ActionPlan(turn, settings)
    memory = memory or GameMemory()
    s = Strategy(turn, plan, memory)
    # This isolates material allocation from the closure FSM. The 17 targets
    # are synthetic; integrated blueprint/exit tests exercise real home walls.
    walls = [Pos(20 + i // 5, 3 + i % 5) for i in range(missing)]
    s.construction_walls = lambda: walls
    s.wall_keeps_exit = lambda role, target: True
    s.wall_schedule.enabled = False  # Isolate these synthetic quotas from real blueprint arcs.
    planner = StonePlanner(s)
    return raw, s, plan, planner


class StonePlannerTests(unittest.TestCase):
    def test_empty_bags_split_exact_seventeen_without_extra_seal_stone(self):
        _, s, _, planner = scene()
        self.assertEqual(planner.targets(), {501: 9, 504: 8})
        self.assertEqual(sum(planner.targets().values()), 17)
        self.assertEqual(s.memory.worker_tasks[501]['stone_quota'], 9)

    def test_actual_team_stone_suffices_so_neither_worker_overcollects(self):
        _, s, plan, planner = scene(first={'backpack': ['stone'] * 9},
                                   second={'backpack': ['stone'] * 8})
        for worker in s.turn.workers():
            self.assertFalse(planner.needs_material(worker))
            self.assertFalse(planner.mine(worker))
        self.assertEqual(plan.commands, {})

    def test_departing_buyer_bag_cannot_supply_builder(self):
        _, s, _, planner = scene(first={'backpack': ['stone'] * 10},
                                second={'backpack': ['stone'] * 2}, missing=7)
        s.boss_raid.worker_mission_active = lambda worker: worker.unit_id == 501
        self.assertEqual(planner.targets(), {501: 0, 504: 7})
        self.assertFalse(planner.needs_material(s.turn.workers()[0]))
        self.assertTrue(planner.needs_material(s.turn.workers()[1]))

    def test_unfinished_mining_share_is_retained_when_teammate_builds(self):
        memory = GameMemory(worker_tasks={501: dict(kind='collect:stone',
            target=Pos(4, 8), goal=Pos(3, 8), round=11, stone_quota=10)})
        _, _, _, planner = scene(first={'backpack': ['stone'] * 2},
                                 second={'backpack': ['stone'] * 1},
                                 missing=15, memory=memory)
        self.assertEqual(planner.targets(), {501: 10, 504: 5})

    def test_old_quota_never_creates_demand_after_actual_material_arrives(self):
        memory = GameMemory(worker_tasks={501: dict(kind='collect:stone',
            target=Pos(4, 8), goal=Pos(3, 8), round=11, stone_quota=12)})
        _, s, plan, planner = scene(first={'backpack': ['stone'] * 2},
                                   second={'backpack': ['stone'] * 5},
                                   missing=7, memory=memory)
        self.assertEqual(planner.targets(), {501: 2, 504: 5})
        self.assertFalse(planner.mine(s.turn.workers()[0]))
        self.assertEqual(plan.commands, {})

    def test_capacity_limits_allocation_without_assuming_drop_or_sale(self):
        _, s, plan, planner = scene(first={'backpack': ['iron'] * 99},
                                   second={'backpack': ['iron'] * 100})
        self.assertEqual(planner.targets(), {501: 1, 504: 0})
        self.assertFalse(planner.mine(s.turn.workers()[1]))
        self.assertEqual(plan.commands, {})

    def test_adjacent_actual_wall_build_avoids_another_mine_trip(self):
        _, s, _, planner = scene(first={'backpack': ['stone']})
        s.construction_walls = lambda: [Pos(2, 8)]
        worker = s.turn.workers()[0]
        self.assertTrue(planner.can_build_now(worker))
        s.wall_keeps_exit = lambda role, target: False
        self.assertFalse(planner.can_build_now(worker))

    def test_local_build_probe_rejects_occupied_or_reserved_wall(self):
        _, s, plan, planner = scene(first={'backpack': ['stone']})
        worker = s.turn.workers()[0]
        s.construction_walls = lambda: [Pos(4, 8)]  # An actual mineral occupies it.
        self.assertFalse(planner.can_build_now(worker))
        s.construction_walls = lambda: [Pos(2, 8)]
        plan.reserved.add(Pos(2, 8))
        self.assertFalse(planner.can_build_now(worker))

    def test_same_mine_supports_two_distinct_actual_collection_posts(self):
        _, s, plan, planner = scene()
        for worker in s.turn.workers():
            self.assertTrue(planner.mine(worker))
        expected = dict(action='collect', targetPos=[Pos(4, 8).dump()])
        self.assertEqual(plan.commands, {'501': expected, '504': expected})
        self.assertNotEqual(s.coordinator.job(s.turn.workers()[0])['goal'],
                            s.coordinator.job(s.turn.workers()[1])['goal'])
        self.assertEqual(plan.rejections, [])

    def test_near_peer_mine_does_not_cancel_a_valid_independent_trip(self):
        memory = GameMemory(worker_tasks={501: dict(kind='collect:stone',
            target=Pos(14, 8), goal=Pos(13, 8), round=11, stone_quota=9)})
        _, s, plan, planner = scene(mines=[('stone', Pos(4, 8)), ('stone', Pos(14, 8))],
                                   memory=memory)
        self.assertTrue(planner.mine(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501']['action'],'move')
        self.assertEqual(s.coordinator.job(s.turn.workers()[0])['target'],Pos(14,8))
        self.assertTrue(planner.mine(s.turn.workers()[1]))
        self.assertEqual(plan.commands['504'],dict(action='collect',targetPos=[Pos(4,8).dump()]))

    def test_valid_travel_target_is_kept_instead_of_reversing_mid_route(self):
        memory = GameMemory(worker_tasks={501: dict(kind='collect:stone',
            target=Pos(14, 8), goal=Pos(13, 8), round=11, stone_quota=9)})
        _, s, plan, planner = scene(mines=[('stone', Pos(1, 8)), ('stone', Pos(14, 8))],
                                   memory=memory)
        self.assertTrue(planner.mine(s.turn.workers()[0]))
        self.assertEqual(s.coordinator.job(s.turn.workers()[0])['target'], Pos(14, 8))
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertGreater(plan.commands['501']['targetPos'][0]['x'], 3)

    def test_mine_disappearance_and_failed_feedback_invalidate_old_target(self):
        for absent in (False, True):
            with self.subTest(absent=absent):
                memory = GameMemory(worker_tasks={501: dict(kind='collect:stone',
                    target=Pos(14, 8), goal=Pos(13, 8), round=11, stone_quota=9)})
                if not absent:
                    memory.failed_mines['14,8'] = 15
                mines = [('stone', Pos(1, 8))]
                if not absent:
                    mines.append(('stone', Pos(14, 8)))
                _, s, _, planner = scene(mines=mines, memory=memory)
                self.assertTrue(planner.mine(s.turn.workers()[0]))
                self.assertEqual(s.coordinator.job(s.turn.workers()[0])['target'], Pos(1, 8))

    def test_current_claimed_collection_post_is_not_reused(self):
        memory = GameMemory(worker_tasks={504: dict(kind='collect:stone',
            target=Pos(4, 8), goal=Pos(3, 8), round=12)})
        _, s, plan, planner = scene(memory=memory)
        self.assertTrue(planner.mine(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501']['action'], 'move')
        self.assertNotEqual(s.coordinator.job(s.turn.workers()[0])['goal'], Pos(3, 8))

    def test_submitted_collect_and_build_do_not_change_actual_material_quota(self):
        _, s, plan, planner = scene(missing=2)
        original = planner.targets()
        self.assertTrue(planner.mine(s.turn.workers()[0]))
        self.assertEqual(planner.targets(), original)
        plan.build_targets.add(Pos(20, 3))  # A pending build is not an observed wall.
        self.assertEqual(planner.targets(), original)
        self.assertEqual(s.turn.workers()[0].backpack, ())

    def test_closed_stone_mines_are_not_collected(self):
        memory = GameMemory(mine_closures=[dict(name='stone', startDay=1, endDay=1)])
        _, s, plan, planner = scene(memory=memory)
        self.assertFalse(planner.mine(s.turn.workers()[0]))
        self.assertEqual(plan.commands, {})

    def test_first_day_stone_trip_has_no_return_home_time_budget(self):
        _, s, plan, planner = scene(number=70)
        self.assertTrue(planner.mine(s.turn.workers()[0], return_cells={Pos(40, 31)}))
        self.assertEqual(plan.commands['501']['action'], 'collect')


if __name__ == '__main__':
    unittest.main()
