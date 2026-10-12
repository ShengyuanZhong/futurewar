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
from tools.smoke_first_day_flow import fixture


def copy_frame(raw,number,phase=''):
    copied = json.loads(json.dumps(raw))
    copied.update(roundNo=number,phaseTask=phase,llmResp='',errors=[])
    return copied


def observations():
    first = fixture('gap-relay')
    first['teamOur']['goldNum'] = 20
    records = [('accept_first',copy_frame(first,1))]
    one = copy_frame(first,2,phase='Local first fixture task.')
    one['lastRoundRoleActionResults'] = {'502':True}
    records.append(('prompt_first',one))
    answer = copy_frame(one,3,phase=one['phaseTask'])
    answer['llmResp'] = json.dumps({'action':'final_answer','answer':'first-fixture-result'})
    records.append(('submit_first',answer))
    second = copy_frame(first,4)
    second['lastRoundRoleActionResults'] = {'502':True}
    second['teamOur']['goldNum'] = 120
    second['teamOur']['totalScore'] = 51
    second['teamOur']['playerTasks'][0].update(isValid=False,coldDownRounds=100)
    records.append(('accept_second',second))
    two = copy_frame(second,5,phase='Local second fixture task.')
    two['lastRoundRoleActionResults'] = {'502':True}
    records.append(('prompt_second',two))
    answer = copy_frame(two,6,phase=two['phaseTask'])
    answer['llmResp'] = json.dumps({'action':'final_answer','answer':'second-fixture-result'})
    records.append(('submit_second',answer))
    buy = copy_frame(second,7)
    buy['teamOur']['playerTasks'][1].update(isValid=False,coldDownRounds=100)
    buy['lastRoundRoleActionResults'] = {'502':True}
    buy['errors'] = [{'errorCode':2}]
    use = json.loads(json.dumps(buy))
    use.update(roundNo=8,lastRoundRoleActionResults={'502':True})
    use['errors'] = []
    use['teamOur']['goldNum'] = 0
    role(use,502)['backpack'] = ['BossRobotSummonOrder']
    evening = json.loads(json.dumps(use))
    evening.update(roundNo=70,lastRoundRoleActionResults={})
    role(evening,502).update(pos=Pos(4,7).dump(),backpack=[])
    role(evening,501).update(pos=Pos(8,7).dump(),backpack=['stone'])
    role(evening,505)['pos'] = Pos(8,8).dump()
    role(evening,504)['pos'] = Pos(38,23).dump()
    night = json.loads(json.dumps(evening))
    night.update(roundNo=71,lastRoundRoleActionResults={})
    night['teamEnemy']['roles'] = [unit(990,'station',33,25),unit(991,'rocket',35,25,health=1000),
                                 unit(992,'pioneer',36,25,health=500)]
    boss = robot(31035,37,25,health=800,roleType='bossRobot',targetTeam='defender')
    night['teamOur']['summonRobotList'] = [boss]
    night['robot']['roles'] = [boss]
    fallen = json.loads(json.dumps(night))
    fallen.update(roundNo=72,lastRoundRoleActionResults={'501':True})
    role(fallen,501).update(pos=GAP.dump(),health=0)
    return records+[('buy',buy),('use',use),('evening',evening),('worker',night),('imp',fallen)]


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
                if stage in ('accept_first','accept_second'):
                    assert commands['502']['action']=='acceptTask',commands
                if stage.startswith(('accept_','prompt_','submit_')):
                    assert not any(c.get('name')=='BossRobotSummonOrder' for c in commands.values())
                    assert not any(c.get('action')=='buy' and c.get('name','').startswith('WeaponUpgradeVoucher') for c in commands.values())
                if stage=='buy':
                    assert commands['502']=={'action':'buy','name':'BossRobotSummonOrder','num':1},commands
                elif stage=='use':
                    assert commands['502']['action']=='use' and commands['502']['name']=='BossRobotSummonOrder'
                elif stage=='worker':
                    assert commands['501']=={'action':'move','targetPos':[GAP.dump()]},commands
                    assert commands['31035']['action'] in ('move','attack')
                elif stage=='imp':
                    assert commands['505']=={'action':'move','targetPos':[GAP.dump()]},commands
                    assert '501' not in commands
                assert not any(c['action']=='remove' for c in commands.values())
                results.append(dict(stage=stage,round=raw['roundNo'],status=response.status,
                                    elapsed_ms=round(elapsed,3),response=payload))
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
