"""Real HTTP task submissions -> outcome quota -> buy/use -> weapon unlock.

Fixtures supply task verdicts and LLM answers. Only local requests are made;
executeCmd is never executed. This is not an official match simulator.
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
from agent.protocol import Pos,Turn,distance
from tests.fixtures import request
from tests.test_gap_defense import occupied,role


def fixture(case):
    raw = occupied(1)
    raw['teamOur'].update(teamId='first-day-flow-'+case,goldNum=1000,totalScore=0)
    role(raw,502).update(pos=Pos(2,6).dump(),health=500)
    role(raw,501).update(pos=Pos(3,7).dump(),health=500,backpack=['WallFixer']*5)
    role(raw,504)['pos'] = Pos(0,5).dump()
    raw['teamOur']['playerTasks'] = copy.deepcopy(request()['teamOur']['playerTasks'])
    for index,pos in enumerate((Pos(1,7),Pos(1,6))):
        raw['teamOur']['playerTasks'][index].update(taskPosition=pos.dump(),timeoutRounds=12,
            scoreReward=51-index,goldReward=100,isValid=True,coldDownRounds=0)
    raw['mapInfo']['zones'] += [{'neutralType':kind,'pos':pos.dump()} for kind,pos in
        (('challengerTaskPoint1',Pos(1,7)),('challengerTaskPoint2',Pos(1,6)),('challengerTaskPoint2',Pos(1,5)))]
    raw['weaponShopList'].append({'name':'BossRobotSummonOrder','price':120})
    return raw


def apply_commands(raw,commands):
    before = Turn.load(raw)
    destinations = set()
    for uid,command in commands.items():
        actor = role(raw,int(uid))
        if command['action']=='move':
            point = Pos.load(command['targetPos'][0])
            assert distance(Pos.load(actor['pos']),point)==1
            assert point not in before.occupied_cells() and point not in destinations
            destinations.add(point)
    for uid,command in commands.items():
        actor = role(raw,int(uid))
        action = command['action']
        if action=='move':
            actor['pos'] = command['targetPos'][0]
        elif action=='buy':
            count = command.get('num',1)
            raw['teamOur']['goldNum'] -= before.shop_prices[command['name']]*count
            actor['backpack'] += [command['name']]*count
        elif action=='use':
            actor['backpack'].remove(command['name'])
            if command['name'].startswith('WeaponUpgradeVoucher'):
                target = next(u for u in raw['teamOur']['roles'] if u['pos']==command['targetPos'][0])
                target['level'] += 1
                target['health'] = 500+500*target['level']
        elif action=='collect':
            actor['backpack'].append(before.zones[Pos.load(command['targetPos'][0])])
        elif action=='sell':
            count = command['num']
            raw['teamOur']['goldNum'] += before.vendor_prices[command['name']]*count
            for _ in range(count):
                actor['backpack'].remove(command['name'])
    raw['lastRoundRoleActionResults'] = {uid:True for uid in commands}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port = sock.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    capture = tempfile.TemporaryFile()
    process = subprocess.Popen([sys.executable,str(ROOT/'main3.py'),str(port)],cwd=ROOT.parent,
        stdout=subprocess.DEVNULL,stderr=capture,creationflags=flags)
    rows = []
    try:
        deadline = time.monotonic()+5
        while True:
            conn = http.client.HTTPConnection('127.0.0.1',port,timeout=1)
            try:
                conn.request('GET','/health');response = conn.getresponse();response.read()
                if response.status==200:
                    break
            except (OSError,http.client.HTTPException):
                if time.monotonic()>=deadline:
                    raise RuntimeError('CLI did not start')
                time.sleep(.05)
            finally:
                conn.close()
        for case,outcomes in (('none',(False,False)),('first',(True,False)),
                              ('second',(False,True)),('both',(True,True))):
            raw = fixture(case)
            wanted = sum(outcomes)
            spawns = []
            upgrade_seen = False
            for number in range(1,9+wanted):
                raw.update(roundNo=number,llmResp='',errors=[])
                if number in (2,3):
                    raw['phaseTask'] = 'Local fixture task one: return the requested result.'
                elif number in (5,6):
                    raw['phaseTask'] = 'Local fixture task two: return the requested result.'
                else:
                    raw['phaseTask'] = ''
                if number in (3,6):
                    raw['llmResp'] = json.dumps({'action':'final_answer','answer':'fixture-result-'+str(number)})
                if number in (4,7):
                    index = 0 if number==4 else 1
                    raw['teamOur']['playerTasks'][index].update(isValid=False,coldDownRounds=100)
                    if outcomes[index]:
                        raw['teamOur']['goldNum'] += 100
                        raw['teamOur']['totalScore'] += 51-index
                    else:
                        raw['errors'] = [{'errorCode':2}]
                conn = http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                try:
                    started = time.perf_counter()
                    conn.request('POST','/',json.dumps(raw).encode(),{'Content-Type':'application/json'})
                    response = conn.getresponse();result = json.loads(response.read())
                    elapsed = (time.perf_counter()-started)*1000
                    assert response.status==200
                    assert set(result)=={'roleCommandMap','prompt','executeCmd'}
                    assert not result['executeCmd']
                    commands = result['roleCommandMap']
                    if number in (1,4):
                        assert commands['502']['action']=='acceptTask',(case,number,commands)
                    if number in (3,6):
                        assert commands['502']['action']=='submitAnswer',(case,number,commands)
                    if number<7:
                        assert not any(c.get('name')=='BossRobotSummonOrder' for c in commands.values())
                        assert not any(c.get('action')=='buy' and c.get('name','').startswith('WeaponUpgradeVoucher')
                                       for c in commands.values())
                    if number==7:
                        if wanted:
                            assert commands['502']=={'action':'buy','name':'BossRobotSummonOrder','num':wanted},commands
                        else:
                            assert not any(c.get('name')=='BossRobotSummonOrder' for c in commands.values())
                    if number>=7 and any(c.get('action')=='buy' and c.get('name','').startswith('WeaponUpgradeVoucher')
                                         for c in commands.values()):
                        upgrade_seen = True
                    if number in range(8,8+wanted):
                        assert commands['502']['action']=='use' and commands['502']['name']=='BossRobotSummonOrder'
                        spawns.append(commands['502']['targetPos'][0])
                    rows.append(dict(case=case,outcomes=outcomes,round=number,status=response.status,
                        elapsed_ms=round(elapsed,3),commands=commands,prompt_chars=len(result['prompt'])))
                    apply_commands(raw,commands)
                finally:
                    conn.close()
            assert len(spawns)==wanted and len({(p['x'],p['y']) for p in spawns})==wanted
            assert upgrade_seen,(case,'weapon purchases stayed locked after the order step')
    finally:
        process.terminate();process.wait(timeout=3)
        capture.seek(0);logs = capture.read().decode('utf-8',errors='replace');capture.close()
    assert 'action_rejected' not in logs
    report = dict(scope='Synthetic verdicts and LLM answers over a real HTTP process; no sandbox or official match',
        requests=len(rows),results=rows,bind_verified=f'0.0.0.0:{port}' in logs,bash_executed=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'requests':len(rows),'cases':['none','first','second','both'],'all_http_200':True}))


if __name__=='__main__':
    main()
