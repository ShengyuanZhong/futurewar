"""First-day scouting takes actual friendly cars and keeps collision-safe sight."""
import unittest

from agent.protocol import Pos, Turn, distance
from tests.fixtures import unit
from tests.test_raid_scouts import HOME_ID, WORKER_ID, role, scout_memory, scout_request
from tests.test_worker_safety import strategy


START, CAR, LOOKOUT = Pos(12,10), Pos(14,10), Pos(26,10)


def scene(round_no=20, driving=False, car=CAR):
    raw = scout_request(round_no,boss=round_no>=71)
    role(raw,WORKER_ID).update(pos=START.dump(),isDriving=driving)
    if car is not None:
        raw['mapInfo']['zones'].append({'neutralType':'challengerVehicle','pos':car.dump()})
    memory = scout_memory()
    memory.raid_scouts.update(worker_id=WORKER_ID,home_worker_id=HOME_ID)
    return raw,memory


def scout_strategy(raw,memory):
    s,plan = strategy(raw,memory)
    s.raid_scouts.post = lambda actor:LOOKOUT
    actor = next(w for w in s.turn.workers() if w.unit_id==WORKER_ID)
    return s,plan,actor


class ScoutVehicleTests(unittest.TestCase):
    def test_observed_unoccupied_car_is_a_worthwhile_stop(self):
        raw,memory = scene()
        s,plan,actor = scout_strategy(raw,memory)
        route = s.raid_scouts.scout_route(actor)
        rounds,car = s.raid_scouts.travel_budget(actor,LOOKOUT,route)
        self.assertEqual((rounds,car),(8,CAR))
        self.assertTrue(s.raid_scouts.worker(actor))
        self.assertEqual(memory.worker_tasks[WORKER_ID]['kind'],'raid_scout_vehicle')
        self.assertEqual(memory.worker_tasks[WORKER_ID]['goal'],CAR)
        self.assertEqual(len(plan.commands[str(WORKER_ID)]['targetPos']),1)
        self.assertEqual(memory.raid_scouts['posts'][WORKER_ID]['travel_rounds'],8)
        self.assertEqual(memory.raid_scouts['posts'][WORKER_ID]['status'],'collecting_vehicle')

    def test_without_observed_car_task_success_does_not_invent_one(self):
        raw,memory = scene(car=None)
        s,plan,actor = scout_strategy(raw,memory)
        s.raid_scouts.worker(actor)
        self.assertEqual(memory.worker_tasks[WORKER_ID]['kind'],'raid_scout')
        self.assertEqual(len(plan.commands[str(WORKER_ID)]['targetPos']),1)
        self.assertIsNone(memory.raid_scouts['posts'][WORKER_ID]['vehicle'])

    def test_enemy_or_occupied_car_is_not_chased(self):
        for occupied in (False,True):
            with self.subTest(occupied=occupied):
                raw,memory = scene()
                if occupied:
                    raw['teamOur']['roles'].append(unit(600,'pioneer',CAR.x,CAR.y,isDriving=True))
                else:
                    raw['mapInfo']['zones'][-1]['neutralType']='defenderVehicle'
                s,_,actor = scout_strategy(raw,memory)
                route = s.raid_scouts.scout_route(actor)
                self.assertIsNone(s.raid_scouts.travel_budget(actor,LOOKOUT,route)[1])

    def test_large_car_detour_is_ignored(self):
        raw,memory = scene(car=Pos(2,25))
        s,_,actor = scout_strategy(raw,memory)
        route = s.raid_scouts.scout_route(actor)
        self.assertIsNone(s.raid_scouts.travel_budget(actor,LOOKOUT,route)[1])

    def test_two_actual_route_segments_are_used_while_driving(self):
        raw,memory = scene(driving=True,car=START)
        raw['teamEnemy']['roles'].append(unit(888,'wall',14,10))
        s,plan,actor = scout_strategy(raw,memory)
        self.assertTrue(s.raid_scouts.worker(actor))
        points = tuple(Pos.load(p) for p in plan.commands[str(WORKER_ID)]['targetPos'])
        self.assertEqual(len(points),2)
        self.assertEqual(distance(START,points[0]),1)
        self.assertEqual(distance(points[0],points[1]),1)
        self.assertNotIn(Pos(14,10),points)
        self.assertTrue(set(points)<=plan.reserved)

    def test_late_first_day_assignment_uses_driving_rounds(self):
        raw,memory = scene(round_no=65,driving=True,car=START)
        role(raw,WORKER_ID)['pos']=Pos(18,10).dump()
        raw['mapInfo']['zones'][-1]['pos']=Pos(18,10).dump()
        s,_,actor = scout_strategy(raw,memory)
        route = s.raid_scouts.scout_route(actor)
        self.assertEqual(route.cost[LOOKOUT],8)
        self.assertEqual(s.raid_scouts.travel_budget(actor,LOOKOUT,route),(4,None))
        s.raid_scouts.worker(actor)
        self.assertTrue(memory.raid_scouts['posts'][WORKER_ID]['ready_by_night'])

    def test_final_single_step_dismounts_instead_of_overshooting_lookout(self):
        raw,memory = scene(driving=True,car=Pos(25,10))
        role(raw,WORKER_ID)['pos']=Pos(25,10).dump()
        s,plan,actor = scout_strategy(raw,memory)
        s.raid_scouts.worker(actor)
        self.assertEqual(plan.commands[str(WORKER_ID)]['targetPos'],[LOOKOUT.dump()])

    def test_first_night_no_longer_drives_even_if_stale_flag_is_true(self):
        raw,memory = scene(round_no=71,driving=True,car=None)
        s,plan,actor = scout_strategy(raw,memory)
        self.assertTrue(s.raid_scouts.worker(actor))
        self.assertEqual(len(plan.commands[str(WORKER_ID)]['targetPos']),1)
        self.assertEqual(memory.raid_scouts['posts'][WORKER_ID]['travel_rounds'],14)

    def test_incomplete_home_walls_prevent_car_departure(self):
        raw,memory = scene()
        raw['teamOur']['roles']=[u for u in raw['teamOur']['roles']
            if not(u['roleType']=='wall' and u['pos']==Pos(9,7).dump())]
        s,plan,actor = scout_strategy(raw,memory)
        self.assertFalse(s.raid_scouts.worker(actor))
        self.assertNotIn(str(WORKER_ID),plan.commands)

    def test_two_failed_pickup_moves_stop_the_car_detour(self):
        raw,memory = scene()
        memory.worker_tasks[WORKER_ID] = dict(kind='raid_scout_vehicle',target=Pos(30,10),
            goal=CAR,round=19,position=START,moving=True,stalled=1)
        s,_,actor = scout_strategy(raw,memory)
        s.raid_scouts.worker(actor)
        self.assertIn(CAR,memory.raid_scouts['avoided_vehicle_sites'])
        self.assertEqual(memory.worker_tasks[WORKER_ID]['kind'],'raid_scout')

    def test_car_trip_reaches_lookout_then_keeps_real_sight_without_reboarding(self):
        raw,memory = scene()
        arrived=None
        for number in range(20,32):
            raw['roundNo']=number
            s,plan,actor = scout_strategy(raw,memory)
            s.raid_scouts.worker(actor)
            command = plan.commands.get(str(WORKER_ID))
            if command is None:
                self.assertEqual(actor.pos,LOOKOUT)
                self.assertEqual(memory.raid_scouts['posts'][WORKER_ID]['status'],'holding')
                arrived=number
                break
            points = tuple(Pos.load(p) for p in command['targetPos'])
            before = actor.pos
            car_cells=s.turn.vehicle_cells()
            if actor.is_driving and len(points)==2:
                for zone in raw['mapInfo']['zones']:
                    if zone['neutralType']=='challengerVehicle':
                        zone['pos']=points[-1].dump()
                driving=True
            else:
                driving=points[-1] in car_cells
            self.assertEqual(distance(before,points[0]),1)
            if len(points)==2:
                self.assertEqual(distance(points[0],points[1]),1)
            role(raw,WORKER_ID).update(pos=points[-1].dump(),isDriving=driving)
        self.assertEqual(arrived,28)
        self.assertTrue(s.raid_scouts.seen(Pos(30,10)))


if __name__=='__main__':
    unittest.main()
