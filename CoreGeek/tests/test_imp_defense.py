"""First-day capture and home defence using only current public observations.

Movement is checked against the original frame and the shared ActionPlan.
No test treats a planned catch as an already dead enemy or creates catch income.
"""
import copy
import unittest
from dataclasses import replace

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.first_day_tasks import finish_attempt, finished_count, record_attempt, TASK_SEQUENCE
from agent.imp_defense import ImpDefense
from agent.protocol import Pos, Turn, distance, move_command
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import Session, TurnService
from tests.fixtures import request, robot, unit
from tests.test_worker_boss_buyer import (
    BUYER, ORDER, PIONEER, SCOUT, actor, load_strategy, role, worker_raid_scene,
)


ENEMY_IMP = 905


def scene(round_no=40, finished=3, lower_right=False):
    raw = request(round_no)
    base = Pos(31, 8) if lower_right else Pos(10, 24)
    raw['teamOur']['roles'] = [
        unit(503, 'station', base.x, base.y, health=2000),
        unit(BUYER, 'worker', base.x - 5, base.y - 1, health=500),
        unit(PIONEER, 'pioneer', base.x - 5, base.y, health=500),
        unit(SCOUT, 'worker', 20, 16, health=500),
    ]
    raw['teamOur'].update(playerTasks=[], goldNum=0)
    raw['mapInfo']['zones'] = []
    raw['teamEnemy']['roles'] = []
    settings = Settings(enable_news=False, enable_first_night_defense=False)
    turn = Turn.load(raw)
    for uid, p in enumerate(settings.build_cells(turn, 'rocket'), 600):
        raw['teamOur']['roles'].append(unit(uid, 'rocket', p.x, p.y, health=1000))
    memory = GameMemory(opening_complete=True)
    memory.boss_raid.update(buyer_id=BUYER, order_decision_round=38,
        target_count=1, acquired_count=1, deployed_count=1, status='deployed',
        deployment_ledger_confirmed=True, purchase_stage_done=True)
    memory.raid_scouts.update(worker_id=SCOUT, home_worker_id=BUYER)
    for index in range(finished):
        point = (15, 14) if index != 1 else (13, 14)
        key = record_attempt(memory, 1, 1 + index * 10, point,
            '自进化类2' if index != 1 else '自进化类1')
        finish_attempt(memory, key, 4 + index * 10, succeeded=True)
    memory.task_active_attempt = None
    return raw, memory, settings


def add_imp(raw, pos=Pos(7, 24), health=500, uid=ENEMY_IMP):
    raw['teamEnemy']['roles'].append(unit(uid, 'imp', pos.x, pos.y, health=health))


def policy(raw, memory, settings):
    s, plan = load_strategy(raw, memory, settings)
    return s, plan, ImpDefense(s)


class ImpCaptureTests(unittest.TestCase):
    def test_pioneer_and_worker_capture_every_adjacent_direction_day_and_night(self):
        for number in (40, 71):
            for uid in (PIONEER, BUYER):
                for delta in Pos(0, 0).neighbours():
                    with self.subTest(round=number, actor=uid, direction=delta):
                        raw, memory, settings = scene(number)
                        source = Pos(16, 14)
                        actor(raw, uid)['pos'] = source.dump()
                        target = Pos(source.x + delta.x, source.y + delta.y)
                        add_imp(raw, target)
                        s, plan, defense = policy(raw, memory, settings)
                        self.assertTrue(defense.catch_near(role(s, uid)))
                        self.assertEqual(plan.commands[str(uid)],
                            dict(action='catch', targetPos=[target.dump()]))
                        self.assertEqual(plan.rejections, [])

    def test_diagonal_catch_ignores_the_two_side_walls(self):
        raw, memory, settings = scene(71)
        actor(raw, PIONEER)['pos'] = Pos(7, 24).dump()
        add_imp(raw, Pos(8, 25))
        raw['teamOur']['roles'] += [unit(800, 'wall', 8, 24), unit(801, 'wall', 7, 25)]
        s, plan, defense = policy(raw, memory, settings)
        self.assertTrue(defense.catch_near(role(s, PIONEER)))
        self.assertEqual(plan.commands[str(PIONEER)]['targetPos'], [Pos(8, 25).dump()])

    def test_action_gate_rejects_non_imp_friendly_dead_and_distant_targets(self):
        for kind, health, target, friendly in (
            ('worker', 500, Pos(6, 24), False),
            ('pioneer', 500, Pos(6, 24), False),
            ('imp', 0, Pos(6, 24), False),
            ('imp', 500, Pos(8, 24), False),
            ('imp', 500, Pos(6, 24), True),
        ):
            with self.subTest(kind=kind, health=health, target=target, friendly=friendly):
                raw, _, settings = scene()
                target_role = unit(ENEMY_IMP, kind, target.x, target.y, health=health)
                raw['teamOur' if friendly else 'teamEnemy']['roles'].append(target_role)
                plan = ActionPlan(Turn.load(raw), settings)
                self.assertFalse(plan.add(PIONEER,
                    dict(action='catch', targetPos=[target.dump()])))
                self.assertNotIn(str(PIONEER), plan.commands)

    def test_catch_requires_exactly_one_coordinate_and_no_extra_fields(self):
        for cmd in (
            dict(action='catch'), dict(action='catch', targetPos=[]),
            dict(action='catch', targetPos=Pos(6, 24).dump()),
            dict(action='catch', targetPos=[Pos(6, 24).dump(), Pos(6, 24).dump()]),
            dict(action='catch', targetPos=[Pos(6, 24).dump()], controllerId='501'),
        ):
            with self.subTest(command=cmd):
                raw, _, settings = scene()
                add_imp(raw, Pos(6, 24))
                plan = ActionPlan(Turn.load(raw), settings)
                self.assertFalse(plan.add(PIONEER, cmd))

    def test_action_gate_does_not_allow_dead_actor_or_tower_capture(self):
        for uid in (PIONEER, 600):
            raw, _, settings = scene()
            source = Pos.load(actor(raw, uid)['pos'])
            if uid == PIONEER:
                actor(raw, uid)['health'] = 0
            add_imp(raw, Pos(source.x - 1, source.y))
            plan = ActionPlan(Turn.load(raw), settings)
            self.assertFalse(plan.add(uid, dict(action='catch',
                targetPos=[Pos(source.x - 1, source.y).dump()])))

    def test_two_roles_do_not_capture_the_same_imp_and_remain_single_action(self):
        raw, memory, settings = scene()
        add_imp(raw, Pos(6, 24))
        s, plan, defense = policy(raw, memory, settings)
        self.assertTrue(defense.catch_near(role(s, PIONEER)))
        self.assertFalse(defense.catch_near(role(s, BUYER)))
        self.assertFalse(plan.add(PIONEER, move_command(Pos(4, 24))))
        self.assertTrue(plan.add(BUYER, move_command(Pos(4, 23))))
        self.assertEqual(sum(c['action'] == 'catch' for c in plan.commands.values()), 1)
        self.assertEqual(plan.commands[str(BUYER)]['action'], 'move')

    def test_action_gate_rejects_a_second_capture_of_the_same_target(self):
        raw, _, settings = scene()
        add_imp(raw, Pos(6, 24))
        plan = ActionPlan(Turn.load(raw), settings)
        command = dict(action='catch', targetPos=[Pos(6, 24).dump()])
        self.assertTrue(plan.add(PIONEER, command))
        self.assertFalse(plan.add(BUYER, command))
        self.assertNotIn(BUYER, plan.used)
        self.assertEqual(plan.gold, 0)

    def test_two_distinct_adjacent_imps_can_both_be_captured(self):
        raw, memory, settings = scene()
        add_imp(raw, Pos(6, 24))
        add_imp(raw, Pos(6, 23), uid=906)
        s, plan, defense = policy(raw, memory, settings)
        self.assertTrue(defense.catch_near(role(s, PIONEER)))
        self.assertTrue(defense.catch_near(role(s, BUYER)))
        targets = [c['targetPos'][0] for c in plan.commands.values()]
        self.assertEqual(len(targets), 2)
        self.assertNotEqual(targets[0], targets[1])

    def test_catch_does_not_finance_purchase_or_remove_observed_occupancy(self):
        raw, memory, settings = scene()
        add_imp(raw, Pos(6, 24))
        raw['mapInfo']['zones'] = [dict(neutralType='weaponShop', pos=Pos(4, 23).dump())]
        raw['weaponShopList'] = [dict(name='WallFixer', price=10)]
        s, plan, defense = policy(raw, memory, settings)
        self.assertTrue(defense.catch_near(role(s, PIONEER)))
        self.assertEqual(plan.gold, 0)
        self.assertIn(Pos(6, 24), s.turn.occupied_cells())
        self.assertFalse(plan.add(BUYER, dict(action='buy', name='WallFixer', num=1)))

    def test_catch_preempts_healing_for_a_live_actor(self):
        raw, memory, settings = scene(71)
        actor(raw, PIONEER).update(health=1, backpack=['Medicine'])
        add_imp(raw, Pos(6, 24))
        s, plan = load_strategy(raw, memory, settings)
        s.run()
        self.assertEqual(plan.commands[str(PIONEER)]['action'], 'catch')

    def test_unrelated_mining_worker_keeps_its_collect_action(self):
        raw, memory, settings = scene()
        actor(raw, SCOUT)['pos'] = Pos(20, 16).dump()
        raw['mapInfo']['zones'] = [dict(neutralType='iron', pos=Pos(21, 16).dump())]
        settings = replace(settings, enable_boss_raid=False)
        original = copy.deepcopy(raw)
        before, before_plan = load_strategy(original, copy.deepcopy(memory), settings)
        before.run()
        add_imp(raw, Pos(6, 24))
        after, after_plan = load_strategy(raw, memory, settings)
        after.run()
        self.assertEqual(after_plan.commands[str(PIONEER)]['action'], 'catch')
        self.assertEqual(after_plan.commands[str(SCOUT)], before_plan.commands[str(SCOUT)])
        self.assertEqual(after_plan.commands[str(SCOUT)]['action'], 'collect')


class FirstDayImpDefenseTests(unittest.TestCase):
    def assert_legal_chase(self, raw, s, plan, uid=PIONEER):
        cmd = plan.commands[str(uid)]
        self.assertEqual(cmd['action'], 'move')
        previous = Pos.load(actor(raw, uid)['pos'])
        target = next(u.pos for u in s.turn.enemies if u.kind == 'imp' and u.health > 0)
        destinations = set()
        for point in cmd['targetPos']:
            step = Pos.load(point)
            self.assertEqual(distance(previous, step), 1)
            self.assertNotIn(step, s.turn.blocked(role(s, uid)))
            self.assertNotIn(step, destinations)
            destinations.add(step)
            previous = step
        self.assertLess(distance(previous, target), distance(role(s, uid).pos, target))
        self.assertEqual(plan.rejections, [])

    def test_three_finished_attempts_allow_home_chase_day_and_night(self):
        for number in (40, 70, 71):
            with self.subTest(round=number):
                raw, memory, settings = scene(number)
                add_imp(raw)
                s, plan, defense = policy(raw, memory, settings)
                self.assertTrue(defense.defend(role(s, PIONEER)))
                self.assert_legal_chase(raw, s, plan)

    def test_late_day_chase_has_no_return_home_budget(self):
        raw, memory, settings = scene(70)
        actor(raw, PIONEER)['pos'] = Pos(2, 24).dump()
        add_imp(raw)
        s, plan, defense = policy(raw, memory, settings)
        self.assertEqual(s.turn.daylight_left, 1)
        self.assertTrue(defense.defend(role(s, PIONEER)))
        self.assert_legal_chase(raw, s, plan)

    def test_two_completed_attempts_do_not_preempt_third_task_for_far_imp(self):
        raw, memory, settings = scene(70, finished=2)
        add_imp(raw)
        s, plan, defense = policy(raw, memory, settings)
        self.assertFalse(defense.defend(role(s, PIONEER)))
        self.assertNotIn(str(PIONEER), plan.commands)

    def test_active_task_is_not_interrupted_by_far_imp_even_with_three_old_results(self):
        raw, memory, settings = scene()
        raw['phaseTask'] = 'an actual active question'
        add_imp(raw)
        s, plan, defense = policy(raw, memory, settings)
        self.assertFalse(defense.defend(role(s, PIONEER)))
        self.assertNotIn(str(PIONEER), plan.commands)

    def test_adjacent_imp_does_not_interrupt_any_unfinished_pioneer_itinerary(self):
        for ended in (0, 1, 2):
            for number in (40, 70, 71):
                with self.subTest(finished=ended, round=number):
                    raw, memory, settings = scene(number, finished=ended)
                    add_imp(raw, Pos(6, 24))
                    s, plan, defense = policy(raw, memory, settings)
                    self.assertFalse(defense.catch_near(role(s, PIONEER)))
                    self.assertFalse(defense.defend(role(s, PIONEER)))
                    self.assertNotIn(PIONEER, plan.used)
                    # The independent worker keeps the immediate-neighbour rule.
                    self.assertTrue(defense.catch_near(role(s, BUYER)))
                    self.assertEqual(plan.commands[str(BUYER)]['action'], 'catch')

    def test_three_actual_failed_attempts_still_enable_pioneer_capture(self):
        raw, memory, settings = scene()
        for job in memory.task_attempts.values():
            job['succeeded'] = False
        memory.task_points_succeeded.clear()
        add_imp(raw, Pos(6, 24))
        s, plan, defense = policy(raw, memory, settings)
        self.assertEqual(finished_count(memory), 3)
        self.assertTrue(defense.catch_near(role(s, PIONEER)))
        self.assertEqual(plan.commands[str(PIONEER)]['action'], 'catch')

    def test_disabled_tasks_do_not_waive_the_three_finished_attempt_requirement(self):
        raw, memory, settings = scene(finished=0)
        settings = replace(settings, enable_tasks=False)
        add_imp(raw, Pos(6, 24))
        s, plan, defense = policy(raw, memory, settings)
        self.assertFalse(defense.catch_near(role(s, PIONEER)))
        self.assertFalse(defense.defend(role(s, PIONEER)))
        s.run()
        self.assertEqual(plan.commands[str(PIONEER)]['action'], 'move')
        self.assertEqual(plan.commands[str(BUYER)]['action'], 'catch')
        self.assertEqual(finished_count(memory), 0)
        self.assertEqual(plan.rejections, [])

    def test_buyer_only_chases_after_its_coupon_mission_is_complete(self):
        raw, memory, settings = scene()
        add_imp(raw)
        s, plan, defense = policy(raw, memory, settings)
        self.assertTrue(defense.defend(role(s, BUYER)))
        self.assert_legal_chase(raw, s, plan, BUYER)

    def test_buyer_with_a_remaining_order_or_pending_feedback_does_not_far_chase(self):
        for pending in ('held', 'pending_buy', 'pending_use'):
            with self.subTest(pending=pending):
                raw, memory, settings = scene()
                add_imp(raw)
                memory.boss_raid.update(deployed_count=0, purchase_closed=False,
                    purchase_stage_done=False, departure_authorized=True, mission_started=True,
                    buyer_departed=True)
                if pending == 'held':
                    actor(raw, BUYER)['backpack'] = [ORDER]
                elif pending == 'pending_buy':
                    memory.boss_raid[pending] = dict(round=40, held=0, num=1, actor_id=BUYER)
                else:
                    actor(raw, BUYER)['backpack'] = [ORDER]
                    memory.boss_raid[pending] = dict(round=40, held=1, actor_id=BUYER,
                        spawn=Pos(34, 8), scouted=True)
                s, plan, defense = policy(raw, memory, settings)
                self.assertFalse(defense.defend(role(s, BUYER)))
                self.assertNotIn(str(BUYER), plan.commands)

    def test_buyer_at_shop_captures_adjacent_imp_without_losing_purchase_mission(self):
        raw, memory, settings = worker_raid_scene(successes=1)
        add_imp(raw, Pos(17, 14))
        s, plan = load_strategy(raw, memory, settings)
        s.run()
        self.assertEqual(plan.commands[str(BUYER)],
            dict(action='catch', targetPos=[Pos(17, 14).dump()]))
        self.assertFalse(any(c.get('action') == 'buy' and c.get('name') == ORDER
                             for c in plan.commands.values()))
        # Only public next-frame feedback deletes the enemy and supplies gold.
        memory.record(s.turn, plan)
        raw.update(roundNo=41, lastRoundRoleActionResults={str(BUYER): True})
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['id'] != ENEMY_IMP]
        raw['teamOur']['goldNum'] += 20
        memory.observe(Turn.load(raw))
        s, plan = load_strategy(raw, memory, settings)
        s.run()
        self.assertEqual(plan.commands[str(BUYER)], dict(action='buy', name=ORDER, num=1))

    def test_scout_worker_keeps_survey_instead_of_joining_far_pursuit(self):
        raw, memory, settings = scene()
        actor(raw, SCOUT)['pos'] = Pos(5, 25).dump()
        add_imp(raw)
        s, plan, defense = policy(raw, memory, settings)
        self.assertFalse(defense.defend(role(s, SCOUT)))
        self.assertNotIn(str(SCOUT), plan.commands)

    def test_two_defenders_cannot_reserve_the_same_actual_destination(self):
        raw, memory, settings = scene()
        add_imp(raw, Pos(8, 24))
        s, plan, defense = policy(raw, memory, settings)
        self.assertTrue(defense.defend(role(s, PIONEER)))
        defense.defend(role(s, BUYER))
        steps = [Pos.load(p) for cmd in plan.commands.values()
                 if cmd['action'] == 'move' for p in cmd['targetPos']]
        self.assertEqual(len(steps), len(set(steps)))
        self.assertTrue(all(p not in s.turn.occupied_cells() for p in steps))
        self.assertEqual(plan.rejections, [])

    def test_hidden_or_dead_target_stops_chase_without_using_old_coordinates(self):
        for hidden in (True, False):
            with self.subTest(hidden=hidden):
                raw, memory, settings = scene()
                add_imp(raw)
                s, plan, defense = policy(raw, memory, settings)
                self.assertTrue(defense.defend(role(s, PIONEER)))
                memory.record(s.turn, plan)
                actor(raw, PIONEER)['pos'] = plan.commands[str(PIONEER)]['targetPos'][-1]
                raw['roundNo'] = 41
                if hidden:
                    raw['teamEnemy']['roles'] = []
                else:
                    raw['teamEnemy']['roles'][0]['health'] = 0
                s, plan, defense = policy(raw, memory, settings)
                self.assertFalse(defense.defend(role(s, PIONEER)))
                self.assertNotIn(str(PIONEER), plan.commands)
                self.assertTrue(s.move_to_control(role(s, PIONEER)))
                self.assertEqual(plan.commands[str(PIONEER)]['action'], 'move')

    def test_target_retreating_far_from_home_stops_the_next_frame_pursuit(self):
        raw, memory, settings = scene()
        add_imp(raw)
        s, plan, defense = policy(raw, memory, settings)
        self.assertTrue(defense.defend(role(s, PIONEER)))
        memory.record(s.turn, plan)
        raw.update(roundNo=41)
        raw['teamEnemy']['roles'][0]['pos'] = Pos(23, 18).dump()
        s, plan, defense = policy(raw, memory, settings)
        self.assertFalse(defense.defend(role(s, PIONEER)))
        self.assertTrue(s.move_to_control(role(s, PIONEER)))

    def test_a_fully_walled_off_target_does_not_cause_wait_or_illegal_movement(self):
        raw, memory, settings = scene()
        actor(raw, PIONEER)['pos'] = Pos(4, 24).dump()
        add_imp(raw)
        raw['teamOur']['roles'] += [unit(800 + i, 'wall', p.x, p.y)
            for i, p in enumerate(Pos(7, 24).neighbours())]
        s, plan, defense = policy(raw, memory, settings)
        self.assertFalse(defense.defend(role(s, PIONEER)))
        self.assertNotIn(str(PIONEER), plan.commands)
        self.assertTrue(s.move_to_control(role(s, PIONEER)))
        target = Pos.load(plan.commands[str(PIONEER)]['targetPos'][0])
        self.assertNotIn(target, s.turn.blocked(role(s, PIONEER)))

    def test_no_visible_home_imp_preserves_actual_night_weapon_operation(self):
        raw, memory, settings = scene(71)
        turn = Turn.load(raw)
        actor(raw, PIONEER)['pos'] = settings.default_operator_position(turn).dump()
        raw['robot']['roles'] = [robot(990, 5, 24)]
        s, plan, defense = policy(raw, memory, settings)
        self.assertFalse(defense.defend(role(s, PIONEER)))
        s.run()
        attacks = [c for c in plan.commands.values() if c['action'] == 'attack']
        self.assertEqual(len(attacks), 1)
        self.assertEqual(attacks[0]['controllerId'], str(PIONEER))
        self.assertNotIn(str(PIONEER), plan.commands)

    def test_lower_right_home_uses_its_actual_base_for_pursuit(self):
        raw, memory, settings = scene(lower_right=True)
        add_imp(raw, Pos(28, 8))
        s, plan, defense = policy(raw, memory, settings)
        self.assertTrue(defense.defend(role(s, PIONEER)))
        self.assert_legal_chase(raw, s, plan)

    def test_zero_order_buyer_without_a_raid_trip_keeps_its_original_ore_sale(self):
        raw, memory, settings = scene()
        memory.boss_raid.update(target_count=0, acquired_count=0, deployed_count=0,
                               status='no_successful_tasks')
        for job in memory.task_attempts.values():
            job['succeeded'] = False
        memory.task_points_succeeded.clear()
        actor(raw, BUYER)['backpack'] = ['iron'] * 12
        raw['mapInfo']['zones'] = [dict(neutralType='vendor', pos=Pos(4, 23).dump())]
        raw['vendorShopList'] = [dict(name='iron', price=3)]
        s, plan, defense = policy(raw, memory, settings)
        self.assertFalse(defense.defend(role(s, BUYER)))
        self.assertNotIn(str(BUYER), plan.commands)
        s.run()
        self.assertEqual(plan.commands[str(BUYER)], dict(action='sell', name='iron', num=12))
        self.assertFalse(memory.boss_raid.get('mission_started'))
        self.assertNotIn('buyer_home_arrived', memory.imp_defense)
        self.assertEqual(plan.rejections, [])


class TaskCaptureIntegrationTests(unittest.TestCase):
    def test_before_each_first_day_task_neighbour_imp_does_not_replace_acceptance(self):
        for ended in (0, 1, 2):
            for number in (40, 70, 71):
                with self.subTest(finished=ended, round=number):
                    raw = request(number)
                    memory = GameMemory()
                    tasks = Turn.load(raw).tasks
                    for index in range(ended):
                        selected = tasks[1 if TASK_SEQUENCE[index] == 2 else 0]
                        key = record_attempt(memory, 1, 1 + index * 7,
                            (selected.pos.x, selected.pos.y), selected.kind)
                        finish_attempt(memory, key, 4 + index * 7, succeeded=False)
                    memory.task_active_attempt = None
                    source = Pos(16, 16) if TASK_SEQUENCE[ended] == 2 else Pos(14, 13)
                    actor(raw, PIONEER)['pos'] = source.dump()
                    add_imp(raw, Pos(source.x - 1, source.y))
                    service = TurnService(Settings(enable_news=False))
                    session_key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
                    service.sessions[session_key] = Session(memory=memory)
                    response = service.decide(copy.deepcopy(raw))
                    self.assertEqual(response['roleCommandMap'][str(PIONEER)], dict(action='acceptTask'))
                    self.assertEqual(finished_count(service.sessions[session_key].memory), ended)

    def live_task(self, ended, number):
        """The current question follows 0/1/2 settled Task2/Task1 attempts."""
        raw = request(number - 1)
        tasks = Turn.load(raw).tasks
        memory = GameMemory()
        for index in range(ended):
            selected = tasks[1 if TASK_SEQUENCE[index] == 2 else 0]
            point = (selected.pos.x, selected.pos.y)
            key = record_attempt(memory, 1, 1 + index * 7, point, selected.kind)
            finish_attempt(memory, key, 4 + index * 7, succeeded=index % 2 == 0)
        selected = tasks[1 if TASK_SEQUENCE[ended] == 2 else 0]
        point = (selected.pos.x, selected.pos.y)
        memory.task_agent.accept(selected)
        record_attempt(memory, 1, number - 2, point, selected.kind)
        memory.task_accept_round = memory.last_round = number - 2
        memory.last_task_point = point
        memory.last_commands = {str(PIONEER): dict(action='acceptTask')}
        source = Pos(16, 16) if TASK_SEQUENCE[ended] == 2 else Pos(14, 13)
        actor(raw, PIONEER)['pos'] = source.dump()
        target = Pos(source.x - 1, source.y)
        add_imp(raw, target)
        raw.update(phaseTask='Read the active first-day task fixture',
                   lastRoundRoleActionResults={str(PIONEER): True})
        service = TurnService(Settings(enable_news=False))
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        service.sessions[key] = Session(memory=memory)
        response = service.decide(copy.deepcopy(raw))
        self.assertTrue(response['prompt'])
        self.assertNotEqual(response['roleCommandMap'].get(str(PIONEER), {}).get('action'), 'catch')
        raw.update(roundNo=number, lastRoundRoleActionResults={})
        return raw, service, key

    def start_active_task(self):
        raw = request()
        service = TurnService(Settings(enable_news=False))
        service.decide(copy.deepcopy(raw))
        raw.update(roundNo=2, phaseTask='Read task_1_capture_fixture.md', llmResp='')
        first = service.decide(copy.deepcopy(raw))
        self.assertTrue(first['prompt'])
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        return raw, service, key

    def test_current_final_answer_precedes_neighbour_capture_until_three_attempts_end(self):
        for ended in (0, 1, 2):
            for number in (40, 70, 71):
                with self.subTest(finished=ended, round=number):
                    raw, service, key = self.live_task(ended, number)
                    raw['llmResp'] = '{"action":"final_answer","answer":"verified task result"}'
                    submitted = service.decide(copy.deepcopy(raw))
                    self.assertEqual(submitted['roleCommandMap'][str(PIONEER)],
                        dict(action='submitAnswer', taskAnswer='verified task result'))
                    self.assertEqual(submitted['executeCmd'], '')
                    self.assertEqual(service.sessions[key].memory.task_agent.deferred_role_reply, '')
                    self.assertEqual(finished_count(service.sessions[key].memory), ended)
                    self.assertEqual(service.decide(copy.deepcopy(raw)), submitted)

    def test_task_tool_call_is_not_postponed_by_an_adjacent_imp(self):
        for ended in (0, 1, 2):
            for number in (70, 71):
                with self.subTest(finished=ended, round=number):
                    raw, service, key = self.live_task(ended, number)
                    raw['llmResp'] = '{"action":"execute_command","command":"read_task_fixture"}'
                    response = service.decide(copy.deepcopy(raw))
                    self.assertEqual(response['executeCmd'], 'read_task_fixture')
                    self.assertNotEqual(response['roleCommandMap'].get(str(PIONEER), {}).get('action'), 'catch')
                    self.assertEqual(service.sessions[key].memory.task_agent.deferred_role_reply, '')
                    self.assertEqual(finished_count(service.sessions[key].memory), ended)

    def test_three_accepts_do_not_enable_capture_while_third_question_is_delayed(self):
        raw, service, key = self.live_task(2, 40)
        # Reconstruct the confirmed-accept frame before its question becomes
        # visible. No active question is not proof that the attempt has ended.
        memory = copy.deepcopy(service.sessions[key].memory)
        memory.task_agent.self_evolve_active = False
        memory.task_agent.observed_description = ''
        memory.task_description = ''
        memory.last_round = 39
        memory.last_commands = {}
        raw.update(roundNo=40, phaseTask='', llmResp='')
        pending_key = memory.task_active_attempt
        self.assertEqual(len(memory.task_attempts), 3)
        self.assertEqual(finished_count(memory), 2)
        service = TurnService(Settings(enable_news=False))
        service.sessions[key] = Session(memory=memory)
        response = service.decide(copy.deepcopy(raw))
        self.assertNotIn(str(PIONEER), response['roleCommandMap'])
        self.assertEqual(finished_count(service.sessions[key].memory), 2)
        self.assertFalse(service.sessions[key].memory.task_attempts[pending_key]['finished'])

    def test_worker_capture_income_does_not_turn_an_unrewarded_answer_into_task_success(self):
        raw, service, key = self.start_active_task()
        # Observe one real tool round so the resulting success/failure archive
        # has useful command evidence; executeCmd is never run on this host.
        raw.update(roundNo=3,
            llmResp='{"action":"execute_command","command":"read_fixture_evidence"}')
        response = service.decide(copy.deepcopy(raw))
        self.assertEqual(response['executeCmd'], 'read_fixture_evidence')
        raw.update(roundNo=4, llmResp='', lastCmdResult='[exitCode:0]\nfixture evidence')
        service.decide(copy.deepcopy(raw))
        raw.update(roundNo=5, lastCmdResult='',
            llmResp='{"action":"final_answer","answer":"legal but incorrect answer"}')
        add_imp(raw, Pos(9, 22))  # Worker 501 is adjacent; the pioneer is not.
        submitted = service.decide(copy.deepcopy(raw))
        self.assertEqual(submitted['roleCommandMap'][str(PIONEER)]['action'], 'submitAnswer')
        self.assertEqual(submitted['roleCommandMap'][str(BUYER)]['action'], 'catch')
        self.assertFalse(any(job['succeeded']
            for job in service.sessions[key].memory.task_attempts.values()))
        # Official legal-action feedback does not say that an answer is right.
        # The only observed income here is the captured imp's 20 gold.
        raw['teamOur']['goldNum'] += 20
        raw.update(roundNo=6, phaseTask='', llmResp='', lastRoundRoleActionResults={
            str(PIONEER): True, str(BUYER): True})
        raw['teamEnemy']['roles'] = []
        service.decide(copy.deepcopy(raw))
        memory = service.sessions[key].memory
        self.assertTrue(any(job['finished'] for job in memory.task_attempts.values()))
        self.assertFalse(any(job['succeeded'] for job in memory.task_attempts.values()))
        self.assertEqual(memory.task_points_succeeded, set())
        self.assertFalse(any(entry.get('ok') for entry in memory.task_agent.self_evolve_sop.values()))
        self.assertFalse(memory.task_agent.self_evolve_skill)


if __name__ == '__main__':
    unittest.main()
