"""First-day real HTTP vehicle pickup, observation-confirmed driving and night walking.

The fixtures are synthetic. Cars are supplied as official neutral elements,
and isDriving is updated only by this local driver's successful movement
settlement. Enemy heroes/guns are filtered by ordinary friendly sight.
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
from tests.fixtures import request, robot
from tests.test_layout_survey import actor, enemy_blueprint, reveal
from tests.test_raid_scouts import WORKER_ID, HOME_ID
from tests.test_scout_vehicle import START, CAR, scene
from tools.smoke_first_day_flow import task_frame
from tools.validate import independent_contract

ORDER = 'BossRobotSummonOrder'


def setup(name, number=1, car=None):
    raw, _ = scene(round_no=number, car=car)
    raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                              if not (u['roleType']=='wall' and u['pos']==Pos(5,9).dump())]
    raw['teamOur'].update(teamId='vehicle-flow-' + name, goldNum=1000, totalScore=0)
    actor(raw, 502).update(pos=Pos(13, 10).dump(), health=500)
    actor(raw, HOME_ID).update(pos=Pos(6,8).dump(), backpack=['stone'] + ['WallFixer'] * 5)
    raw['teamOur']['playerTasks'] = copy.deepcopy(request()['teamOur']['playerTasks'])
    for index, pos in enumerate((Pos(14, 9), Pos(14, 11))):
        raw['teamOur']['playerTasks'][index].update(taskPosition=pos.dump(), timeoutRounds=12,
            scoreReward=51 - index, goldReward=100, isValid=True, coldDownRounds=0)
    raw['mapInfo']['zones'] = [z for z in raw['mapInfo']['zones'] if 'TaskPoint' not in z['neutralType']]
    raw['mapInfo']['zones'] += [{'neutralType': kind, 'pos': pos.dump()} for kind, pos in (
        ('challengerTaskPoint1', Pos(14, 9)), ('challengerTaskPoint2', Pos(14, 11)),
        ('challengerTaskPoint2', Pos(14, 12)))]
    raw['weaponShopList'].append({'name': ORDER, 'price': 120})
    raw['teamOur']['summonRobotList'] = []
    raw['robot']['roles'] = []
    return raw, enemy_blueprint('vertical_gap', base=Pos(30, 10))


def settle(raw, commands, spawns):
    """Atomic movement with no collision; ambiguous collision outcomes are unmodelled."""
    before = Turn.load(raw)
    actors = {str(u['id']): u for u in raw['teamOur']['roles'] + raw['teamOur']['summonRobotList']}
    car = next((z for z in raw['mapInfo']['zones'] if z['neutralType'] == 'challengerVehicle'), None)
    parked = Pos.load(car['pos']) if car else None
    events = []
    for uid, command in commands.items():
        item = actors[uid]
        action = command['action']
        if action == 'move':
            origin = Pos.load(item['pos'])
            points = tuple(Pos.load(p) for p in command['targetPos'])
            was_driving = item.get('isDriving') is True
            owned_robot = any(str(r['id']) == uid for r in raw['teamOur']['summonRobotList'])
            if was_driving and before.is_day and len(points) == 2 and not owned_robot:
                assert car is not None and parked == origin
                car['pos'] = points[-1].dump()
                item['isDriving'] = True
                event = 'drive_two_steps'
            else:
                item['isDriving'] = bool(before.is_day and not owned_robot and parked == points[-1])
                event = ('board_observed_car' if item['isDriving'] else
                         'single_step_dismount' if was_driving and before.is_day else 'walk_one_step')
            item['pos'] = points[-1].dump()
            if int(uid) == WORKER_ID:
                events.append(dict(event=event, origin=origin.dump(), path=[p.dump() for p in points],
                                   next_observed_is_driving=item['isDriving']))
        elif action == 'remove':
            wall = next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'wall'
                        and u['pos'] == command['targetPos'][0])
            raw['teamOur']['roles'].remove(wall)
        elif action == 'build':
            assert before.is_day and command['name'] == 'wall'
            target = command['targetPos'][0]
            item['backpack'].remove('stone')
            from tests.fixtures import unit
            new_id = max(u['id'] for u in raw['teamOur']['roles']) + 1
            raw['teamOur']['roles'].append(unit(new_id, 'wall', target['x'], target['y'], health=1000))
        elif action == 'buy':
            count = command.get('num', 1)
            raw['teamOur']['goldNum'] -= before.shop_prices[command['name']] * count
            assert raw['teamOur']['goldNum'] >= 0
            item['backpack'] += [command['name']] * count
        elif action == 'use':
            name = command['name']
            item['backpack'].remove(name)
            if name == ORDER:
                spawns.append(copy.deepcopy(command['targetPos'][0]))
            elif 'UpgradeVoucher' in name:
                building = next(u for u in raw['teamOur']['roles'] if u['pos'] == command['targetPos'][0])
                building['level'] += 1
                building['health'] = 500 + 500 * building['level']
            elif name == 'WallFixer':
                building = next(u for u in raw['teamOur']['roles'] if u['pos'] == command['targetPos'][0])
                building['health'] = min(500 + 500 * building['level'], building['health'] + 1000)
            elif name != 'Medicine':
                raise AssertionError(('unmodelled use', command))
        elif action == 'collect':
            item['backpack'].append(before.zones[Pos.load(command['targetPos'][0])])
        elif action == 'sell':
            count = command.get('num', 1)
            raw['teamOur']['goldNum'] += before.vendor_prices[command['name']] * count
            for _ in range(count):
                item['backpack'].remove(command['name'])
        elif action not in ('acceptTask', 'submitAnswer', 'attack'):
            raise AssertionError(('unmodelled action', uid, command))
    raw['lastRoundRoleActionResults'] = {uid: True for uid in commands}
    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
    return events


def post(port, raw):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        conn.request('POST', '/', json.dumps(raw).encode(), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        result = json.loads(response.read())
        assert response.status == 200
        assert not result['executeCmd']
        independent_contract(raw, result)
        return response.status, result
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    rows, cases, failure = [], [], None
    capture = tempfile.TemporaryFile()
    with tempfile.TemporaryDirectory() as config_dir:
        config = Path(config_dir) / 'config.json'
        config.write_text(json.dumps({'enable_news': False, 'enable_first_night_defense': False}), encoding='utf-8')
        process = subprocess.Popen([sys.executable, str(ROOT / 'main3.py'), str(port), '--config', str(config)],
            cwd=ROOT.parent, stdout=subprocess.DEVNULL, stderr=capture,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
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
                        raise RuntimeError('CLI did not become healthy')
                    time.sleep(.05)
                finally:
                    conn.close()
            for name, first, last in (('task2-car-early', 1, 71), ('late-car-night-boundary', 59, 71)):
                raw, truth = setup(name, first, car=CAR if first > 1 else None)
                if first > 1:
                    # Isolate the observer's transport mission; no pioneer
                    # purchase/quota state is fabricated in this late fixture.
                    raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['id'] != 502]
                spawns, timeline = [], []
                for number in range(first, last + 1):
                    if first == 1:
                        task_frame(raw, number, (True, True, True))
                        if number == 4:
                            # The synthetic judge reports a real car zone only
                            # after this fixture's Task2 success settlement.
                            raw['mapInfo']['zones'].append({'neutralType': 'challengerVehicle', 'pos': CAR.dump()})
                    else:
                        raw.update(roundNo=number, phaseTask='', llmResp='', errors=[])
                        raw['teamOur']['playerTasks'] = []
                    if number == 71:
                        raw['mapInfo']['zones'] = [z for z in raw['mapInfo']['zones']
                                                  if not z['neutralType'].endswith('Vehicle')]
                        for item in raw['teamOur']['roles']:
                            item['isDriving'] = False
                        born = [robot(30005 + i, p['x'], p['y'], roleType='bossRobot', health=800)
                                for i, p in enumerate(spawns)]
                        if not born:
                            born = [robot(30005, 34, 10, roleType='bossRobot', health=800)]
                        raw['teamOur']['summonRobotList'] = born
                        raw['robot']['roles'] = copy.deepcopy(born)
                    reveal(raw, truth)
                    scout_before = copy.deepcopy(actor(raw, WORKER_ID))
                    cars_before = [copy.deepcopy(z) for z in raw['mapInfo']['zones'] if z['neutralType'].endswith('Vehicle')]
                    status, response = post(port, raw)
                    commands = response['roleCommandMap']
                    assert not any(c.get('name')==ORDER for uid,c in commands.items() if uid!=str(HOME_ID)),commands
                    if first==1:
                        assert ORDER not in actor(raw,502)['backpack']
                        if number<37:
                            assert not any(c.get('name')==ORDER for c in commands.values()),commands
                        if number==37:
                            assert commands[str(HOME_ID)]=={'action':'buy','name':ORDER,'num':3},commands
                    events = settle(raw, commands, spawns)
                    for event in events:
                        event.update(round=number)
                        timeline.append(event)
                    rows.append(dict(case=name, round=number, status=status,
                        scout_before={'pos': scout_before['pos'], 'isDriving': scout_before.get('isDriving', False)},
                        observed_cars=cars_before, scout_command=commands.get(str(WORKER_ID)),
                        scout_after={'pos': copy.deepcopy(actor(raw, WORKER_ID)['pos']),
                                     'isDriving': actor(raw, WORKER_ID).get('isDriving', False)},
                        movement_events=events, commands=commands))
                if first == 1:
                    board = next(e for e in timeline if e['event'] == 'board_observed_car')
                    driven = [e for e in timeline if e['event'] == 'drive_two_steps']
                    dismount = [e for e in timeline if e['event'] == 'single_step_dismount'][-1]
                    assert board['round'] >= 4 and driven and min(e['round'] for e in driven) > board['round']
                    assert dismount['round'] > min(e['round'] for e in driven)
                    cases.append(dict(case=name, board_round=board['round'], driving_rounds=[e['round'] for e in driven],
                                      dismount_round=dismount['round'], spawns=spawns))
                else:
                    night = next(e for e in timeline if e['round'] == 71)
                    assert night['event'] == 'walk_one_step' and len(night['path']) == 1
                    assert any(e['event'] == 'board_observed_car' for e in timeline)
                    assert any(e['event'] == 'drive_two_steps' for e in timeline)
                    cases.append(dict(case=name, night_round=71, night_event=night, timeline=timeline))
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
    report = dict(scope='First-day synthetic sequential observations over real HTTP; not an official match',
        requests=len(rows), cases=cases, results=rows, failure=repr(failure) if failure else None,
        boss_buyer_id=HOME_ID,scout_id=WORKER_ID,task_sequence=[2,1,2],accepted_rounds=[1,4,34],
        rounds='R1..R71 and a separate R59..R71 scenario, all day 1',
        assumptions=['Synthetic Task2 success supplies a car beside its point as an observed neutral element at R4; other case starts with an observed parked car.',
                     'Task verdicts at neighbouring points are prescribed fixture feedback; ambiguous point selection is not an official-judge validation.',
                     'Successful neighbour moves determine the next synthetic isDriving observation; no collision outcome is assumed.',
                     'Two-step driving transports the car; one-step movement leaves it parked; all cars disappear at R71.',
                     'The other 16 home walls begin observed completed; the temporary gate is open and its worker starts inside with sealing stone. First-night procurement is disabled to isolate scouting transport.',
                     'The late observer scenario has no pioneer and starts with an observed parked car; one owned BOSS is supplied at R71 to keep the view mission active.',
                     'Enemy buildings/heroes are stationary fixture truth filtered by ordinary range-four friendly sight.',
                     'Combat damage and official sandbox execution are not simulated.'],
        bind_verified=f'0.0.0.0:{port}' in logs, execute_cmd_executed=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if failure is not None:
        raise failure
    print(json.dumps({'requests': len(rows), 'all_http_200': True, 'cases': cases}))


if __name__ == '__main__':
    main()
