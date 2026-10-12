"""Three actual attempts in Task2/Task1/Task2 order with official cooldown."""
import copy
import unittest

from agent.actions import ActionPlan
from agent.first_day_tasks import (record_attempt,finish_attempt,task_attempts,
                                   finished_count,success_count)
from agent.protocol import Pos,Turn
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import Session,TurnService
from tests.test_layout_survey import survey_request,actor,reveal
from tests.test_summon_control import ORDER
from tests.fixtures import request
from tests.test_worker_safety import strategy


def three_task_request(number=1,near=False):
    raw,truth = survey_request(number,near=near)
    raw['teamOur'].update(goldNum=1000,totalScore=0)
    actor(raw,502)['pos'] = Pos(2,6).dump()
    actor(raw,501).update(pos=Pos(3,7).dump(),backpack=['stone']+['WallFixer']*5)
    if not near:
        actor(raw,504)['pos'] = Pos(3,6).dump()
    raw['mapInfo']['zones'] = [z for z in raw['mapInfo']['zones'] if 'TaskPoint' not in z['neutralType']]
    raw['mapInfo']['zones'] += [dict(neutralType=kind,pos=pos.dump()) for kind,pos in
        (('challengerTaskPoint1',Pos(1,7)),('challengerTaskPoint2',Pos(1,6)),('challengerTaskPoint2',Pos(1,5)))]
    raw['teamOur']['playerTasks'] = copy.deepcopy(request()['teamOur']['playerTasks'])
    for task,kind,pos in zip(raw['teamOur']['playerTasks'],('自进化类1','自进化类2'),(Pos(1,7),Pos(1,6))):
        task.update(taskType=kind,taskPosition=pos.dump(),isValid=True,coldDownRounds=0,
                    timeoutRounds=12,goldReward=100,scoreReward=10)
    return raw,truth


def completed_memory(outcomes=(True,True,True)):
    memory = GameMemory(opening_complete=True)
    for accept,end,point,kind,success in zip((1,4,34),(4,7,37),((1,6),(1,7),(1,6)),
                                          ('自进化类2','自进化类1','自进化类2'),outcomes):
        key = record_attempt(memory,1,accept,point,kind)
        finish_attempt(memory,key,end,succeeded=success)
    return memory


class ThreeTaskTests(unittest.TestCase):
    def test_same_point_has_two_separate_confirmed_attempts(self):
        memory = completed_memory()
        self.assertEqual(len(task_attempts(memory)),3)
        self.assertEqual(len(memory.task_points_attempted),2)
        self.assertEqual(len(memory.task_points_succeeded),2)
        self.assertEqual(finished_count(memory),3)
        self.assertEqual(success_count(memory),3)

    def test_attempt_finish_and_success_are_idempotent(self):
        memory = GameMemory()
        key = record_attempt(memory,1,1,(1,6),'自进化类2')
        record_attempt(memory,1,1,(1,6),'自进化类2')
        for number in (4,5,6):
            finish_attempt(memory,key,number,succeeded=True)
        self.assertEqual(finished_count(memory),1)
        self.assertEqual(success_count(memory),1)
        self.assertEqual(memory.task_attempts[key]['finished_round'],4)

    def test_two_successful_attempts_do_not_allow_buy_before_third(self):
        raw,_ = three_task_request(20)
        memory = completed_memory()
        del memory.task_attempts[(1,34,1,6)]
        memory.task_active_attempt = (1,4,1,7)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        self.assertFalse(s.boss_raid.tasks_finished())
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))
        self.assertEqual(s.boss_raid.budget_reserve(),360)
        self.assertFalse(s.boss_raid.weapon_upgrades_ready())

    def test_zero_to_three_successes_choose_exact_batch(self):
        for count in range(4):
            with self.subTest(count=count):
                raw,_ = three_task_request(38)
                memory = completed_memory(tuple(i<count for i in range(3)))
                s,plan = strategy(raw,memory,Settings(enable_news=False))
                s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
                command = plan.commands.get('501',{})
                if count:
                    self.assertEqual(command,dict(action='buy',name=ORDER,num=count))
                else:
                    self.assertNotEqual(command.get('name'),ORDER)
                self.assertEqual(memory.boss_raid['target_count'],count)

    def test_two_order_gold_does_not_reduce_a_three_success_quota(self):
        raw,_ = three_task_request(38)
        raw['teamOur']['goldNum'] = 240
        memory = completed_memory()
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        self.assertEqual(memory.boss_raid['target_count'],3)
        self.assertNotEqual(plan.commands.get('501',{}).get('action'),'buy')

    def test_third_task_two_waits_at_point_for_official_cooldown(self):
        raw,_ = three_task_request(20)
        raw['teamOur']['playerTasks'][1].update(isValid=False,coldDownRounds=14)
        memory = completed_memory()
        del memory.task_attempts[(1,34,1,6)]
        memory.task_active_attempt = (1,4,1,7)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        pioneer = next(u for u in s.turn.controllable() if u.kind=='pioneer')
        self.assertTrue(s.task(pioneer))
        self.assertIn(pioneer.unit_id,plan.used)
        self.assertNotIn('502',plan.commands)
        self.assertEqual(memory.task_schedule['status'],'waiting_cooldown')
        self.assertEqual(memory.task_schedule['expected_point'],2)
        raw['roundNo'] = 34
        raw['teamOur']['playerTasks'][1].update(isValid=True,coldDownRounds=0)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        self.assertTrue(s.task(next(u for u in s.turn.controllable() if u.kind=='pioneer')))
        self.assertEqual(plan.commands['502'],{'action':'acceptTask'})

    def test_first_task_is_task_two_even_if_task_one_is_closer(self):
        raw,_ = three_task_request()
        raw['teamOur']['playerTasks'][1]['taskPosition'] = Pos(1,9).dump()
        raw['mapInfo']['zones'] = [z for z in raw['mapInfo']['zones'] if z['neutralType']!='challengerTaskPoint2']
        raw['mapInfo']['zones'] += [dict(neutralType='challengerTaskPoint2',pos=p.dump())
                                  for p in (Pos(1,9),Pos(1,8))]
        memory = GameMemory()
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        self.assertTrue(s.task(next(u for u in s.turn.controllable() if u.kind=='pioneer')))
        self.assertEqual(plan.commands['502']['action'],'move')
        self.assertEqual(memory.task_schedule['expected_point'],2)

    def test_failed_acceptance_is_not_a_task_attempt(self):
        raw,_ = three_task_request(2)
        raw['lastRoundRoleActionResults'] = {'502':False}
        memory = GameMemory(last_round=1,last_commands={'502':{'action':'acceptTask'}},
                            task_accept_round=1,last_task_point=(1,6))
        memory.observe(Turn.load(raw))
        self.assertFalse(memory.task_attempts)

    def test_third_cooldown_past_dusk_stays_waiting_without_illegal_accept(self):
        raw,_ = three_task_request(69)
        memory = completed_memory()
        del memory.task_attempts[(1,34,1,6)]
        raw['teamOur']['playerTasks'][1].update(isValid=False,coldDownRounds=10)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        self.assertTrue(s.task(next(u for u in s.turn.controllable() if u.kind=='pioneer')))
        self.assertEqual(finished_count(memory),2)
        self.assertFalse(s.boss_raid.tasks_finished())
        self.assertFalse(memory.task_schedule.get('itinerary_closed',False))
        self.assertEqual(memory.task_schedule['status'],'waiting_cooldown')
        self.assertNotIn('502',plan.commands)

    def test_late_third_visit_is_accepted_without_task_or_home_budget(self):
        raw,_ = three_task_request(70)
        raw['teamOur']['playerTasks'][1].update(timeoutRounds=30)
        memory = completed_memory()
        del memory.task_attempts[(1,34,1,6)]
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        self.assertTrue(s.task(next(u for u in s.turn.controllable() if u.kind=='pioneer')))
        self.assertEqual(plan.commands['502'],{'action':'acceptTask'})
        self.assertEqual(memory.task_schedule['expected_point'],2)
        self.assertEqual(finished_count(memory),2)
        self.assertFalse(s.boss_raid.tasks_finished())

    def test_first_night_continues_third_visit_and_respects_actual_cooldown(self):
        raw,_ = three_task_request(71)
        raw['teamOur']['playerTasks'][1].update(isValid=False,coldDownRounds=1)
        memory = completed_memory()
        del memory.task_attempts[(1,34,1,6)]
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        s.run()
        self.assertEqual(memory.task_schedule['expected_point'],2)
        self.assertEqual(memory.task_schedule['status'],'waiting_cooldown')
        self.assertFalse(s.pioneer_should_defend(next(u for u in s.turn.controllable() if u.kind=='pioneer')))
        self.assertNotIn('502',plan.commands)
        raw.update(roundNo=72)
        raw['teamOur']['playerTasks'][1].update(isValid=True,coldDownRounds=0)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        s.run()
        self.assertEqual(plan.commands['502'],{'action':'acceptTask'})
        self.assertEqual(finished_count(memory),2)
        self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))

    def test_daytime_accepted_active_third_task_continues_through_night(self):
        raw,_ = three_task_request(70)
        raw.update(phaseTask='active late task2',lastRoundRoleActionResults={'502':True})
        memory = completed_memory()
        del memory.task_attempts[(1,34,1,6)]
        current = record_attempt(memory,1,69,(1,6),'自进化类2')
        memory.task_agent.accept(Turn.load(raw).tasks[1])
        memory.task_accept_round = 69
        memory.last_task_point = (1,6)
        memory.last_round = 69
        memory.last_commands = {'502':{'action':'acceptTask'}}
        service = TurnService(Settings(enable_news=False))
        key = (raw['teamOur']['teamId'],raw['teamOur']['type'])
        service.sessions[key] = Session(memory=memory)
        response = service.decide(copy.deepcopy(raw))
        self.assertTrue(response['prompt'])
        self.assertNotIn('502',response['roleCommandMap'])
        raw.update(roundNo=71,llmResp='{"action":"final_answer","answer":"night-completion"}',
                   lastRoundRoleActionResults={})
        response = service.decide(copy.deepcopy(raw))
        self.assertEqual(response['roleCommandMap']['502']['action'],'submitAnswer')
        self.assertFalse(service.sessions[key].memory.task_attempts[current]['finished'])
        self.assertEqual(finished_count(service.sessions[key].memory),2)

    def test_three_confirmed_coupons_use_different_positions_without_rebuy(self):
        raw,truth = three_task_request(38,near=True)
        raw['teamOur']['goldNum'] = 0
        actor(raw,501)['backpack'] += [ORDER]*3
        memory = completed_memory()
        service = TurnService(Settings(enable_news=False))
        key = (raw['teamOur']['teamId'],raw['teamOur']['type'])
        service.sessions[key] = Session(memory=memory)
        spawns = []
        for number,held in ((38,3),(39,2),(40,1)):
            raw.update(roundNo=number,lastRoundRoleActionResults={'501':True} if number>38 else {})
            actor(raw,501)['backpack'] = ['stone']+['WallFixer']*5+[ORDER]*held
            reveal(raw,truth)
            response = service.decide(copy.deepcopy(raw))
            command = response['roleCommandMap']['501']
            self.assertEqual(command['action'],'use')
            spawns.append(Pos.load(command['targetPos'][0]))
        raw.update(roundNo=41,lastRoundRoleActionResults={'501':True})
        actor(raw,501)['backpack'] = ['stone']+['WallFixer']*5
        service.decide(copy.deepcopy(raw))
        state = service.sessions[key].memory.boss_raid
        self.assertEqual(state['deployed_count'],3)
        self.assertEqual(state['acquired_count'],3)
        self.assertEqual(len(set(spawns)),3)
        self.assertEqual(len(state['scouted_spawns']),3)

    def test_same_description_reacceptance_starts_a_new_controller_run(self):
        raw,_ = three_task_request(35)
        raw['phaseTask'] = 'identical task text'
        raw['lastRoundRoleActionResults'] = {'502':True}
        memory = GameMemory(last_round=34,task_description=raw['phaseTask'],task_started=1,
            task_accept_round=34,last_task_point=(1,6),last_commands={'502':{'action':'acceptTask'}})
        old = record_attempt(memory,1,1,(1,6),'自进化类2')
        finish_attempt(memory,old,4,succeeded=True)
        memory.task_agent.accept(Turn.load(raw).tasks[1])
        memory.task_agent.attempt_key = old
        memory.task_agent.observed_description = raw['phaseTask']
        memory.task_agent.self_evolve_started_round = 1
        memory.task_agent.self_evolve_task_desc = raw['phaseTask']
        service = TurnService(Settings(enable_news=False))
        key = (raw['teamOur']['teamId'],raw['teamOur']['type'])
        service.sessions[key] = Session(memory=memory)
        response = service.decide(copy.deepcopy(raw))
        current = service.sessions[key].memory
        self.assertEqual(current.task_agent.attempt_key,(1,34,1,6))
        self.assertEqual(current.task_agent.self_evolve_started_round,34)
        self.assertEqual(len(current.task_attempts),2)
        self.assertEqual(success_count(current),1)
        self.assertTrue(response['prompt'])

    def test_delayed_question_keeps_confirmed_third_point_and_reward_identity(self):
        raw,_ = three_task_request(36)
        raw['phaseTask'] = 'third question arrived after a waiting frame'
        memory = completed_memory()
        third = (1,34,1,6)
        memory.task_attempts[third].update(finished=False,succeeded=False)
        memory.task_agent.accept(Turn.load(raw).tasks[1])
        memory.task_agent.attempt_key = (1,4,1,7)
        memory.task_agent.self_evolve_started_round = 4
        memory.task_accept_round = 34
        memory.last_task_point = (1,6)
        memory.last_round = 35
        service = TurnService(Settings(enable_news=False))
        key = (raw['teamOur']['teamId'],raw['teamOur']['type'])
        service.sessions[key] = Session(memory=memory)
        reply = service.decide(copy.deepcopy(raw))
        active = service.sessions[key].memory
        self.assertTrue(reply['prompt'])
        self.assertEqual(active.task_agent.attempt_key,third)
        self.assertEqual(active.task_agent.accepted_task['task_position'],(1,6))
        self.assertEqual(active.task_agent.self_evolve_started_round,34)
        raw.update(roundNo=37,llmResp='{"action":"final_answer","answer":"third-result"}')
        reply = service.decide(copy.deepcopy(raw))
        self.assertEqual(reply['roleCommandMap']['502']['action'],'submitAnswer')
        raw.update(roundNo=38,phaseTask='',llmResp='',lastRoundRoleActionResults={'502':True})
        raw['teamOur']['totalScore'] = 10
        reply = service.decide(copy.deepcopy(raw))
        active = service.sessions[key].memory
        self.assertEqual(success_count(active),3)
        self.assertEqual(finished_count(active),3)
        self.assertEqual(reply['roleCommandMap']['501'],dict(action='buy',name=ORDER,num=3))
        self.assertNotEqual(reply['roleCommandMap'].get('502',{}).get('name'),ORDER)


if __name__=='__main__':
    unittest.main()
