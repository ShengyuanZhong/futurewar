"""Robot traces describe observations without changing tactical decisions."""
import copy
import json
import time
import unittest
from unittest.mock import patch

from app.config import Settings
from app.service.turn_service import LOGGER, Session, TurnService
from tests.fixtures import unit
from tests.test_boss_raid import update_robot
from tests.test_summon_control import finished_tasks, raid_request
from tests.test_worker_safety import strategy


BOSS_ID = 30005


class RobotDiagnosticTests(unittest.TestCase):
    def service(self, raw, enabled=True):
        service = TurnService(Settings(enable_news=False, enable_robot_diagnostics=enabled))
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        service.sessions[key] = Session(memory=finished_tasks())
        return service

    def logged_decision(self, service, raw):
        with self.assertLogs(LOGGER, level='INFO') as captured:
            response = service.decide(copy.deepcopy(raw))
        messages = [r.getMessage() for r in captured.records]
        observations = [json.loads(m[len('robot_observation '):]) for m in messages
                        if m.startswith('robot_observation ')]
        diagnostics = [json.loads(m[len('robot_diagnostic '):]) for m in messages
                       if m.startswith('robot_diagnostic ')]
        return response, observations, diagnostics

    def boss_record(self, diagnostics):
        return next(record for record in diagnostics if record['robot']['id'] == BOSS_ID)

    def test_direct_attack_records_observed_candidate_and_actual_command(self):
        raw = raid_request(71, boss=True)
        response, observations, records = self.logged_decision(self.service(raw), raw)
        trace = self.boss_record(records)
        self.assertEqual(observations[0]['owned_ids'], [BOSS_ID])
        self.assertEqual(trace['robot']['pos'], {'x': 39, 'y': 25})
        self.assertEqual(trace['robot']['attack_power'], 40)
        self.assertEqual(trace['robot']['attack_range'], 3)
        self.assertEqual(trace['selected']['id'], 992)
        self.assertEqual(trace['selected']['hp'], 500)
        candidate = next(e for e in trace['events'] if e['kind'] == 'candidate')
        self.assertEqual(candidate['check']['attack_range'], 3)
        self.assertEqual(candidate['check']['distance'], 3)
        self.assertTrue(candidate['check']['clear'])
        self.assertTrue(candidate['direct'])
        self.assertEqual(candidate['rank'][3], 500)
        self.assertTrue(trace['accepted'])
        self.assertEqual(trace['reason'], 'direct_attack')
        self.assertEqual(trace['final_command'], response['roleCommandMap'][str(BOSS_ID)])

    def test_wall_block_and_reposition_include_firing_sweep_reasons(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'].append(unit(993, 'wall', 38, 25))
        response, _, records = self.logged_decision(self.service(raw), raw)
        trace = self.boss_record(records)
        candidate = next(e for e in trace['events'] if e['kind'] == 'candidate')
        self.assertEqual(candidate['check']['blocked_by'], 'wall')
        self.assertEqual(candidate['check']['wall']['id'], 993)
        wall_cell = next(c for c in trace['route']['adjacent'] if c['pos']=={'x':38,'y':25})
        self.assertFalse(wall_cell['reachable'])
        self.assertIn({'id':993,'type':'wall'},wall_cell['occupants'])
        self.assertFalse(candidate['direct'])
        sweep = next(e for e in trace['events'] if e['kind'] == 'firing_sweep')
        self.assertFalse(sweep['timed_out'])
        self.assertGreater(sweep['counts']['wall_blocked'], 0)
        self.assertGreater(sweep['counts']['legal'], 0)
        self.assertEqual(sweep['counts']['examined'],
                         sum(value for key, value in sweep['counts'].items() if key != 'examined'))
        self.assertIsNotNone(sweep['best'])
        self.assertEqual(response['roleCommandMap'][str(BOSS_ID)]['action'], 'move')
        self.assertEqual(trace['reason'], 'reposition')

    def test_matched_feedback_distinguishes_legal_illegal_and_missing(self):
        for result, expected in ((True, 'legal'), (False, 'illegal'), (None, 'missing')):
            with self.subTest(result=result):
                raw = raid_request(71, boss=True)
                service = self.service(raw)
                self.logged_decision(service, raw)
                raw['roundNo'] = 72
                raw['lastRoundRoleActionResults'] = {} if result is None else {str(BOSS_ID): result}
                _, _, records = self.logged_decision(service, raw)
                trace = self.boss_record(records)
                previous = trace['previous']
                self.assertTrue(previous['command_matched'])
                self.assertEqual(previous['raw_action_result'], result)
                self.assertEqual(previous['legality'], expected)
                self.assertEqual(previous['target_observation'], 'unchanged')
                self.assertEqual(previous['observed_hp_delta'], 0)
                if result is False:
                    self.assertEqual(trace['failed_cache'], [{'target_id': 992,
                        'target_pos': {'x': 36, 'y': 25}, 'post': {'x': 39, 'y': 25},
                        'until_round': 76}])
                    candidate = next(e for e in trace['events'] if e['kind'] == 'candidate')
                    self.assertFalse(candidate['direct'])
                    self.assertEqual(candidate['cache_until'], 76)
                else:
                    self.assertEqual(trace['failed_cache'], [])

    def test_unmatched_feedback_is_not_assigned_to_an_unknown_previous_action(self):
        raw = raid_request(72, boss=True)
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): True}
        _, _, records = self.logged_decision(self.service(raw), raw)
        previous = self.boss_record(records)['previous']
        self.assertFalse(previous['command_matched'])
        self.assertEqual(previous['legality'], 'unmatched')
        self.assertTrue(previous['raw_action_result'])
        self.assertIsNone(previous['command'])

    def test_legal_move_feedback_does_not_hide_observed_unchanged_position(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:2]
        service = self.service(raw)
        response, _, _ = self.logged_decision(service, raw)
        self.assertEqual(response['roleCommandMap'][str(BOSS_ID)]['action'], 'move')
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): True}
        _, _, records = self.logged_decision(service, raw)
        previous = self.boss_record(records)['previous']
        self.assertEqual(previous['legality'], 'legal')
        self.assertEqual(previous['movement'], 'unchanged')
        self.assertEqual(previous['displacement'], 0)

    def test_four_observed_positions_identify_abab_without_changing_commands(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:2]
        service = self.service(raw)
        positions = [(39, 25), (38, 24), (39, 25), (38, 24)]
        for number, (x, y) in enumerate(positions, 71):
            raw['roundNo'] = number
            update_robot(raw, {'x': x, 'y': y})
            _, _, records = self.logged_decision(service, raw)
        previous = self.boss_record(records)['previous']
        self.assertTrue(previous['oscillating'])
        self.assertEqual(previous['positions'], [{'x': x, 'y': y} for x, y in positions])

    def test_target_hp_changes_death_and_loss_of_sight_are_observations(self):
        for health, expected, delta in ((460, 'decreased', -40), (540, 'increased', 40),
                (500, 'unchanged', 0), (0, 'observed_dead', -500),
                (None, 'not_visible_or_absent', None)):
            with self.subTest(health=health):
                raw = raid_request(71, boss=True)
                service = self.service(raw)
                self.logged_decision(service, raw)
                raw['roundNo'] = 72
                raw['lastRoundRoleActionResults'] = {str(BOSS_ID): True}
                if health is None:
                    raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:2]
                else:
                    raw['teamEnemy']['roles'][2]['health'] = health
                _, _, records = self.logged_decision(service, raw)
                previous = self.boss_record(records)['previous']
                self.assertEqual(previous['target_observation'], expected)
                self.assertEqual(previous['observed_hp_delta'], delta)
                self.assertEqual(previous['target_hp_now'], health)

    def test_target_switch_records_departed_role_and_new_weapon_crew(self):
        raw = raid_request(71, boss=True)
        service = self.service(raw)
        self.logged_decision(service, raw)
        raw['roundNo'] = 72
        raw['teamEnemy']['roles'][2]['pos'] = {'x': 36, 'y': 20}
        raw['teamEnemy']['roles'].append(unit(994, 'worker', 36, 25, health=40))
        _, _, records = self.logged_decision(service, raw)
        trace = self.boss_record(records)
        self.assertTrue(trace['target_changed'])
        self.assertEqual(trace['selected']['id'], 994)
        departed = next(u for u in trace['visible_heroes'] if u['id'] == 992)
        self.assertEqual(departed['near_weapon_ids'], [])
        self.assertFalse(departed['eligible'])
        self.assertEqual(trace['previous_job']['controller_id'], 992)

    def test_ineligible_robots_still_get_explicit_skip_records(self):
        for variant, expected in (('stun', 'skip_stunned'), ('day', 'skip_daytime'),
                                 ('later', 'skip_after_day_one'), ('dead', 'skip_dead')):
            with self.subTest(variant=variant):
                raw = raid_request(71, boss=True)
                if variant == 'stun':
                    raw['teamOur']['summonRobotList'][0]['abnormalState'] = 'dizzy'
                elif variant == 'day':
                    raw['roundNo'] = 70
                elif variant == 'later':
                    raw['roundNo'] = 201
                else:
                    raw['teamOur']['summonRobotList'][0]['health'] = 0
                response, _, records = self.logged_decision(self.service(raw), raw)
                trace = self.boss_record(records)
                self.assertEqual(trace['reason'], expected)
                self.assertTrue(trace['called'])
                self.assertIsNone(trace['final_command'])
                self.assertNotIn(str(BOSS_ID), response['roleCommandMap'])

    def test_deadline_before_robot_loop_and_during_candidates_are_distinct(self):
        raw = raid_request(71, boss=True)
        s, plan = strategy(raw, finished_tasks())
        s.deadline = time.monotonic() - 1
        s.run()
        _, records = s.raider.diag.finish()
        trace = self.boss_record(records)
        self.assertEqual(trace['reason'], 'skip_deadline_before_robot_loop')
        self.assertFalse(trace['called'])
        self.assertIsNone(trace['final_command'])
        s, plan = strategy(raw, finished_tasks())
        s.deadline = 1
        with patch('agent.robot_raider.time.monotonic', return_value=2):
            s.raider.decide(s.turn.summon_robots[0])
        _, records = s.raider.diag.finish()
        trace = self.boss_record(records)
        self.assertEqual(trace['reason'], 'deadline_during_candidates')
        self.assertTrue(trace['called'])
        self.assertLess(trace['deadline_remaining_ms'], 0)
        self.assertIsNone(trace['final_command'])

    def test_same_frame_cache_replay_does_not_append_history_or_diagnostics(self):
        raw = raid_request(71, boss=True)
        service = self.service(raw)
        response, _, _ = self.logged_decision(service, raw)
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        before = copy.deepcopy(service.sessions[key].memory)
        with patch.object(LOGGER, 'info') as info:
            replay = service.decide(copy.deepcopy(raw))
        self.assertEqual(replay, response)
        info.assert_not_called()
        self.assertEqual(service.sessions[key].memory, before)

    def test_diagnostic_switch_preserves_full_responses_and_strategy_memory(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'].append(unit(993, 'wall', 38, 25))
        enabled, disabled = self.service(raw), self.service(raw, enabled=False)
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        for number, result in ((71, None), (72, False), (73, True)):
            raw['roundNo'] = number
            raw['lastRoundRoleActionResults'] = {} if result is None else {str(BOSS_ID): result}
            active, _, active_trace = self.logged_decision(enabled, raw)
            silent, silent_observation, silent_trace = self.logged_decision(disabled, raw)
            self.assertEqual(active, silent)
            self.assertTrue(active_trace)
            self.assertEqual(silent_observation, [])
            self.assertEqual(silent_trace, [])
            # asdict turns hashable Pos dictionary keys into unhashable dicts.
            active_memory = copy.deepcopy(enabled.sessions[key].memory)
            silent_memory = copy.deepcopy(disabled.sessions[key].memory)
            active_memory.robot_motion = {}
            silent_memory.robot_motion = {}
            self.assertEqual(active_memory, silent_memory)


if __name__ == '__main__':
    unittest.main()
