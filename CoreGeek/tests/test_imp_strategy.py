"""Round-of-32 imp commands, continuous destruction and observed respawns."""
import copy
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn, distance
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import TurnService
from tests.fixtures import request, unit, robot


def imp_request(number=1, lower_base=False):
    raw = request(number)
    raw['teamOur']['playerTasks'] = []
    base, imp, enemy, friendly = ((30,7),(8,20),(9,20),(30,6)) if lower_base else (
        (10,24),(20,7),(21,7),(7,22))
    raw['teamOur']['roles'] = [unit(503,'station',*base),
                               unit(905,'imp',*imp,health=500,level=0)]
    raw['mapInfo']['zones'] = [{'neutralType':'iron','pos':Pos(*enemy).dump()},
                              {'neutralType':'stone','pos':Pos(*friendly).dump()}]
    return raw


def strategy(raw, memory=None):
    turn = Turn.load(raw)
    # Isolate the unchanged mineral policy from the day-one BOSS sight mission.
    plan = ActionPlan(turn, Settings(enable_news=False, enable_boss_raid=False))
    return Strategy(turn, plan, memory or GameMemory()), plan


class ImpStrategyTests(unittest.TestCase):
    def test_imp_destroys_the_opposite_diagonal_half_in_either_team(self):
        for lower in (False, True):
            for team in ('challenger','defender'):
                raw = imp_request(lower_base=lower)
                raw['teamOur']['type'] = team
                s, plan = strategy(raw); s.run()
                self.assertEqual(plan.commands['905'], {'action':'destroy',
                    'targetPos':[{'x':9,'y':20} if lower else {'x':21,'y':7}]})
                self.assertEqual(plan.rejections, [])

    def test_own_adjacent_mine_is_skipped_for_an_enemy_mine(self):
        raw = imp_request()
        raw['teamOur']['roles'][1]['pos'] = {'x':15,'y':14}
        raw['mapInfo']['zones'][1]['pos'] = {'x':16,'y':14}
        s, plan = strategy(raw); s.run()
        self.assertEqual(plan.commands['905']['action'], 'move')
        self.assertGreater(distance(Pos.load(plan.commands['905']['targetPos'][0]), Pos(16,14)), 0)
        self.assertEqual(s.memory.imp_tasks[905]['target'], Pos(21,7))

    def test_four_continuous_destroys_cross_dusk_without_retargeting(self):
        raw = imp_request(70)
        memory = GameMemory()
        for number in range(70, 74):
            raw['roundNo'] = number
            raw['lastRoundRoleActionResults'] = {'905':True}
            if number == 71:
                raw['mapInfo']['zones'].append({'neutralType':'copper','pos':{'x':20,'y':6}})
            s, plan = strategy(raw, memory); s.run()
            self.assertEqual(plan.commands['905'], {'action':'destroy','targetPos':[{'x':21,'y':7}]})
            memory.record(s.turn, plan)
        raw['roundNo'] = 74
        raw['mapInfo']['zones'] = [z for z in raw['mapInfo']['zones'] if z['pos'] != {'x':21,'y':7}]
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['905'], {'action':'destroy','targetPos':[{'x':20,'y':6}]})

    def test_imp_ignores_robot_threat_and_low_health_at_night(self):
        raw = imp_request(71)
        raw['teamOur']['roles'][1]['health'] = 1
        raw['robot']['roles'] = [robot(990,20,8,health=500)]
        s, plan = strategy(raw); s.run()
        self.assertGreater(s.danger.get(Pos(20,7),0), 0)
        self.assertEqual(plan.commands['905']['action'], 'destroy')

    def test_night_walk_crosses_threat_range_but_not_a_robot_cell(self):
        for robot_pos in ((22,9),(21,6)):
            raw = imp_request(71)
            raw['mapInfo']['zones'][0]['pos'] = {'x':25,'y':7}
            raw['robot']['roles'] = [robot(990,*robot_pos,health=500)]
            s, plan = strategy(raw); s.run()
            self.assertEqual(plan.commands['905']['action'], 'move')
            step = Pos.load(plan.commands['905']['targetPos'][0])
            self.assertNotEqual(step, Pos(*robot_pos))
            self.assertLess(distance(step,Pos(25,7)),distance(Pos(20,7),Pos(25,7)))
            self.assertGreater(s.danger.get(step,0),0)
            self.assertEqual(plan.rejections, [])

    def test_death_clears_the_job_and_next_day_first_turn_acts(self):
        raw = imp_request(129)
        memory = GameMemory()
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] = 130
        raw['teamOur']['roles'][1].update(health=0,pos={'x':-1,'y':-1})
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        self.assertNotIn('905', plan.commands)
        self.assertNotIn(905, memory.imp_tasks)
        raw['roundNo'] = 131
        raw['teamOur']['roles'][1].update(health=500,pos={'x':9,'y':24})
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['905']['action'], 'move')
        self.assertEqual(plan.rejections, [])

    def test_disappeared_mine_is_replaced_during_the_walk(self):
        raw = imp_request()
        raw['mapInfo']['zones'][0]['pos'] = {'x':25,'y':7}
        memory = GameMemory()
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['teamOur']['roles'][1]['pos'] = plan.commands['905']['targetPos'][0]
        raw['roundNo'] = 2
        raw['mapInfo']['zones'][0]['pos'] = {'x':21,'y':8}
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(memory.imp_tasks[905]['target'], Pos(21,8))
        self.assertIn(plan.commands['905']['action'], ('move','destroy'))

    def test_teleported_respawn_replans_without_a_death_observation(self):
        raw = imp_request(130)
        memory = GameMemory()
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] = 131
        raw['teamOur']['roles'][1]['pos'] = {'x':9,'y':24}
        raw['mapInfo']['zones'].append({'neutralType':'copper','pos':{'x':17,'y':10}})
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(memory.imp_tasks[905]['target'], Pos(17,10))
        self.assertEqual(plan.commands['905']['action'], 'move')

    def test_base_missing_from_observation_keeps_the_known_enemy_half(self):
        raw = imp_request(1)
        memory = GameMemory()
        s, plan = strategy(raw, memory); s.run(); memory.record(s.turn, plan)
        raw['roundNo'] = 2
        raw['teamOur']['roles'] = [raw['teamOur']['roles'][1]]
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['905'], {'action':'destroy','targetPos':[{'x':21,'y':7}]})

    def test_target_does_not_expire_locally_after_four_failed_attempts(self):
        raw = imp_request(71)
        memory = GameMemory()
        for number in range(71,77):
            raw.update(roundNo=number,lastRoundRoleActionResults={'905':False})
            s, plan = strategy(raw, memory); s.run()
            self.assertEqual(plan.commands['905']['action'], 'destroy')
            memory.record(s.turn, plan)

    def test_no_enemy_mine_never_destroys_a_friendly_or_boundary_mine(self):
        raw = imp_request()
        raw['mapInfo']['zones'] = [{'neutralType':'stone','pos':{'x':7,'y':22}},
                                  {'neutralType':'iron','pos':{'x':40,'y':31}}]
        s, plan = strategy(raw); s.run()
        self.assertNotIn('905',plan.commands)

    def test_destroy_gate_checks_role_single_target_range_and_mineral(self):
        command = {'action':'destroy','targetPos':[{'x':21,'y':7}]}
        for number in (1,71):
            s, plan = strategy(imp_request(number))
            self.assertTrue(plan.add(905,command), plan.rejections)
            self.assertFalse(plan.add(905,command))
        for actor, target in ((503,Pos(21,7)), (905,Pos(25,7)), (905,Pos(19,7))):
            s, plan = strategy(imp_request())
            self.assertFalse(plan.add(actor, {'action':'destroy','targetPos':[target.dump()]}))
        for points in ([], [{'x':21,'y':7},{'x':20,'y':6}]):
            s, plan = strategy(imp_request())
            self.assertFalse(plan.add(905, {'action':'destroy','targetPos':points}))
        for uid, kind in ((501,'worker'),(502,'pioneer')):
            raw = imp_request()
            raw['teamOur']['roles'].append(unit(uid,kind,20,6))
            s, plan = strategy(raw)
            self.assertFalse(plan.add(uid, command))

    def test_task_prompt_does_not_pause_the_imp(self):
        raw = imp_request()
        raw['phaseTask'] = 'Read task_fixture.md'
        raw['teamOur']['roles'].append(unit(502,'pioneer',14,13))
        result = TurnService(Settings(enable_news=False, enable_boss_raid=False)).decide(raw)
        self.assertTrue(result['prompt'])
        self.assertEqual(result['roleCommandMap']['905']['action'], 'destroy')

    def test_service_keeps_imps_separate_and_logs_their_commands(self):
        service = TurnService(Settings(enable_news=False, enable_boss_raid=False))
        raw = imp_request()
        first_team = raw['teamOur']['teamId']
        with self.assertLogs('app.service.turn_service',level='INFO') as logged:
            result = service.decide(copy.deepcopy(raw))
        self.assertEqual(result['roleCommandMap']['905']['action'], 'destroy')
        self.assertTrue(any('imp_motion' in line for line in logged.output))
        raw.update(roundNo=2)
        service.decide(copy.deepcopy(raw))
        raw['teamOur']['teamId'] = 'other-team'
        raw['mapInfo']['zones'][0]['pos'] = {'x':20,'y':6}
        result = service.decide(copy.deepcopy(raw))
        self.assertEqual(result['roleCommandMap']['905']['targetPos'], [{'x':20,'y':6}])
        raw['teamOur']['teamId'] = first_team
        raw['roundNo'] = 1
        raw['mapInfo']['zones'].append({'neutralType':'iron','pos':{'x':21,'y':7}})
        result = service.decide(copy.deepcopy(raw))
        self.assertEqual(result['roleCommandMap']['905']['targetPos'], [{'x':20,'y':6}])


if __name__ == '__main__':
    unittest.main()
