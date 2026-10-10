"""Observed-inventory accounting for at most two first-night BOSS deployments."""
import copy
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Pos, Turn
from app.config import Settings
from app.service.llm_service import LLMService
from app.service.memory import GameMemory
from app.service.task_service import TaskService
from app.service.turn_service import Session, TurnService
from tests.test_summon_control import ORDER, finished_tasks, raid_request
from tests.test_worker_safety import strategy


PIONEER_ID = 502


def pioneer(raw):
    return next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'pioneer')


def memory_for(raw, attempted=True):
    memory = finished_tasks() if attempted else GameMemory(opening_complete=True)
    memory.last_round = raw['roundNo']-1
    memory.day = 1
    return memory


def policy_step(raw, memory, settings=None):
    turn = Turn.load(raw)
    memory.observe(turn)
    # Isolate the deployment ledger from the separately tested first-night budget.
    plan = ActionPlan(turn, settings or Settings(enable_first_night_defense=False), memory.summon_attempts, memory.pending_summon_positions)
    s = Strategy(turn, plan, memory)
    actor = next(iter(s.turn.alive(('pioneer',))), None)
    if actor:
        s.boss_raid.pioneer(actor)
    memory.record(s.turn, plan)
    return s, plan


def next_frame(raw, result=None, held=None, gold=None, jump=1):
    raw['roundNo'] += jump
    raw['lastRoundRoleActionResults'] = {} if result is None else {str(PIONEER_ID): result}
    if held is not None:
        pioneer(raw)['backpack'] = [ORDER]*held
    if gold is not None:
        raw['teamOur']['goldNum'] = gold


class DualBossTests(unittest.TestCase):
    def command(self, plan):
        return plan.commands.get(str(PIONEER_ID), {})

    def test_wealth_buys_two_in_one_transaction_before_task_attempts(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 240
        memory = memory_for(raw, attempted=False)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan), {'action': 'buy', 'name': ORDER, 'num': 2})
        self.assertEqual(plan.gold, 0)
        self.assertEqual(memory.task_points_attempted, set())
        self.assertEqual(memory.boss_raid['target_count'], 2)
        self.assertEqual(memory.boss_raid['acquired_count'], 0)

    def test_actual_price_and_unbuilt_weapon_reserve_control_dual_threshold(self):
        for gold, price, guns, expected in ((260, 130, 3, 2), (259, 130, 3, 1), (129,130,3,None),
                                          (315, 120, 0, 2), (314, 120, 0, 1), (194,120,0,None)):
            with self.subTest(gold=gold, price=price, guns=guns):
                raw = raid_request(); raw['teamOur']['goldNum'] = gold
                raw['weaponShopList'][-1]['price'] = price
                if guns == 0:
                    raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['roleType'] != 'rocket']
                s, plan = policy_step(raw, memory_for(raw, attempted=False))
                self.assertEqual(self.command(plan).get('num'), expected)
                if expected:
                    self.assertEqual(plan.gold, gold-expected*price)
                    self.assertGreaterEqual(plan.gold, (3-guns)*25)

    def test_active_task_is_never_interrupted_even_with_two_order_budget(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 500; raw['phaseTask'] = 'active task'
        memory = memory_for(raw)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan), {})
        self.assertEqual(s.boss_raid.budget_reserve(), 240)

    def test_two_attempts_without_two_successes_keep_single_order_fallback(self):
        raw = raid_request(); memory = memory_for(raw)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan), {'action':'buy', 'name':ORDER, 'num':1})
        self.assertFalse(s.boss_raid.tasks_succeeded())
        raw = raid_request(); memory = memory_for(raw, attempted=False)
        memory.task_points_attempted = {(1, 3, 9)}
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan), {'action':'buy','name':ORDER,'num':1})

    def test_confirmed_two_successes_enable_preparation_without_overbuying(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 50
        memory = memory_for(raw, attempted=False)
        memory.task_points_succeeded = {(1, 3, 9), (1, 4, 9)}
        s, plan = policy_step(raw, memory)
        self.assertTrue(s.boss_raid.tasks_succeeded())
        self.assertEqual(memory.boss_raid['target_count'], 2)
        self.assertIn(PIONEER_ID, plan.used)
        self.assertNotIn(str(PIONEER_ID), plan.commands)
        self.assertEqual(s.boss_raid.budget_reserve(), 240)

    def test_batch_buy_is_confirmed_then_used_on_two_consecutive_distinct_rounds(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 240
        memory = memory_for(raw)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['num'], 2)
        next_frame(raw, True, held=2, gold=0)
        s, plan = policy_step(raw, memory)
        first = Pos.load(self.command(plan)['targetPos'][0])
        self.assertEqual(self.command(plan)['action'], 'use')
        self.assertEqual(memory.boss_raid['acquired_count'], 2)
        self.assertEqual(memory.boss_raid['deployed_count'], 0)
        self.assertIn(first, memory.pending_summon_positions)
        next_frame(raw, True, held=1)
        s, plan = policy_step(raw, memory)
        second = Pos.load(self.command(plan)['targetPos'][0])
        self.assertEqual(self.command(plan)['action'], 'use')
        self.assertNotEqual(first, second)
        self.assertEqual(memory.boss_raid['deployed_count'], 1)
        self.assertEqual(len(plan.commands), 1)
        self.assertEqual(memory.pending_summon_positions, {first, second})
        next_frame(raw, True, held=0)
        s, plan = policy_step(raw, memory)
        self.assertEqual(memory.boss_raid['deployed_count'], 2)
        self.assertEqual(memory.boss_raid['spawns'], [first, second])
        self.assertEqual(memory.boss_raid['status'], 'deployed')
        self.assertEqual(self.command(plan)['action'], 'move')

    def test_one_carried_order_can_be_topped_up_once_before_deployment(self):
        raw = raid_request(); pioneer(raw)['backpack'] = [ORDER]
        memory = memory_for(raw, attempted=False)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan), {'action':'buy', 'name':ORDER, 'num':1})
        next_frame(raw, True, held=2, gold=0)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['action'], 'use')
        self.assertEqual(memory.boss_raid['acquired_count'], 2)
        self.assertEqual(memory.boss_raid['bought_count'], 1)

    def test_two_carried_orders_do_not_need_task_completion_or_another_purchase(self):
        raw = raid_request(); pioneer(raw)['backpack'] = [ORDER]*2
        raw['teamOur']['goldNum'] = 0
        memory = memory_for(raw, attempted=False)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['action'], 'use')
        next_frame(raw, True, held=1)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['action'], 'use')
        self.assertEqual(memory.boss_raid['target_count'], 2)

    def test_late_purchase_downgrades_to_one_and_never_returns_for_a_top_up(self):
        raw = raid_request(64); raw['teamOur']['goldNum'] = 240
        memory = memory_for(raw)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan), {'action':'buy', 'name':ORDER, 'num':1})
        self.assertEqual(memory.boss_raid['target_count'], 1)
        next_frame(raw, True, held=1, gold=120)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['action'], 'use')
        next_frame(raw, True, held=0, gold=500)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['action'], 'move')
        self.assertEqual(memory.boss_raid['deployed_count'], 1)
        self.assertEqual(memory.boss_raid['target_count'], 1)

    def test_return_budget_counts_both_uses_and_does_not_buy_too_late(self):
        for number, quantity in ((63, 2), (64, 1), (65, None), (70, None)):
            with self.subTest(number=number):
                raw = raid_request(number); raw['teamOur']['goldNum'] = 240
                s, plan = policy_step(raw, memory_for(raw))
                self.assertEqual(self.command(plan).get('num'), quantity)

    def test_confirmed_single_deployment_can_make_one_affordable_later_top_up(self):
        raw = raid_request(); memory = memory_for(raw)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['num'], 1)
        next_frame(raw, True, held=1, gold=0)
        s, plan = policy_step(raw, memory)
        first = Pos.load(self.command(plan)['targetPos'][0])
        next_frame(raw, True, held=0)
        s, plan = policy_step(raw, memory)
        pioneer(raw)['pos'] = self.command(plan)['targetPos'][0]
        self.assertEqual(memory.boss_raid['deployed_count'], 1)
        next_frame(raw, True, held=0, gold=120)
        memory.task_points_succeeded = {(1, 3, 9), (1, 4, 9)}
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['action'], 'move')
        pioneer(raw)['pos'] = self.command(plan)['targetPos'][0]
        next_frame(raw, True)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan), {'action':'buy', 'name':ORDER, 'num':1})
        next_frame(raw, True, held=1, gold=0)
        s, plan = policy_step(raw, memory)
        self.assertEqual(self.command(plan)['action'], 'use')
        second = Pos.load(self.command(plan)['targetPos'][0])
        self.assertNotEqual(first, second)
        next_frame(raw, True, held=0)
        s, plan = policy_step(raw, memory)
        self.assertEqual(memory.boss_raid['acquired_count'], 2)
        self.assertEqual(memory.boss_raid['deployed_count'], 2)
        self.assertEqual(memory.boss_raid['bought_count'], 2)
        self.assertEqual(memory.boss_raid['spawns'], [first, second])
        next_frame(raw, True, held=0, gold=500)
        s, plan = policy_step(raw, memory)
        self.assertNotIn(self.command(plan).get('action'), ('buy', 'use'))

    def test_legacy_deployed_marker_does_not_authorize_unknown_extra_purchase(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 500
        memory = memory_for(raw)
        memory.boss_raid = {'status':'deployed', 'order_acquired':True, 'spawn':Pos(37,25)}
        s, plan = policy_step(raw, memory)
        self.assertFalse(memory.boss_raid['deployment_ledger_confirmed'])
        self.assertNotIn(self.command(plan).get('action'), ('buy', 'use'))

    def test_failed_purchase_retries_but_success_without_inventory_does_not(self):
        for feedback, retries in ((False, True), (True, False), (None, False)):
            with self.subTest(feedback=feedback):
                raw = raid_request(); raw['teamOur']['goldNum'] = 240
                memory = memory_for(raw)
                policy_step(raw, memory)
                next_frame(raw, feedback, held=0)
                s, plan = policy_step(raw, memory)
                self.assertEqual(self.command(plan).get('action') == 'buy', retries)
                if not retries:
                    self.assertTrue(memory.boss_raid['purchase_closed'])
                    next_frame(raw, True, held=0, gold=500)
                    s, plan = policy_step(raw, memory)
                    self.assertNotEqual(self.command(plan).get('action'), 'buy')

    def test_partial_batch_inventory_deploys_only_observed_order_without_rebuy(self):
        for feedback in (True, False, None):
            with self.subTest(feedback=feedback):
                raw = raid_request(); raw['teamOur']['goldNum'] = 240
                memory = memory_for(raw)
                policy_step(raw, memory)
                next_frame(raw, feedback, held=1, gold=120)
                s, plan = policy_step(raw, memory)
                self.assertEqual(self.command(plan)['action'], 'use')
                self.assertEqual(memory.boss_raid['acquired_count'], 1)
                self.assertTrue(memory.boss_raid['purchase_closed'])
                next_frame(raw, True, held=0, gold=500)
                s, plan = policy_step(raw, memory)
                self.assertEqual(memory.boss_raid['deployed_count'], 1)
                self.assertNotIn(self.command(plan).get('action'), ('buy', 'use'))

    def test_both_failed_deployments_retry_other_cells_and_rollback_once(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 0; pioneer(raw)['backpack'] = [ORDER]*2
        memory = memory_for(raw)
        s, plan = policy_step(raw, memory)
        failed_first = Pos.load(self.command(plan)['targetPos'][0])
        next_frame(raw, False, held=2)
        s, plan = policy_step(raw, memory)
        first = Pos.load(self.command(plan)['targetPos'][0])
        self.assertNotEqual(first, failed_first)
        self.assertNotIn(failed_first, memory.pending_summon_positions)
        self.assertEqual(memory.summon_attempts, 1)
        next_frame(raw, True, held=1)
        s, plan = policy_step(raw, memory)
        failed_second = Pos.load(self.command(plan)['targetPos'][0])
        self.assertNotEqual(first, failed_second)
        next_frame(raw, False, held=1)
        s, plan = policy_step(raw, memory)
        second = Pos.load(self.command(plan)['targetPos'][0])
        self.assertNotIn(second, (first, failed_first, failed_second))
        self.assertNotIn(failed_second, memory.pending_summon_positions)
        self.assertEqual(memory.summon_attempts, 2)
        next_frame(raw, True, held=0)
        s, plan = policy_step(raw, memory)
        self.assertEqual(memory.boss_raid['spawns'], [first, second])
        self.assertEqual(memory.boss_raid['deployed_count'], 2)
        self.assertEqual(memory.summon_attempts, 2)

    def test_missing_use_feedback_waits_for_inventory_without_duplicate_use(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 0; pioneer(raw)['backpack'] = [ORDER]*2
        memory = memory_for(raw)
        s, plan = policy_step(raw, memory)
        first = Pos.load(self.command(plan)['targetPos'][0])
        next_frame(raw, None, held=2)
        s, plan = policy_step(raw, memory)
        self.assertNotEqual(self.command(plan).get('action'), 'use')
        self.assertEqual(memory.boss_raid['deployed_count'], 0)
        self.assertIn('pending_use', memory.boss_raid)
        next_frame(raw, None, held=1)
        s, plan = policy_step(raw, memory)
        self.assertEqual(memory.boss_raid['deployed_count'], 1)
        self.assertEqual(self.command(plan)['action'], 'use')
        self.assertNotEqual(self.command(plan)['targetPos'], [first.dump()])

    def test_nonconsecutive_feedback_is_not_attributed_to_old_use(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 0; pioneer(raw)['backpack'] = [ORDER]*2
        memory = memory_for(raw)
        policy_step(raw, memory)
        next_frame(raw, False, held=1, jump=2)
        s, plan = policy_step(raw, memory)
        self.assertEqual(memory.boss_raid['deployed_count'], 1)
        self.assertEqual(self.command(plan)['action'], 'use')
        self.assertFalse(memory.boss_raid.get('failed_positions'))

    def test_daily_limit_ten_caps_buy_and_use_before_deployment(self):
        for used, quantity in ((8, 2), (9, 1), (10, None)):
            with self.subTest(used=used):
                raw = raid_request(); raw['teamOur']['goldNum'] = 240
                memory = memory_for(raw); memory.summon_attempts = used
                s, plan = policy_step(raw, memory)
                self.assertEqual(self.command(plan).get('num'), quantity)
                self.assertLessEqual(plan.summon_used, 10)

    def test_two_order_budget_survives_shop_movement_and_worker_upgrade_attempts(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 240
        pioneer(raw)['pos'] = {'x': 4, 'y': 7}
        worker = next(u for u in raw['teamOur']['roles'] if u['id'] == 501)
        worker['pos'] = {'x': 3, 'y': 7}
        memory = memory_for(raw)
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(self.command(plan)['action'], 'move')
        self.assertEqual(s.boss_raid.budget_reserve(), 240)
        self.assertFalse(any(c['action'] == 'buy' for c in plan.commands.values()))
        self.assertEqual(plan.gold, 240)

    def test_coupon_disappearing_without_use_never_starts_infinite_repurchases(self):
        raw = raid_request(); pioneer(raw)['backpack'] = [ORDER]; raw['phaseTask'] = 'active'
        memory = memory_for(raw)
        policy_step(raw, memory)
        next_frame(raw, None, held=0, gold=500)
        policy_step(raw, memory)
        raw['phaseTask'] = ''
        for number in (32, 33, 34):
            raw['roundNo'] = number
            s, plan = policy_step(raw, memory)
            self.assertNotEqual(self.command(plan).get('action'), 'buy')
            self.assertTrue(memory.boss_raid['purchase_closed'])
            self.assertEqual(memory.boss_raid['acquired_count'], 1)

    def test_dead_pioneer_bag_is_observed_but_never_gets_an_action(self):
        raw = raid_request(); pioneer(raw)['health'] = 0; pioneer(raw)['backpack'] = [ORDER]*2
        memory = memory_for(raw)
        s, plan = policy_step(raw, memory)
        self.assertEqual(memory.boss_raid['acquired_count'], 2)
        self.assertNotIn(str(PIONEER_ID), plan.commands)
        raw['roundNo'] = 131; pioneer(raw)['health'] = 200
        s, plan = policy_step(raw, memory)
        self.assertNotIn(self.command(plan).get('action'), ('buy', 'use'))

    def test_unknown_midday_restart_does_not_rebuy_but_carried_orders_can_deploy(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 500
        s, plan = policy_step(raw, GameMemory(opening_complete=True))
        self.assertNotEqual(self.command(plan).get('action'), 'buy')
        self.assertTrue(s.memory.boss_raid['purchase_closed'])
        raw = raid_request(); pioneer(raw)['backpack'] = [ORDER]*2; raw['teamOur']['goldNum'] = 0
        s, plan = policy_step(raw, GameMemory(opening_complete=True))
        self.assertEqual(self.command(plan)['action'], 'use')
        raw = raid_request(); pioneer(raw)['backpack'] = [ORDER]; raw['teamOur']['goldNum'] = 500
        s, plan = policy_step(raw, GameMemory(opening_complete=True))
        self.assertEqual(self.command(plan)['action'], 'use')
        self.assertTrue(s.memory.boss_raid['purchase_closed'])
        self.assertEqual(s.memory.boss_raid['target_count'], 1)

    def test_service_cache_does_not_count_pending_feedback_twice(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 240
        service = TurnService(Settings(enable_news=False,enable_first_night_defense=False))
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        service.sessions[key] = Session(memory=memory_for(raw))
        response = service.decide(copy.deepcopy(raw))
        self.assertEqual(response['roleCommandMap'][str(PIONEER_ID)]['num'], 2)
        next_frame(raw, True, held=2, gold=0)
        response = service.decide(copy.deepcopy(raw))
        before = copy.deepcopy(service.sessions[key].memory)
        replay = service.decide(copy.deepcopy(raw))
        self.assertEqual(response, replay)
        self.assertEqual(before, service.sessions[key].memory)
        self.assertEqual(before.boss_raid['deployed_count'], 0)

    def test_task_success_record_needs_submission_reward_and_no_judger_rejection(self):
        for mode, expected in (('reward', True), ('gold_only', True), ('no_reward', False),
                ('wrong', False), ('timeout', False), ('missing_feedback', False),
                ('phase_only', False), ('other_sale', False)):
            with self.subTest(mode=mode):
                raw = raid_request(); raw['teamOur']['goldNum'] = 100; raw['teamOur']['totalScore'] = 10
                memory = memory_for(raw)
                agent = memory.task_agent
                agent.self_evolve_active = True
                agent.self_evolve_last_action = 'submitAnswer'
                agent.self_evolve_task_desc = 'synthetic task'
                agent.self_evolve_first_question = 'synthetic task'
                agent.observed_description = 'synthetic task'
                agent.accepted_task = {'task_position':(3,9), 'task_type':'selfEvolve',
                                       'timeout_rounds':12, 'is_valid':True}
                agent._submit_baseline = (100, 10)
                memory.last_commands = {str(PIONEER_ID): {'action':'submitAnswer', 'taskAnswer':'answer'}}
                raw['lastRoundRoleActionResults'] = {str(PIONEER_ID): True}
                if mode == 'reward': raw['teamOur']['totalScore'] = 20
                if mode in ('gold_only', 'other_sale'): raw['teamOur']['goldNum'] = 150
                if mode in ('wrong', 'timeout'):
                    raw['teamOur']['totalScore'] = 20
                    raw['errors'] = [{'errorCode':2 if mode=='wrong' else 1}]
                if mode == 'missing_feedback':
                    raw['teamOur']['totalScore'] = 20; raw['lastRoundRoleActionResults'] = {}
                if mode == 'phase_only':
                    memory.last_commands = {}; raw['teamOur']['totalScore'] = 20
                if mode == 'other_sale':
                    memory.last_commands['501'] = {'action':'sell', 'name':'iron', 'num':1}
                s, plan = strategy(raw, memory)
                TaskService().active(s.turn, memory, plan, LLMService(), '')
                self.assertEqual((1,3,9) in memory.task_points_succeeded, expected)
                self.assertNotIn((1,4,9), memory.task_points_succeeded)

    def test_two_rewarded_task_points_are_recorded_distinctly_and_enable_two(self):
        raw = raid_request(); raw['teamOur']['goldNum'] = 100; raw['teamOur']['totalScore'] = 10
        memory = memory_for(raw, attempted=False)
        for point in ((3,9), (4,9)):
            agent = memory.task_agent
            agent.self_evolve_active = True
            agent.self_evolve_last_action = 'submitAnswer'
            agent.self_evolve_task_desc = 'synthetic task'
            agent.self_evolve_first_question = 'synthetic task'
            agent.observed_description = 'synthetic task'
            agent.accepted_task = {'task_position':point, 'task_type':'selfEvolve',
                                   'timeout_rounds':12, 'is_valid':True}
            agent._submit_baseline = (raw['teamOur']['goldNum'], raw['teamOur']['totalScore'])
            memory.last_round = raw['roundNo']-1
            memory.last_commands = {str(PIONEER_ID): {'action':'submitAnswer', 'taskAnswer':'answer'}}
            raw['lastRoundRoleActionResults'] = {str(PIONEER_ID): True}
            raw['teamOur']['goldNum'] += 100; raw['teamOur']['totalScore'] += 10
            s, plan = strategy(raw, memory)
            TaskService().active(s.turn, memory, plan, LLMService(), '')
            raw['roundNo'] += 1
        self.assertEqual(memory.task_points_succeeded, {(1,3,9), (1,4,9)})
        s, plan = policy_step(raw, memory)
        self.assertTrue(s.boss_raid.tasks_succeeded())
        self.assertEqual(self.command(plan), {'action':'buy', 'name':ORDER, 'num':2})


if __name__ == '__main__':
    unittest.main()
