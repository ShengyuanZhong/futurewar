import json
import re
from typing import Optional

from .task_state import TaskAction as ActionType
from .task_evidence import inspect_result, merged_strings


class SelfEvolveController:
    """自进化类任务 Agent：acceptTask → (executeCmd ⇄ prompt/LLM) → submitAnswer

    增加防卡死：命令连续失败/无进展时主动放弃，避免开拓者长期被任务拖住。
    """

    MAX_STEPS = 30
    MAX_CONSECUTIVE_FAIL_CMD = 4
    ABANDON_COOLDOWN = 25  # 放弃后冷回合，不立刻重接同一任务

    def __init__(self, state):
        self.state = state

    def decide(self, role) -> bool:
        """返回 True 表示已消耗本回合指令并接管开拓者"""
        if not self.state.self_evolve_active:
            if self.state.phase_task:
                self.state.self_evolve_active = True
                return self._continue_agent(role)
            return self._try_start(role)
        return self._continue_agent(role)

    # ---------- 状态存取 ----------

    def _has_engaged(self) -> bool:
        return getattr(self.state, "self_evolve_active", False)

    def _reset_agent(self, cooldown=True):
        self.state.self_evolve_active = False
        self.state.self_evolve_steps = 0
        self.state.self_evolve_context = []
        self.state.self_evolve_command_trace = []
        self.state._self_evolve_diags = set()
        self.state._self_evolve_fail_streak = 0
        # 清空遗留动作标记：否则下个任务 acceptTask 成功回合会被
        # _done_by_result 误判为「提交成功」而重置任务，白丢首回合预算
        # （pk-742941 nanjing 即因该延迟致 final_answer 落在超时回合、奖励丢失）
        self.state.self_evolve_last_action = ""
        # 清空提交奖励基线，防止跨任务残留误判
        self.state._submit_baseline = None
        if cooldown:
            self.state.self_evolve_abandon_tick = getattr(self.state, "round_no", 0) + self.ABANDON_COOLDOWN
        else:
            self.state.self_evolve_abandon_tick = 0

    def _cooling_down(self) -> bool:
        return getattr(self.state, "round_no", 0) < getattr(self.state, "self_evolve_abandon_tick", 0)

    # ---------- 启动 ----------

    def _try_start(self, role) -> bool:
        if self._cooling_down():
            return False
        task = self._find_valid_self_evolve_task()
        if task is None:
            return False
        if self.state.movement.is_adjacent(role.pos, task.task_position):
            role.desired_action = ActionType.ACCEPT_TASK.value
            self.state.self_evolve_pending_pos = task.task_position
            return True
        self.state.movement.move_to_surrounding(role, task.task_position)
        return True

    def _find_valid_self_evolve_task(self):
        for task in self.state.player_tasks.values():
            if task.is_valid and task.task_position is not None:
                return task
        return None

    # ---------- 任务执行 ----------

    def _continue_agent(self, role) -> bool:
        if self.state.phase_task:
            # 持续缓存任务描述与第一个问题，提交成功后 phaseTask 会被判题器清空，
            # 归档 SOP / Skill 需要依据这里记录的描述还原任务与首问
            self.state.self_evolve_task_desc = self.state.phase_task
            if not self.state.self_evolve_first_question:
                self.state.self_evolve_first_question = self.state.phase_task
        if self.state.self_evolve_steps >= self.MAX_STEPS:
            # 步数耗尽：先结算本轮判题结果（成功归档 / 判错归档失败经验），
            # 再对无结果的空转归档已探索经验
            if self._done_by_result(role):
                return False
            self._archive_experience()
            self._reset_agent()
            return False
        if self._done_by_result(role):
            return False
        if not self.state.phase_task:
            # 判题器可能因任务超时先行清空 phaseTask（pk-737957 gamma 任务
            # ./check 6/6 通过后恰逢 10 回合预算耗尽），上轮 LLM 已生成的
            # final_answer 仍要尽力提交，避免已完成任务静默丢分。
            # 超时后任务上下文已失效：遗留 execute_command 不再下发（引擎丢弃且
            # 浪费一轮），改为先归档已探索经验再放弃，供同类后续任务复用
            # （pk-737826 beta/gamma 连续两轮 t12 任务超时，探索经验随重置丢弃，
            # 下个同类任务只能从零重探，10 回合预算内必然再次超时）。
            if self._pending_final_answer() and self._handle_tool_response():
                return True
            if self.state.last_cmd_result:
                # 超时前放行的最后一条命令结果刚返回（如 ./check 输出的 TOKEN，
                # pk-744456 gamma 任务即因拦截后结果无门可入而静默失败）：
                # 接入上下文并重发一次 prompt，给 LLM 最后一次基于真实结果
                # 提交的机会；下轮 LLM 提交 final_answer 时由上方兜底分支接手。
                self._handle_tool_response()
                self._dispatch_prompt(role)
                return True
            self._archive_experience()
            self._reset_agent()
            return False
        if self._stalled_by_failed_cmds(role):
            return False
        self.state.self_evolve_steps += 1
        if self._budget_blocks_cmd():
            # 剩余 ≤1 回合：新命令全流程（执行+结果返回+提交）必然超出预算，
            # 拒绝下发并强制本回合直接提交，避免 final_answer 落在预算外被丢弃
            self.state.self_evolve_context.append(
                "budget_forced: 回合预算已不足（剩余 ≤1 回合），新命令被拒绝执行，"
                "请用当前已有数据直接提交 final_answer。"
            )
            self._dispatch_prompt(role)
            return True
        if self._handle_tool_response():
            return True
        self._dispatch_prompt(role)
        return True

    def _budget_blocks_cmd(self) -> bool:
        """剩余回合已不足以走完「命令执行+结果返回+提交」全流程时，
        拒绝下发新命令。命令每条约 2 回合且需预留 1 回合提交答案，
        steps 递增后 ≥ timeout-1（剩余 ≤1）再发命令，final_answer
        必然落在预算外（pk-743687 beijing 任务即因此丢奖励）。

        例外：上下文最近一条命令结果是非零退出码（修复/验证流程中途失败，
        如 ./check 的 CRLF 126）时放行最后一条命令作最后一搏——此时 LLM
        尚无答案可提交，强制提交只会空转（pk-744456 gamma 任务即因此
        在差一步拿 TOKEN 时静默失败）。"""
        timeout = self._timeout_rounds()
        if timeout <= 0:
            return False
        if self._elapsed_steps() < timeout - 1:
            return False
        action, payload = _parse_llm_response(self.state.llm_resp or "")
        if action != "execute_command" or not payload:
            return False
        return not self._last_result_failed()

    def _last_result_failed(self) -> bool:
        """上下文最后一条命令结果是否为非零退出码（修复流程中途失败的信号）。

        只看上下文（不含本轮 last_cmd_result）：结果在上一轮已接入上下文，
        而本轮 last_cmd_result 是待处理的新结果，尚未入库。"""
        for line in reversed(self.state.self_evolve_context):
            if "[exitCode:" in line:
                return not inspect_result(line.removeprefix('cmd_result: ')).ok
        return False

    def _elapsed_steps(self) -> int:
        return max(0, self.state.round_no - self.state.self_evolve_started_round)

    def _stalled_by_failed_cmds(self, role) -> bool:
        """连续多次命令执行失败（沙盒不可用等），放弃当前任务避免空转"""
        cmd_result = self.state.last_cmd_result or ""
        if not cmd_result:
            return False
        # 判定只看整体是否有成功退出码：exitCode 标记可能出现在多行输出任意位置，
        # 首行常是命令自身输出文本，不能以其判定成败
        if inspect_result(cmd_result).ok:
            self.state._self_evolve_fail_streak = 0
            return False
        self.state._self_evolve_fail_streak = getattr(self.state, "_self_evolve_fail_streak", 0) + 1
        if self.state._self_evolve_fail_streak >= self.MAX_CONSECUTIVE_FAIL_CMD:
            self.state._self_evolve_fail_streak = 0
            self._archive_experience()
            self._reset_agent()
            return True
        return False

    def _record_command_result(self):
        """Persist complete command feedback before success/failure settlement."""
        raw = self.state.last_cmd_result or ""
        if not raw or getattr(self.state, "_result_recorded", False):
            return
        self.state._result_recorded = True
        evidence = inspect_result(raw)
        commands = [line[5:] for line in self.state.self_evolve_context if line.startswith('cmd: ')]
        if commands:
            self.state.self_evolve_command_trace.append({
                'command': commands[-1], 'ok': evidence.ok, 'schema': evidence.schema})
        self.state.self_evolve_context.append(f"cmd_result: {_clip_cmd_result(raw)}")
        diag = _extract_api_diag(raw)
        for item in merged_strings([diag] if diag else [], evidence.diagnostics):
            if item not in self.state._self_evolve_diags:
                self.state._self_evolve_diags.add(item)
                self.state.self_evolve_context.append(f"api_diag: {item}")
        if evidence.schema:
            self.state.self_evolve_context.append(f'api_schema: {evidence.schema}')
        self.state.response_prompt = None

    def _done_by_result(self, role) -> bool:
        result = self.state.last_round_action_results.get(role.id)
        err_codes = {e.errorCode for e in self.state.errors}
        if 5 in err_codes:
            self._archive_experience()
            self._reset_agent()
            return True
        if self._was_submitting() and (1 in err_codes or 2 in err_codes):
            self._archive_experience()
            self._reset_agent()
            return True
        if result is False:
            if 1 in err_codes or 2 in err_codes:  # 提交被判错：固化失败经验供下轮避坑
                self._archive_experience()
                self._reset_agent()
                return True
            if 5 in err_codes:  # LLM 额度超限：本日无法继续，放弃
                self._reset_agent()
                return True
        if result is True and self._was_submitting():
            if self._submission_rewarded():
                self._archive_sop()
            else:
                # 提交动作合法但未获得奖励：答案被判错或超时提交被拒，
                # 按失败归档，避免错误答案与半成品命令序列污染同型 Skill
                self._archive_experience()
            self._reset_agent()
            return True
        return False

    def _submission_rewarded(self) -> bool:
        """提交后是否真正获得奖励（gold/score 增量）。

        判题器对 submitAnswer 动作总是返回结果合法（lastRoundRoleActionResults=true），
        答案正确性只体现在奖励上：答案错误或超时提交被拒时资源不增加。
        仅凭 result=True 归档会把失败提交误记为成功（污染同型 Skill）。
        """
        baseline = getattr(self.state, "_submit_baseline", None)
        if baseline is None:
            return False
        return self.state.gold > baseline[0] or self.state.total_score > baseline[1]

    def _was_submitting(self) -> bool:
        return getattr(self.state, "self_evolve_last_action", "") == ActionType.SUBMIT_ANSWER.value

    def _pending_final_answer(self) -> bool:
        """上轮 LLM 遗留响应是否为可提交的 final_answer。

        phaseTask 清空（任务超时）后仅允许提交答案：
        execute_command 在无任务上下文中既无法执行也没有意义，不再下发。
        """
        llm_resp = self.state.llm_resp or ""
        if llm_resp.startswith('"') and llm_resp.endswith('"'):
            llm_resp = llm_resp[1:-1]
        action, payload = _parse_llm_response(llm_resp)
        if action != "final_answer" or not payload:
            return False
        # 明显伪造/占位符答案（PLACEHOLDER_TOKEN 等）直接提交必得 0 分
        # （pk-745859 beta/gamma 两次提交均因此终结任务），不视为可提交答案
        return not _is_placeholder_answer(payload)

    def _handle_tool_response(self) -> bool:
        llm_resp = self.state.llm_resp or ""
        cmd_result = self.state.last_cmd_result or ""
        if llm_resp:
            if llm_resp.startswith('"') and llm_resp.endswith('"'):
                llm_resp = llm_resp[1:-1]
            action, payload = _parse_llm_response(llm_resp)
            if action == "final_answer" and payload:
                if _is_placeholder_answer(payload):
                    # 明显伪造/占位符答案（如 PLACEHOLDER_TOKEN）：拒绝提交并
                    # 注入上下文重发 prompt，给 LLM 机会基于真实命令结果补全
                    # （pk-745859 beta/gamma 两次占位符提交均终结任务得 0 分）
                    self.state.self_evolve_context.append(
                        "placeholder_rejected: 上轮 final_answer 含占位符/伪造值"
                        "（如 PLACEHOLDER_TOKEN），禁止提交；请依据已有命令结果"
                        "提取真实答案重新提交，或继续执行命令获取数据。"
                    )
                    return False
                self.state.self_evolve_context.append(f"llm_answer: {payload}")
                role = self.state.our_pioneer
                if role is not None:
                    role.desired_action = ActionType.SUBMIT_ANSWER.value
                    role.task_answer = payload
                    self.state.self_evolve_last_action = ActionType.SUBMIT_ANSWER.value
                    # 记录提交时的资源基线：判题器次轮据此判定提交是否真正获得奖励
                    self.state._submit_baseline = (self.state.gold, self.state.total_score)
                    return True
            if action == "execute_command" and payload:
                self.state.response_execute_cmd = payload
                self.state.self_evolve_context.append(f"cmd: {payload}")
                self.state.self_evolve_last_action = ActionType.NOTHING.value
                return True
            if action is None:
                self.state.self_evolve_context.append(
                    "llm_parse_error: 上轮 LLM 输出无法解析，请严格按 JSON 协议返回。"
                )
        if cmd_result and not getattr(self.state, "_result_recorded", False):
            self.state.self_evolve_context.append(f"cmd_result: {_clip_cmd_result(cmd_result)}")
            diag = _extract_api_diag(cmd_result)
            if diag:
                diags = getattr(self.state, "_self_evolve_diags", None)
                if diags is None:
                    diags = set()
                    self.state._self_evolve_diags = diags
                if diag not in diags:
                    diags.add(diag)
                    self.state.self_evolve_context.append(f"api_diag: {diag}")
            self.state.response_prompt = None
        return False

    def _dispatch_prompt(self, role):
        from . import task_prompt
        desc = self.state.self_evolve_task_desc or self.state.phase_task
        prompt = task_prompt.build_self_evolve_prompt(
            desc,
            self.state.self_evolve_context,
            steps_used=self._elapsed_steps(),
            timeout_rounds=self._timeout_rounds(),
            sop_hint=self._sop_hint(),
            skill_hint=self._skill_hint(),
            category=self._task_category(
                f"{desc}\n" + "\n".join(self.state.self_evolve_context)
            ),
        )
        self.state.response_prompt = prompt
        self.state.self_evolve_last_action = ActionType.NOTHING.value
        role.desired_action = ActionType.NOTHING.value

    def _timeout_rounds(self) -> int:
        """返回当前正在执行任务的真实回合预算。

        优先按已接受任务坐标（self_evolve_pending_pos）精确定位；
        定位不到时才退回"所有有效任务的最大超时"作兜底，
        避免 10 回合的后续任务被 15 回合的旁路任务误导预算。
        """
        pending = self._current_task()
        if pending and pending.timeout_rounds > 0:
            return pending.timeout_rounds
        timeout = 0
        for task in self.state.player_tasks.values():
            if task.is_valid and task.task_position is not None:
                timeout = max(timeout, task.timeout_rounds)
        return timeout

    def _current_task(self):
        """按已接受任务坐标定位当前任务对象（task_type 可用于 SOP 分库）"""
        pending = getattr(self.state, "self_evolve_pending_pos", None)
        if pending:
            return self.state.player_tasks.get(f"{pending[0]},{pending[1]}")
        return None

    # ---------- SOP 沉淀与复用 ----------

    @staticmethod
    def _task_type_key(task_type: str):
        """SOP 分库键：按 playerTasks 携带的 taskType 分别存储/使用。

        同一任务点的后续任务即使任务书文件名变化、超时缩短（如 15→10），
        taskType 始终保持不变，是跨轮次复用经验最稳定的锚点。
        """
        if not task_type:
            return None
        return f"type::{task_type}"

    @staticmethod
    def _sop_key(text: str):
        """从任务描述中提取标识该任务的稳定 key（工作区名或任务书文件名）"""
        if not text:
            return None
        m = re.search(r"ws[_-]?\d+", text, re.IGNORECASE)
        if m:
            return m.group(0).lower()
        m = re.search(r"task[_-]?\d+[_-]?[A-Za-z_]+", text)
        if m:
            return m.group(0).lower()
        return None

    _CATEGORY_PAT = re.compile(r"/\d+-([a-z][a-z0-9-]*)", re.I)
    # 路径包装段等非任务大类，提取时过滤
    _CATEGORY_SKIP = {"fixed-step", "selfevolutiontask", "step", "base"}

    def _task_category(self, text: str):
        """从沙盒路径/任务书内容中识别任务大类（如 engineering-fix / unknown-api）。

        同一大类的后续任务可复用先期验证过的命令路径，是跨任务快速完成的关键。
        路径形如 .../1-fixed-step/2-engineering-fix/task_*.md，取最后一段大类。
        """
        if not text:
            return None
        segs = self._CATEGORY_PAT.findall(text)
        segs = [s.strip("-").lower() for s in segs if s.strip("-").lower() not in self._CATEGORY_SKIP]
        return segs[-1] if segs else None

    def _extract_trace(self):
        """从上下文提取成功路径：仅保留执行成功（[exitCode:0]）的命令 + 最终提交答案"""
        steps = []
        answer = None
        pending_cmd = None
        for line in self.state.self_evolve_context:
            if line.startswith("cmd: "):
                pending_cmd = line[len("cmd: "):]
            elif line.startswith("cmd_result: ") and pending_cmd is not None:
                result = line[len("cmd_result: "):]
                if inspect_result(result).ok:
                    steps.append(pending_cmd)
                pending_cmd = None
            elif line.startswith("llm_answer: ") and answer is None:
                answer = line[len("llm_answer: "):]
        trace = getattr(self.state, 'self_evolve_command_trace', [])
        if trace:
            steps = [item['command'] for item in trace if item['ok']]
        return steps, answer

    def _extract_experience(self):
        """从上下文提取失败任务经验：已验证命令 / 失败命令 / 尝试过的答案 / 接口诊断"""
        success_steps = []
        fail_steps = []
        answer = None
        pending_cmd = None
        for line in self.state.self_evolve_context:
            if line.startswith("cmd: "):
                pending_cmd = line[len("cmd: "):]
            elif line.startswith("cmd_result: ") and pending_cmd is not None:
                result = line[len("cmd_result: "):]
                if inspect_result(result).ok:
                    success_steps.append(pending_cmd)
                else:
                    fail_steps.append(pending_cmd)
                pending_cmd = None
            elif line.startswith("llm_answer: "):
                answer = line[len("llm_answer: "):]
        trace = getattr(self.state, 'self_evolve_command_trace', [])
        if trace:
            success_steps = [item['command'] for item in trace if item['ok']]
            fail_steps = [item['command'] for item in trace if not item['ok']]
        diags = sorted(getattr(self.state, "_self_evolve_diags", None) or [])
        return success_steps, fail_steps, answer, diags

    def _archive_experience(self):
        """任务失败/放弃时，把已探索到的信息固化进经验库，方便后续同类任务继续探索。

        与成功归档（_archive_sop）对称但标记 ok=False，
        固化内容：已验证可行的命令、接口/认证诊断、尝试过但被判错的答案、已知失败命令。
        不覆盖已确认成功的 ok=True 条目；后续成功提交会再次覆盖失败条目。
        """
        steps, fail_steps, answer, diags = self._extract_experience()
        if not steps and not fail_steps and not diags:
            return
        desc = self.state.self_evolve_task_desc or self.state.phase_task
        if not desc:
            return
        entry = {
            "task": desc[:200],
            "steps": steps,
            "fail_steps": fail_steps[:10],
            "diags": diags[:10],
            "answer": (answer or "")[:500],
            "ok": False,
        }
        keys = []
        task = self._current_task()
        if task is not None:
            type_key = self._task_type_key(task.task_type)
            if type_key:
                keys.append(type_key)
        key = self._sop_key(desc)
        if key:
            keys.append(key)
        cat = self._task_category(desc + "\n" + "\n".join(self.state.self_evolve_context))
        if cat:
            keys.append(f"cat::{cat}")
        for k in keys:
            existing = self.state.self_evolve_sop.get(k)
            if existing is not None and existing.get("ok"):
                updates = {}
                for field in ('fail_steps', 'diags'):
                    if entry.get(field):
                        updates[field] = merged_strings(existing.get(field, []), entry[field])
                if updates:
                    self.state.self_evolve_sop[k] = {**existing, **updates}
                continue
            self.state.self_evolve_sop[k] = entry

    def _observed_schemas(self):
        return merged_strings([item.get('schema', '') for item in
                               self.state.self_evolve_command_trace if item['ok']], limit=4)

    def _archive_sop(self):
        """任务提交成功后，把验证过的命令序列固化进同局可复用 SOP 库。

        以 playerTasks 携带的 taskType 为主分库键（type::xxx），
        并保留精确任务 key 与任务大类 key 多路索引：
        后续同类任务（同 taskType、同大类）无需重复探索即可复刻成功路径。

        同时按"每类任务的第一个问题"沉淀 Skill：把该 taskType 的首个问题原文
        连同成功解法归档，后续同类任务命中 Skill 时可直接给出题型与解法速览。
        """
        steps, fail_steps, answer, diags = self._extract_experience()
        if not steps:
            return
        desc = self.state.self_evolve_task_desc or self.state.phase_task
        entry = {
            "task": desc[:200],
            "steps": steps,
            "answer": answer,
            "ok": True,
            "fail_steps": fail_steps[:10],
            "diags": diags[:10],
            "schemas": self._observed_schemas(),
        }
        task = self._current_task()
        if task is not None:
            type_key = self._task_type_key(task.task_type)
            if type_key:
                self.state.self_evolve_sop[type_key] = entry
                self._archive_skill(type_key, task.task_type, entry)
        key = self._sop_key(desc)
        if key:
            self.state.self_evolve_sop[key] = entry
        cat = self._task_category(desc + "\n" + "\n".join(self.state.self_evolve_context))
        if cat:
            cat_key = f"cat::{cat}"
            existing = self.state.self_evolve_sop.get(cat_key)
            if existing is None or not existing.get("ok"):
                self.state.self_evolve_sop[cat_key] = entry

    def _archive_skill(self, type_key: str, task_type: str, entry: dict):
        """按 taskType 沉淀解题 Skill。

        记录该类任务的第一个问题原文（题型锚点）+ 已验证成功的关键命令序列，
        后续同类任务（taskType 相同）启动时命中 Skill，可直接获得
        "题型速览 + 解法速览"，配合 SOP 双通道快速完成。
        """
        previous = self.state.self_evolve_skill.get(type_key, {})
        question = previous.get("question") or self.state.self_evolve_first_question or entry.get("task", "")
        self.state.self_evolve_skill[type_key] = {
            "task_type": task_type,
            "question": question[:500],
            "steps": entry.get("steps", []),
            "answer": entry.get("answer"),
            "ok": True,
        }

    def _skill_hint(self):
        """命中当前 taskType 的 Skill 时，返回题型 + 解法速览提示文本"""
        task = self._current_task()
        if task is None:
            return None
        type_key = self._task_type_key(task.task_type)
        if not type_key:
            return None
        skill = self.state.self_evolve_skill.get(type_key)
        if not skill or not skill.get("steps"):
            return None
        question = skill.get("question", "")
        steps = "\n".join(
            f"  {i + 1}. {cmd}" for i, cmd in enumerate(skill["steps"])
        )
        lines = ["# 同型任务已掌握（Skill，可直接复用经验）"]
        lines.append(f"该任务类型（{skill.get('task_type')}）此前已熟练掌握，可直接复用经验：")
        if question:
            lines.append(f"首次触达该类型时的任务描述：{question}")
        if skill.get("answer"):
            lines.append(f"上次成功提交答案参考：{skill['answer']}")
        lines.append(f"上次成功的关键命令序列（{len(skill['steps'])} 条，顺序执行）：\n{steps}")
        sop = self.state.self_evolve_sop.get(type_key, {})
        if sop.get('diags'):
            lines.append('已知接口/认证要求：\n' + '\n'.join(f"  - {item}" for item in sop['diags']))
        if sop.get('schemas'):
            lines.append('已验证响应字段结构：\n' + '\n'.join(sop['schemas']))
        if sop.get('fail_steps'):
            lines.append('以下命令曾失败，不要原样执行：\n' +
                         '\n'.join(f"  - {item}" for item in sop['fail_steps'][:5]))
        lines.append('按当前任务重新核对路径、参数与答案，不要复用上次的答案值。')
        return "\n".join(lines) + self._budget_hint()

    def _budget_hint(self) -> str:
        """命中经验时附带回合预算提醒，让 LLM 在既定预算内安排剩余步骤"""
        timeout = self._timeout_rounds()
        if timeout <= 0:
            return ""
        used = self._elapsed_steps()
        remaining = max(timeout - used, 0)
        if remaining <= 2:
            # 剩 2 回合时再执行命令，其结果返回后仅剩 0 回合提交答案，
            # final_answer 必然落在预算外（pk-743687 beijing 即因此丢奖励）
            return (
                f"\n（预算提醒：本次任务限时 {timeout} 回合，已用 {used}，"
                f"只剩 {remaining} 回合，已不足以再执行命令"
                f"（每条约 2 回合，需预留 1 回合提交答案）："
                f"本回合必须直接提交 final_answer，不要再执行任何命令。）"
            )
        cmds = (remaining - 1) // 2  # 每条命令约 2 回合（执行+结果返回），预留 1 回合提交
        return (
            f"\n（预算提醒：本次任务限时 {timeout} 回合，已用 {used}，"
            f"剩约 {remaining} 回合，≈ 还够 {cmds} 条命令"
            f"（每条约 2 回合，需预留 1 回合提交答案）。）"
        )

    def _sop_hint(self):
        """新启动任务时，若命中已归档经验，返回可利用的提示文本。

        命中顺序：taskType 分库 key > 精确任务 key > 任务大类 key，
        各档内优先取成功条目（ok=True），无成功条目才退回失败经验条目。
        - 成功条目：此前已走通，直接照做。
        - 失败条目：上次任务未完成，提供已验证命令/接口诊断/错误答案供避坑继续探索。
        """
        desc = self.state.self_evolve_task_desc or self.state.phase_task
        candidates = []
        task = self._current_task()
        if task is not None:
            type_key = self._task_type_key(task.task_type)
            if type_key:
                candidates.append(self.state.self_evolve_sop.get(type_key))
        key = self._sop_key(desc)
        if key:
            candidates.append(self.state.self_evolve_sop.get(key))
        cat = self._task_category(
            f"{desc}\n" + "\n".join(self.state.self_evolve_context)
        )
        if cat:
            candidates.append(self.state.self_evolve_sop.get(f"cat::{cat}"))
        entry = next((e for e in candidates if e and e.get("ok")), None)
        if entry is None:
            entry = next((e for e in candidates if e), None)
        if not entry:
            return None
        steps = entry.get("steps") or []
        diags = entry.get("diags") or []
        if not steps and not diags:
            return None
        steps_block = "\n".join(f"  {i + 1}. {cmd}" for i, cmd in enumerate(steps))
        if entry.get("ok"):
            tip = ""
            if entry.get("answer"):
                tip = f"\n  最终提交答案参考：{entry['answer']}"
            return (
                "# 已知成功流程（SOP，优先照做，但是不可以直接抄答案返回）\n"
                f"该任务已有验证成功的固定流程（关键命令 {len(steps)} 条），"
                f"请直接按以下顺序执行，不要重复探索、不要调整步骤：\n{steps_block}{tip}"
            ) + self._budget_hint()
        lines = [
            "# 已探索经验（上次任务未完成，仅供继续探索参考，勿照搬流程）",
            "该同类任务上次未能完成，以下探索结果可减少重复尝试：",
        ]
        if steps:
            lines.append(f"已验证可行的命令（{len(steps)} 条，可优先复用）：\n{steps_block}")
        if diags:
            lines.append("已知接口/认证要求（避坑）：\n" + "\n".join(f"  - {d}" for d in diags))
        if entry.get("fail_steps"):
            fails = "\n".join(f"  - {c}" for c in entry["fail_steps"][:5])
            lines.append(f"已知执行失败的命令（不要再原样重试）：\n{fails}")
        if entry.get("answer"):
            lines.append(f"上次提交的答案已被判定错误，仅作参考，不要直接复用：{entry['answer']}")
        return "\n".join(lines)


class TreasureController:
    """长上下文类：收集民间传闻，推断宝藏并召唤"""

    _TREASURE_ITEMS = [
        "AcientTablet", "StarSand", "FlameBreath",
        "FrostPotion", "ThornAmulet", "IronWhistle",
    ]
    _HINT_COUNT_MAP = {
        "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    MIN_START_DAY = 3

    def __init__(self, state):
        self.state = state

    def decide(self, role) -> bool:
        code = self.state.last_summon_treasure_result
        if code == 1:
            self.state.treasure_claimed = True
        if getattr(self.state, "treasure_claimed", False):
            return False
        if code == 3:
            self._mark_failed_combo()
        self._collect_news()
        if not self._should_summon():
            return False
        target, items = self._derive_treasure(role)
        if target is None or items is None:
            return False
        if not self.state.movement.is_adjacent(role.pos, target):
            self.state.movement.move_to_surrounding(role, target)
            return True
        role.desired_action = ActionType.SUMMON_TREASURE.value
        role.target_positions = [target]
        role.item = items
        self.state.last_summon_items = items
        return True

    def _mark_failed_combo(self):
        combo = getattr(self.state, "last_summon_items", None)
        if not combo:
            return
        tried = getattr(self.state, "treasure_fail_combos", set())
        tried.add(tuple(sorted(combo)))
        self.state.treasure_fail_combos = tried

    def _collect_news(self):
        news = self.state.world_news
        if news is None:
            return
        folk = news.folk_legends or ""
        if folk and folk not in getattr(self.state, "folk_log", []):
            self.state.folk_log.append(folk)

    def _should_summon(self) -> bool:
        if self.state.day < self.MIN_START_DAY:
            return False
        return True

    def _derive_treasure(self, role):
        text = " ".join(getattr(self.state, "folk_log", []))
        target = self._infer_treasure_pos(text)
        if target is None:
            target = self._fallback_pos()
        if target is None:
            return None, None
        need = self._hint_item_count(text)
        candidates = [i for i in self._TREASURE_ITEMS if role.backpack_count(i) > 0]
        if len(candidates) < need:
            return None, None
        tried = getattr(self.state, "treasure_fail_combos", set())
        for k in range(len(candidates) - need + 1):
            combo = candidates[k:k + need]
            if tuple(sorted(combo)) not in tried:
                return target, combo
        return target, candidates[:need]

    def _hint_item_count(self, text: str) -> int:
        counts = [count for ch, count in self._HINT_COUNT_MAP.items() if ch in text]
        return max(counts) if counts else 1

    def _infer_treasure_pos(self, text: str):
        station = self.state.our_station
        if station is None or station.pos is None:
            return None
        sx, sy = station.pos
        if "西" in text and "东" not in _neg(text):
            return self._pick_mine_near((max(0, sx - 10), sy))
        if "东" in text:
            return self._pick_mine_near((min(40, sx + 10), sy))
        if "南" in text:
            return self._pick_mine_near((sx, max(0, sy - 10)))
        if "北" in text:
            return self._pick_mine_near((sx, min(31, sy + 10)))
        return None

    def _pick_mine_near(self, center):
        mines = self.state.map.get_mine_positions()
        if not mines:
            return None
        return min(mines, key=lambda p: max(abs(p[0] - center[0]), abs(p[1] - center[1])))

    def _fallback_pos(self):
        mines = self.state.map.get_mine_positions()
        if not mines:
            return None
        return mines[0]


def _neg(text: str):
    return text.replace("东", "").replace("西", "").replace("南", "").replace("北", "")


def _extract_json_object(text: str) -> Optional[str]:
    """从 LLM 输出中提取首个完整 JSON 对象子串（容忍代码块/前后缀文字）。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def _parse_llm_response(resp: str):
    """解析 LLM 返回，返回 (action, payload)；无法识别时返回 (None, None)。

    支持 JSON 协议（推荐）与旧 XML 协议兜底：
    - {"action": "execute_command", "command": "..."}  /  <execute_command>...</execute_command>
    - {"action": "final_answer", "answer": "..."}      /  <final_answer>...</final_answer>
    """
    raw = resp.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    obj = _extract_json_object(raw)
    if obj is not None:
        try:
            data = json.loads(obj)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            action = data.get("action")
            if action == "final_answer":
                answer = str(data.get("answer", "")).strip()
                return ("final_answer", answer) if answer else (None, None)
            if action == "execute_command":
                cmd = str(data.get("command", "")).strip()
                return ("execute_command", cmd) if cmd else (None, None)
    m = re.search(r"<final_answer>\s*(.*?)\s*</final_answer>", raw, re.S)
    if m:
        answer = m.group(1).strip()
        return ("final_answer", answer) if answer else (None, None)
    m = re.search(r"<execute_command>\s*(.*?)\s*</execute_command>", raw, re.S)
    if m:
        cmd = m.group(1).strip()
        return ("execute_command", cmd) if cmd else (None, None)
    return (None, None)


_PLACEHOLDER_RE = re.compile(
    r"PLACEHOLDER(?:_?TOKEN)?|<PLACEHOLDER>|待填写|占位符",
    re.IGNORECASE,
)


def _is_placeholder_answer(answer: str) -> bool:
    """明显伪造/占位符答案判定：命中即拒绝提交。

    LLM 在拿不到真实数据时（./check 未跑成功、预算将尽）会输出
    PLACEHOLDER_TOKEN 之类占位符凑数，直接提交必得 0 分
    （pk-745859 beta/gamma 两次提交均因此终结任务）。
    """
    if not answer:
        return True
    return _PLACEHOLDER_RE.search(answer) is not None


def _clip_cmd_result(cmd_result: str, head: int = 1600, tail: int = 800) -> str:
    """截断命令输出：保留头部与尾部，避免把 API 示例/关键报错同时裁掉。"""
    if len(cmd_result) <= head + tail:
        return cmd_result
    return f"{cmd_result[:head]}\n...[中间省略%d字符]...\n{cmd_result[-tail:]}" % (
        len(cmd_result) - head - tail,
    )


def _extract_api_diag(cmd_result: str):
    """从命令输出中提取服务端 API 错误提示，生成确定性的自动纠错指令。

    LLM 常忽略 4xx 响应中的 message 而重复错误参数，这里把提示以明确指令形态
    注入上下文，替代依赖 LLM 自行阅读错误正文。
    """
    if not cmd_result:
        return None
    m = re.search(r"Missing required parameter: ([A-Za-z_]+)", cmd_result)
    if m:
        p = m.group(1)
        return (f"服务端 API 提示缺少参数 `{p}`：请求必须携带 `{p}=<值>`"
                f"（此前使用的其他参数名无效），下次请求请直接用 `{p}=<值>` 替换。")
    if "Missing 'Authorization' header" in cmd_result or "Authentication failed" in cmd_result:
        fm = (re.search(r"Expected format:\s*'([^']+)'", cmd_result)
              or re.search(r"Expected format:\s*([^\n]+)", cmd_result))
        if fm:
            return (f"服务端要求认证头格式：`{fm.group(1).strip()}`，"
                    f"下一次请求必须按该格式携带认证头。")
        return ("服务端认证失败：按服务端提示的格式携带认证头"
                "（通常为 `Authorization: Bearer <key>`）后重试。")
    return None
