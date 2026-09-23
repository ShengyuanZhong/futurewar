"""Classify observed sandbox feedback and remember shape, never execute commands."""
from dataclasses import dataclass
import json
import re

from agent.protocol import CommandResult
from .task_context import diagnose


@dataclass(frozen=True)
class ResultEvidence:
    ok: bool
    diagnostics: tuple[str, ...]
    schema: str = ''


def response_schema(value) -> str:
    """Bounded JSON field names and types without record values or task answers."""
    objects, arrays = [], []

    def kind(item):
        if isinstance(item, dict):
            return 'object'
        if isinstance(item, list):
            return 'array'
        if item is None:
            return 'null'
        if isinstance(item, bool):
            return 'boolean'
        return 'string' if isinstance(item, str) else 'number'

    def walk(item, path, depth=0):
        if depth > 4 or len(objects)+len(arrays) >= 12:
            return
        if isinstance(item, dict):
            names = sorted(item)[:20]
            objects.append({'path': path, 'fields': {k[:80]: kind(item[k]) for k in names}})
            for name in names:
                if isinstance(item[name], (dict, list)):
                    walk(item[name], path+[name[:80]], depth+1)
        elif isinstance(item, list):
            samples = item[:3]
            names = sorted({k for row in samples if isinstance(row, dict) for k in row})[:20]
            arrays.append({'path': path, 'item_types': sorted({kind(x) for x in samples}),
                           'sample_fields': [k[:80] for k in names]})

    walk(value, [])
    return json.dumps({'objects': objects, 'arrays': arrays}, ensure_ascii=False, separators=(',', ':'))


def inspect_result(raw: str) -> ResultEvidence:
    """Exit zero alone does not confirm an API call, pipeline or check succeeded."""
    result = CommandResult.load(raw)
    failed, generic = diagnose(result)
    hints = [line.removeprefix('api_diag: ') for line in generic.splitlines() if line]
    if re.search(r'(?m)^(?:/bin/)?(?:bash|sh):[^\n]*bad interpreter:', result.output):
        failed = True
        hints.append('解释器启动失败，即使被|| true掩盖为exitCode 0也未完成验证；'
                     '检查脚本首行和CRLF换行，修复后重新运行check。')
    if re.search(r"AttributeError:\s*'str' object has no attribute 'get'", result.output):
        failed = True
        hints.append('检测到把对象当作列表遍历的风险：遍历dict会得到字符串键。先输出type/keys，'
                     '根据实际响应定位记录数组，确认isinstance(records, list)及每项是dict后再统计。'
                     '这是JSON结构/解析问题；没有新的401/400证据时不要改回旧认证头或旧请求参数。')
    if re.search(r'(?:/bin/)?(?:bash|sh):[^\n]*syntax error', result.output):
        failed = True
        hints.append('shell语法错误可能来自python3 -c外层单引号被内部撇号截断。'
                     '多行Python改用带引号的heredoc或脚本文件；curl结果先存文件，'
                     '不要让heredoc脚本与json.load(sys.stdin)争用stdin。')
    if 'JSONDecodeError:' in result.output:
        failed = True
        hints.append('JSON解码失败：先保留并查看响应原文与状态，确认不是错误页、空输出或stdin被脚本占用；'
                     '不要用空列表替代未解析的数据，也不要把解析失败当成零条记录。')
    if 'Traceback (most recent call last):' in result.output:
        failed = True
    schema = ''
    if result.exit_code == 0 and not failed and not result.truncated:
        try:
            body = json.loads(result.output)
        except (ValueError, TypeError, RecursionError):
            body = None
        if isinstance(body, (dict, list)):
            schema = response_schema(body)
    return ResultEvidence(result.exit_code == 0 and not failed, tuple(dict.fromkeys(hints)), schema)


def merged_strings(*groups, limit=10) -> list[str]:
    """Keep the newest distinct evidence, in observation order."""
    values = list(dict.fromkeys(item for group in groups for item in group if item))
    return values[-limit:]
