#!/usr/bin/env python3
"""从 CoreGeek 回放链接导出每回合的观察、响应和决策诊断。

用法：
    python replay_crawler/crawl.py "http://host:8768/turns.html?match=..."
    python replay_crawler/crawl.py "http://host:8768/turns.html?match=..." --side both

默认输出到本文件旁的 logs/<match-id>/，每种数据各一个 JSONL 文件。
每行包含 half、round、side、data 字段，便于按回合检索。
数据来自回放页使用的同站点 /api/matches 接口，无需逐次点击右箭头。
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator, TextIO


DEFAULT_URL = (
    "http://101.245.78.174:8768/turns.html"
    "?match=0df417d673710fe4e14f8b43&map=observed-growth-10"
)
SIDES = ("challenger", "defender")


def make_opener(use_system_proxy: bool) -> urllib.request.OpenerDirector:
    # 该回放服务可直连；某些本机环境的 HTTP_PROXY 指向不可用的占位端口。
    proxy = urllib.request.ProxyHandler() if use_system_proxy else urllib.request.ProxyHandler({})
    return urllib.request.build_opener(proxy)


def read_json(opener: urllib.request.OpenerDirector, url: str) -> Any:
    with opener.open(url, timeout=60) as response:
        return json.load(response)


def json_lines(opener: urllib.request.OpenerDirector, url: str) -> Iterator[dict[str, Any]]:
    with opener.open(url, timeout=120) as response:
        for line_number, raw in enumerate(response, 1):
            if raw.strip():
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{url} 第 {line_number} 行不是有效 JSON") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"{url} 第 {line_number} 行不是 JSON 对象")
                yield value


def safe_file_url(base: str, path: str) -> str:
    parts = path.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"清单包含非法路径：{path!r}")
    return base + "/files/" + "/".join(urllib.parse.quote(part, safe="") for part in parts)


def write_record(stream: TextIO, half: int, round_no: int, side: str, value: Any) -> None:
    json.dump(
        {"half": half, "round": round_no, "side": side, "data": value},
        stream,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    stream.write("\n")


def get_manifest(opener: urllib.request.OpenerDirector, base: str, half: int) -> dict[str, Any]:
    try:
        manifest = read_json(opener, f"{base}?half={half}")
    except urllib.error.HTTPError as exc:
        if exc.code != 413:
            raise
        # 与网页相同：完整回放超过 64 MiB 时使用该半场的精简清单。
        manifest = read_json(opener, f"{base}?compact=1&half={half}")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError(f"第 {half} 半场的清单格式不正确")
    return manifest


def find_path(manifest: dict[str, Any], expected: str) -> str | None:
    for item in manifest["files"]:
        if isinstance(item, dict) and item.get("path") == expected:
            return expected
    return None


def crawl_half(
    opener: urllib.request.OpenerDirector,
    base: str,
    streams: dict[str, TextIO],
    half: int,
    side_option: str,
    max_rounds: int | None,
) -> tuple[int, int]:
    manifest = get_manifest(opener, base, half)
    turns_path = find_path(manifest, f"half-{half}/turns.jsonl")
    decisions_path = find_path(manifest, f"half-{half}/strategy-decisions.jsonl")
    if turns_path is None:
        print(f"half-{half}: 清单没有 turns.jsonl，跳过", file=sys.stderr)
        return 0, 0

    selected_sides = SIDES if side_option == "both" else (side_option,)
    decisions: dict[tuple[int, str], list[dict[str, Any]]] = {}
    if decisions_path is not None:
        for decision in json_lines(opener, safe_file_url(base, decisions_path)):
            round_no, side = decision.get("round"), decision.get("side")
            if isinstance(round_no, int) and side in selected_sides:
                decisions.setdefault((round_no, side), []).append(decision)

    count = 0
    missing_diagnostics = 0
    for turn in json_lines(opener, safe_file_url(base, turns_path)):
        round_no = turn.get("round")
        if not isinstance(round_no, int) or round_no < 1:
            raise ValueError(f"第 {half} 半场存在无效回合号：{round_no!r}")
        for side in selected_sides:
            for field, output_type in (
                ("observations", "observations"),
                ("responses", "responses"),
            ):
                by_side = turn.get(field)
                if isinstance(by_side, dict) and side in by_side:
                    write_record(streams[output_type], half, round_no, side, by_side[side])
                else:
                    print(f"half-{half} round-{round_no} {side}: 缺少 {field}", file=sys.stderr)

            matched = decisions.get((round_no, side), [])
            if matched:
                # 原始日志可能在同一回合同一方包含多条决策，保留全部。
                write_record(
                    streams["diagnostics"], half, round_no, side,
                    matched[0] if len(matched) == 1 else matched,
                )
            else:
                missing_diagnostics += 1
        count += 1
        if max_rounds is not None and count >= max_rounds:
            break
    print(f"half-{half}: 导出 {count} 回合；缺少决策诊断 {missing_diagnostics} 份")
    return count, missing_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="回放页 URL")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "logs")
    parser.add_argument("--side", choices=(*SIDES, "both"), default="challenger")
    parser.add_argument("--half", type=int, choices=(1, 2), help="只导出指定半场；默认导出清单中的全部半场")
    parser.add_argument("--max-rounds", type=int, help="每半场最多导出多少回合，便于试运行")
    parser.add_argument("--use-system-proxy", action="store_true", help="使用系统代理；默认直连")
    args = parser.parse_args()
    if args.max_rounds is not None and args.max_rounds < 1:
        parser.error("--max-rounds 必须大于 0")

    parsed = urllib.parse.urlparse(args.url)
    query = urllib.parse.parse_qs(parsed.query)
    match_id = query.get("match", [None])[0]
    if parsed.scheme not in ("http", "https") or not parsed.netloc or not match_id:
        parser.error("请提供带有 match 参数的 http(s) 回放页 URL")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", match_id):
        parser.error("match ID 含有不安全字符")
    base = f"{parsed.scheme}://{parsed.netloc}/api/matches/{urllib.parse.quote(match_id, safe='')}"
    opener = make_opener(args.use_system_proxy)
    match_dir = args.output_dir / match_id

    first_half = args.half or int(query.get("half", [1])[0])
    manifest = get_manifest(opener, base, first_half)
    result_path = find_path(manifest, "result.json")
    halves = [first_half]
    if args.half is None and result_path:
        result = read_json(opener, safe_file_url(base, result_path))
        recorded = result.get("halves", []) if isinstance(result, dict) else []
        halves = sorted({h["half"] for h in recorded if isinstance(h, dict) and h.get("half") in (1, 2)}) or halves

    match_dir.mkdir(parents=True, exist_ok=True)
    names = ("observations", "responses", "diagnostics")
    temporary = {name: match_dir / f"{name}.jsonl.tmp" for name in names}
    total = 0
    with ExitStack() as stack:
        streams = {
            name: stack.enter_context(path.open("w", encoding="utf-8", newline="\n"))
            for name, path in temporary.items()
        }
        for half in halves:
            count, _ = crawl_half(opener, base, streams, half, args.side, args.max_rounds)
            total += count
    for name, path in temporary.items():
        path.replace(match_dir / f"{name}.jsonl")
    print(f"完成：{total} 回合，输出目录：{match_dir.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f"抓取失败：{error}", file=sys.stderr)
        raise SystemExit(1) from error
