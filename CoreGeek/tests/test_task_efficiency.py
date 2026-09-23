"""Evidence-driven task setup and reply handling, without a real sandbox/LLM."""
import json
import unittest
from unittest.mock import patch

from app.config import Settings
from app.service.turn_service import TurnService
from tests import test_task_prompt


class TaskEfficiencyTests(unittest.TestCase):
    def start(self, description='Read task_demo.md'):
        return test_task_prompt.TaskPromptTests().start(description)

    def test_exact_task_path_is_read_before_spending_an_llm_round(self):
        service = TurnService(Settings(enable_news=False))
        from tests.fixtures import request
        raw = request(1);service.decide(raw)
        raw.update(roundNo=2, phaseTask='Read /tmp/task/spec.md and solve it')
        with patch('subprocess.run', side_effect=AssertionError('no host execution')):
            reply = service.decide(raw)
        self.assertTrue(reply['executeCmd'])
        self.assertIn('/tmp/task/spec.md', reply['executeCmd'])
        self.assertEqual(reply['prompt'], '')
        raw.update(roundNo=3, lastCmdResult='[exitCode:0]\nSUBMIT: exact schema here')
        reply = service.decide(raw)
        self.assertEqual(reply['executeCmd'], '')
        self.assertIn('SUBMIT: exact schema here', reply['prompt'])
        self.assertNotIn('head -1', reply['prompt'])

    def test_ambiguous_paths_do_not_guess_first_task(self):
        _, _, prompt = self.start('Either /tmp/a.md or /tmp/b.md; select correct current task')
        self.assertTrue(prompt)
        self.assertNotIn('head -1', prompt)

    def test_structured_v2_answer_preserves_json_types(self):
        service, raw, _ = self.start()
        answer = {'count': 3, 'ratio': 1.25, 'name': 'actual', 'ok': True, 'missing': None}
        raw.update(roundNo=3, llmResp=json.dumps({'action':'final_answer', 'answer':answer}))
        reply = service.decide(raw)
        self.assertEqual(json.loads(reply['roleCommandMap']['502']['taskAnswer']), answer)

    def test_third_identical_command_with_same_output_is_not_executed(self):
        service, raw, _ = self.start()
        command = 'cat task_demo.md'
        for n in (3, 5):
            raw.update(roundNo=n, lastCmdResult='', llmResp=json.dumps({'action':'execute_command','command':command}))
            self.assertEqual(service.decide(raw)['executeCmd'], command)
            raw.update(roundNo=n+1, lastCmdResult='[exitCode:0]\nunchanged task specification', llmResp='')
            service.decide(raw)
        raw.update(roundNo=7, lastCmdResult='', llmResp=json.dumps({'action':'execute_command','command':command}))
        reply = service.decide(raw)
        self.assertEqual(reply['executeCmd'], '')
        self.assertIn('重复', reply['prompt'])

    def test_checker_can_be_reused_after_a_different_repair_command(self):
        service, raw, _ = self.start()
        for n, command in ((3,'./check'), (5,'python3 repair.py'), (7,'./check')):
            raw.update(roundNo=n, lastCmdResult='', llmResp=json.dumps({'action':'execute_command','command':command}))
            self.assertEqual(service.decide(raw)['executeCmd'], command)
            raw.update(roundNo=n+1, lastCmdResult='[exitCode:0]\nactual check result', llmResp='')
            service.decide(raw)

    def test_success_token_does_not_override_failed_verification(self):
        service, raw, _ = self.start()
        raw.update(roundNo=3, llmResp='{"action":"execute_command","command":"./check"}')
        service.decide(raw)
        raw.update(roundNo=4, llmResp='', lastCmdResult='[exitCode:0]\n[FAIL] missing requirement\nTOKEN: partial-token')
        reply = service.decide(raw)
        self.assertNotIn('一旦输出“全部通过”或 `TOKEN:`，必须立即', reply['prompt'])
        self.assertNotIn('submitAnswer', str(reply['roleCommandMap']))
        self.assertIn('失败', reply['prompt'])

    def test_bootstrap_is_quoted_read_only_and_bounded_on_fixture_files(self):
        import contextlib
        import io
        import shlex
        import tempfile
        from pathlib import Path
        from app.service.task_bootstrap import READ_SCRIPT, bootstrap_command
        command = bootstrap_command('Read /tmp/task/spec.md; this text is data')
        args = shlex.split(command)
        self.assertEqual(args[:2], ['python3', '-c'])
        self.assertEqual(args[2], READ_SCRIPT)
        self.assertEqual(args[3:], ['/tmp/task/spec.md'])
        self.assertEqual(bootstrap_command('Read /tmp/../private/spec.md'), '')
        self.assertEqual(bootstrap_command('Read task_demo.md'), '')
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'spec.md'
            p.write_text('Actual task\n' + 'x'*8000, encoding='utf-8')
            doc = Path(directory)/'api.md';doc.write_text('Actual API', encoding='utf-8')
            original = p.read_bytes()
            output = io.StringIO()
            # Run our read-only Python reader on fixture files, not a replay command.
            with patch('sys.argv', ['reader', str(p)]), contextlib.redirect_stdout(output):
                exec(compile(READ_SCRIPT, '<fixture-reader>', 'exec'), {})
            evidence = json.loads(output.getvalue())
            self.assertTrue(evidence['task']['truncated'])
            self.assertEqual(len(evidence['task']['text']), 7000)
            self.assertEqual(evidence['interface_docs'][0]['text'], 'Actual API')
            self.assertEqual(p.read_bytes(), original)

    def test_failed_bootstrap_reprompts_and_is_not_automatically_repeated(self):
        from tests.fixtures import request
        service = TurnService(Settings(enable_news=False));raw=request(1)
        service.decide(raw);raw.update(roundNo=2, phaseTask='Read /tmp/missing/spec.md')
        self.assertTrue(service.decide(raw)['executeCmd'])
        raw.update(roundNo=3, lastCmdResult='[exitCode:0]\n{"read_error":"File not found"}')
        reply = service.decide(raw)
        self.assertEqual(reply['executeCmd'], '')
        self.assertIn('File not found', reply['prompt'])
        raw.update(roundNo=4, lastCmdResult='', llmResp='invalid JSON')
        self.assertEqual(service.decide(raw)['executeCmd'], '')

    def test_next_task_has_fresh_bootstrap_and_no_stale_evidence(self):
        from tests.fixtures import request
        service=TurnService(Settings(enable_news=False));raw=request(1);service.decide(raw)
        raw.update(roundNo=2,phaseTask='Read /tmp/a/spec.md');service.decide(raw)
        raw.update(roundNo=3,phaseTask='Read /tmp/b/spec.md',lastCmdResult='[exitCode:0]\nold private result')
        reply=service.decide(raw)
        self.assertIn('/tmp/b/spec.md',reply['executeCmd'])
        self.assertNotIn('old private result',reply['prompt'])

    def test_available_budget_includes_unchanged_pioneer_return_deadline(self):
        from tests.test_maintenance import fortified
        raw=fortified(64);raw['phaseTask']='Active task with a long timeout'
        service=TurnService(Settings(enable_news=False))
        reply=service.decide(raw)
        self.assertIn('实际可用预算：3 回合',reply['prompt'])
        raw.update(roundNo=65,llmResp='{"action":"execute_command","command":"late_probe"}')
        reply=service.decide(raw)
        self.assertEqual(reply['executeCmd'],'')
        self.assertTrue(reply['prompt'])
        raw.update(roundNo=66,llmResp='{"action":"final_answer","answer":"verified"}')
        self.assertEqual(service.decide(raw)['roleCommandMap']['502']['taskAnswer'],'verified')

    def test_changed_output_allows_polling_to_continue(self):
        service,raw,_=self.start()
        command='python3 query_progress.py'
        for n in (3,5,7):
            raw.update(roundNo=n,lastCmdResult='',llmResp=json.dumps({'action':'execute_command','command':command}))
            self.assertEqual(service.decide(raw)['executeCmd'],command)
            raw.update(roundNo=n+1,llmResp='',lastCmdResult=f'[exitCode:0]\nprogress={n}')
            service.decide(raw)

    def test_structured_answers_reject_nonfinite_values_and_conflicting_commands(self):
        from app.service.task_context import normalize_reply
        for obj in ({'action':'final_answer','answer':{'x':float('nan')}},
                    {'action':'final_answer','answer':{'x':1},'command':'pwd'},
                    {'action':'final_answer','answer':{'x':'\ud800'}}):
            self.assertEqual(normalize_reply(obj),('',''))
        self.assertEqual(json.loads(normalize_reply({'action':'final_answer','answer':[1, '2', None]})[1]),[1,'2',None])
