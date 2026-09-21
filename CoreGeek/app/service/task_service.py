"""Task lifecycle. Returned commands are never executed on the contestant host."""
from agent.protocol import PIONEER
from .task_context import append_context, normalize_reply, remaining_rounds


class TaskService:
    def active(self, turn, memory, plan, llm, reply: dict, defense_due: bool = False) -> tuple[str, str]:
        if defense_due:
            # Release the sole gunner before night; only the judger ends the task.
            return "", ""
        pioneers = turn.alive((PIONEER,))
        if not turn.phase_task or not pioneers:
            return "", ""
        pioneer = pioneers[0]
        # Protect the task anchor only while no defense duty is due.
        kind, value = normalize_reply(reply)
        skill = reply.get("skill")
        if kind and isinstance(skill, str) and skill.strip():
            memory.skills = (memory.skills + [skill[:4000]])[-8:]
        prompt, execute = "", ""
        if kind == 'answer':
            if plan.add(pioneer.unit_id, {"action": "submitAnswer", "taskAnswer": value}):
                memory.task_history.append({"round": turn.round_no, "submitted": value[:4000]})
                append_context(memory, f'round {turn.round_no}: submitted_answer: {value}')
        elif kind == 'command':
            if remaining_rounds(turn, memory) <= 2:
                append_context(memory, 'adapter: 剩余回合不足以完成命令→结果→LLM答案→提交；请立即基于已有证据返回 final_answer。')
                prompt = llm.task_prompt(turn, memory)
            elif memory.task_last_command_failed and value.strip() == memory.task_last_command.strip():
                append_context(memory, 'adapter: 拒绝原样重复上一条已确认失败的命令；请根据 cmd_result 修正命令或提交已有答案。')
                prompt = llm.task_prompt(turn, memory)
            else:
                execute = value
                memory.task_execution = {'round': turn.round_no, 'task': turn.phase_task,
                                         'started': memory.task_started, 'command': value}
        else:
            prompt = llm.task_prompt(turn, memory)
        plan.used.add(pioneer.unit_id)
        return prompt, execute
