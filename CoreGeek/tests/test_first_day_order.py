"""Three task attempts precede success-count BOSS purchases and weapon shopping."""
import copy
import unittest
from unittest.mock import patch
from agent.protocol import Pos
from agent.first_day_tasks import record_attempt, finish_attempt
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import Session,TurnService
from tests.fixtures import request
from tests.test_gap_defense import role
from tests.test_summon_control import ORDER,finished_tasks,provide_scout,raid_request
from tests.test_worker_safety import strategy


def task_memory(successes=1,attempts=3,number=30):
    memory = finished_tasks(successes, attempts)
    memory.day, memory.last_round = 1, number-1
    return memory


def day_strategy(successes=1,attempts=3,gold=1000,number=30):
    raw = raid_request(number)
    raw['teamOur']['goldNum'] = gold
    raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:1]
    role(raw,501).update(pos=Pos(2,8).dump(),backpack=['WallFixer']*5+['stone'])
    memory = task_memory(successes,attempts,number)
    s,plan = strategy(raw,memory,Settings(enable_news=False))
    return raw,memory,s,plan


class FirstDayOrderTests(unittest.TestCase):
    def test_rich_buyer_cannot_buy_before_three_attempts(self):
        for attempts in (0,1,2):
            raw,memory,s,plan = day_strategy(successes=attempts,attempts=attempts)
            buyer = next(w for w in s.turn.workers() if w.unit_id==501)
            s.boss_raid.worker(buyer)
            self.assertIsNone(s.boss_raid.target_orders())
            self.assertNotIn('order_decision_round',memory.boss_raid)
            self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))

    def test_active_third_task_blocks_purchase_even_after_three_accepts(self):
        raw,memory,_,_ = day_strategy()
        raw['phaseTask'] = 'unfinished third task'
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        self.assertIsNone(s.boss_raid.target_orders())
        self.assertFalse(s.boss_raid.weapon_upgrades_ready())

    def test_third_accept_without_task_start_does_not_count_as_finished(self):
        raw,memory,_,_ = day_strategy(1,attempts=2)
        record_attempt(memory,1,34,(4,9),'自进化类2',origin='isolated_fixture')
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        self.assertIsNone(s.boss_raid.target_orders())
        self.assertFalse(s.boss_raid.weapon_upgrades_ready())
        self.assertNotIn('order_decision_round',memory.boss_raid)

    def test_zero_one_two_three_successes_define_purchase_quantity(self):
        for successes in (0,1,2,3):
            with self.subTest(successes=successes):
                raw,memory,s,plan = day_strategy(successes)
                buyer = next(w for w in s.turn.workers() if w.unit_id==501)
                s.boss_raid.worker(buyer)
                self.assertEqual(memory.boss_raid['target_count'],successes)
                if successes:
                    self.assertEqual(plan.commands['501'],{'action':'buy','name':ORDER,'num':successes})
                else:
                    self.assertNotEqual(plan.commands.get('501',{}).get('name'),ORDER)
                    self.assertTrue(s.boss_raid.weapon_upgrades_ready())

    def test_one_success_never_becomes_two_due_to_wealth(self):
        raw,memory,s,plan = day_strategy(1,gold=10000)
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        self.assertEqual(plan.commands['501']['num'],1)
        self.assertEqual(memory.boss_raid['target_count'],1)

    def test_failure_record_does_not_count_as_success(self):
        _,_,s,plan = day_strategy(0)
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))
        self.assertEqual(s.boss_raid.budget_reserve(),0)

    def test_task_successes_from_previous_days_do_not_inflate_quota(self):
        raw,memory,_,_ = day_strategy(1)
        for day in (2,3):
            key = record_attempt(memory,day,(day-1)*130+3,(3,9),'自进化类1')
            finish_attempt(memory,key,(day-1)*130+6,succeeded=True)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        self.assertEqual(plan.commands['501']['num'],1)

    def test_first_day_starts_with_accepting_a_task_despite_shop_budget(self):
        raw = request(1)
        raw['teamOur']['goldNum'] = 1000
        raw['weaponShopList'].append({'name':ORDER,'price':120})
        role(raw,502)['pos'] = Pos(17,16).dump()
        s,plan = strategy(raw,GameMemory(),Settings(enable_news=False));s.run()
        self.assertEqual(plan.commands['502'],{'action':'acceptTask'})
        self.assertFalse(any(c.get('name','').startswith('WeaponUpgradeVoucher') for c in plan.commands.values()))

    def test_second_task_precedes_treasure_and_shopping(self):
        raw = request(20)
        raw['teamOur']['goldNum'] = 1000
        raw['weaponShopList'].append({'name':ORDER,'price':120})
        first = raw['teamOur']['playerTasks'][1]['taskPosition']
        memory = GameMemory(opening_complete=True,last_round=19,day=1)
        key = record_attempt(memory,1,1,(first['x'],first['y']),'自进化类2')
        finish_attempt(memory,key,4,succeeded=True)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        with patch.object(s,'treasure',return_value=True) as treasure,patch.object(s,'task',wraps=s.task) as task:
            s.run()
            treasure.assert_not_called()
            self.assertTrue(task.called)
        self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))

    def test_both_weapon_purchase_paths_are_closed_before_boss_buy_attempt(self):
        raw,memory,s,plan = day_strategy(1,attempts=1)
        worker = next(w for w in s.turn.workers() if w.unit_id==501)
        self.assertFalse(s.buy_upgrade(worker))
        self.assertFalse(s.first_defense.supply(worker))
        self.assertNotIn('501',plan.commands)

    def test_buyer_does_not_shop_for_weapon_while_walking_to_boss_shop(self):
        raw,memory,_,_ = day_strategy(1)
        role(raw,502)['pos'] = Pos(4,7).dump()
        role(raw,501)['pos'] = Pos(4,8).dump()
        s,plan = strategy(raw,memory,Settings(enable_news=False));s.run()
        self.assertEqual(plan.commands['501']['action'],'move')
        self.assertFalse(s.boss_raid.weapon_upgrades_ready())
        self.assertFalse(any(c.get('name','').startswith('WeaponUpgradeVoucher') for c in plan.commands.values()))

    def test_buyer_buy_attempt_unlocks_weapon_stage_but_uses_its_single_action(self):
        raw,memory,s,plan = day_strategy(1)
        s.run()
        self.assertEqual(plan.commands['501'],{'action':'buy','name':ORDER,'num':1})
        self.assertEqual(memory.boss_raid['purchase_attempt_round'],raw['roundNo'])
        self.assertEqual(memory.boss_raid['buyer_id'],501)
        self.assertTrue(s.boss_raid.weapon_upgrades_ready())
        self.assertNotEqual(plan.commands.get('502',{}).get('name'),ORDER)

    def test_two_successes_with_one_order_budget_wait_for_two_instead_of_downgrading(self):
        _,memory,s,plan = day_strategy(2,gold=120)
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        self.assertEqual(memory.boss_raid['target_count'],2)
        self.assertFalse(any(c.get('action')=='buy' and c.get('name')==ORDER for c in plan.commands.values()))
        self.assertEqual(s.boss_raid.budget_reserve(),240)
        self.assertFalse(s.boss_raid.weapon_upgrades_ready())

    def test_task_phase_reserves_possible_three_orders_without_deciding(self):
        _,memory,s,_ = day_strategy(1,attempts=1)
        self.assertEqual(s.boss_raid.budget_reserve(),360)
        self.assertNotIn('target_count',memory.boss_raid)
        self.assertNotIn('order_decision_round',memory.boss_raid)

    def test_frozen_quota_does_not_change_after_later_score_or_gold_updates(self):
        raw,memory,_,_ = day_strategy(1,gold=0)
        role(raw,502)['pos'] = Pos(4,7).dump()
        s,_ = strategy(raw,memory,Settings(enable_news=False))
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        for key in memory.task_attempts:
            finish_attempt(memory,key,31,succeeded=True)
        raw.update(roundNo=31)
        raw['teamOur']['goldNum'] = 1000
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        self.assertEqual(s.boss_raid.target_orders(),1)

    def test_no_success_releases_worker_weapon_supply_after_boss_skip(self):
        _,memory,s,plan = day_strategy(0)
        s.run()
        self.assertEqual(memory.boss_raid['status'],'no_successful_tasks')
        self.assertEqual(plan.commands['501']['name'],'WeaponUpgradeVoucher1')

    def test_second_day_and_disabled_boss_do_not_lock_weapon_upgrades(self):
        for number,enabled in ((131,True),(30,False)):
            raw = raid_request(number)
            s,_ = strategy(raw,GameMemory(),Settings(enable_boss_raid=enabled,enable_news=False))
            self.assertTrue(s.boss_raid.weapon_upgrades_ready())

    def test_first_night_does_not_relock_weapon_purchases_after_daytime_buy(self):
        raw,memory,s,_ = day_strategy(1)
        s.boss_raid.worker(next(w for w in s.turn.workers() if w.unit_id==501))
        raw['roundNo'] = 71
        s,_ = strategy(raw,memory,Settings(enable_news=False))
        self.assertTrue(s.boss_raid.weapon_upgrades_ready())
        self.assertFalse(s.boss_raid.day_available())

    def test_expired_daytime_window_releases_upgrades_without_inventing_task_success(self):
        raw = raid_request(71)
        memory = GameMemory(opening_complete=True)
        s,_ = strategy(raw,memory,Settings(enable_news=False))
        self.assertTrue(s.boss_raid.weapon_upgrades_ready())
        self.assertFalse(s.boss_raid.day_available())
        self.assertFalse(memory.task_points_succeeded)
        self.assertNotIn('order_decision_round',memory.boss_raid)

    def test_service_two_successes_buy_then_use_two_distinct_positions(self):
        raw,memory,_,_ = day_strategy(2,gold=240)
        provide_scout(raw,memory)
        service = TurnService(Settings(enable_news=False))
        key = (raw['teamOur']['teamId'],raw['teamOur']['type'])
        service.sessions[key] = Session(memory=memory)
        response = service.decide(copy.deepcopy(raw))
        self.assertEqual(response['roleCommandMap']['501'],{'action':'buy','name':ORDER,'num':2})
        raw.update(roundNo=31,lastRoundRoleActionResults={'501':True})
        raw['teamOur']['goldNum'] = 0
        role(raw,501)['backpack'] += [ORDER]*2
        response = service.decide(copy.deepcopy(raw))
        first = response['roleCommandMap']['501']['targetPos'][0]
        self.assertEqual(response['roleCommandMap']['501']['action'],'use')
        raw.update(roundNo=32,lastRoundRoleActionResults={'501':True})
        role(raw,501)['backpack'] = ['stone']+['WallFixer']*5+[ORDER]
        response = service.decide(copy.deepcopy(raw))
        second = response['roleCommandMap']['501']['targetPos'][0]
        self.assertEqual(response['roleCommandMap']['501']['action'],'use')
        self.assertNotEqual(first,second)
        raw.update(roundNo=33,lastRoundRoleActionResults={'501':True})
        role(raw,501)['backpack'] = ['stone']+['WallFixer']*5
        service.decide(copy.deepcopy(raw))
        self.assertEqual(service.sessions[key].memory.boss_raid['deployed_count'],2)
