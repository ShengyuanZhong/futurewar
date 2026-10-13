"""First-day perimeter scheduling with public observed positions only."""
import copy
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn, distance, build_command
from agent.wall_schedule import WallSchedule
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, unit


def scene(upper=False, round_no=29, memory=None):
    raw = request(round_no)
    base = Pos(9, 22) if upper else Pos(30, 10)
    enemy = Pos(30, 10) if upper else Pos(9, 22)
    raw['teamOur'].update(playerTasks=[], goldNum=0, roles=[
        unit(503, 'station', base.x, base.y),
        unit(501, 'worker', 3 if upper else 35, 28 if upper else 3, backpack=['stone'] * 9),
        unit(504, 'worker', 4 if upper else 35, 28 if upper else 4, backpack=['stone'] * 8)])
    raw['teamEnemy']['roles'] = [unit(903, 'station', enemy.x, enemy.y)]
    # Fixed real observation for both local scenarios, intentionally not mirrored.
    raw['mapInfo']['zones'] = [dict(neutralType='weaponShop', pos=Pos(24, 20).dump())]
    raw['weaponShopList'] = []
    settings = Settings(enable_tasks=False, enable_boss_raid=False,
                        enable_first_night_defense=False, enable_news=False)
    turn = Turn.load(raw)
    for uid, pos in enumerate(settings.build_cells(turn, 'rocket'), 601):
        raw['teamOur']['roles'].append(unit(uid, 'rocket', pos.x, pos.y, health=1000))
    memory = memory or GameMemory()
    return raw, memory, settings


def strategy(raw, memory, settings):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, settings)
    s = Strategy(turn, plan, memory)
    scheduler = WallSchedule(s)
    return s, scheduler


class WallScheduleTests(unittest.TestCase):
    def test_yield_keeps_an_external_worker_outside_the_unbuilt_ring(self):
        raw,memory,settings=scene()
        next(u for u in raw['teamOur']['roles'] if u['id']==501)['pos']=Pos(34,7).dump()
        next(u for u in raw['teamOur']['roles'] if u['id']==504)['pos']=Pos(34,8).dump()
        s,_=strategy(raw,memory,settings)
        requester,blocker=s.turn.workers()
        self.assertIn(blocker.pos,s.sealed_home.outside)
        # Two legal unoccupied sidesteps: an unfinished wall and an exterior
        # cell. Yielding must choose the exterior one, even though the wall
        # appears earlier in the old lateral-distance/coordinate ordering.
        s.plan.reserved.update(set(blocker.pos.neighbours())-{Pos(33,8),Pos(35,8)})
        self.assertTrue(s.coordinator.yield_blocker(requester,blocker,Pos(34,11)))
        destination=Pos.load(s.plan.commands['504']['targetPos'][0])
        self.assertEqual(destination,Pos(35,8))
        self.assertIn(destination,s.sealed_home.outside)
        self.assertFalse(s.plan.rejections)

    def test_material_shares_follow_seven_and_ten_wall_arcs(self):
        raw,memory,settings = scene()
        for u in raw['teamOur']['roles']:
            if u['roleType']=='worker':
                u['backpack']=[]
        s,schedule = strategy(raw,memory,settings)
        self.assertEqual(s.stone_targets(),{501:7,504:10})
        self.assertEqual(sum(s.stone_targets().values()),17)

    def test_pending_build_never_reduces_actual_personal_material(self):
        raw,memory,settings = scene()
        next(u for u in raw['teamOur']['roles'] if u['id']==501).update(
            pos=Pos(34,6).dump(),backpack=['stone'])
        next(u for u in raw['teamOur']['roles'] if u['id']==504)['backpack']=[]
        s,schedule = strategy(raw,memory,settings)
        worker = next(w for w in s.turn.workers() if w.unit_id==501)
        before=s.stone_targets()
        remaining=schedule.remaining(worker)
        self.assertTrue(s.plan.add(501,build_command(Pos(33,7),'wall')))
        self.assertEqual(schedule.remaining(worker),remaining)
        self.assertEqual(s.stone_targets(),before)
        self.assertEqual(sum(before.values()),17)

    def test_cached_posts_follow_real_same_turn_reservations(self):
        s,schedule = strategy(*scene())
        worker=s.turn.workers()[0]
        target=schedule.targets(worker,s.construction_walls())[0]
        posts=schedule.posts(worker,target)
        self.assertTrue(posts)
        self.assertLess(schedule.cost(worker,target),10000)
        s.plan.reserved.update(posts)
        self.assertFalse(schedule.posts(worker,target))
        self.assertEqual(schedule.cost(worker,target),10000)

    def test_historical_empty_gap_does_not_hijack_the_daytime_sweep(self):
        raw,memory,settings=scene(round_no=37)
        gap=Pos(28,11)
        next(u for u in raw['teamOur']['roles'] if u['id']==501)['pos']=Pos(32,6).dump()
        memory.wall_gap_defense=dict(worker_id=501,gaps={gap:dict(first_seen=36,last_seen=36,enemy_id=900)})
        s,schedule=strategy(raw,memory,settings)
        worker=next(w for w in s.turn.workers() if w.unit_id==501)
        self.assertIn(gap,s.gap_guard.gaps)
        self.assertFalse(s.gap_guard.worker(worker))
        self.assertFalse(s.plan.commands)
        s.run_worker(worker)
        command=s.plan.commands['501']
        self.assertEqual(command['action'],'build')
        self.assertEqual(command['targetPos'][0]['y'],7)
        self.assertNotEqual(s.coordinator.job(worker).get('kind'),'gap_rebuild')
        self.assertFalse(s.plan.rejections)

    def test_one_legal_blueprint_wall_uses_safe_fallback(self):
        raw,memory,settings=scene()
        from dataclasses import replace
        settings=replace(settings,layouts={'challenger':dict(verified=True,source='isolated one-wall fixture',
            weapons=[dict(x=2,y=1),dict(x=2,y=0),dict(x=2,y=-1)],walls=[dict(x=-2,y=0)])})
        s,schedule=strategy(raw,memory,settings)
        self.assertFalse(schedule.enabled)
        self.assertEqual(schedule.targets(s.turn.workers()[0],s.construction_walls()),[Pos(28,10)])

    def test_complete_blueprint_is_split_once_without_shared_targets(self):
        for upper in (False, True):
            with self.subTest(upper=upper):
                s, schedule = strategy(*scene(upper))
                arcs = list(schedule.state['arcs'].values())
                self.assertEqual(len(arcs), 2)
                self.assertFalse(set(arcs[0]) & set(arcs[1]))
                self.assertEqual(set(arcs[0]) | set(arcs[1]), set(s.construction_walls()))
                self.assertEqual(sum(map(len, arcs)), 17)

    def test_actual_shop_is_used_on_both_sides_without_mirroring(self):
        for upper in (False, True):
            s, schedule = strategy(*scene(upper))
            buyer = s.memory.boss_raid['buyer_id']
            self.assertEqual(schedule.state['destinations'][buyer], Pos(24, 20))
            scout = next(w.unit_id for w in s.turn.workers() if w.unit_id != buyer)
            self.assertEqual(schedule.state['destinations'][scout],
                             Pos(30, 10) if upper else Pos(9, 22))

    def test_departure_end_points_towards_each_observed_future_job(self):
        lower, lower_schedule = strategy(*scene(False))
        upper, upper_schedule = strategy(*scene(True))
        self.assertGreater(lower_schedule.state['departure'].y, lower.turn.station().pos.y)
        self.assertLess(upper_schedule.state['departure'].y, upper.turn.station().pos.y)

    def test_mining_workers_begin_on_arrival_side_not_departure_side(self):
        for upper in (False, True):
            s, schedule = strategy(*scene(upper))
            for worker in s.turn.workers():
                choices = schedule.targets(worker, s.construction_walls())
                self.assertTrue(choices)
                end = schedule.state['arcs'][worker.unit_id][-1]
                if upper:
                    # The cannon gap may leave a worker's arc starting midway
                    # along the west side. It still sweeps south towards its
                    # actual shop/base, rather than back north after building.
                    self.assertGreater(choices[0].y, end.y)
                else:
                    self.assertEqual(choices[0].y, 7)
                    self.assertLess(choices[0].y, end.y)

    def test_order_and_identity_survive_changed_worker_positions(self):
        raw, memory, settings = scene()
        s, schedule = strategy(raw, memory, settings)
        arcs = copy.deepcopy(schedule.state['arcs'])
        raw['roundNo'] += 1
        workers = [u for u in raw['teamOur']['roles'] if u['roleType'] == 'worker']
        workers[0]['pos'], workers[1]['pos'] = workers[1]['pos'], workers[0]['pos']
        _, next_schedule = strategy(raw, memory, settings)
        self.assertEqual(next_schedule.state['arcs'], arcs)

    def test_local_branch_uses_the_same_frontier_as_travel_branch(self):
        s, schedule = strategy(*scene())
        for worker in s.turn.workers():
            choices = schedule.targets(worker, s.construction_walls())
            local = schedule.targets(worker, s.construction_walls(), local_only=True)
            self.assertEqual(local, [choices[0]] if distance(worker.pos, choices[0]) == 1 else [])

    def test_live_travel_appointment_is_preserved(self):
        s, schedule = strategy(*scene())
        worker = s.turn.workers()[0]
        choices = schedule.targets(worker, s.construction_walls())
        target = choices[-1]
        goal = min(schedule.posts(worker, target))
        s.coordinator.assign(worker, 'build:wall', target, goal, moving=True)
        self.assertEqual(schedule.targets(worker, s.construction_walls())[0], target)

    def test_departed_buyer_releases_remaining_work_to_actual_builder(self):
        s, schedule = strategy(*scene())
        buyer = s.memory.boss_raid['buyer_id']
        s.boss_raid.worker_mission_active = lambda w: w.unit_id == buyer
        survivor = next(w for w in s.turn.workers() if w.unit_id != buyer)
        self.assertEqual(schedule.remaining(survivor), len(s.construction_walls()))
        self.assertEqual(set(schedule.targets(survivor, s.construction_walls())),
                         set(s.construction_walls()))
        self.assertEqual(schedule.targets(next(w for w in s.turn.workers() if w.unit_id == buyer),
                         s.construction_walls()), [])

    def test_dead_teammate_does_not_keep_target_ownership(self):
        raw, memory, settings = scene()
        _, initial = strategy(raw, memory, settings)
        self.assertEqual(len(initial.state['arcs']), 2)
        raw['roundNo'] += 1
        next(u for u in raw['teamOur']['roles'] if u['id'] == 501)['health'] = 0
        s, schedule = strategy(raw, memory, settings)
        survivor = s.turn.workers()[0]
        self.assertEqual(schedule.remaining(survivor), len(s.construction_walls()))
        self.assertEqual(set(schedule.targets(survivor, s.construction_walls())),
                         set(s.construction_walls()))

    def test_external_posts_are_legal_and_exclude_future_blueprint_cells(self):
        s, schedule = strategy(*scene())
        for worker in s.turn.workers():
            for target in s.construction_walls():
                posts = schedule.posts(worker, target)
                self.assertTrue(posts <= s.sealed_home.outside)
                self.assertFalse(posts & schedule.walls)
                self.assertTrue(all(distance(p, target) == 1 for p in posts))

    def test_occupied_or_already_claimed_candidates_do_not_block_sweep(self):
        s, schedule = strategy(*scene())
        worker = s.turn.workers()[0]
        choices = schedule.targets(worker, s.construction_walls())
        blocked = choices[0]
        available = [p for p in s.construction_walls() if p != blocked]
        self.assertTrue(schedule.targets(worker, available))
        self.assertNotIn(blocked, schedule.targets(worker, available))


if __name__ == '__main__':
    unittest.main()
