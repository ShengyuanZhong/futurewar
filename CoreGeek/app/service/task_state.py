"""Persistent state expected by the supplied task controller, scoped to one game."""
from dataclasses import dataclass, field
from enum import Enum


class TaskAction(Enum):
    NOTHING = ""  # Internal idle marker; never emitted as an official action.
    ACCEPT_TASK = "acceptTask"
    SUBMIT_ANSWER = "submitAnswer"
    SUMMON_TREASURE = "summonTreasure"


@dataclass
class TaskAgentMemory:
    self_evolve_active: bool = False
    self_evolve_steps: int = 0
    self_evolve_context: list[str] = field(default_factory=list)
    self_evolve_command_trace: list[dict] = field(default_factory=list)
    self_evolve_task_desc: str = ""
    self_evolve_first_question: str = ""
    self_evolve_started_round: int = 0
    self_evolve_last_action: str = ""
    self_evolve_pending_pos: tuple[int, int] | None = None
    self_evolve_abandon_tick: int = 0
    self_evolve_sop: dict = field(default_factory=dict)
    self_evolve_skill: dict = field(default_factory=dict)
    _self_evolve_diags: set[str] = field(default_factory=set)
    _self_evolve_fail_streak: int = 0
    accepted_task: dict | None = None
    execution_round: int = 0
    observed_description: str = ""
    suspended: bool = False
    _submit_baseline: tuple[int, int] | None = None

    def accept(self, task) -> None:
        """Capture the selected point, type and budget before its display changes."""
        self.self_evolve_pending_pos = (task.pos.x, task.pos.y)
        self.accepted_task = dict(task_position=self.self_evolve_pending_pos,
                                 task_type=task.kind, timeout_rounds=task.timeout if task.timeout > 0 else 15,
                                 is_valid=task.valid)
