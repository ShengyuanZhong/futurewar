"""Real HTTP: finish tasks, buy, reveal enemy layout with a worker, then summon.

The map and task verdicts are synthetic. Private ground truth is filtered by
ordinary range-four friendly sight on every request. BOSS robots never reveal
guns/characters, and executeCmd is asserted empty rather than executed.
"""
import argparse
import copy
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from agent.protocol import CONTROLLABLE_TYPES, TOWER_TYPES, Pos, Turn, distance
from tests.fixtures import request, robot, unit
from tools.smoke_first_day_flow import task_frame
from tools.validate import independent_planning_clear
from tests.test_layout_survey import (SCOUT, HOME, PIONEER, actor, enemy_blueprint, reveal,
                                     survey_request)

ORDER = 'BossRobotSummonOrder'


def fixture(name, pattern, mirror_x, mirror_y):
    raw, _ = survey_request(1)
    raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                              if not (u['roleType']=='wall' and u['pos']==Pos(5,9).dump())]
    raw['teamOur'].update(teamId='scout-flow-' + name, goldNum=400, totalScore=0)
    actor(raw, PIONEER)['pos'] = Pos(2, 6).dump()
    actor(raw, HOME).update(pos=Pos(6,8).dump(),backpack=['stone']+['WallFixer']*5)
    actor(raw, SCOUT)['pos'] = Pos(3,6).dump()
    raw['teamOur']['playerTasks'] = copy.deepcopy(request()['teamOur']['playerTasks'])
    for index, pos in enumerate((Pos(1, 7), Pos(1, 6))):
        raw['teamOur']['playerTasks'][index].update(taskPosition=pos.dump(), timeoutRounds=12,
            scoreReward=51-index, goldReward=100, isValid=True, coldDownRounds=0)
    raw['mapInfo']['zones'] += [{'neutralType': kind, 'pos': pos.dump()} for kind, pos in
        (('challengerTaskPoint1', Pos(1, 7)), ('challengerTaskPoint2', Pos(1, 6)),
         ('challengerTaskPoint2', Pos(1, 5)))]
    truth = enemy_blueprint(pattern, mirror_x=mirror_x, mirror_y=mirror_y)
    return reveal(raw, truth), truth


def ordinary_sight(raw):
    turn = Turn.load(raw)
    return {p for u in turn.ours if u.health > 0
            and u.kind in CONTROLLABLE_TYPES + TOWER_TYPES + ('station', 'wall')
            for p in (u.pos,)}


def apply(raw, truth, commands, spawns):
    """Small evidence driver, not a full official game simulator."""
    before = Turn.load(raw)
    actors = {str(u['id']): u for u in raw['teamOur']['roles']}
    actors.update((str(u['id']), u) for u in raw['teamOur']['summonRobotList'])
    destinations, hits = set(), []
    for uid, command in commands.items():
        action = command['action']
        if action == 'move':
            target = Pos.load(command['targetPos'][0])
            assert distance(Pos.load(actors[uid]['pos']), target) == 1
            assert target not in before.occupied_cells() and target not in destinations
            assert target not in {r.pos for r in before.robots}
            destinations.add(target)
        elif action == 'attack' and uid in {str(r.robot_id) for r in before.summon_robots}:
            # The request, not private truth or an inferred control cell, must
            # contain the live victim. Check diagonal wall LOS independently.
            target = Pos.load(command['targetPos'][0])
            victim = next((u for u in before.enemies if u.health > 0
                           and target in before.footprint(u)), None)
            assert victim is not None, ('unseen attack', uid, target)
            assert 0 < distance(Pos.load(actors[uid]['pos']), target) <= 3
            assert independent_planning_clear(raw,Pos.load(actors[uid]['pos']),target)
            if victim.kind in ('worker', 'pioneer'):
                assert any(distance(p, target) <= 4 for p in ordinary_sight(raw))
            hits.append((victim.unit_id, 40))
    for uid, command in commands.items():
        item = actors.get(uid)
        action = command['action']
        if action == 'move':
            item['pos'] = command['targetPos'][0]
        elif action == 'buy':
            count = command.get('num', 1)
            raw['teamOur']['goldNum'] -= before.shop_prices[command['name']] * count
            assert raw['teamOur']['goldNum'] >= 0
            item['backpack'] += [command['name']] * count
        elif action == 'use':
            name = command['name']
            item['backpack'].remove(name)
            if name == ORDER:
                point = command['targetPos'][0]
                assert point not in spawns
                spawns.append(point)
            elif 'UpgradeVoucher' in name:
                target = next(u for u in raw['teamOur']['roles'] if u['pos'] == command['targetPos'][0])
                target['level'] += 1
                target['health'] = 500 + 500 * target['level']
            elif name == 'WallFixer':
                target = next(u for u in raw['teamOur']['roles'] if u['pos'] == command['targetPos'][0])
                target['health'] = min(500 + 500 * target['level'], target['health'] + 1000)
        elif action == 'collect':
            item['backpack'].append(before.zones[Pos.load(command['targetPos'][0])])
        elif action == 'sell':
            count = command['num']
            raw['teamOur']['goldNum'] += before.vendor_prices[command['name']] * count
            for _ in range(count):
                item['backpack'].remove(command['name'])
        elif action == 'remove':
            assert before.is_day
            wall = next(u for u in raw['teamOur']['roles']
                        if u['roleType']=='wall' and u['pos']==command['targetPos'][0])
            raw['teamOur']['roles'].remove(wall)
        elif action == 'build':
            assert before.is_day and command['name']=='wall' and 'stone' in item['backpack']
            point = Pos.load(command['targetPos'][0])
            assert point not in before.occupied_cells() and distance(Pos.load(item['pos']),point)==1
            item['backpack'].remove('stone')
            new_id = max(u['id'] for u in raw['teamOur']['roles'])+1
            raw['teamOur']['roles'].append(unit(new_id,'wall',point.x,point.y,health=1000))
        elif action in ('acceptTask', 'submitAnswer', 'attack'):
            pass
        else:
            raise AssertionError(('unmodelled action', uid, command))
    # Damage is simultaneous, never let the first robot erase the second's
    # visible target before this driver's end-of-turn settlement.
    for uid, damage in hits:
        target = next(u for u in truth if u['id'] == uid)
        target['health'] = max(0, target['health'] - damage)
    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
    raw['lastRoundRoleActionResults'] = {uid: True for uid in commands}


def diagnostics(logs):
    rows = []
    for line in logs.splitlines():
        for marker in ('raid_survey ', 'first_day_policy ', 'robot_diagnostic '):
            if marker in line:
                try:
                    data = json.loads(line.split(marker, 1)[1])
                    if marker == 'robot_diagnostic ':
                        data = {key: data.get(key) for key in ('round', 'team_id', 'robot', 'reason',
                            'stage', 'selected', 'candidates', 'final_command', 'accepted', 'rejections')}
                    rows.append({'kind': marker.strip(), 'data': data})
                except json.JSONDecodeError:
                    pass
                break
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    capture = tempfile.TemporaryFile()
    process = subprocess.Popen([sys.executable, str(ROOT / 'main3.py'), str(port)], cwd=ROOT.parent,
        stdout=subprocess.DEVNULL, stderr=capture, creationflags=flags)
    rows, cases, failure = [], [], None
    try:
        deadline = time.monotonic() + 5
        while True:
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
            try:
                conn.request('GET', '/health'); response = conn.getresponse(); response.read()
                if response.status == 200:
                    break
            except (OSError, http.client.HTTPException):
                if time.monotonic() >= deadline:
                    raise RuntimeError('CLI did not start')
                time.sleep(.05)
            finally:
                conn.close()
        for name, pattern, mx, my in (
            ('drawing1', 'corner_closed', False, False),
            ('drawing2', 'corner_gap', False, False),
            ('drawing3-reflected', 'corner_closed_low', True, True),
            ('drawing4-reflected', 'vertical_gap', True, False)):
            raw, truth = fixture(name, pattern, mx, my)
            spawns, first_use, buy_round, crew_attacks = [], None, None, []
            waited_for_scout = False
            buyer_walked = False
            for number in range(1, 131):
                task_frame(raw,number,(True,True,True))
                if number == 71:
                    assert len(spawns) == 3, (name, 'not deployed', spawns)
                    assert len([u for u in raw['teamOur']['roles']
                                if u['roleType']=='wall' and u['health']>0])==17
                    occupied = Turn.load(raw).occupied_cells()
                    assert all(Pos.load(p) not in occupied for p in spawns), ('spawn needs displacement', name)
                    raw['teamOur']['summonRobotList'] = [robot(30005+i, p['x'], p['y'],
                        roleType='bossRobot', health=800) for i, p in enumerate(spawns)]
                    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
                reveal(raw, truth)
                visible = [{'id': u['id'], 'kind': u['roleType'], 'pos': u['pos'], 'hp': u['health']}
                           for u in raw['teamEnemy']['roles'] if u['roleType'] not in ('station', 'wall')]
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                try:
                    start = time.perf_counter()
                    conn.request('POST', '/', json.dumps(raw).encode(), {'Content-Type': 'application/json'})
                    response = conn.getresponse(); result = json.loads(response.read())
                    elapsed = (time.perf_counter() - start) * 1000
                    assert response.status == 200
                    assert set(result) == {'roleCommandMap', 'prompt', 'executeCmd'}
                    assert not result['executeCmd']
                    commands = result['roleCommandMap']
                    if number<37 and commands.get(str(HOME),{}).get('action')=='move':
                        buyer_walked = True
                    assert not any(c.get('name')==ORDER for uid,c in commands.items() if uid!=str(HOME)),commands
                    assert ORDER not in actor(raw,PIONEER)['backpack']
                    if number < 37:
                        assert not any(c.get('name') == ORDER for c in commands.values())
                        assert not any(c['action']=='buy' and c.get('name','').startswith('WeaponUpgradeVoucher')
                                       for c in commands.values())
                    if number in (1,4,34):
                        assert commands[str(PIONEER)]['action']=='acceptTask',commands
                    if number in (3,6,36):
                        assert commands[str(PIONEER)]['action']=='submitAnswer',commands
                    if number == 37:
                        assert commands[str(HOME)] == {'action': 'buy', 'name': ORDER, 'num': 3}, commands
                        buy_round = number
                    uses = [c for c in commands.values() if c.get('name') == ORDER and c['action'] == 'use']
                    if uses:
                        if first_use is None:
                            first_use = number
                        assert len([u for u in visible if u['kind'] in TOWER_TYPES]) == 3
                        assert actor(raw, SCOUT)['health'] > 0
                        operator = next(u for u in truth if u['id'] == 994)
                        assert distance(Pos.load(actor(raw, SCOUT)['pos']), Pos.load(operator['pos'])) <= 4
                    elif number > 37 and len(spawns) < 3 and actor(raw, HOME)['backpack'].count(ORDER):
                        waited_for_scout = True
                    for uid, command in commands.items():
                        if uid in ('30005', '30006', '30007') and command['action'] == 'attack':
                            target = command['targetPos'][0]
                            if any(u['pos'] == target and u['kind'] in ('worker', 'pioneer') for u in visible):
                                crew_attacks.append({'round': number, 'robot': uid, 'target': target})
                    rows.append(dict(case=name, round=number, status=response.status,
                        elapsed_ms=round(elapsed, 3), gold=raw['teamOur']['goldNum'],
                        scout={'pos': copy.deepcopy(actor(raw, SCOUT)['pos']), 'hp': actor(raw, SCOUT)['health']},
                        boss_buyer={'id':HOME,'kind':'worker','pos':copy.deepcopy(actor(raw,HOME)['pos']),
                                    'held_orders':actor(raw,HOME)['backpack'].count(ORDER)},
                        ordinary_sight_origins=[p.dump() for p in sorted(ordinary_sight(raw))],
                        visible_enemy_roles=visible, commands=commands, prompt_chars=len(result['prompt'])))
                    apply(raw, truth, commands, spawns)
                finally:
                    conn.close()
            assert buy_round == 37 and first_use > buy_round
            assert len(spawns) == 3 and len({(p['x'],p['y']) for p in spawns})==3
            assert crew_attacks, (name, 'no visible crew attacks')
            assert actor(raw, HOME)['health'] > 0
            assert buyer_walked,(name,'buyer did not walk from home to the shop')
            cases.append(dict(case=name, pattern=pattern, mirror_x=mx, mirror_y=my, buy_round=buy_round,
                first_use_round=first_use, waited_for_scout=waited_for_scout, spawns=spawns,
                crew_attacks=crew_attacks, home_worker_id=HOME))
    except Exception as error:
        failure = error
    finally:
        process.terminate(); process.wait(timeout=3)
        capture.seek(0); logs = capture.read().decode('utf-8', errors='replace'); capture.close()
    if failure is None and 'action_rejected' in logs:
        failure = AssertionError('HTTP process logged action_rejected')
    report = dict(scope='Synthetic map, task answers, verdicts and damage over real HTTP; not an official match',
        task_sequence=[2,1,2],accepted_rounds=[1,4,34],boss_buyer_id=HOME,scout_id=SCOUT,
        visibility='Only living ordinary friendly units supply range-four sight; enemy base/wall global; BOSS no sight',
        requests=len(rows), cases=cases, results=rows, diagnostics=diagnostics(logs),
        bind_verified=f'0.0.0.0:{port}' in logs, execute_cmd_executed=False,
        failure=repr(failure) if failure is not None else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if failure is not None:
        raise failure
    print(json.dumps({'requests': len(rows), 'cases': [c['case'] for c in cases], 'all_http_200': True,
                      'first_use_rounds': [c['first_use_round'] for c in cases]}))


if __name__ == '__main__':
    main()
