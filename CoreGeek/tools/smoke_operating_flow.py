"""Local HTTP flow from a built first-night home through day-three operation.

The local applier models successful economic actions and one failed removal.
It does not model opposing tactics, mine respawns, official tasks or scoring.
"""
import argparse
from collections import Counter
import copy
import http.client
import json
import logging
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from agent.protocol import Pos, Turn
from app.config import Settings
from app.server import AgentServer
from app.service.turn_service import TurnService
from tests.fixtures import unit
from tests.test_operating_home import scene, actor, OPERATING, CLOSURES
from tests.test_u_layout import point
from tools.validate import independent_contract


def apply(raw, response, fail_remove=False):
    turn = Turn.load(raw)
    feedback = {}
    for uid, command in response['roleCommandMap'].items():
        role = actor(raw, int(uid))
        action, name = command['action'], command.get('name')
        feedback[uid] = not (action == 'remove' and fail_remove)
        if not feedback[uid]:
            fail_remove = False
            continue
        if action == 'move':
            role['pos'] = command['targetPos'][-1]
        elif action == 'remove':
            raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                if not (u['roleType'] == 'wall' and u['pos'] == command['targetPos'][0])]
        elif action == 'collect':
            role['backpack'].append(turn.zones[Pos.load(command['targetPos'][0])])
        elif action == 'buy':
            role['backpack'] += [name] * command.get('num', 1)
            raw['teamOur']['goldNum'] -= turn.shop_prices[name] * command.get('num', 1)
        elif action == 'sell':
            for _ in range(command['num']):
                role['backpack'].remove(name)
            raw['teamOur']['goldNum'] += turn.vendor_prices[name] * command['num']
        elif action == 'use':
            role['backpack'].remove(name)
            target = next(u for u in raw['teamOur']['roles'] if u['pos'] == command['targetPos'][0])
            if name != 'WallFixer':
                target['level'] += 1
            target['health'] = 500 + 500 * target['level']
        elif action == 'build':
            assert name == 'wall'
            role['backpack'].remove('stone')
            pos = command['targetPos'][0]
            raw['teamOur']['roles'].append(unit(10000 + raw['roundNo'], 'wall', **pos, health=1000))
        else:
            raise AssertionError(f'unexpected action {command}')
    assert raw['teamOur']['goldNum'] >= 0
    raw['lastRoundRoleActionResults'] = feedback


def run_case(port, service, mirrored):
    raw = scene(130, mirrored=mirrored, closed=True)
    raw['teamOur']['teamId'] = 'operating-http-' + str(mirrored)
    raw['teamOur']['goldNum'] = 5000
    raw['weaponShopList'][-2]['price'] = 15  # v2.0 WallFixer price.
    raw['vendorShopList'] = [{'name': 'stone', 'price': 1}]
    trace, counts = [], Counter()
    failed, restored, upgraded = False, None, None
    for number in range(130, 332):
        raw['roundNo'] = number
        if number == 331:
            for y in (7, 6):
                target = point(9, y, mirrored).dump()
                next(u for u in raw['teamOur']['roles']
                     if u['roleType'] == 'wall' and u['pos'] == target)['health'] = 599
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        conn.request('POST', '/', json.dumps(raw).encode('utf-8'), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        assert response.status == 200
        reply = json.loads(response.read())
        conn.close()
        independent_contract(raw, reply)
        commands = reply['roleCommandMap']
        if number == 130:
            assert all(c['action'] != 'remove' for c in commands.values())
        remove = any(c['action'] == 'remove' for c in commands.values())
        if not failed and remove:
            fail = True
            failed = True
        else:
            fail = False
        for command in commands.values():
            counts[command['action'] + ':' + command.get('name', '')] += 1
            assert command.get('name') != 'BossRobotSummonOrder'
        trace.append(dict(round=number, commands=copy.deepcopy(commands), failed_remove=fail))
        apply(raw, reply, fail)
        walls = {w.pos for w in Turn.load(raw).walls()}
        if restored is None and walls == {point(x, y, mirrored) for x, y in OPERATING}:
            restored = number
        if upgraded is None and all(u['level'] == 3 for u in raw['teamOur']['roles'] if u['roleType'] == 'rocket'):
            front = {point(9, y, mirrored) for y in range(4, 10)}
            if all(w.level == (3 if w.pos in front else 2) for w in Turn.load(raw).walls()):
                upgraded = number
        if number == 331:
            for uid in ('501', '504'):
                assert commands[uid]['action'] == 'use' and commands[uid]['name'] == 'WallFixer', commands
            assert commands['501']['targetPos'] != commands['504']['targetPos']
    assert restored is not None and upgraded is not None
    assert counts['collect:'] > 0 and counts['sell:stone'] > 0 and counts['buy:WallFixer'] > 0
    assert len(Turn.load(raw).walls()) == 12
    assert not {point(x, y, mirrored) for x, y in CLOSURES} & {w.pos for w in Turn.load(raw).walls()}
    state = next(s.memory for key, s in service.sessions.items() if key[0] == raw['teamOur']['teamId'])
    assert state.operating_home['status'] == 'operating'
    return dict(mirrored=mirrored, requests=len(trace), restored_round=restored,
                upgraded_round=upgraded, action_counts=dict(counts), trace=trace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    service = TurnService(Settings(enable_tasks=False, enable_news=False))
    server = AgentServer(('127.0.0.1', 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        scenarios = [run_case(server.server_port, service, mirrored) for mirrored in (False, True)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    report = dict(scope='Local HTTP R130-R331 in both horizontal mirrors, not official matches',
                  assumptions=['Initially built first-day defenses, synthetic fixed shop and stone mine',
                               'No hostile robots, official scoring, mine depletion/respawns or moving enemies',
                               'All economic actions succeed except the first removal; task/news LLM disabled'],
                  scenarios=scenarios)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps([dict(mirrored=s['mirrored'], requests=s['requests'], restored=s['restored_round'],
                           upgraded=s['upgraded_round']) for s in scenarios]))


if __name__ == '__main__':
    main()
