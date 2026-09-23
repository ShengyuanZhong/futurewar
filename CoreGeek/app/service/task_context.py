"""Bounded task evidence and protocol adaptation; never executes commands."""
import json
from agent.protocol import PIONEER, distance
from .task_prompt import HISTORY_WINDOW


ENTRY_LIMIT = 12000
CONTEXT_LIMIT = 96000
COMMAND_LIMIT = 32 * 1024
ANSWER_LIMIT = 128 * 1024
DEFAULT_TIMEOUT = 15


def clipped(value: str, limit: int = ENTRY_LIMIT) -> str:
    if len(value) <= limit:
        return value
    marker = '\n[LOCAL_CONTEXT_TRUNCATED]\n'
    head = (limit - len(marker)) // 2
    return value[:head] + marker + value[-(limit - len(marker) - head):]


def append_context(memory, value: str) -> None:
    memory.task_context.append(clipped(value))
    memory.task_context = memory.task_context[-HISTORY_WINDOW:]
    while sum(map(len, memory.task_context)) > CONTEXT_LIMIT:
        memory.task_context.pop(0)


def normalize_reply(reply: dict) -> tuple[str, str]:
    """Return (kind, exact string); reject ambiguous v2/legacy combinations."""
    if 'action' in reply:
        action = reply['action']
        field = {'execute_command': 'command', 'final_answer': 'answer'}.get(action) if isinstance(action, str) else None
        if not field or set(reply) - {'action', field, 'skill'}:
            return '', ''
        kind = 'command' if field == 'command' else 'answer'
        value = reply.get(field)
    else:
        if set(reply) - {'executeCmd', 'taskAnswer', 'skill'}:
            return '', ''
        command, answer = reply.get('executeCmd', ''), reply.get('taskAnswer', '')
        if not isinstance(command, str) or not isinstance(answer, str) or bool(command.strip()) == bool(answer.strip()):
            return '', ''
        kind, value = ('command', command) if command.strip() else ('answer', answer)
    limit = COMMAND_LIMIT if kind == 'command' else ANSWER_LIMIT
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        return '', ''
    try:
        if len(value.encode('utf-8')) > limit:
            return '', ''
    except UnicodeError:
        return '', ''
    return kind, value


def task_timeout(turn) -> int:
    """Read the current adjacent task point, never assume a fixed fixture budget."""
    pioneers = turn.alive((PIONEER,))
    candidates = [task.timeout for task in turn.tasks if task.timeout > 0 and pioneers
                  and any(distance(pioneers[0].pos, p) <= 1 for p in turn.task_cells(task))]
    return min(candidates) if candidates else DEFAULT_TIMEOUT


def remaining_rounds(turn, memory) -> int:
    return max(0, memory.task_timeout_rounds - max(0, turn.round_no - memory.task_started))


def diagnose(result) -> tuple[bool, str]:
    """Process success is distinct from application success. Advice is evidence-based."""
    failed = result.status in ('timeout', 'judger_error') or (result.exit_code is not None and result.exit_code != 0)
    hints = []
    if result.exit_code == 126 and ('^M' in result.output or 'bad interpreter' in result.output):
        hints.append('检测到解释器/CRLF 错误：核对脚本首行及换行，修复后重新验证。')
    if '[FAIL]' in result.output:
        failed = True
        hints.append('验证脚本仍有失败项；依据实际失败项修复，不把 exitCode 0 当作全部通过。')
    # Whole JSON or a JSON line after curl/log output; do not infer hidden API fields.
    candidates = [result.output] + result.output.splitlines()[-30:]
    for candidate in candidates:
        try:
            body = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if not isinstance(body, dict):
            continue
        code = body.get('code', body.get('statusCode', body.get('status')))
        code_text = str(code)
        bad_code = code_text.isascii() and code_text.isdigit() and 400 <= int(code_text) <= 599
        if bad_code or str(body.get('status', '')).lower() in ('error', 'failed', 'failure') or body.get('success') is False:
            failed = True
            hints.append('API 返回业务错误，即使 exitCode 为 0 也未成功。根据响应 message 和当前任务文档核对认证头及参数后再请求；不要猜测字段或原样重复失败请求。')
            break
    if failed and not hints:
        hints.append('命令未成功，先查看实际错误再修正；不能当作已取得答案。')
    if result.truncated:
        hints.append('官方输出已截断；缺失部分不能推断，按需分页或输出摘要。')
    return failed, '\n'.join('api_diag: ' + hint for hint in hints)


def observe_task(turn, memory) -> None:
    changed = turn.phase_task != memory.task_description
    if changed:
        accepted = memory.task_accept_round > 0 and memory.task_accept_round == turn.round_no - 1
        memory.task_description = turn.phase_task
        memory.task_started = (memory.task_accept_round if accepted else turn.round_no) if turn.phase_task else 0
        memory.task_timeout_rounds = memory.task_accept_timeout if accepted else task_timeout(turn)
        memory.task_context.clear()
        memory.task_execution = None
        memory.task_last_command = ''
        memory.task_last_command_failed = False
    execution = memory.task_execution
    if execution:
        memory.task_execution = None
        if (turn.phase_task and execution['task'] == turn.phase_task
                and execution['started'] == memory.task_started and execution['round'] + 1 == turn.round_no):
            failed, hint = diagnose(turn.command_result)
            memory.task_last_command = execution['command']
            memory.task_last_command_failed = failed
            append_context(memory, f"round {turn.round_no}: command: {clipped(execution['command'], 2000)}\n"
                           f"cmd_result: {turn.command_result.raw or '(未收到命令结果，不能推断成功)'}\n{hint}")
    if turn.phase_task and turn.errors and not changed:
        append_context(memory, f'round {turn.round_no}: judger_errors: ' + json.dumps(turn.errors, ensure_ascii=False))
