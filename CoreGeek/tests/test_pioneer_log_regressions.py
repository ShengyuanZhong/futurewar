"""Regression inputs derived from bug_log1/2; no runtime dependency on logs.

The original logs omit raw requests and the initial pioneer position. Opening
tests therefore cover several legal birth cells with the logged base/task
coordinates, rather than claim to reproduce the entire official match.
"""
import unittest

from agent.first_day_tasks import record_attempt,finish_attempt,finished_count,success_count
from agent.protocol import Pos
from app.config import Settings
from app.service.memory import GameMemory
from tests.test_opening_log_regressions import opening_geometry
from tests.test_three_tasks import three_task_request,completed_memory
from tests.test_worker_safety import strategy


class PioneerLogRegressionTests(unittest.TestCase):
    def test_forecast_trip_cannot_authorize_an_expired_real_purchase(self):
        for forecast_first in (False,True):
            with self.subTest(forecast_first=forecast_first):
                raw,_ = three_task_request(69)
                s,_ = strategy(raw,completed_memory(),Settings(enable_news=False))
                pioneer = next(u for u in s.turn.controllable() if u.kind=='pioneer')
                if forecast_first:
                    forecast = s.boss_raid.shop_trip(pioneer,3,start=pioneer.pos)
                    actual = s.boss_raid.shop_trip(pioneer,3)
                else:
                    actual = s.boss_raid.shop_trip(pioneer,3)
                    forecast = s.boss_raid.shop_trip(pioneer,3,start=pioneer.pos)
                self.assertIsNone(actual)
                self.assertIsNotNone(forecast)
                self.assertGreater(forecast[0],s.turn.daylight_left)

    def test_logged_base_does_not_virtually_trap_pioneer_at_opening(self):
        for birth in (Pos(33,10),Pos(32,11),Pos(30,11),Pos(29,9)):
            with self.subTest(birth=birth):
                raw = opening_geometry('bug_log2')
                raw['teamOur']['roles'][-1]['pos'] = birth.dump()
                raw['teamOur']['playerTasks'] = [dict(taskType='自进化类1',
                    taskPosition=Pos(23,14).dump(),isValid=True,coldDownRounds=0,
                    timeoutRounds=15,goldReward=120,scoreReward=10),
                    dict(taskType='自进化类2',taskPosition=Pos(26,17).dump(),
                    isValid=True,coldDownRounds=0,timeoutRounds=15,goldReward=120,scoreReward=10)]
                raw['mapInfo']['zones'] += [dict(neutralType=kind,pos=pos.dump())
                    for kind,pos in (('defenderTaskPoint1',Pos(23,14)),
                                     ('defenderTaskPoint2',Pos(26,17)),
                                     ('defenderTaskPoint2',Pos(27,17)),
                                     ('weaponShop',Pos(20,16)))]
                s,plan = strategy(raw,GameMemory(),Settings(enable_news=False,enable_first_night_defense=False))
                s.run()
                self.assertEqual(plan.commands['20011']['action'],'move')
                self.assertNotEqual(s.memory.task_schedule.get('status'),'insufficient_daylight')
                self.assertFalse(s.memory.task_schedule.get('itinerary_closed',False))
                self.assertFalse(plan.rejections)

    def test_third_task_that_cannot_fit_shop_use_return_releases_two_order_purchase(self):
        raw,_ = three_task_request(50)
        raw['teamOur']['goldNum'] = 240
        raw['teamOur']['playerTasks'][0].update(isValid=False,coldDownRounds=16,timeoutRounds=15)
        memory = completed_memory()
        del memory.task_attempts[(1,34,1,7)]
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        s.run()
        self.assertTrue(memory.task_schedule['itinerary_closed'])
        self.assertEqual(memory.task_schedule['unattempted_steps'],[1])
        self.assertEqual(finished_count(memory),2)
        self.assertEqual(success_count(memory),2)
        self.assertEqual(plan.commands['502'],dict(action='buy',name='BossRobotSummonOrder',num=2))
        self.assertEqual(memory.boss_raid['target_count'],2)

    def test_exhausted_second_point_does_not_lock_one_success_out_of_shop(self):
        raw,_ = three_task_request(43)
        raw['teamOur']['goldNum'] = 120
        raw['teamOur']['playerTasks'][1].update(isValid=False,coldDownRounds=0)
        memory = GameMemory(opening_complete=True)
        key = record_attempt(memory,1,32,(1,7),'自进化类1')
        finish_attempt(memory,key,43,succeeded=True)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        s.run()
        self.assertEqual(memory.task_schedule['close_reason'],'point_unavailable')
        self.assertEqual(finished_count(memory),1)
        self.assertEqual(plan.commands['502']['num'],1)

    def test_temporarily_blocked_route_does_not_close_or_buy_early(self):
        raw,_ = three_task_request(20)
        memory = completed_memory()
        del memory.task_attempts[(1,34,1,7)]
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        pioneer = next(u for u in s.turn.controllable() if u.kind=='pioneer')
        route = s.route(pioneer)
        route.cost = {pioneer.pos:0}
        raw_task = s.turn.tasks[0]
        # Move the target away from the actor: a dynamic blockage cannot be
        # misreported as 10,000 rounds of travel and close the task itinerary.
        from dataclasses import replace
        s.turn = replace(s.turn,tasks=(replace(raw_task,pos=Pos(10,15)),))
        self.assertTrue(s.task(pioneer))
        self.assertEqual(memory.task_schedule['status'],'route_blocked')
        self.assertFalse(memory.task_schedule.get('itinerary_closed',False))
        self.assertFalse(s.boss_raid.tasks_finished())
        self.assertNotIn('502',plan.commands)
