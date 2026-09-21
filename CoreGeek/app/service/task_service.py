"""Task lifecycle. Returned commands are never executed on the contestant host."""
from agent.protocol import PIONEER


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
        skill = reply.get("skill")
        if isinstance(skill, str) and skill.strip():
            memory.skills = (memory.skills + [skill[:4000]])[-8:]
        answer = reply.get("taskAnswer")
        command = reply.get("executeCmd")
        prompt, execute = "", ""
        if isinstance(answer, str) and answer and len(answer.encode()) <= 128 * 1024:
            if plan.add(pioneer.unit_id, {"action": "submitAnswer", "taskAnswer": answer}):
                memory.task_history.append({"round": turn.round_no, "submitted": answer[:4000]})
        elif isinstance(command, str) and command.strip() and len(command.encode()) <= 32 * 1024 and "\x00" not in command:
            execute = command
        else:
            prompt = llm.task_prompt(turn, memory)
        plan.used.add(pioneer.unit_id)
        return prompt, execute
