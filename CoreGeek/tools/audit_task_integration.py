"""Read reference source/logs and check parsing only; never execute logged commands."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from app.service.task_service import controller_reply


def fingerprint(path):
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def functions(path):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    result = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, ast.FunctionDef):
                    result[f'{node.name}.{method.name}'] = ast.dump(method, include_attributes=False)
        elif isinstance(node, ast.FunctionDef):
            result[node.name] = ast.dump(node, include_attributes=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt', required=True, type=Path)
    parser.add_argument('--controller', required=True, type=Path)
    parser.add_argument('--log', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = {'scope': 'reference provenance and offline parsing; no shell/LLM/game execution',
              'sources': [fingerprint(args.prompt), fingerprint(args.controller)]}
    before = functions(args.controller)
    after = functions(ROOT / 'app/service/task_controller.py')
    report['controller_functions'] = {
        'unchanged': sorted(k for k in before if after.get(k) == before[k]),
        'adapted': sorted(k for k in before if k in after and after[k] != before[k]),
        'added': sorted(set(after) - set(before)), 'removed': sorted(set(before) - set(after))}
    if args.log:
        report['sources'].append(fingerprint(args.log))
        text = args.log.read_text(encoding='utf-8-sig')
        counts, invalid, nonempty = Counter(), [], 0
        for match in re.finditer(r'^llmResp\s*:[ \t]*(.*?)(?=^lastCmdResult\s*:)', text, re.M | re.S):
            raw = match.group(1).strip()
            if not raw:
                continue
            nonempty += 1
            parsed = controller_reply(raw)
            if parsed:
                counts[json.loads(parsed)['action']] += 1
            else:
                invalid.append(text.count('\n', 0, match.start())+1)
        report['log_parsing'] = {'nonempty_llm_responses': nonempty, 'accepted_actions': dict(counts),
            'unparsed_line_numbers': invalid,
            'note': 'Parsing success is not answer correctness or this version completing a match.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
