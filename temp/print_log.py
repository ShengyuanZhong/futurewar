state.game_logger.log_info(
        f"[TASK-DEBUG R{state.round_no} day{state.day} tick{state.tick_in_day} {phase}]\n"
        f"phaseTask : {state.phase_task or ''}\n"
        f"llmResp   : {state.llm_resp or ''}\n"
        f"lastCmdResult   : {state.last_cmd_result or ''}\n"
        f"prompt    : {response.get('prompt', '') or ''}\n"
        f"executeCmd: {response.get('executeCmd', '') or ''}"
    )