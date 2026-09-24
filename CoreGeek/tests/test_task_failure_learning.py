"""Regressions from the failed task: business errors, JSON shape and shell quoting."""
import json
import unittest

from app.config import Settings
from app.service.turn_service import TurnService
from app.service.task_prompt import build_self_evolve_prompt
from tests.fixtures import request


class TaskFailureLearningTests(unittest.TestCase):
    def setUp(self):
        self.service = TurnService(Settings(enable_news=False))
        self.raw = request()
        self.service.decide(self.raw)
        self.step(phaseTask='Read task_first.md')

    @property
    def agent(self):
        return self.service.sessions[(self.raw['teamOur']['teamId'], self.raw['teamOur']['type'])].memory.task_agent

    @property
    def key(self):
        return 'type::' + self.raw['teamOur']['playerTasks'][0]['taskType']

    def step(self, **changes):
        self.raw.update(roundNo=self.raw['roundNo']+1, llmResp='', lastCmdResult='',
                        errors=[], lastRoundRoleActionResults={})
        self.raw.update(changes)
        return self.service.decide(self.raw)

    def execute(self, command, result):
        response = self.step(llmResp=json.dumps({'action': 'execute_command', 'command': command}))
        self.assertEqual(response['executeCmd'], command)
        return self.step(lastCmdResult=result)

    def finish(self):
        self.step(llmResp='{"action":"final_answer","answer":"fixture-answer"}')
        self.raw['teamOur']['totalScore'] = self.raw['teamOur'].get('totalScore', 0) + 10
        self.step(phaseTask='', lastRoundRoleActionResults={'502': True})

    def test_api_errors_with_zero_exit_are_excluded_from_successful_sop_and_skill(self):
        self.execute('wrong_auth', '[exitCode:0]\n{"code":401,"message":"Missing Authorization"}')
        self.execute('wrong_parameter', '[exitCode:0]\n{"code":400,"message":"Missing required parameter: region"}')
        self.execute('working_request', '[exitCode:0]\n{"code":200,"data":{"records":[]}}')
        self.finish()
        sop = self.agent.self_evolve_sop[self.key]
        self.assertEqual(sop['steps'], ['working_request'])
        self.assertEqual(sop['fail_steps'], ['wrong_auth', 'wrong_parameter'])
        self.assertEqual(self.agent.self_evolve_skill[self.key]['steps'], ['working_request'])
        prompt = self.step(phaseTask='Read task_second.md')['prompt']
        self.assertIn('region', prompt)
        self.assertIn('不要原样执行', prompt)
        self.assertNotIn('不要调整步骤', prompt)

    def test_response_shape_and_real_field_names_survive_task_change_without_values(self):
        body = {'code': 200, 'data': {'records': [{'name': 'PRIVATE_RECORD', 'protected_level': 'local',
                    'type': 'temple', 'era': 'ancient'}], 'pagination': {'total_count': 1, 'offset': 0, 'limit': 10}}}
        response = self.execute('request_records', '[exitCode:0]\n'+json.dumps(body))
        self.assertIn('api_schema:', response['prompt'])
        self.finish()
        schema = '\n'.join(self.agent.self_evolve_sop[self.key]['schemas'])
        self.assertIn('records', schema)
        self.assertIn('protected_level', schema)
        self.assertIn('pagination', schema)
        self.assertNotIn('PRIVATE_RECORD', schema)
        prompt = self.step(phaseTask='Read task_new_region.md')['prompt']
        self.assertIn(schema, prompt)
        self.assertNotIn('PRIVATE_RECORD', prompt)

    def test_shape_error_and_shell_quote_error_both_get_specific_recovery_advice(self):
        response = self.execute('bad_parser', "[exitCode:1]\nAttributeError: 'str' object has no attribute 'get'\n"
                                '/bin/bash: -c: line 24: syntax error near unexpected token `print`')
        history = '\n'.join(self.agent.self_evolve_context)
        self.assertIn('对象当作列表', history)
        self.assertIn('认证', history)
        self.assertIn('heredoc', history)
        self.assertIn('api_diag:', response['prompt'])

    def test_diagnostics_from_failed_followup_are_added_without_losing_good_steps(self):
        self.execute('working_request', '[exitCode:0]\n{"code":200,"data":{"records":[]}}')
        self.finish()
        self.step(phaseTask='Read task_followup.md')
        self.execute('broken_parser', "[exitCode:1]\nAttributeError: 'str' object has no attribute 'get'")
        self.step(phaseTask='')
        sop = self.agent.self_evolve_sop[self.key]
        self.assertTrue(sop['ok'])
        self.assertEqual(sop['steps'], ['working_request'])
        self.assertIn('broken_parser', sop['fail_steps'])
        self.assertTrue(sop['diags'])

    def test_business_error_seen_before_clipping_is_not_lost_in_archive(self):
        body = {'status': 'error', 'padding': 'x' * 8000, 'code': 400, 'message': 'request rejected'}
        self.execute('bad_request', '[exitCode:0]\n'+json.dumps(body))
        self.execute('good_check', '[exitCode:0]\n[ OK ] all passed\nTOKEN: fake-token')
        self.finish()
        self.assertEqual(self.agent.self_evolve_sop[self.key]['steps'], ['good_check'])

    def test_pipeline_masked_python_and_check_failures_are_not_success_steps(self):
        self.execute('masked_parser', "[exitCode:0]\nTraceback (most recent call last):\nAttributeError: 'str' object has no attribute 'get'")
        self.execute('masked_check', '[exitCode:0]\n[FAIL] 2/6')
        self.execute('working_check', '[exitCode:0]\n[ OK ] all passed\nTOKEN: example')
        self.finish()
        self.assertEqual(self.agent.self_evolve_sop[self.key]['steps'], ['working_check'])

    def test_masked_bad_interpreter_in_reference_log_is_not_verified(self):
        response = self.execute('check_or_true', '[exitCode:0]\n/bin/bash: ./check: /bin/sh^M: bad interpreter: No such file or directory')
        self.assertFalse(self.agent.self_evolve_command_trace[-1]['ok'])
        self.assertIn('CRLF', response['prompt'])

    def test_prompt_command_budget_scales_with_time_left(self):
        ample = build_self_evolve_prompt('task', [], steps_used=1, timeout_rounds=10)
        tight = build_self_evolve_prompt('task', ['known evidence'], steps_used=7, timeout_rounds=10)
        self.assertIn('最多约 4 条', ample)
        self.assertIn('最多约 1 条', tight)
        self.assertNotIn('5~7', tight)
        self.assertIn('剩余约 3 回合', tight)

    def test_prompt_preserves_successful_engineering_path_and_adds_safe_python_usage(self):
        prompt = build_self_evolve_prompt('task', [])
        for text in ('spec.md', 'CRLF', 'TOKEN:', 'final_answer', '数字/字符串', 'heredoc', 'isinstance'):
            self.assertIn(text, prompt)
        self.assertIn('stdin', prompt)

    def test_four_business_failures_use_existing_failure_cooldown(self):
        for index in range(4):
            response = self.execute(f'bad_request_{index}', '[exitCode:0]\n{"code":401,"status":"error"}')
        self.assertEqual(response['prompt'], '')
        self.assertTrue(self.agent.suspended)
        self.assertEqual(self.agent.self_evolve_abandon_tick, self.raw['roundNo']+25)

    def test_schema_is_bounded_and_failed_json_does_not_supply_verified_shape(self):
        from app.service.task_evidence import inspect_result
        body = {'code': 200, 'data': {f'group{i}': [{'field': 'private'}] for i in range(100)}}
        evidence = inspect_result('[exitCode:0]\n'+json.dumps(body))
        shape = json.loads(evidence.schema)
        self.assertLessEqual(len(shape['objects'])+len(shape['arrays']), 12)
        self.assertNotIn('private', evidence.schema)
        error = inspect_result('[exitCode:0]\n{"code":400,"data":{"records":[]}}')
        self.assertFalse(error.ok)
        self.assertEqual(error.schema, '')
