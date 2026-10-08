"""Regressions for productive parallel work and stable trips across dusk."""
import unittest

from agent.protocol import Pos
from app.service.memory import GameMemory
from tests.fixtures import unit, request, robot
from tests.test_u_layout import drawing_request, point
from tests.test_worker_safety import strategy
from tests.test_maintenance import fortified
from app.config import Settings


class WorkerEfficiencyTests(unittest.TestCase):
    def test_stocked_builder_works_while_other_worker_is_still_mining(self):
        for mirrored in (False, True):
            raw = drawing_request(mirrored, built=True, round_no=25)
            raw['teamOur']['roles'][2].update(pos=point(8, 7, mirrored).dump(), backpack=['stone']*6)
            raw['teamOur']['roles'][3]['pos'] = point(2, 5, mirrored).dump()
            raw['mapInfo']['zones'] = [{'neutralType':'stone', 'pos':point(3, 5, mirrored).dump()}]
            s, plan = strategy(raw, GameMemory()); s.run()
            self.assertEqual(plan.commands['501']['action'], 'build')
            self.assertEqual(plan.commands['504']['action'], 'collect')
            self.assertEqual(plan.rejections, [])

    def test_worker_without_construction_material_keeps_economy_running(self):
        raw = drawing_request(built=True, round_no=25)
        raw['teamOur']['roles'][2]['pos'] = {'x':2, 'y':5}
        raw['teamOur']['roles'][3].update(pos={'x':8, 'y':7}, backpack=['stone']*12)
        raw['mapInfo']['zones'] = [{'neutralType':'iron', 'pos':{'x':3, 'y':5}}]
        raw['vendorShopList'] = [{'name':'iron', 'price':3}]
        s, plan = strategy(raw, GameMemory()); s.run()
        self.assertEqual(plan.commands['501']['action'], 'collect')
        self.assertEqual(plan.commands['504']['action'], 'build')

    def test_missing_stone_mine_does_not_leave_the_worker_idle(self):
        raw = drawing_request(built=True, round_no=25)
        raw['teamOur']['roles'][2]['pos'] = {'x':2,'y':5}
        raw['teamOur']['roles'][3]['health'] = 0
        raw['mapInfo']['zones'] = [{'neutralType':'iron','pos':{'x':3,'y':5}}]
        raw['vendorShopList'] = [{'name':'iron','price':3}]
        s, plan = strategy(raw, GameMemory()); s.run()
        self.assertEqual(plan.commands['501']['action'], 'collect')

    def test_dusk_does_not_start_a_wall_trip_that_cannot_finish(self):
        raw = drawing_request(built=True, round_no=70)
        raw['teamOur']['roles'][2].update(pos={'x':1, 'y':12}, backpack=['stone']*12)
        raw['teamOur']['roles'][3]['health'] = 0
        raw['mapInfo']['zones'] = [{'neutralType':'iron', 'pos':{'x':2, 'y':12}}]
        raw['vendorShopList'] = [{'name':'iron', 'price':3}]
        memory = GameMemory()
        for number in (70, 71):
            raw['roundNo'] = number
            s, plan = strategy(raw, memory); s.run()
            self.assertEqual(plan.commands['501']['action'], 'collect')
            self.assertEqual(plan.commands['501']['targetPos'], [{'x':2, 'y':12}])
            memory.record(s.turn, plan)

    def test_build_target_keeps_its_identity_during_the_trip(self):
        raw = drawing_request(built=True, round_no=25)
        raw['teamOur']['roles'][2].update(pos={'x':1, 'y':12}, backpack=['stone']*12)
        raw['teamOur']['roles'][3]['health'] = 0
        memory = GameMemory()
        s, plan = strategy(raw, memory); s.run()
        target = memory.worker_tasks[501]['target']
        self.assertIsInstance(target, Pos)
        for number in range(26, 42):
            command = plan.commands['501']
            if command['action'] == 'build':
                self.assertEqual(command['targetPos'], [target.dump()])
                break
            raw['teamOur']['roles'][2]['pos'] = command['targetPos'][0]
            memory.record(s.turn, plan)
            raw['roundNo'] = number
            s, plan = strategy(raw, memory); s.run()
            self.assertEqual(memory.worker_tasks[501]['target'], target)
        else:
            self.fail('builder abandoned its chosen wall')

    def test_failed_yield_allows_worker_to_choose_other_work(self):
        raw = drawing_request(built=True, round_no=25)
        raw['teamOur']['roles'] = [unit(501,'worker',2,2), unit(504,'worker',3,2)]
        free = {Pos(2,2), Pos(3,2), Pos(4,2)}
        raw['mapInfo']['zones'] = [{'neutralType':'stone', 'pos':{'x':x,'y':y}}
            for x in range(41) for y in range(32) if Pos(x,y) not in free]
        s, plan = strategy(raw)
        self.assertFalse(s.coordinator.move_to(s.turn.workers()[0], {Pos(4,2)}, 'delivery', Pos(4,2)))
        self.assertNotIn(501, plan.used)
        self.assertEqual(plan.commands, {})

    def test_only_one_worker_travels_for_the_same_upgrade_purchase(self):
        raw = fortified(200)
        raw['teamOur']['roles'][2].update(pos={'x':1, 'y':3}, backpack=[])
        raw['teamOur']['roles'][3].update(pos={'x':12, 'y':12}, backpack=[])
        raw['mapInfo']['zones'].append({'neutralType':'iron', 'pos':{'x':13, 'y':12}})
        memory = GameMemory(opening_complete=True)
        for number in (200, 201, 202):
            raw['roundNo'] = number
            s, plan = strategy(raw, memory, Settings(repair_start_day=10)); s.run()
            self.assertEqual(memory.worker_tasks[501]['kind'], 'buy_upgrade')
            self.assertEqual(plan.commands['504']['action'], 'collect')
            for uid, command in plan.commands.items():
                if command['action'] == 'move':
                    next(r for r in raw['teamOur']['roles'] if str(r['id']) == uid)['pos'] = command['targetPos'][0]
            memory.record(s.turn, plan)

    def test_valid_mining_trip_is_not_abandoned_when_peer_uses_same_mine(self):
        raw = request(200)
        raw['teamOur']['roles'] = [unit(501,'worker',1,1), unit(504,'worker',10,9)]
        raw['mapInfo']['zones'] = [{'neutralType':'iron','pos':{'x':10,'y':10}},
                                  {'neutralType':'iron','pos':{'x':1,'y':3}}]
        memory = GameMemory(opening_complete=True)
        s, _ = strategy(raw, memory)
        s.coordinator.assign(s.turn.workers()[0], 'collect:iron', Pos(10,10), Pos(9,9), True)
        s.coordinator.assign(s.turn.workers()[1], 'collect:iron', Pos(10,10), Pos(10,9))
        raw['roundNo'] = 201
        raw['teamOur']['roles'][0]['pos'] = {'x':2,'y':2}
        s, plan = strategy(raw, memory)
        self.assertTrue(s.mine(s.turn.workers()[0]))
        self.assertEqual(memory.worker_tasks[501]['target'], Pos(10,10))
        self.assertEqual(plan.rejections, [])

    def test_builders_keep_their_distinct_in_progress_wall_assignments(self):
        for mirrored in (False, True):
            raw = drawing_request(mirrored, built=True, round_no=25)
            raw['teamOur']['roles'][2].update(pos=point(8,7,mirrored).dump(), backpack=['stone']*6)
            raw['teamOur']['roles'][3].update(pos=point(8,10,mirrored).dump(), backpack=['stone']*6)
            lower, upper = point(9,4,mirrored), point(9,9,mirrored)
            memory = GameMemory(worker_tasks={
                501:{'round':24,'kind':'build:wall','target':lower,'goal':point(8,5,mirrored)},
                504:{'round':24,'kind':'build:wall','target':upper,'goal':point(8,10,mirrored)}})
            s, plan = strategy(raw, memory); s.run()
            self.assertEqual(memory.worker_tasks[501]['target'], lower)
            self.assertEqual(memory.worker_tasks[504]['target'], upper)
            self.assertEqual(plan.commands['501']['action'], 'move')
            self.assertEqual(plan.commands['504']['action'], 'build')
            self.assertEqual(plan.rejections, [])

    def test_mining_commitment_releases_an_unsafe_or_exhausted_mine(self):
        for unsafe in (False, True):
            raw = request(201)
            raw['teamOur']['roles'] = [unit(501,'worker',1,1)]
            raw['mapInfo']['zones'] = [{'neutralType':'iron','pos':{'x':1,'y':2}}]
            if unsafe:
                raw['mapInfo']['zones'].append({'neutralType':'iron','pos':{'x':10,'y':10}})
                raw['robot']['roles'] = [robot(900,10,10)]
            memory = GameMemory(opening_complete=True, worker_tasks={501:{'round':200,
                'kind':'collect:iron', 'target':Pos(10,10), 'goal':Pos(9,9)}})
            s, plan = strategy(raw, memory)
            self.assertTrue(s.mine(s.turn.workers()[0]))
            self.assertEqual(plan.commands['501']['targetPos'], [{'x':1,'y':2}])


if __name__ == '__main__':
    unittest.main()
