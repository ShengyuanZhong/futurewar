"""Format the task trace supplied by the user for this project's Turn model."""
from agent.protocol import ROUNDS_PER_DAY


def task_debug_message(turn, response: dict) -> str:
    phase = "DAY" if turn.is_day else "NIGHT"
    return (
        f"[TASK-DEBUG R{turn.round_no} day{turn.day} tick{(turn.round_no - 1) % ROUNDS_PER_DAY} {phase}]\n"
        f"phaseTask : {turn.phase_task or ''}\n"
        f"llmResp   : {turn.llm_response or ''}\n"
        f"lastCmdResult   : {turn.command_result.raw or ''}\n"
        f"prompt    : {response.get('prompt', '') or ''}\n"
        f"executeCmd: {response.get('executeCmd', '') or ''}"
    )
