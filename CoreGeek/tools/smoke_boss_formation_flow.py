"""First-night HTTP regressions from the logged BOSS opening and its mirrors.

Only geometry and a short observation window are reconstructed. This is not
an official match replay: damage, role re-entry and feedback are local inputs.
No private memory is injected, and executeCmd is never executed.
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
sys.path[:0] = [str(ROOT),str(ROOT/'src')]
from agent.protocol import Pos, Turn
from tests.fixtures import request, robot, unit
from tests.test_boss_formation import reflected, reflected_cell
from tools.smoke_scout_flow import apply, diagnostics, ordinary_sight
from tools.smoke_worker_buyer_flow import post
from tools.validate import independent_contract, independent_planning_clear

FRONT,REAR,BASE,CREW = 31035,31036,10013,10011


def scene(mx,my):
    raw = request(78)
    raw['mapInfo']['zones'] = []
    raw['teamOur'].update(teamId=f'boss-log-opening-{int(mx)}{int(my)}',goldNum=0,
                          playerTasks=[],totalScore=0)
    raw['weaponShopList'] = []
    raw['teamOur']['roles'] = [unit(20013,'station',31,8,health=1500),
        unit(20012,'worker',6,19,health=500),unit(20014,'imp',4,19,health=500)]
    raw['teamEnemy']['roles'] = [unit(BASE,'station',9,22,health=1500),
        unit(10040,'rocket',8,20,health=1000),unit(10041,'rocket',9,20,health=1000),
        unit(10042,'rocket',8,22,health=1000)]
    ring = {Pos(x,y) for x in range(7,13) for y in range(19,25)
            if x in (7,12) or y in (19,24)}-{Pos(7,21)}
    raw['teamEnemy']['roles'] += [unit(40000+i,'wall',p.x,p.y,health=1000)
                                  for i,p in enumerate(sorted(ring))]
    raw['teamOur']['summonRobotList'] = [robot(FRONT,6,21,health=760,roleType='bossRobot'),
                                        robot(REAR,5,21,health=750,roleType='bossRobot')]
    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
    return reflected(raw,mx,my)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port = sock.getsockname()[1]
    capture = tempfile.TemporaryFile()
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    process = subprocess.Popen([sys.executable,str(ROOT/'main3.py'),str(port)],cwd=ROOT.parent,
        stdout=subprocess.DEVNULL,stderr=capture,creationflags=flags)
    rows,cases,failure = [],[],None
    try:
        deadline = time.monotonic()+5
        while True:
            conn = http.client.HTTPConnection('127.0.0.1',port,timeout=1)
            try:
                conn.request('GET','/health')
                response = conn.getresponse();response.read()
                if response.status==200:
                    break
            except (OSError,http.client.HTTPException):
                if time.monotonic()>=deadline:
                    raise RuntimeError('CLI did not start')
                time.sleep(.05)
            finally:
                conn.close()
        for mx,my in ((False,False),(True,False),(False,True),(True,True)):
            raw = scene(mx,my)
            truth = copy.deepcopy(raw['teamEnemy']['roles'])
            gap = reflected_cell(Pos(7,21),mx,my)
            operator = reflected_cell(Pos(8,21),mx,my)
            rear_post = reflected_cell(Pos(6,21),mx,my)
            case = dict(mirror_x=mx,mirror_y=my,front_moves=[],rear_moves=[],base_attacks=[],crew_attacks=[])
            for number in range(78,86):
                raw['roundNo'] = number
                if number==82:
                    # A live enemy can return to the approach, but cannot
                    # occupy the cannon control cell held by our front BOSS.
                    truth.append(unit(CREW,'pioneer',gap.x,gap.y,health=80))
                origins = ordinary_sight(raw)
                raw['teamEnemy']['roles'] = [copy.deepcopy(u) for u in truth
                    if u['roleType'] in ('station','wall') or any(
                        max(abs(p.x-u['pos']['x']),abs(p.y-u['pos']['y']))<=4 for p in origins)]
                before = Turn.load(raw)
                result,elapsed = post(port,raw)
                independent_contract(raw,result)
                commands = result['roleCommandMap']
                front = commands.get(str(FRONT),{})
                rear = commands.get(str(REAR),{})
                if number==78:
                    assert front==dict(action='move',targetPos=[gap.dump()]),commands
                    assert not rear,('rear must observe the lane opening before entry',commands)
                if number==79:
                    assert front==dict(action='move',targetPos=[operator.dump()]),commands
                    assert rear==dict(action='move',targetPos=[rear_post.dump()]),commands
                base_cells = before.footprint(next(u for u in before.enemies if u.unit_id==BASE))
                for uid in (FRONT,REAR):
                    command = commands.get(str(uid),{})
                    if command.get('action')=='move':
                        target = Pos.load(command['targetPos'][0])
                        assert any(independent_planning_clear(raw,target,p) for p in base_cells)
                        case['front_moves' if uid==FRONT else 'rear_moves'].append(dict(round=number,target=target.dump()))
                    elif command.get('action')=='attack':
                        target = Pos.load(command['targetPos'][0])
                        assert target in base_cells or (number==82 and target==gap),commands
                        case['crew_attacks' if number==82 else 'base_attacks'].append(dict(round=number,robot=uid,target=target.dump()))
                    if number>=80:
                        assert command.get('action')=='attack',commands
                rows.append(dict(case=raw['teamOur']['teamId'],round=number,status=200,
                    elapsed_ms=round(elapsed,3),owned_positions={str(r.robot_id):r.pos.dump() for r in before.summon_robots},
                    ordinary_sight_origins=[p.dump() for p in sorted(origins)],
                    visible_enemies=raw['teamEnemy']['roles'],commands=commands))
                apply(raw,truth,commands,[])
            assert len(case['front_moves'])==2 and len(case['rear_moves'])==1
            assert len(case['crew_attacks'])==2 and len(case['base_attacks'])==10
            case['base_hp_final'] = next(u['health'] for u in truth if u['id']==BASE)
            cases.append(case)
    except Exception as error:
        failure = error
    finally:
        process.terminate();process.wait(timeout=3)
        capture.seek(0);logs=capture.read().decode('utf-8',errors='replace');capture.close()
    if failure is None and 'action_rejected' in logs:
        failure = AssertionError('HTTP process logged action_rejected')
    report = dict(scope='First-night R78..85 logged geometry and four reflections over real HTTP; not official match replay',
        assumptions='Full outer wall ring filled synthetically; base HP1500, re-entering crew HP80, damage and successful feedback local; robot/weapon/gap/observer geometry taken from boss_attack_log',
        requests=len(rows),cases=cases,results=rows,diagnostics=diagnostics(logs),
        no_private_memory_seed=True,execute_cmd_executed=False,
        bind_verified=f'0.0.0.0:{port}' in logs,failure=repr(failure) if failure else None)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if failure:
        raise failure
    print(json.dumps(dict(requests=len(rows),cases=len(cases),all_http_200=True,
        front_moves=2,rear_moves=1,both_resume_base_attacks_round=80,returning_crew_attacked_round=82)))


if __name__=='__main__':
    main()
