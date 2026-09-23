"""The task trace must describe the committed response and actual round."""
import json
import unittest
from unittest.mock import patch

from app.config import Settings
from app.service.turn_service import TurnService
from tests.fixtures import request


class TaskLoggingTests(unittest.TestCase):
    def test_log_tracks_task_prompt_command_feedback_and_idempotent_retry(self):
        service = TurnService(Settings(enable_news=False))
        raw = request()
        with self.assertLogs('app.service.turn_service', level='INFO') as captured:
            service.decide(raw)
        self.assertEqual(sum('[TASK-DEBUG ' in line for line in captured.output), 1)

        raw.update(roundNo=2, phaseTask='Read task_fixture.md')
        with self.assertLogs('app.service.turn_service', level='INFO') as captured:
            response = service.decide(raw)
            self.assertEqual(service.decide(raw), response)
        traces = [line for line in captured.output if '[TASK-DEBUG ' in line]
        self.assertEqual(len(traces), 1)
        self.assertIn('[TASK-DEBUG R2 day1 tick1 DAY]', traces[0])
        self.assertIn('phaseTask : Read task_fixture.md', traces[0])
        self.assertIn('prompt    : ' + response['prompt'], traces[0])

        raw.update(roundNo=3, llmResp=json.dumps({'action': 'execute_command', 'command': 'fixture_cmd'}))
        with self.assertLogs('app.service.turn_service', level='INFO') as captured:
            response = service.decide(raw)
        trace = next(line for line in captured.output if '[TASK-DEBUG ' in line)
        self.assertEqual(response['executeCmd'], 'fixture_cmd')
        self.assertIn('llmResp   : ' + raw['llmResp'], trace)
        self.assertIn('executeCmd: fixture_cmd', trace)

        raw.update(roundNo=4, llmResp='', lastCmdResult='[exitCode:0]\nfixture result')
        with self.assertLogs('app.service.turn_service', level='INFO') as captured:
            response = service.decide(raw)
        trace = next(line for line in captured.output if '[TASK-DEBUG ' in line)
        self.assertIn('lastCmdResult   : [exitCode:0]\nfixture result', trace)
        self.assertIn('prompt    : ' + response['prompt'], trace)

    def test_day_and_tick_follow_official_130_round_cycle(self):
        service = TurnService(Settings(enable_news=False))
        for round_no, expected in ((70, 'day1 tick69 DAY'), (71, 'day1 tick70 NIGHT'),
                                   (130, 'day1 tick129 NIGHT'), (131, 'day2 tick0 DAY')):
            raw = request(round_no)
            raw['teamOur']['teamId'] = f'log-test-{round_no}'
            with self.assertLogs('app.service.turn_service', level='INFO') as captured:
                service.decide(raw)
            trace = next(line for line in captured.output if '[TASK-DEBUG ' in line)
            self.assertIn(expected, trace)

    def test_log_has_no_effect_on_response(self):
        raw = request()
        with self.assertLogs('app.service.turn_service', level='INFO'):
            logged = TurnService(Settings(enable_news=False)).decide(raw)
        with patch('app.service.turn_service.LOGGER.info'):
            quiet = TurnService(Settings(enable_news=False)).decide(raw)
        self.assertEqual(logged, quiet)
