"""Read task episodes and failure evidence from a debug log, without running commands."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from app.service.task_controller import _parse_llm_response
from app.service.task_evidence import inspect_result


def read_turns(path):
    text = path.read_text(encoding='utf-8-sig')
    marks = list(re.finditer(r'^\[R(\d+) day(\d+) tick(\d+) (DAY|NIGHT)\] gold=(\d+) score=(\d+)[^\n]*', text, re.M))
    turns = []
    for i, mark in enumerate(marks):
        block = text[mark.end():marks[i+1].start() if i+1 < len(marks) else len(text)]

        def field(name, end):
            match = re.search(r'^'+name+r'\s*:[ \t]*(.*?)(?=^'+end+r'\s*:)', block, re.M | re.S)
            return match.group(1).strip() if match else ''

        turns.append({'round': int(mark[1]), 'line': text.count('\n', 0, mark.start())+1,
                      'score': int(mark[6]), 'gold': int(mark[5]),
                      'phase': field('phaseTask', 'llmResp'), 'llm': field('llmResp', 'lastCmdResult'),
                      'result': field('lastCmdResult', 'prompt')})
    return turns


def analyze(path):
    turns = read_turns(path)
    episodes, episode, pending = [], None, None
    for turn in turns:
        if episode and turn['phase'] != episode['description']:
            episode['end_round'] = turn['round']
            episode['end_line'] = turn['line']
            episode['score_delta'] = turn['score'] - episode['start_score']
            episode['outcome_evidence'] = ('answer_then_score_increase' if episode['answer_rounds'] and episode['score_delta'] > 0
                                           else 'no_answer_before_phase_end' if not episode['answer_rounds'] else 'unconfirmed')
            episodes.append(episode)
            episode, pending = None, None
        if turn['phase'] and episode is None:
            episode = {'description': turn['phase'], 'start_round': turn['round'], 'start_line': turn['line'],
                       'start_score': turn['score'], 'answer_rounds': [], 'commands': []}
        if not episode:
            continue
        if turn['result'] and pending and pending['round'] == turn['round']-1:
            evidence = inspect_result(turn['result'])
            pending.update(result_round=turn['round'], result_line=turn['line'],
                           header=turn['result'].splitlines()[0], application_ok=evidence.ok,
                           diagnostics=list(evidence.diagnostics), observed_schema=evidence.schema)
            pending = None
        action, payload = _parse_llm_response(turn['llm'])
        if action == 'execute_command':
            pending = {'round': turn['round'], 'line': turn['line'],
                       'sha256': hashlib.sha256(payload.encode('utf-8')).hexdigest()}
            episode['commands'].append(pending)
        elif action == 'final_answer':
            episode['answer_rounds'].append(turn['round'])
    if episode:
        episode['outcome_evidence'] = 'log_ended_while_active'
        episodes.append(episode)
    return {'source': {'path': str(path), 'bytes': path.stat().st_size,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
            'round_count': len(turns), 'episodes': episodes,
            'summary': {'episodes': len(episodes),
                        'answer_then_score_increase': sum(e['outcome_evidence'] == 'answer_then_score_increase' for e in episodes),
                        'no_answer_before_phase_end': sum(e['outcome_evidence'] == 'no_answer_before_phase_end' for e in episodes),
                        'exit_zero_but_failed': sum(c.get('header') == '[exitCode:0]' and not c['application_ok']
                                                  for e in episodes for c in e['commands'] if 'application_ok' in c)},
            'scope': 'Read-only reference log analysis. Score changes are evidence, not current-version match results. '
                     'No full official action feedback exists in this log; timeout/completion causes are inferred. '
                     'Commands, answers and authentication values are not copied into this report.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = analyze(args.log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()
