"""Real HTTP process: affordable BOSS buy/use and an observed worker/imp relay.

Synthetic observations seed history and skip intermediate walking rounds. They
do not simulate official damage, simultaneous movement or task rewards.
"""
import argparse
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
from tests.fixtures import unit,robot
from tests.test_gap_defense import occupied,role,GAP
from agent.protocol import Pos
from tools.smoke_first_day_flow import fixture,task_frame,apply_commands


def copy_frame(raw,number,phase=''):
    copied = json.loads(json.dumps(raw))
    copied.update(roundNo=number,phaseTask=phase,llmResp='',errors=[])
    return copied


def observations():
    first = fixture('gap-relay')
    first['teamOur']['goldNum'] = 20
    first['teamOur']['roles'] = [u for u in first['teamOur']['roles']
                                if not (u['roleType']=='wall' and u['pos']==GAP.dump())]
    first['teamOur']['roles'].append(unit(505,'imp',8,8,health=500))
    first['teamEnemy']['roles'].append(unit(901,'worker',GAP.x,GAP.y,health=500))
    names = {1:'accept_first',2:'prompt_first',3:'submit_first',4:'accept_second',
             5:'prompt_second',6:'submit_second',7:'settle_second',
             34:'accept_third',35:'prompt_third',36:'submit_third',37:'buy',38:'use'}
    # This short evidence path skips uneventful waiting/walking observations.
    # R34 is genuinely 30 rounds after the first R4 outcome, never an early CD.
    for number in list(range(1,8))+list(range(34,39)):
        task_frame(first,number,(True,False,False))
        yield names[number],first
    task_frame(first,68,(True,False,False))
    role(first,502).update(pos=Pos(4,7).dump(),backpack=[])
    role(first,501).update(pos=Pos(6,8).dump(),backpack=['stone']+['WallFixer']*5)
    role(first,505)['pos'] = Pos(8,8).dump()
    yield 'seal_gate',first
    for number in (69,70):
        task_frame(first,number,(True,False,False))
        yield 'evening',first
    first.update(roundNo=71,phaseTask='',llmResp='',errors=[])
    role(first,501)['pos'] = Pos(8,7).dump()
    role(first,505)['pos'] = Pos(8,8).dump()
    first['teamEnemy']['roles'] = [u for u in first['teamEnemy']['roles'] if u['id']!=901]
    first['teamEnemy']['roles'].append(unit(992,'pioneer',36,25,health=500))
    # The short relay fixture supplies one observed BOSS at its own intended
    # deployment neighbourhood; it does not simulate spawn displacement.
    boss = robot(31035,37,25,health=800,roleType='bossRobot',targetTeam='defender')
    first['teamOur']['summonRobotList'] = [boss]
    first['robot']['roles'] = [boss]
    yield 'worker',first
    first.update(roundNo=72,lastRoundRoleActionResults={'501':True})
    role(first,501).update(pos=GAP.dump(),health=0)
    yield 'imp',first


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port = listener.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    capture = tempfile.TemporaryFile()
    process = subprocess.Popen([sys.executable,str(ROOT/'main3.py'),str(port)],cwd=ROOT.parent,
                               stdout=subprocess.DEVNULL,stderr=capture,creationflags=flags)
    results = []
    try:
        deadline = time.monotonic()+5
        while True:
            conn = http.client.HTTPConnection('127.0.0.1',port,timeout=1)
            try:
                conn.request('GET','/health')
                response = conn.getresponse()
                response.read()
                if response.status==200:
                    break
            except (OSError,http.client.HTTPException):
                if time.monotonic()>=deadline:
                    raise RuntimeError('HTTP process did not become healthy')
                time.sleep(.05)
            finally:
                conn.close()
        for stage,raw in observations():
            conn = http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                started = time.perf_counter()
                conn.request('POST','/',json.dumps(raw).encode(),{'Content-Type':'application/json'})
                response = conn.getresponse()
                payload = json.loads(response.read())
                elapsed = (time.perf_counter()-started)*1000
                assert response.status==200
                assert set(payload)=={'roleCommandMap','prompt','executeCmd'}
                commands = payload['roleCommandMap']
                if stage in ('accept_first','accept_second','accept_third'):
                    assert commands['502']['action']=='acceptTask',commands
                if stage.startswith(('accept_','prompt_','submit_','settle_')):
                    assert not any(c.get('name')=='BossRobotSummonOrder' for c in commands.values())
                    assert not any(c.get('action')=='buy' and c.get('name','').startswith('WeaponUpgradeVoucher') for c in commands.values())
                if stage=='buy':
                    assert commands['502']=={'action':'buy','name':'BossRobotSummonOrder','num':1},commands
                elif stage=='use':
                    assert commands['502']['action']=='use' and commands['502']['name']=='BossRobotSummonOrder'
                elif stage=='worker':
                    assert len([u for u in raw['teamOur']['roles'] if u['roleType']=='wall'])==16
                    assert commands['501']=={'action':'move','targetPos':[GAP.dump()]},commands
                    assert commands['31035']['action'] in ('move','attack')
                elif stage=='imp':
                    assert commands['505']=={'action':'move','targetPos':[GAP.dump()]},commands
                    assert '501' not in commands
                if raw['roundNo']>=71:
                    assert not any(c['action'] in ('remove','build') for c in commands.values())
                results.append(dict(stage=stage,round=raw['roundNo'],status=response.status,
                                    elapsed_ms=round(elapsed,3),response=payload))
                apply_commands(raw,commands)
            finally:
                conn.close()
    finally:
        process.terminate()
        process.wait(timeout=3)
        capture.seek(0)
        logs = capture.read().decode('utf-8',errors='replace')
        capture.close()
    diagnostics = []
    for line in logs.splitlines():
        for marker in ('gap_defense','first_day_policy','defense_diagnostic','robot_diagnostic'):
            if marker+' {' in line:
                diagnostics.append(dict(log_type=marker,data=json.loads(line.split(marker+' ',1)[1])))
    assert 'action_rejected' not in logs
    assert any(r['log_type']=='gap_defense' and r['data'].get('imp_status')=='holding_gap' for r in diagnostics)
    report = dict(scope='Synthetic HTTP observations, not an official match simulation',results=results,
                  diagnostics=diagnostics,bind_verified=f'0.0.0.0:{port}' in logs,bash_executed=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'requests':len(results),'statuses':[r['status'] for r in results],
                      'stages':[r['stage'] for r in results],'output':str(args.output)}))


if __name__=='__main__':
    main()
