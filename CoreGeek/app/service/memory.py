from dataclasses import dataclass, field
from typing import Any
from agent.construction import DefenseLayout
from .task_context import DEFAULT_TIMEOUT, observe_task, task_timeout


def treasure_signature(clue: dict) -> tuple:
    return (clue["targetPos"]["x"], clue["targetPos"]["y"], tuple(sorted(clue["items"])), clue["startRound"], clue["endRound"])


@dataclass
class GameMemory:
    day: int = 0
    ordinary_llm_calls: int = 0
    summon_attempts: int = 0
    pending: dict[str, Any] | None = None
    news: list[dict[str, Any]] = field(default_factory=list)
    analysed_news: str = ""
    treasure: dict[str, Any] | None = None
    treasure_done: bool = False
    treasure_attempt_round: int = 0
    failed_treasures: set[tuple] = field(default_factory=set)
    mine_closures: list[dict[str, Any]] = field(default_factory=list)
    task_description: str = ""
    task_started: int = 0
    task_timeout_rounds: int = DEFAULT_TIMEOUT
    task_accept_round: int = 0
    task_accept_timeout: int = DEFAULT_TIMEOUT
    task_context: list[str] = field(default_factory=list)
    task_execution: dict[str, Any] | None = None
    task_last_command: str = ""
    task_last_command_failed: bool = False
    task_history: list[dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    failed_mines: dict[str, int] = field(default_factory=dict)
    last_commands: dict[str, Any] = field(default_factory=dict)
    last_round: int = 0
    defense_layout: DefenseLayout | None = None
    opening_complete: bool = False
    repair_worker_id: int | None = None
    repair_supplier_id: int | None = None
    dual_repair_active: bool = False
    worker_tasks: dict[int, dict[str, Any]] = field(default_factory=dict)
    repair_usage_today: dict[int, int] = field(default_factory=dict)
    repair_usage_previous: dict[int, int] = field(default_factory=dict)

    def observe(self, turn) -> None:
        if self.last_round == turn.round_no - 1:
            for actor, command in self.last_commands.items():
                if (command.get("action") == "use" and command.get("name") == "WallFixer"
                        and turn.action_results.get(actor) is True):
                    uid = int(actor)
                    self.repair_usage_today[uid] = self.repair_usage_today.get(uid, 0) + 1
        if self.day != turn.day:
            self.repair_usage_previous = self.repair_usage_today if self.day == turn.day-1 else {}
            self.repair_usage_today = {}
            self.day = turn.day
            self.ordinary_llm_calls = 0
            self.summon_attempts = 0
        entry = {"day": turn.day, "officialNews": turn.official_news, "folkLegends": turn.folk_legends}
        if (turn.official_news or turn.folk_legends) and entry not in self.news:
            self.news.append(entry)
        if turn.phase_task != self.task_description:
            if self.task_description:
                self.task_history.append({"event": "task_ended", "round": turn.round_no,
                                          "errors": turn.errors, "note": "结束不代表全部通过；分数与奖励由判题器决定"})
        observe_task(turn, self)
        if turn.phase_task and (turn.command_result.raw or turn.errors):
            self.task_history.append({"round": turn.round_no, "commandStatus": turn.command_result.status,
                                      "exitCode": turn.command_result.exit_code,
                                      "truncated": turn.command_result.truncated, "errors": turn.errors})
        self.task_history = self.task_history[-12:]
        if self.treasure_attempt_round == turn.round_no - 1:
            if turn.treasure_result in (1, 4):
                self.treasure_done = True
                self.treasure = None
            elif turn.treasure_result in (2, 3):
                # A legal failed attempt consumes the items. Do not retry the same guess.
                if self.treasure:
                    self.failed_treasures.add(treasure_signature(self.treasure))
                self.treasure = None
                self.analysed_news = ""
        if self.last_round == turn.round_no - 1:
            for actor, command in self.last_commands.items():
                if command["action"] == "collect" and turn.action_results.get(actor) is False:
                    point = command["targetPos"][0]
                    self.failed_mines[f'{point["x"]},{point["y"]}'] = turn.round_no + 3
        self.failed_mines = {k: v for k, v in self.failed_mines.items() if v > turn.round_no}

    def record(self, turn, plan) -> None:
        self.last_round = turn.round_no
        self.last_commands = plan.commands
        self.summon_attempts = plan.summon_used
        if any(c["action"] == "acceptTask" for c in plan.commands.values()):
            self.task_accept_round = turn.round_no
            self.task_accept_timeout = task_timeout(turn)
        if any(c["action"] == "summonTreasure" for c in plan.commands.values()):
            self.treasure_attempt_round = turn.round_no
