"""Official-envelope integration tests for the user-supplied controller."""
import copy
import json
import unittest
from app.config import Settings
from app.service.turn_service import TurnService
from app.service.task_controller import SelfEvolveController
from app.service.task_prompt import build_self_evolve_prompt
from tests.fixtures import request


class ControllerIntegrationTests(unittest.TestCase):
    def start(self, desc='Read task_1_fixture.md'):
        self.service = TurnService(Settings(enable_news=False))
        self.raw = request()
        self.service.decide(self.raw)
        self.raw.update(roundNo=2, phaseTask=desc)
        self.response = self.service.decide(self.raw)
        return self.response

    @property
    def agent(self):
        raw = self.raw
        return self.service.sessions[(raw['teamOur']['teamId'], raw['teamOur']['type'])].memory.task_agent

    @property
    def type_key(self):
        return 'type::' + self.raw['teamOur']['playerTasks'][0]['taskType']

    def step(self, **changes):
        self.raw.update(roundNo=self.raw['roundNo']+1, llmResp='', lastCmdResult='',
                        errors=[], lastRoundRoleActionResults={})
        self.raw.update(changes)
        return self.service.decide(self.raw)

    def command(self, cmd='fixture_read'):
        return self.step(llmResp=json.dumps({'action': 'execute_command', 'command': cmd}))

    def solve(self):
        self.command()
        self.step(lastCmdResult='[exitCode:0]\nfixture evidence')
        self.step(llmResp='{"action":"final_answer","answer":"fixture answer"}')

    def test_supplied_prompt_and_skill_are_used_without_bootstrap_command(self):
        response = self.start('/tmp/task_1_fixture.md')
        self.assertEqual(response['executeCmd'], '')
        self.assertIn('find /tmp /var/tmp /root /home /workspace', response['prompt'])
        self.assertIn('SOP_MARK', build_self_evolve_prompt('t', [], sop_hint='SOP_MARK'))
        self.assertIn('SKILL_MARK', build_self_evolve_prompt('t', [], skill_hint='SKILL_MARK'))

    def test_prose_fence_xml_and_legacy_response_reach_controller(self):
        for reply in ('说明：{"action":"execute_command","command":"fixture_cmd"} 完成',
                      '```json\n{"action":"execute_command","command":"fixture_cmd"}\n```',
                      '<execute_command>fixture_cmd</execute_command>',
                      '{"executeCmd":"fixture_cmd"}'):
            with self.subTest(reply=reply):
                self.start()
                self.assertEqual(self.step(llmResp=reply)['executeCmd'], 'fixture_cmd')
        self.start()
        result = self.step(llmResp='<final_answer>{"city":"北京","count":3}</final_answer>')
        self.assertEqual(result['roleCommandMap']['502']['taskAnswer'], '{"city":"北京","count":3}')

    def test_success_archived_after_phase_clear_and_reused_by_type(self):
        self.start()
        self.solve()
        self.raw['teamOur']['totalScore'] += 10
        self.step(phaseTask='', lastRoundRoleActionResults={'502': True})
        self.assertTrue(self.agent.self_evolve_sop[self.type_key]['ok'])
        self.assertEqual(self.agent.self_evolve_sop[self.type_key]['steps'], ['fixture_read'])
        self.assertEqual(self.agent.self_evolve_skill[self.type_key]['question'], 'Read task_1_fixture.md')
        # A new accepted task can use the same type even when its filename changes.
        response = self.step(phaseTask='Read task_2_other.md')
        self.assertIn('同型任务已掌握', response['prompt'])
        self.assertIn('fixture_read', response['prompt'])
        self.assertEqual(self.agent.self_evolve_first_question, 'Read task_2_other.md')

    def test_legal_submission_without_reward_archives_failure(self):
        self.start()
        self.solve()
        self.step(lastRoundRoleActionResults={'502': True})
        self.assertFalse(self.agent.self_evolve_sop[self.type_key]['ok'])
        self.assertNotIn(self.type_key, self.agent.self_evolve_skill)

    def test_placeholder_answer_is_rejected_before_submission(self):
        self.start()
        response = self.step(llmResp='{"action":"final_answer","answer":"PLACEHOLDER_TOKEN"}')
        self.assertNotEqual(response['roleCommandMap'].get('502', {}).get('action'), 'submitAnswer')
        self.assertIn('placeholder_rejected', response['prompt'])

    def test_category_experience_is_used_without_an_existing_sop(self):
        prompt = build_self_evolve_prompt('Read the task', [], category='unknown-api')
        self.assertIn('unknown-api', prompt)
        self.assertIn('pagination.total_count', prompt)
        preferred = build_self_evolve_prompt('Read the task', [], category='unknown-api',
                                             skill_hint='KNOWN_SKILL')
        self.assertIn('KNOWN_SKILL', preferred)
        self.assertNotIn('pagination.total_count', preferred)

    def test_wrong_or_timeout_answer_never_overwrites_successful_sop(self):
        for code in (1, 2):
            with self.subTest(code=code):
                self.start()
                saved = {'task': 'old', 'steps': ['known_good'], 'answer': 'old', 'ok': True}
                self.agent.self_evolve_sop[self.type_key] = saved
                self.solve()
                self.step(lastRoundRoleActionResults={'502': True},
                          errors=[{'errorCode': code, 'description': 'judger rejection'}])
                self.assertEqual(self.agent.self_evolve_sop[self.type_key], saved)
                self.assertTrue(self.agent.suspended)

    def test_four_failed_commands_archive_last_failure_and_cool_down(self):
        for failure in ('[exitCode:10]\nfailed', '[TIMEOUT]\npartial', '[JUDGER_ERROR]\noffline'):
            with self.subTest(failure=failure):
                self.start()
                for number in range(4):
                    self.command(f'bad_command_{number}')
                    response = self.step(lastCmdResult=failure)
                self.assertEqual(response['prompt'], '')
                self.assertTrue(self.agent.suspended)
                self.assertEqual(len(self.agent.self_evolve_sop[self.type_key]['fail_steps']), 4)
                until = self.agent.self_evolve_abandon_tick
                self.assertEqual(until, self.raw['roundNo']+25)
                response = self.step()
                self.assertEqual(response['prompt'], '')
                response = self.step(phaseTask='')
                self.assertEqual(response['roleCommandMap']['502']['action'], 'move')
                # The failed point cools down, while the other point remains available.
                response = self.step(roundNo=until)
                self.assertEqual(response['roleCommandMap']['502']['action'], 'move')
                # A new day permits another attempt at the original point.
                response = self.step(roundNo=131)
                self.assertEqual(response['roleCommandMap']['502']['action'], 'acceptTask')

    def test_max_steps_release_and_api_diagnostics_are_deduplicated(self):
        self.start()
        for _ in range(2):
            self.command('fixture_api')
            self.step(lastCmdResult='[exitCode:0]\nMissing required parameter: location')
        self.assertEqual(len(self.agent._self_evolve_diags), 1)
        self.agent.self_evolve_steps = SelfEvolveController.MAX_STEPS
        self.assertEqual(self.step()['prompt'], '')
        self.assertTrue(self.agent.suspended)

    def test_precise_selected_budget_and_elapsed_rounds_including_gaps(self):
        self.service = TurnService(Settings(enable_news=False))
        self.raw = request()
        self.raw['teamOur']['playerTasks'][0]['timeoutRounds'] = 10
        self.raw['teamOur']['playerTasks'][1]['timeoutRounds'] = 15
        self.service.decide(self.raw)
        response = self.step(phaseTask='Read task_a.md')
        self.assertIn('限时约 10 回合', response['prompt'])
        response = self.step(roundNo=7)
        self.assertIn('已用 6，', response['prompt'])

    def test_failure_without_success_commands_is_available_next_attempt(self):
        self.start()
        self.command('failed_command')
        self.step(lastCmdResult='[exitCode:2]\nwrong')
        self.step(phaseTask='')
        response = self.step(phaseTask='Read task_next.md')
        self.assertIn('已探索经验', response['prompt'])
        self.assertIn('failed_command', response['prompt'])

    def test_task_state_does_not_leak_between_teams_or_new_games(self):
        self.start()
        self.solve()
        self.raw['teamOur']['totalScore'] += 10
        self.step(phaseTask='', lastRoundRoleActionResults={'502': True})
        other = copy.deepcopy(self.raw)
        other['teamOur']['teamId'] = 'other'
        other.update(roundNo=2, phaseTask='Read task_next.md')
        response = self.service.decide(other)
        self.assertNotIn('fixture_read', response['prompt'])
        self.raw.update(roundNo=1, phaseTask='Read new_game.md')
        response = self.service.decide(self.raw)
        self.assertNotIn('fixture_read', response['prompt'])
        self.assertEqual(self.agent.self_evolve_sop, {})

    def test_llm_quota_error_releases_even_without_role_failure(self):
        self.start()
        result = self.step(errors=[{'errorCode': 5, 'description': 'no quota'}])
        self.assertEqual((result['prompt'], result['executeCmd']), ('', ''))
        self.assertTrue(self.agent.suspended)
