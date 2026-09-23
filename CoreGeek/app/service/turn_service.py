"""Serialize and transactionally commit a team's memory once per observed turn."""
import copy
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.protocol import Turn
from app.config import Settings
from .llm_service import LLMService, digest
from .memory import GameMemory
from .task_service import TaskService

LOGGER = logging.getLogger(__name__)


def empty_response() -> dict:
    return {"roleCommandMap": {}, "prompt": "", "executeCmd": ""}


@dataclass
class Session:
    memory: GameMemory = field(default_factory=GameMemory)
    round_no: int = 0
    fingerprint: str = ""
    response: dict = field(default_factory=empty_response)


class TurnService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.sessions: OrderedDict[tuple, Session] = OrderedDict()
        self.lock = threading.Lock()
        self.llm, self.tasks = LLMService(), TaskService()

    def decide(self, payload: dict) -> dict:
        started = time.monotonic()
        turn = Turn.load(payload)
        fingerprint = digest(payload)
        key = (turn.team_id, turn.team_type)
        # The official loop is sequential. Overlapping traffic must not wait 5 seconds.
        if not self.lock.acquire(timeout=.1):
            LOGGER.warning("decision_busy round=%s", turn.round_no)
            return empty_response()
        try:
            session = self.sessions.get(key, Session())
            if session.round_no == turn.round_no:
                if session.fingerprint == fingerprint:
                    return copy.deepcopy(session.response)
                raise ValueError("conflicting payload for an already processed round")
            if turn.round_no < session.round_no and turn.round_no != 1:
                raise ValueError("out-of-order round")
            if turn.round_no == 1 and session.round_no > 1:
                session = Session()
            memory = copy.deepcopy(session.memory)
            memory.observe(turn)
            purpose, reply = self.llm.consume(turn, memory)
            if purpose == "news":
                self.llm.apply_news(turn, memory, reply)
                if not reply:
                    memory.analysed_news = ""
            plan = ActionPlan(turn, self.settings, memory.summon_attempts)
            strategy = Strategy(turn, plan, memory)
            strategy.deadline = started + 3.5
            pioneer = next(iter(turn.alive(("pioneer",))), None)
            defense_due = pioneer is not None and strategy.pioneer_should_defend(pioneer)
            memory.task_defense_deadline = None
            if pioneer is not None and turn.weapons():
                control = strategy.control_position(pioneer)
                travel = strategy.route(pioneer).cost.get(control, 10_000)
                memory.task_defense_deadline = turn.round_no + max(0, turn.daylight_left-travel-self.settings.return_margin)
            prompt, execute = self.tasks.active(turn, memory, plan, self.llm,
                                                reply if purpose == "task" else {}, defense_due=defense_due)
            strategy.run()
            if self.settings.enable_news and not turn.phase_task:
                prompt = self.llm.news_prompt(turn, memory)
            memory.record(turn, plan)
            response = {"roleCommandMap": plan.commands, "prompt": prompt, "executeCmd": execute}
            self.sessions[key] = Session(memory, turn.round_no, fingerprint, copy.deepcopy(response))
            self.sessions.move_to_end(key)
            while len(self.sessions) > 16:
                self.sessions.popitem(last=False)
            LOGGER.info("decision round=%s team=%s actions=%d rejected=%d elapsed_ms=%.1f feedback_failed=%d errors=%s opening=%s shared_control=%s repair_worker=%s worker_danger_cells=%d full_time_repair=%s repair_supplier=%s worker_jobs=%s",
                        turn.round_no, turn.team_type, len(plan.commands), len(plan.rejections),
                        (time.monotonic() - started) * 1000,
                        sum(v is False for v in turn.action_results.values()),
                        [e.get("errorCode") for e in turn.errors], strategy.opening_stage(), strategy.layout.shared_control,
                        strategy.guard.worker_id, len(strategy.danger), strategy.guard.full_time, memory.repair_supplier_id,
                        {uid:(job.get('kind'),job.get('goal'),job.get('stalled',0)) for uid,job in memory.worker_tasks.items()})
            LOGGER.info("worker_motion round=%s details=%s", turn.round_no,
                        {w.unit_id: {'position': w.pos, 'job': memory.worker_tasks.get(w.unit_id, {}).get('kind'),
                         'target': memory.worker_tasks.get(w.unit_id, {}).get('target'),
                         'goal': memory.worker_tasks.get(w.unit_id, {}).get('goal'),
                         'command': plan.commands.get(str(w.unit_id)),
                         'last_action_ok': turn.action_results.get(str(w.unit_id)),
                         'oscillating': memory.worker_tasks.get(w.unit_id, {}).get('oscillating', False)}
                         for w in turn.workers()})
            for reason in plan.rejections:
                LOGGER.warning("action_rejected %s", reason)
            return response
        finally:
            self.lock.release()
