"""Supplied v2 prompt adapter and multi-round command/result context."""
import json
import unittest
from unittest.mock import patch
from app.config import Settings
from app.service.turn_service import TurnService
from app.service.llm_service import parse_object
from app.service.memory import GameMemory
from app.service.task_context import append_context, CONTEXT_LIMIT, ENTRY_LIMIT, diagnose
from agent.protocol import CommandResult
from tests.fixtures import request


class TaskPromptTests(unittest.TestCase):
    def test_first_observation_active_task_does_not_invent_round_zero_acceptance(self):
        service = TurnService(Settings(enable_news=False))
        raw = request(1)
        raw['phaseTask'] = 'already active'
        prompt = service.decide(raw)['prompt']
        memory = self.memory(service, raw)
        self.assertEqual(memory.task_started, 1)
        self.assertEqual(memory.task_timeout_rounds, 12)
        self.assertIn('已用 0，', prompt)

    def test_reject_duplicate_json_keys_nonfinite_and_invalid_unicode(self):
        for raw in ('{"action":"execute_command","action":"final_answer","answer":"x"}',
                    '{"answer":NaN}', '\ud800'):
            self.assertEqual(parse_object(raw), {})

    def test_context_is_bounded_by_count_and_total_size(self):
        memory = GameMemory()
        for i in range(40):
            append_context(memory, f'entry {i}:' + 'x' * 20000 + ':tail')
        self.assertLessEqual(len(memory.task_context), 20)
        self.assertLessEqual(sum(map(len, memory.task_context)), CONTEXT_LIMIT)
        self.assertTrue(all(len(entry) <= ENTRY_LIMIT for entry in memory.task_context))
        self.assertTrue(memory.task_context[-1].startswith('entry 39:'))
        self.assertTrue(memory.task_context[-1].endswith(':tail'))

    def test_timeout_is_captured_at_acceptance_and_has_fallback(self):
        for timeout, expected in ((8, 8), (0, 15)):
            service = TurnService(Settings(enable_news=False))
            raw = request(1)
            for task in raw['teamOur']['playerTasks']:
                task['timeoutRounds'] = timeout
            service.decide(raw)
            raw.update(roundNo=2, phaseTask='active')
            # The official point may refresh its displayed timeout after acceptance.
            for task in raw['teamOur']['playerTasks']:
                task['timeoutRounds'] = 99
            prompt = service.decide(raw)['prompt']
            self.assertIn(f'{expected} 回合', prompt)
            self.assertEqual(self.memory(service, raw).task_started, 1)

    def test_command_failures_are_not_success_and_api_diagnostic_is_conservative(self):
        for raw in ('[TIMEOUT]\n', '[JUDGER_ERROR]\n', '[exitCode:1]\nfailed',
                    '[exitCode:0]\n[FAIL] 2/6',
                    '[exitCode:0]\n{"code":401,"message":"Missing Authorization"}'):
            failed, hint = diagnose(CommandResult.load(raw))
            self.assertTrue(failed)
            self.assertIn('api_diag:', hint)
        failed, hint = diagnose(CommandResult.load('[exitCode:0]\n{"code":200,"data":{"count":0}}'))
        self.assertFalse(failed)
        self.assertEqual(hint, '')

    def test_gap_does_not_attribute_unmatched_command_output(self):
        service, raw, _ = self.start()
        raw.update(roundNo=3, llmResp='{"action":"execute_command","command":"pwd"}')
        service.decide(raw)
        raw.update(roundNo=5, llmResp='', lastCmdResult='[exitCode:0]\nunmatched result')
        self.assertNotIn('unmatched result', service.decide(raw)['prompt'])

    def test_same_description_after_empty_phase_starts_clean(self):
        service, raw, _ = self.start('repeatable task')
        raw.update(roundNo=3, llmResp='{"action":"execute_command","command":"read_previous"}')
        service.decide(raw)
        raw.update(roundNo=4, llmResp='', phaseTask='')
        service.decide(raw)
        raw.update(roundNo=5, phaseTask='repeatable task', lastCmdResult='[exitCode:0]\nprevious evidence')
        prompt = service.decide(raw)['prompt']
        self.assertNotIn('previous evidence', prompt)
        self.assertNotIn('read_previous', prompt)

    def start(self, desc='Read task_demo.md and return the required JSON text'):
        service = TurnService(Settings(enable_news=False))
        raw = request(1)
        service.decide(raw)  # acceptTask at the fixture's point, timeout=12
        raw.update(roundNo=2, phaseTask=desc)
        prompt = service.decide(raw)['prompt']
        return service, raw, prompt

    def memory(self, service, raw):
        return service.sessions[(raw['teamOur']['teamId'], raw['teamOur']['type'])].memory

    def test_supplied_builder_v2_protocol_and_actual_budget(self):
        _, _, prompt = self.start()
        self.assertIn('execute_command', prompt)
        self.assertIn('final_answer', prompt)
        self.assertIn('12 回合', prompt)
        self.assertIn('task_demo.md', prompt)

    def test_v2_command_then_answer_preserved_without_local_execution(self):
        service, raw, _ = self.start()
        raw.update(roundNo=3, llmResp=json.dumps({'action': 'execute_command', 'command': 'python3 solve.py'}))
        with patch('subprocess.run', side_effect=AssertionError('must not run locally')), patch('os.system', side_effect=AssertionError('must not run locally')):
            response = service.decide(raw)
        self.assertEqual(response['executeCmd'], 'python3 solve.py')
        self.assertEqual(response['prompt'], '')
        raw.update(roundNo=4, llmResp='', lastCmdResult='[exitCode:0]\n{"count":15}')
        self.assertIn('"count":15', service.decide(raw)['prompt'])
        answer = '{"count":15,"label":"原样保留"}'
        raw.update(roundNo=5, lastCmdResult='', llmResp=json.dumps({'action': 'final_answer', 'answer': answer}))
        self.assertEqual(service.decide(raw)['roleCommandMap']['502']['taskAnswer'], answer)

    def test_earlier_command_output_survives_next_command(self):
        service, raw, _ = self.start()
        for command_round, command, output in ((3, 'cat task_demo.md', 'submission schema: city, total_count'),
                                                (5, 'curl http://localhost/data', '{"records":[1,2,3]}')):
            raw.update(roundNo=command_round, lastCmdResult='', llmResp=json.dumps({'action':'execute_command','command':command}))
            service.decide(raw)
            raw.update(roundNo=command_round+1, llmResp='', lastCmdResult='[exitCode:0]\n'+output)
            response = service.decide(raw)
        self.assertIn('submission schema: city, total_count', response['prompt'])
        self.assertIn('cat task_demo.md', response['prompt'])
        self.assertIn('"records":[1,2,3]', response['prompt'])

    def test_api_error_is_diagnosed_but_supplied_controller_owns_retry(self):
        service, raw, _ = self.start()
        command = 'curl http://localhost/data?city=demo'
        raw.update(roundNo=3, llmResp=json.dumps({'action':'execute_command','command':command}))
        service.decide(raw)
        raw.update(roundNo=4, llmResp='', lastCmdResult='[exitCode:0]\n{"code":400,"message":"Missing required parameter: location"}')
        prompt = service.decide(raw)['prompt']
        self.assertIn('api_diag:', prompt)
        self.assertIn('location', prompt)
        raw.update(roundNo=5, lastCmdResult='', llmResp=json.dumps({'action':'execute_command','command':command}))
        response = service.decide(raw)
        self.assertEqual(response['executeCmd'], command)
        self.assertEqual(response['prompt'], '')

    def test_crlf_failure_hint_and_success_token_remain_task_data(self):
        service, raw, _ = self.start()
        raw.update(roundNo=3, llmResp='{"action":"execute_command","command":"./check"}')
        service.decide(raw)
        raw.update(roundNo=4, llmResp='', lastCmdResult='[exitCode:126]\n/bin/sh^M: bad interpreter')
        self.assertIn('CRLF', service.decide(raw)['prompt'])
        raw.update(roundNo=5, lastCmdResult='', llmResp=json.dumps({'action':'execute_command','command':'sed -i fix check && ./check'}))
        service.decide(raw)
        raw.update(roundNo=6, llmResp='', lastCmdResult='[exitCode:0]\n[ OK ] all passed\nTOKEN: fixture-token')
        response = service.decide(raw)
        self.assertIn('TOKEN: fixture-token', response['prompt'])
        self.assertNotEqual(response['roleCommandMap'].get('502',{}).get('action'), 'submitAnswer')

    def test_task_switch_clears_context_and_ignores_previous_result(self):
        service, raw, _ = self.start()
        raw.update(roundNo=3, llmResp='{"action":"execute_command","command":"cat private_previous_task"}')
        service.decide(raw)
        raw.update(roundNo=4, phaseTask='New task_beta.md', llmResp='', lastCmdResult='[exitCode:0]\nold task private answer')
        prompt = service.decide(raw)['prompt']
        self.assertNotIn('old task private answer', prompt)
        self.assertNotIn('cat private_previous_task', prompt)

    def test_budget_advice_does_not_override_supplied_controller_command(self):
        service, raw, _ = self.start()
        raw.update(roundNo=10, llmResp='', lastCmdResult='')
        service.decide(raw)
        raw.update(roundNo=11, llmResp='{"action":"execute_command","command":"expensive_probe"}')
        response = service.decide(raw)
        self.assertEqual(response['executeCmd'], 'expensive_probe')
        raw.update(roundNo=12, llmResp='', lastCmdResult='[exitCode:0]\nknown-result')
        self.assertTrue(service.decide(raw)['prompt'])
        raw.update(roundNo=13, lastCmdResult='', llmResp='{"action":"final_answer","answer":"known-result"}')
        self.assertEqual(service.decide(raw)['roleCommandMap']['502']['taskAnswer'], 'known-result')

    def test_invalid_legacy_and_oversized_commands_reprompt(self):
        cases = [
            {'executeCmd':'pwd','taskAnswer':'x'},
            {'action':'execute_command','command':'bad\u0000cmd'},
            {'action':'execute_command','command':'x'*(32*1024+1)},
        ]
        for obj in cases:
            service, raw, _ = self.start()
            raw.update(roundNo=3, llmResp=json.dumps(obj))
            response = service.decide(raw)
            self.assertEqual(response['executeCmd'],'')
            self.assertNotEqual(response['roleCommandMap'].get('502',{}).get('action'),'submitAnswer')
            self.assertTrue(response['prompt'])

    def test_long_result_keeps_head_tail_and_marks_clipping(self):
        service, raw, _ = self.start()
        raw.update(roundNo=3, llmResp='{"action":"execute_command","command":"read_large_output"}')
        service.decide(raw)
        raw.update(roundNo=4, llmResp='', lastCmdResult='[exitCode:0]\nSTART-MARKER\n'+'x'*70000+'\nEND-MARKER\n[TRUNCATED]')
        prompt = service.decide(raw)['prompt']
        self.assertIn('START-MARKER',prompt)
        self.assertIn('END-MARKER',prompt)
        self.assertIn('[TRUNCATED]',prompt)
        self.assertIn('中间省略',prompt)
        self.assertLess(len(prompt),40000)

    def test_provisional_skill_not_labelled_successful_sop(self):
        service, raw, _ = self.start()
        self.memory(service,raw).skills=['unverified prior tactic']
        raw.update(roundNo=3, llmResp='invalid')
        prompt=service.decide(raw)['prompt']
        self.assertNotIn('unverified prior tactic',prompt)
        self.assertNotIn('已知成功流程（SOP',prompt)
