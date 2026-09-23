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
        self.state.self_evolve_last_action = ActionType.NOTHING.value
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
        self._record_command_result()
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
            self._reset_agent()
            return False
        if self._stalled_by_failed_cmds(role):
            return False
        self.state.self_evolve_steps += 1
        if self._handle_tool_response():
            return True
        self._dispatch_prompt(role)
        return True

    def _stalled_by_failed_cmds(self, role) -> bool:
        """连续多次命令执行失败（沙盒不可用等），放弃当前任务避免空转"""
        cmd_result = self.state.last_cmd_result or ""
        if not cmd_result:
            return False
        if not inspect_result(cmd_result).ok:
            self.state._self_evolve_fail_streak = getattr(self.state, "_self_evolve_fail_streak", 0) + 1
        else:
            self.state._self_evolve_fail_streak = 0
            return False
        if self.state._self_evolve_fail_streak >= self.MAX_CONSECUTIVE_FAIL_CMD:
            self.state._self_evolve_fail_streak = 0
            self._archive_experience()
            self._reset_agent()
            return True
        return False

    def _done_by_result(self, role) -> bool:
        result = self.state.last_round_action_results.get(role.id)
        err_codes = {e.errorCode for e in self.state.errors}
        if 5 in err_codes:
            self._archive_experience()
            self._reset_agent()
            return True
        if result is False or self._was_submitting():
            if 1 in err_codes or 2 in err_codes:  # 提交被判错：固化失败经验供下轮避坑
                self._archive_experience()
                self._reset_agent()
                return True
        # 官方 actionResults 仅表示动作合法；任务结束且没有判错才归档成功。
        ended = not self.state.phase_task or self.state.phase_task != self.state.self_evolve_task_desc
        if result is True and self._was_submitting() and ended and not err_codes:
            self._archive_sop()
            self._reset_agent()
            return True
        return False

    def _was_submitting(self) -> bool:
        return getattr(self.state, "self_evolve_last_action", "") == ActionType.SUBMIT_ANSWER.value

    def _handle_tool_response(self) -> bool:
        llm_resp = self.state.llm_resp or ""
        if llm_resp:
            if llm_resp.startswith('"') and llm_resp.endswith('"'):
                llm_resp = llm_resp[1:-1]
            action, payload = _parse_llm_response(llm_resp)
            if action == "final_answer" and payload:
                self.state.self_evolve_context.append(f"llm_answer: {payload}")
                role = self.state.our_pioneer
                if role is not None:
                    role.desired_action = ActionType.SUBMIT_ANSWER.value
                    role.task_answer = payload
                    self.state.self_evolve_last_action = ActionType.SUBMIT_ANSWER.value
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
        return False

    def _record_command_result(self):
        """Record feedback before terminal/failure checks; archive the last command too."""
        cmd_result = self.state.last_cmd_result or ""
        if cmd_result and not getattr(self.state, "_result_recorded", False):
            self.state._result_recorded = True
            evidence = inspect_result(cmd_result)
            commands = [line[5:] for line in self.state.self_evolve_context if line.startswith('cmd: ')]
            if commands:
                self.state.self_evolve_command_trace.append({
                    'command': commands[-1], 'ok': evidence.ok, 'schema': evidence.schema})
            self.state.self_evolve_context.append(f"cmd_result: {_clip_cmd_result(cmd_result)}")
            diag = _extract_api_diag(cmd_result)
            for diag in merged_strings([diag] if diag else [], evidence.diagnostics):
                diags = getattr(self.state, "_self_evolve_diags", None)
                if diags is None:
                    diags = set()
                    self.state._self_evolve_diags = diags
                if diag not in diags:
                    diags.add(diag)
                    self.state.self_evolve_context.append(f"api_diag: {diag}")
            if evidence.schema:
                self.state.self_evolve_context.append(f'api_schema: {evidence.schema}')
            self.state.response_prompt = None

    def _dispatch_prompt(self, role):
        from . import task_prompt
        prompt = task_prompt.build_self_evolve_prompt(
            self.state.phase_task,
            self.state.self_evolve_context,
            steps_used=max(0, self.state.round_no - self.state.self_evolve_started_round),
            timeout_rounds=self._timeout_rounds(),
            sop_hint=self._sop_hint(),
            skill_hint=self._skill_hint(),
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
        """只保留没有进程/业务错误的步骤；退出码0不能证明HTTP请求成功。"""
        steps, _, answer, _ = self._extract_experience()
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
            # These statuses were computed before output clipping, not inferred from a fragment.
            success_steps = [entry['command'] for entry in trace if entry['ok']]
            fail_steps = [entry['command'] for entry in trace if not entry['ok']]
        diags = sorted(getattr(self.state, "_self_evolve_diags", None) or [])
        return success_steps, fail_steps, answer, diags

    def _observed_schemas(self):
        return merged_strings([item.get('schema', '') for item in
                              getattr(self.state, 'self_evolve_command_trace', []) if item['ok']], limit=4)

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
            "schemas": self._observed_schemas(),
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
                # A later failed task can add lessons without replacing the proven solution.
                updates = {}
                for field in ('fail_steps', 'diags'):
                    if entry.get(field):
                        updates[field] = merged_strings(existing.get(field, []), entry[field])
                if updates:
                    self.state.self_evolve_sop[k] = {**existing, **updates}
                continue
            self.state.self_evolve_sop[k] = entry

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
        lines.append(f"上次成功的关键命令序列（{len(skill['steps'])} 条，按当前题目调整参数）：\n{steps}")
        lines.append('先读当前任务要求；同服务的已验证认证/参数/结构可复用，城市、路径、配置值和答案必须重新核对。')
        return "\n".join(lines)

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
        if not steps and not diags and not entry.get("fail_steps"):
            return None
        steps_block = "\n".join(f"  {i + 1}. {cmd}" for i, cmd in enumerate(steps))
        if entry.get("ok"):
            tip = ""
            if entry.get("answer"):
                tip = f"\n  最终提交答案参考：{entry['answer']}"
            return (
                "# 已知成功流程（SOP，复用方法并适配当前任务，不能直接抄答案）\n"
                f"历史成功步骤（{len(steps)} 条）：\n{steps_block}{tip}\n"
                "先读当前任务，替换城市、工作区、文件名、配置值等变量；历史答案只用于核对提交结构。"
                "若当前任务明确同一服务/接口，沿用已验证的认证与参数，不重复读取相同旧文档，"
                "不重试已否定的认证头和参数；只在当前响应出现新证据时更新。\n"
                + self._evidence_hint(entry)
            )
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
        if entry.get('schemas'):
            lines.append('已观察的JSON结构（需核对当前响应）：\n' + '\n'.join(entry['schemas']))
        return "\n".join(lines)

    @staticmethod
    def _evidence_hint(entry):
        lines = []
        if entry.get('schemas'):
            lines.append('已观察的JSON结构（path为逐层字段路径，字段名按此核对，勿猜别名）：\n'
                         + '\n'.join(entry['schemas']))
        if entry.get('diags'):
            lines.append('已有错误纠正与避坑信息：\n' + '\n'.join(entry['diags']))
        if entry.get('fail_steps'):
            lines.append('以下命令已观察到失败，不要原样执行：\n' + '\n'.join(entry['fail_steps'][:5]))
        return '\n'.join(lines)


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
