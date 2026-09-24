"""Bridge the supplied controller to official turns; never run sandbox commands here."""
import json
from dataclasses import fields
from types import SimpleNamespace

from agent.protocol import PIONEER, distance
from .llm_service import parse_object
from .task_context import COMMAND_LIMIT, ANSWER_LIMIT, normalize_reply
from .task_controller import SelfEvolveController, _parse_llm_response
from .task_state import TaskAgentMemory


def controller_reply(reply: str | dict) -> str:
    """Prefer supplied JSON/XML parsing, retaining the old envelope as a fallback."""
    raw = json.dumps(reply, ensure_ascii=False) if isinstance(reply, dict) else reply
    if not raw:
        return ''
    try:
        if len(raw.encode('utf-8')) > 256 * 1024:
            return ''
        action, payload = _parse_llm_response(raw)
        if action is None:
            kind, payload = normalize_reply(parse_object(raw))
            action = {'command': 'execute_command', 'answer': 'final_answer'}.get(kind)
        if action is None or not payload or '\x00' in payload:
            return ''
        limit = COMMAND_LIMIT if action == 'execute_command' else ANSWER_LIMIT
        if len(payload.encode('utf-8')) > limit:
            return ''
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return ''
    field = 'command' if action == 'execute_command' else 'answer'
    return json.dumps({'action': action, field: payload}, ensure_ascii=False)


class TaskService:
    def active(self, turn, memory, plan, llm, reply: str | dict,
               defense_due: bool = False) -> tuple[str, str]:
        agent = memory.task_agent
        pioneer = next(iter(turn.alive((PIONEER,))), None)
        old_pioneer = next((u for u in turn.ours if u.kind == PIONEER), None)
        role = SimpleNamespace(id=old_pioneer.unit_id if old_pioneer else -1,
                               desired_action='', task_answer='')
        consecutive = memory.last_round == turn.round_no - 1
        new_task = bool(turn.phase_task) and (turn.phase_task != agent.observed_description
                    or memory.task_started != agent.self_evolve_started_round)
        same_run = not new_task and turn.phase_task == agent.observed_description
        tasks = {f'{t.pos.x},{t.pos.y}': SimpleNamespace(task_position=(t.pos.x, t.pos.y),
                 task_type=t.kind, timeout_rounds=t.timeout, is_valid=t.valid) for t in turn.tasks}
        # Keep the accepted point's original type and timeout through completion feedback.
        if agent.accepted_task:
            position = agent.accepted_task['task_position']
            tasks[f'{position[0]},{position[1]}'] = SimpleNamespace(**agent.accepted_task)
        state = SimpleNamespace(**vars(agent), round_no=turn.round_no, phase_task=turn.phase_task,
            gold=turn.gold, total_score=turn.total_score,
            player_tasks=tasks, our_pioneer=role,
            last_round_action_results=({int(k): v for k, v in turn.action_results.items()
                                        if str(k).lstrip('-').isdigit()} if consecutive else {}),
            errors=[SimpleNamespace(errorCode=e.get('errorCode')) for e in turn.errors] if consecutive else [],
            llm_resp=controller_reply(reply) if same_run else '',
            last_cmd_result=(turn.command_result.raw if (same_run or not turn.phase_task)
                             and agent.execution_round == turn.round_no - 1 and consecutive else ''),
            response_prompt='', response_execute_cmd='')
        controller = SelfEvolveController(state)

        def commit():
            for item in fields(TaskAgentMemory):
                setattr(agent, item.name, getattr(state, item.name))
            agent.observed_description = turn.phase_task
            memory.task_context = list(agent.self_evolve_context)

        # Settle the previous submission before clearing context or updating its description.
        controller._record_command_result()
        finished = state.self_evolve_active and controller._done_by_result(role)
        if finished:
            state.suspended = True
        if state.self_evolve_active and (new_task or not turn.phase_task):
            controller._archive_experience()
            controller._reset_agent()
        if new_task:
            if memory.task_accept_round != turn.round_no - 1:
                adjacent = [t for t in turn.tasks if pioneer and
                            any(distance(pioneer.pos, p) <= 1 for p in turn.task_cells(t))]
                # A mid-game observation cannot identify an ambiguous point with certainty.
                inferred = TaskAgentMemory()
                if len(adjacent) == 1:
                    inferred.accept(adjacent[0])
                state.accepted_task = inferred.accepted_task
                state.self_evolve_pending_pos = inferred.self_evolve_pending_pos
            controller._reset_agent(cooldown=False)
            state.self_evolve_task_desc = turn.phase_task
            state.self_evolve_first_question = turn.phase_task
            state.self_evolve_started_round = memory.task_started or turn.round_no
            state.execution_round = 0
            state.suspended = False
            if state.accepted_task:
                position = state.accepted_task['task_position']
                state.player_tasks[f'{position[0]},{position[1]}'] = SimpleNamespace(**state.accepted_task)
            else:
                state.player_tasks = {f'{t.pos.x},{t.pos.y}': SimpleNamespace(
                    task_position=(t.pos.x, t.pos.y), task_type=t.kind,
                    timeout_rounds=t.timeout, is_valid=t.valid) for t in turn.tasks}
        if not turn.phase_task:
            commit()
            return '', ''
        if defense_due or pioneer is None:
            if state.self_evolve_active:
                controller._archive_experience()
                controller._reset_agent()
            state.suspended = True
        if state.suspended:
            commit()
            return '', ''
        if turn.errors and consecutive:
            state.self_evolve_context.append('judger_errors: ' + json.dumps(turn.errors, ensure_ascii=False))
        if reply and not state.llm_resp:
            state.self_evolve_context.append('llm_parse_error: 上轮输出为空、无效或超出字段限制，请重新输出 JSON。')
        handled = controller.decide(role)
        if handled:
            if role.desired_action == 'submitAnswer':
                if plan.add(pioneer.unit_id, {'action': 'submitAnswer', 'taskAnswer': role.task_answer}):
                    memory.task_history.append({'round': turn.round_no, 'submitted': role.task_answer[:4000]})
            plan.used.add(pioneer.unit_id)
        else:
            # A failed/limited run must actually release the pioneer, not restart next turn.
            state.suspended = True
        prompt, execute = state.response_prompt or '', state.response_execute_cmd or ''
        if execute:
            state.execution_round = turn.round_no
        if prompt:
            llm.register_task_prompt(turn, memory)
        commit()
        return prompt, execute
