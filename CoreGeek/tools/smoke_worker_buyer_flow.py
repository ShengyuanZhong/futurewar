"""First-day HTTP evidence: an exterior worker travels to a fixed real shop.

Two synthetic base positions share the same shop. Ordinary observations,
actual movement/bag feedback and Task2 -> Task1 -> Task2 drive the server's
memory; this tool never seeds private memory or executes executeCmd. The
initial completed construction, local pioneer task positions and already
arrived scout are fixture assumptions, not an official opening replay.
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
from agent.protocol import Pos, Turn, distance
from tests.fixtures import request, robot, unit
from tests.test_layout_survey import reveal
from tests.test_worker_boss_buyer import (BUYER, ORDER, PIONEER, SCOUT, SHOP,
                                        actor, worker_raid_scene)
from tools.smoke_first_day_flow import task_frame
from tools.smoke_scout_flow import apply, diagnostics, ordinary_sight


def fixture(lower_right, unfinished=False):
    raw, _, settings = worker_raid_scene(round_no=1, lower_right=lower_right, finished=0)
    name = 'lower-right' if lower_right else 'upper-left'
    raw['teamOur'].update(teamId='worker-buyer-nonsymmetric-' + name, totalScore=0,
                          summonRobotList=[])
    base = Pos.load(actor(raw, 503)['pos'])
    exterior_start = Pos(base.x+(3 if lower_right else -2),base.y+2)
    actor(raw, BUYER)['pos'] = exterior_start.dump()
    actor(raw, PIONEER)['pos'] = Pos(16, 14).dump()
    raw['teamOur']['playerTasks'] = copy.deepcopy(request()['teamOur']['playerTasks'])
    for index, point in enumerate((Pos(15, 15), Pos(15, 14))):
        raw['teamOur']['playerTasks'][index].update(taskPosition=point.dump(), timeoutRounds=12,
            scoreReward=51-index, goldReward=100, isValid=True, coldDownRounds=0)
    raw['mapInfo']['zones'] += [dict(neutralType=kind, pos=point.dump()) for kind, point in (
        ('challengerTaskPoint1', Pos(15, 15)), ('challengerTaskPoint2', Pos(15, 14)),
        ('challengerTaskPoint2', Pos(15, 13)))]
    truth = copy.deepcopy(raw['teamEnemy']['roles'])
    enemy = next(u for u in truth if u['roleType'] == 'station')
    left_enemy = lower_right
    operator = Pos(enemy['pos']['x'] + (-2 if left_enemy else 3), enemy['pos']['y'])
    truth.append(unit(994, 'worker', operator.x, operator.y, health=500))
    gate = Pos(base.x + (2 if lower_right else -1), base.y + 2)
    control = settings.default_operator_position(Turn.load(raw))
    assert len(Turn.load(raw).weapons()) == 3 and len(Turn.load(raw).walls()) == 17
    assert exterior_start not in {p for u in Turn.load(raw).ours if u.unit_id != BUYER
                               for p in Turn.load(raw).footprint(u)}
    assert SHOP not in {Pos.load(u['pos']) for u in raw['teamOur']['roles']}
    if unfinished:
        # This variant begins with seven ordinary walls still unbuilt and
        # stone far from both homes. The second worker performs real mining
        # and construction; an ordinary IMP supplies the enemy sight.
        missing = {u['id'] for u in raw['teamOur']['roles'] if u['roleType']=='wall'}
        missing = set(sorted(missing)[:7])
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['id'] not in missing]
        actor(raw,SCOUT)['pos'] = Pos(base.x+(-3 if lower_right else 4),base.y-2).dump()
        for zone in raw['mapInfo']['zones']:
            if zone['neutralType']=='stone':
                zone['pos'] = Pos(1,1).dump()
        imp_pos = Pos(enemy['pos']['x']+(-5 if lower_right else 6),enemy['pos']['y']-2)
        raw['teamOur']['roles'].append(unit(505,'imp',imp_pos.x,imp_pos.y,health=500))
    name += '-unfinished' if unfinished else ''
    raw['teamOur']['teamId'] = 'worker-buyer-nonsymmetric-'+name
    return raw, truth, dict(case=name, base=base.dump(), shop=SHOP.dump(),
        former_gate=gate.dump(), buyer_initial=exterior_start.dump(), pioneer_control=control.dump(),
        scout_initial=copy.deepcopy(actor(raw, SCOUT)['pos']),
        pioneer_initial=copy.deepcopy(actor(raw, PIONEER)['pos']),unfinished=unfinished,
        initial_wall_count=len(Turn.load(raw).walls()))


def post(port, raw):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        started = time.perf_counter()
        conn.request('POST', '/', json.dumps(raw).encode(), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        result = json.loads(response.read())
        elapsed = (time.perf_counter() - started) * 1000
        assert response.status == 200, result
        assert set(result) == {'roleCommandMap', 'prompt', 'executeCmd'}
        assert not result['executeCmd'], 'executeCmd must stay empty and is never executed here'
        return result, elapsed
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unfinished', action='store_true',
                        help='Exercise purchase deadlines before seven ordinary walls finish')
    parser.add_argument('--lost-sight', action='store_true',
                        help='After actual three-gun observations, the scout dies at R7; use must rely on cached static layout.')
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
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
                conn.request('GET', '/health')
                response = conn.getresponse()
                response.read()
                if response.status == 200:
                    break
            except (OSError, http.client.HTTPException):
                if time.monotonic() >= deadline:
                    raise RuntimeError('CLI did not start')
                time.sleep(.05)
            finally:
                conn.close()
        for lower_right in (False, True):
            raw, truth, summary = fixture(lower_right,args.unfinished)
            spawns, buys, uses, accepts, gate_crossings = [], [], [], [], []
            shop_arrival, first_return, control_arrival = None, None, None
            for number in range(1, 72):
                task_frame(raw, number, (True, True, True))
                if args.lost_sight and number>=7:
                    actor(raw,SCOUT)['health']=0
                reveal(raw, truth)
                buyer_before = Pos.load(actor(raw, BUYER)['pos'])
                pioneer_before = Pos.load(actor(raw, PIONEER)['pos'])
                if distance(buyer_before, SHOP) <= 1 and shop_arrival is None:
                    shop_arrival = number
                if number == 71:
                    assert len(spawns) == 3, (summary['case'], 'three orders were not deployed', spawns)
                    occupied = Turn.load(raw).occupied_cells()
                    assert all(Pos.load(p) not in occupied for p in spawns), 'fixture needs displacement'
                    raw['teamOur']['summonRobotList'] = [robot(30005+i, p['x'], p['y'],
                        roleType='bossRobot', health=800) for i, p in enumerate(spawns)]
                    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
                result, elapsed = post(port, raw)
                commands = result['roleCommandMap']
                pioneer_command = commands.get(str(PIONEER), {})
                buyer_command = commands.get(str(BUYER), {})
                assert ORDER not in actor(raw, PIONEER)['backpack']
                assert not any(c.get('name') == ORDER for uid, c in commands.items() if uid != str(BUYER))
                if number in (1, 4, 34):
                    assert pioneer_command.get('action') == 'acceptTask', (number, commands)
                    accepts.append(dict(round=number, task={1:2, 4:1, 34:2}[number]))
                if number in (3, 6, 36):
                    assert pioneer_command.get('action') == 'submitAnswer', (number, commands)
                if number < 37:
                    assert not any(c.get('name') == ORDER for c in commands.values())
                if buyer_command.get('action') == 'buy' and buyer_command.get('name') == ORDER:
                    assert number >= 37 and distance(buyer_before, SHOP) <= 1
                    buys.append(dict(round=number, actor=BUYER, num=buyer_command.get('num', 1),
                                     pos=buyer_before.dump()))
                if buyer_command.get('action') == 'use' and buyer_command.get('name') == ORDER:
                    operator = next(u for u in truth if u['id'] == 994)
                    if args.lost_sight:
                        assert not any(u['roleType'] in ('worker','pioneer','rocket','railgun','gatling')
                                       for u in raw['teamEnemy']['roles'])
                        assert not any(distance(p,Pos.load(operator['pos']))<=4 for p in ordinary_sight(raw))
                    else:
                        assert any(distance(p, Pos.load(operator['pos'])) <= 4 for p in ordinary_sight(raw))
                        assert any(u['id'] == 994 for u in raw['teamEnemy']['roles'])
                    uses.append(dict(round=number, actor=BUYER, target=buyer_command['targetPos'][0]))
                if number >= 37 and first_return is None and pioneer_command.get('action') == 'move':
                    first_return = number
                if number >= 37 and pioneer_before.dump() == summary['pioneer_control'] and control_arrival is None:
                    control_arrival = number
                if buyer_command.get('action') == 'move' and summary['former_gate'] in buyer_command['targetPos']:
                    gate_crossings.append(number)
                rows.append(dict(case=summary['case'], round=number, status=200,
                    elapsed_ms=round(elapsed, 3), gold=raw['teamOur']['goldNum'],
                    buyer=dict(id=BUYER, pos=buyer_before.dump(), held_orders=actor(raw, BUYER)['backpack'].count(ORDER)),
                    pioneer=dict(id=PIONEER, pos=pioneer_before.dump(), held_orders=0),
                    scout=dict(id=SCOUT, pos=copy.deepcopy(actor(raw, SCOUT)['pos'])),
                    ordinary_sight_origins=[p.dump() for p in sorted(ordinary_sight(raw))],
                    visible_enemy_roles=[dict(id=u['id'], kind=u['roleType'], pos=u['pos'])
                                         for u in raw['teamEnemy']['roles']],
                    observed_wall_count=len(Turn.load(raw).walls()),
                    commands=commands, prompt_chars=len(result['prompt'])))
                apply(raw, truth, commands, spawns)
            assert accepts == [dict(round=1, task=2), dict(round=4, task=1), dict(round=34, task=2)]
            assert len(buys) == 1 and buys[0]['num'] == 3 and buys[0]['actor'] == BUYER, buys
            assert len(uses) == 3 and all(u['actor'] == BUYER for u in uses), uses
            assert len({(p['x'], p['y']) for p in spawns}) == 3
            assert shop_arrival is not None and shop_arrival <= 67
            if not args.unfinished:
                assert not gate_crossings and shop_arrival < 37
            assert first_return == 37 and control_arrival is not None and control_arrival <= 70
            summary.update(shop_arrival_round=shop_arrival, waited_until_task_settlement=max(0,37-shop_arrival),
                gate_crossing_rounds=gate_crossings, buys=buys, uses=uses, spawns=spawns,
                pioneer_first_return_round=first_return, pioneer_control_arrival_round=control_arrival,
                buyer_final=copy.deepcopy(actor(raw, BUYER)['pos']),
                pioneer_final=copy.deepcopy(actor(raw, PIONEER)['pos']),
                scout_final=copy.deepcopy(actor(raw, SCOUT)['pos']))
            cases.append(summary)
    except Exception as error:
        failure = error
    finally:
        process.terminate()
        process.wait(timeout=3)
        capture.seek(0)
        logs = capture.read().decode('utf-8', errors='replace')
        capture.close()
    if failure is None and 'action_rejected' in logs:
        failure = AssertionError('HTTP process logged action_rejected')
    diag = diagnostics(logs)
    if args.unfinished and failure is None:
        for case in cases:
            departures = [row['data'] for row in diag if row['kind']=='first_day_policy'
                          and row['data'].get('team_id')=='worker-buyer-nonsymmetric-'+case['case']
                          and row['data'].get('departure_reason') in ('shop_deadline','personal_walls_ready')
                          and row['data'].get('buyer_id')==BUYER and row['data'].get('departure_authorized')]
            assert departures, 'unfinished team construction must allow personal completion or a purchase deadline'
            if departures[0]['departure_reason']=='personal_walls_ready':
                assert departures[0]['personal_dispatch_ready'], 'personal departure requires actual own-wall completion'
            case.update(departure_round=departures[0]['departure_round'],
                        departure_reason=departures[0]['departure_reason'],
                        departure_budget=departures[0]['departure_budget_at_start'])
            buys = [row for row in rows if row['case']==case['case'] and
                    row['commands'].get(str(BUYER),{}).get('name')==ORDER and
                    row['commands'][str(BUYER)]['action']=='buy']
            assert buys and buys[0]['observed_wall_count']<16, 'fixture must still be unfinished at purchase'
            case['walls_at_purchase'] = buys[0]['observed_wall_count']
    report = dict(scope='First-day R1..71 synthetic observations, task answers and verdicts over real HTTP; not official matches',
        initial_conditions=('Three real guns, ten observed ordinary walls, buyer outside with ordinary stone; '
            'other worker collecting distant stone, actual IMP enemy sight, pioneer near local task fixture'
            if args.unfinished else 'Three real guns, seventeen real ordinary walls and one ordinary stone; '
            'buyer outside, scout already at enemy, pioneer near local task fixture'),
        task_sequence=[2, 1, 2], accepted_rounds=[1, 4, 34], no_private_memory_seed=True,
        visibility='Ordinary alive friendly range-four sight only; enemy station/wall global; summoned robots have no sight',
        scout_dies_round=7 if args.lost_sight else None,
        missing_current_hero_and_weapon_sight_at_use=args.lost_sight,
        fixed_shop=SHOP.dump(), requests=len(rows), cases=cases, results=rows, diagnostics=diag,
        bind_verified=f'0.0.0.0:{port}' in logs, execute_cmd_executed=False,
        failure=repr(failure) if failure is not None else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if failure is not None:
        raise failure
    print(json.dumps(dict(requests=len(rows), all_http_200=True,
        cases=[dict(case=c['case'], shop_arrival=c['shop_arrival_round'], buy_round=c['buys'][0]['round'],
                    use_rounds=[u['round'] for u in c['uses']], pioneer_return=c['pioneer_first_return_round'])
               for c in cases])))


if __name__ == '__main__':
    main()
