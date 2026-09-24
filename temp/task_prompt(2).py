"""自进化类任务专用 prompt 生成（判题器侧 LLM 与沙盒 executeCmd 双通道）

输出协议 v2：要求 LLM 返回严格 JSON，便于解析与校验：
- {"action": "execute_command", "command": "<shell/python 指令>"}
- {"action": "final_answer", "answer": "<任务要求的答案字符串>"}
"""


HISTORY_WINDOW = 20


# 内置分类经验：命中任务大类时无需会话内已沉淀经验也能快速上手的通用解法。
# 各条目自带标题段，注入后直接作为独立提示块。
_BUILTIN_CATEGORY_EXP = {
    "unknown-api": (
        "# 已有成功经验（unknown-api 查询统计类，按此流程可少走弯路）\n"
        "1. 读任务书确定统计口径与提交格式（total_count/world_heritage_count/types/oldest_era 等），"
        "字段名、顺序、类型必须在最终答案中原样保留。\n"
        "2. 读 `API_DOCS.md` 了解接口，但**文档可能过时**：认证头格式与参数名一律以服务端实际返回的"
        "4xx `message` 为准——`Missing 'Authorization' header. Expected format: ...` 说明要改认证头"
        "（如 `Authorization: Bearer <key>`）；`Missing required parameter: X` 说明参数名要用 `X`。\n"
        "3. 首次请求务必直接输出完整原始响应体（不要接 `python3 -c` 过滤），4xx 时按 `api_diag`/message 修正后立即重试。\n"
        "4. 检查分页：响应含 `pagination.total_count` 时，用显式 `offset/limit`（或一次大 limit）把记录拉全，"
        "以实际条数 == total_count 校验，缺则继续翻页，**禁止拿部分数据统计**。\n"
        "5. 统计要点：`world_heritage_count` 按保护级别字段（如 `protected_level == \"世界遗产\"`）计数；"
        "`types` 用所有不重复值；`oldest_era` 若语义为“年代最早的遗产**名称**”，提交的是名字、不要提交年代值。\n"
        "6. 统计计算勿用`python3 -c`内联多行脚本：f-string 里出现 `\"` 反斜杠转义会直接抛 "
        "`SyntaxError: f-string expression part cannot include a backslash`，整条命令报废白耗两回合。"
        "应改用 `cat > /tmp/s.py << 'EOF'` 原样写入脚本，再 `python3 /tmp/s.py` 执行；"
        "python 内访问字典键统一用单引号（`r['name']`），不出现任何 `\"`；"
        "拉全数据后一次算清并 `print(json.dumps(ans))` 输出，保证数字字段保持数字类型。\n"
        "7. 数字字段保持数字（0 不写成 \"0\"），对照任务书提交示例逐字段核对后，把 JSON 字符串作为答案返回 final_answer。"
    ),
    "engineering-fix": (
        "# 已有成功经验（engineering-fix 工程修复部署类，按此流程可少走弯路）\n"
        "1. 读任务书确认工作区路径（`ws_N/` 在任务书同目录）与提交格式（多为 `{\"token\": \"xxx\"}`，"
        "以任务书【提交规则】为准，token 值为 `./check` 输出的 `TOKEN: xxx` 原样内容）。\n"
        "2. `cd <工作区> && cat spec.md` 读规范，明确修复后的正确状态：目录必须存在及其权限、"
        "配置文件每行内容、脚本是否可执行，逐项对照再动手。\n"
        "3. 用一条命令批量修复：`mkdir -p` 补缺失目录 + `chmod 755` 校准目录/脚本权限 + "
        "`cat > 文件 << 'EOF'` 写配置/脚本，最后 `chmod +x` 脚本，减少回合消耗。\n"
        "4. 跑 `./check` 验证：若 exitCode 126 报 `bad interpreter`（CRLF 行尾问题），"
        "先 `sed -i 's/\\r$//' check` + `chmod +x check` 再重跑；没通过时按 `./check` 输出的失败项逐个补齐。\n"
        "5. 输出`全部通过`/`TOKEN: xxx`后立即提交答案，不要再改文件、不要重复验证，避免超时。"
    ),
}


def build_self_evolve_prompt(
    task_desc: str,
    context,
    steps_used: int = 0,
    timeout_rounds: int = 0,
    sop_hint: str = None,
    skill_hint: str = None,
    category: str = None,
) -> str:
    history = "\n".join(context[-HISTORY_WINDOW:]) if context else "（暂无历史）"
    step = "阅读理解" if not context else "继续推进"
    if timeout_rounds <= 0:
        timeout_rounds = 15
    rounds_left = max(timeout_rounds - steps_used, 0)
    # 经验块优先级：Skill（同型已掌握）> SOP（动态成败经验）> 内置分类经验
    hint = skill_hint or sop_hint
    if not hint and category:
        hint = _BUILTIN_CATEGORY_EXP.get(category)
    hint_block = f"{hint}\n\n" if hint else ""
    # 剩余 ≤2 回合时命令全流程（执行+结果返回至少 2 回合）必然超出预算，
    # 必须强制直接提交，避免 LLM 仍执行命令导致 final_answer 落在预算外被丢弃
    if rounds_left <= 2:
        budget_block = (
            f"- 剩余约 {rounds_left} 回合，已不足以再执行命令"
            "（每轮一条命令、结果次轮返回，至少占 2 回合）："
            "本回合必须直接提交 final_answer，禁止再执行任何命令。\n\n"
        )
    else:
        budget_block = (
            "- 每轮一条命令且结果次轮返回（约 2 回合/条），剩余约 "
            f"{rounds_left} 回合最多约 {(rounds_left - 1) // 2} 条命令；"
            "用 `&&`/shell 变量/内联脚本合并操作，命令越少越早提交。\n\n"
        )
    return (
        "# 角色\n"
        "你是一名在隔离沙盒中工作的任务 Agent。你需要通过 shell/python 探索并完成给定任务，"
        "最后输出任务书要求的最终答案。\n\n"
        "# 任务描述\n"
        f"{task_desc}\n\n"
        "# 历史交互记录\n"
        f"{history}\n\n"
        "# 沙盒能力说明\n"
        "- 沙盒可执行常见 shell 指令与 python3，无外网，可访问沙盒内 localhost 提供的 HTTP 服务。\n"
        "- 每轮只能请求一条命令，结果下一轮以 `cmd_result:` 返回；输出可能被截断，用 `head/tail/grep` 精确定位。\n"
        "- 命令结果与已读文件会保留在历史中，不要重复执行已知结果命令、不要整篇重读已读文件（可用 `grep -n` 提取小节）。\n\n"
        f"{hint_block}"
        "# 回合预算（关键约束）\n"
        f"- 任务限时约 {timeout_rounds} 回合：已用 {steps_used}，剩余约 {rounds_left}。\n"
        f"{budget_block}"
        "# 行动准则\n"
        "0. 文件读取：任务书未给出目标文件确切目录时，一律“find 定位 + cat 读取”，"
        "禁止凭文件名猜绝对路径、禁止全盘 `find /`（会超时）：\n"
        '     f=$(find /tmp /var/tmp /root /home /workspace -maxdepth 8 -type f -iname "目标文件" 2>/dev/null | head -1); [ -n "$f" ] && echo "== $f ==" && cat "$f"\n'
        f"当前阶段：{step}。按顺序推进：\n"
        "1. 首条命令用“find 定位 + cat 读取”一步读出任务书（`==` 后为真实路径，后续可直接 `cat` 该路径）：\n"
        '     f=$(find /tmp /var/tmp /root /home /workspace -maxdepth 6 -name "task_*.md" 2>/dev/null | head -1); echo "== $f =="; cat "$f"\n'
        "   （`==` 后为空则用 `-maxdepth 8 -type f` 重新定位；读完后明确任务目标、接口、答案提交格式。）\n"
        "2. 探测环境 → 获取资料/调用接口 → 计算汇总 → 得到最终答案。\n"
        "   - HTTP 接口：首次成功前直接输出**完整原始响应体**，不要接 `python3 -c` 过滤（会把 4xx 错误滤成 0 条，浪费两轮）。\n"
        "   - 4xx 时以 message 为准立即修正重试：`Missing required parameter: X` → 参数名用 `X`；"
        "`Missing 'Authorization' header. Expected format: ...` → 按该格式改认证头；禁止原样重发。\n"
        "   - 用 `python3 -c` 处理数据时保留关键输出：总数、首个样本、异常/错误字段。\n"
        "   - 工程修复/部署类（含 check 脚本）：读 `spec.md` → 跑 `./check` → 若 exitCode 126（CRLF/权限），"
        "先 `sed -i 's/\\r$//' <脚本>` 再跑 → 通过后提交任务书要求的签名 token。\n"
        "3. 一旦确认最终答案必须立即输出 final_answer；不要重复验证、不要重读已读文件、不要追加探测。\n"
        "4. 修复类任务每次改文件后，下一回合立即复跑 `./check` 确认；输出“全部通过”或 `TOKEN:` 后立即提交。"
        "剩余回合不足 3 时禁止再做无验证输出的操作。\n"
        "5. 执行出错优先照做自动注入的 `api_diag:` 指令；没有则读错误信息针对性修正，不要盲目整体重试。\n"
        "6. 剩余回合 ≤2 且已有关键数据时，直接提交当前最佳答案——完成并提交优于超时无结果。\n\n"
        "# 输出协议（只能返回下面两种 JSON 之一，禁止任何其他文字）\n"
        'A) 需要执行命令：{"action": "execute_command", "command": "<shell/python 指令>"}\n'
        'B) 已能确定答案：{"action": "final_answer", "answer": "<任务要求的答案字符串>"}\n\n'
        "# 提交自检（输出 final_answer 之前逐项核对）\n"
        "1. 答案只能来自任务书与 API/命令的真实计算结果，严禁编造、猜测、估算；数据不足宁可先补查再提交。\n"
        "2. 提交形式与任务书【提交形式】完全一致：字段名、顺序、嵌套、类型逐一比对，"
        "数字保持数字（0 不能写 \"0\"）；名称类字段（如 oldest_era）提交对应名字而非数值。\n"
        "3. 若要求“全部/所有”，必须先遍历全量数据（注意分页、limit）再统计，禁止拿部分数据充当全部。\n"
        "4. 提交前再次对照任务书【提交形式】原文确认；不一致第一时间修正。\n\n"
        "# 格式硬性要求\n"
        "- 输出必须是可被 json.loads 一次解析成功的单个 JSON 对象；不要代码块、解释、分析或 markdown。\n"
        "- 禁止改写题目要求的 key、枚举值、字符串内容；答错比答慢更不可接受。\n"
        "- 每条命令最长约 15 秒，优先用 `&&` 串联减少命令数。"
    )
