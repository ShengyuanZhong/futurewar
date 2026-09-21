import copy
import json
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from app.config import Settings
from app.service.llm_service import LLMService, parse_object
from app.service.memory import GameMemory
from app.service.turn_service import TurnService
from agent.protocol import Turn
from tests.fixtures import request


class ServiceTests(unittest.TestCase):
    def service(self):
        return TurnService(Settings(enable_news=False))

    def memory(self, service, raw):
        return service.sessions[(raw["teamOur"]["teamId"], raw["teamOur"]["type"])].memory

    def test_task_sandbox_answer_correction_and_end_lifecycle(self):
        service = self.service()
        raw = request()
        self.assertEqual(service.decide(raw)["roleCommandMap"]["502"]["action"], "acceptTask")
        raw.update(roundNo=2, phaseTask="Read data.json and return an answer as JSON text")
        self.assertIn("data.json", service.decide(raw)["prompt"])
        raw.update(roundNo=3, llmResp=json.dumps({"executeCmd": "python3 -c 'print(42)'", "skill": "Inspect schema first"}))
        with patch("subprocess.run", side_effect=AssertionError("local execution forbidden")), patch("os.system", side_effect=AssertionError("local execution forbidden")):
            reply = service.decide(raw)
        self.assertEqual(reply["executeCmd"], "python3 -c 'print(42)'")
        self.assertEqual(reply["prompt"], "")
        self.assertNotIn("502", reply["roleCommandMap"])
        raw.update(roundNo=4, llmResp="", lastCmdResult="[exitCode:0]\n42")
        self.assertIn("[exitCode:0]", service.decide(raw)["prompt"])
        raw.update(roundNo=5, llmResp=json.dumps({"taskAnswer": '{"answer":41}'}), lastCmdResult="")
        self.assertEqual(service.decide(raw)["roleCommandMap"]["502"]["taskAnswer"], '{"answer":41}')
        raw.update(roundNo=6, llmResp="", errors=[{"errorCode": 2, "description": "partial answer"}])
        self.assertIn("partial answer", service.decide(raw)["prompt"])
        raw.update(roundNo=7, llmResp=json.dumps({"taskAnswer": '{"answer":42}'}), errors=[])
        self.assertEqual(service.decide(raw)["roleCommandMap"]["502"]["taskAnswer"], '{"answer":42}')
        raw.update(roundNo=8, phaseTask="", llmResp="")
        result = service.decide(raw)
        self.assertEqual((result["prompt"], result["executeCmd"]), ("", ""))
        memory = self.memory(service, raw)
        self.assertEqual(memory.ordinary_llm_calls, 0)
        self.assertEqual(memory.skills, ["Inspect schema first"])

    def test_active_task_anchor_survives_night_transition(self):
        raw = request(70)
        raw["phaseTask"] = "active"
        service = self.service()
        service.decide(raw)
        raw.update(roundNo=71, llmResp='{"executeCmd":"pwd"}')
        result = service.decide(raw)
        self.assertEqual(result["executeCmd"], "pwd")
        self.assertNotIn("502", result["roleCommandMap"])

    def test_dead_pioneer_and_expired_task_cannot_execute(self):
        for dead in (False, True):
            raw = request(1)
            raw["phaseTask"] = "active"
            service = self.service()
            service.decide(raw)
            raw.update(roundNo=2, llmResp='{"executeCmd":"pwd","taskAnswer":"stale"}')
            if dead:
                raw["teamOur"]["roles"][2]["health"] = 0
            else:
                raw["phaseTask"] = ""
            result = service.decide(raw)
            self.assertEqual(result["executeCmd"], "")
            self.assertNotEqual(result["roleCommandMap"].get("502", {}).get("action"), "submitAnswer")

    def test_daily_ordinary_llm_limit_and_reset(self):
        service = TurnService()
        raw = request()
        for number in range(1, 6):
            raw["roundNo"] = number
            raw["worldNews"]["folkLegends"] = f"clue {number}"
            raw["llmResp"] = '{"treasure":null,"mineClosures":[]}'
            reply = service.decide(raw)
            self.assertEqual(bool(reply["prompt"]), number <= 3)
        raw["roundNo"] = 131
        self.assertTrue(service.decide(raw)["prompt"])
        self.assertEqual(self.memory(service, raw).ordinary_llm_calls, 1)

    def test_duplicate_and_concurrent_requests_are_idempotent(self):
        raw = request()
        raw["worldNews"]["folkLegends"] = "clue"
        service = TurnService()
        original = service.decide(raw)
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(service.decide, [raw] * 4))
        self.assertTrue(all(reply == original for reply in replies))
        self.assertEqual(self.memory(service, raw).ordinary_llm_calls, 1)
        replies[0]["roleCommandMap"].clear()
        self.assertEqual(service.decide(raw), original)

    def test_conflicting_and_stale_requests_do_not_mutate_memory(self):
        service = self.service()
        raw = request(10)
        service.decide(raw)
        snapshot = copy.deepcopy(service.sessions)
        raw["teamOur"]["goldNum"] += 1
        with self.assertRaises(ValueError):
            service.decide(raw)
        raw["roundNo"] = 9
        with self.assertRaises(ValueError):
            service.decide(raw)
        self.assertEqual(service.sessions, snapshot)

    def test_new_round_one_and_changed_side_isolate_memory(self):
        service = self.service()
        raw = request(100)
        service.decide(raw)
        self.memory(service, raw).skills = ["old"]
        raw["roundNo"] = 1
        service.decide(raw)
        self.assertEqual(self.memory(service, raw).skills, [])
        raw["teamOur"]["type"] = "defender"
        service.decide(raw)
        self.assertEqual(len(service.sessions), 2)

    def test_failure_is_transactional(self):
        service = self.service()
        raw = request()
        service.decide(raw)
        snapshot = copy.deepcopy(service.sessions)
        raw["roundNo"] = 2
        with patch("app.service.turn_service.Strategy.run", side_effect=RuntimeError("unexpected defect")):
            with self.assertRaises(RuntimeError):
                service.decide(raw)
        self.assertEqual(service.sessions, snapshot)

    def test_news_plan_validation_and_failed_sacrifice(self):
        turn = Turn.load(request())
        memory = GameMemory()
        llm = LLMService()
        clue = {"targetPos": {"x": 3, "y": 4}, "items": ["AcientTablet"], "startRound": 5, "endRound": 9,
                "confidence": "high", "evidence": "fixture clues"}
        llm.apply_news(turn, memory, {"treasure": clue})
        self.assertEqual(memory.treasure, clue)
        bad = dict(clue, items=["Medicine"])
        memory.treasure = None
        llm.apply_news(turn, memory, {"treasure": bad})
        self.assertIsNone(memory.treasure)
        memory.treasure = clue
        memory.treasure_attempt_round = 1
        raw = request(2)
        raw["lastSummonTreasureResult"] = 3
        memory.observe(Turn.load(raw))
        self.assertIsNone(memory.treasure)
        self.assertFalse(memory.treasure_done)
        llm.apply_news(turn, memory, {"treasure": clue})
        self.assertIsNone(memory.treasure)

    def test_stale_llm_reply_and_non_json_are_ignored(self):
        self.assertEqual(parse_object("plain answer"), {})
        self.assertEqual(parse_object('```json\n{"taskAnswer":"42"}\n```'), {"taskAnswer": "42"})
        memory = GameMemory(pending={"purpose": "task", "round": 1, "task": "active"})
        raw = request(3)
        raw.update(phaseTask="active", llmResp='{"executeCmd":"pwd"}')
        self.assertEqual(LLMService().consume(Turn.load(raw), memory), ("", {}))

    def test_failed_collection_temporarily_backs_off_without_fake_success(self):
        memory = GameMemory(last_round=1, last_commands={"501": {"action": "collect", "targetPos": [{"x": 7, "y": 22}]}})
        raw = request(2)
        raw["lastRoundRoleActionResults"] = {"501": False}
        memory.observe(Turn.load(raw))
        self.assertEqual(memory.failed_mines, {"7,22": 5})

    def test_previous_day_llm_error_does_not_exhaust_new_day(self):
        memory = GameMemory(day=1, ordinary_llm_calls=3,
                            pending={"purpose": "news", "round": 130, "day": 1})
        raw = request(131)
        raw["errors"] = [{"errorCode": 5, "description": "previous request exceeded allowance"}]
        turn = Turn.load(raw)
        memory.observe(turn)
        LLMService().consume(turn, memory)
        self.assertEqual(memory.ordinary_llm_calls, 0)
