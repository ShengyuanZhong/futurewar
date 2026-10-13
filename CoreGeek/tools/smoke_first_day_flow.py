"""Real HTTP task submissions -> outcome quota -> buy/use -> weapon unlock.

Fixtures supply task verdicts and LLM answers. Only local requests are made;
executeCmd is never executed. This is not an official match simulator.
"""
import argparse
import copy
import http.client
from itertools import product
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
from tests.fixtures import request,unit,robot
from tests.test_gap_defense import role
from tests.test_summon_control import provide_scout
from tests.test_maintenance import fortified
from tests.test_layout_survey import reveal
from tools.validate import independent_planning_clear


def fixture(case):
    raw = fortified(1)
    raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                              if not (u['roleType']=='wall' and u['pos']==Pos(5,9).dump())]
    raw['teamOur'].update(teamId='first-day-flow-'+case,goldNum=1000,totalScore=0)
    role(raw,502).update(pos=Pos(2,6).dump(),health=500)
    role(raw,501).update(pos=Pos(6,8).dump(),health=500,backpack=['stone']+['WallFixer']*5)
    role(raw,504)['pos'] = Pos(3,6).dump()
    raw['teamOur']['playerTasks'] = copy.deepcopy(request()['teamOur']['playerTasks'])
    for index,pos in enumerate((Pos(1,7),Pos(1,6))):
        raw['teamOur']['playerTasks'][index].update(taskPosition=pos.dump(),timeoutRounds=12,
            scoreReward=51-index,goldReward=100,isValid=True,coldDownRounds=0)
    raw['mapInfo']['zones'] += [{'neutralType':kind,'pos':pos.dump()} for kind,pos in
        (('challengerTaskPoint1',Pos(1,7)),('challengerTaskPoint2',Pos(1,6)),('challengerTaskPoint2',Pos(1,5)))]
    raw['weaponShopList'].append({'name':'BossRobotSummonOrder','price':120})
    # This short ledger fixture starts with an observed layout and a real
    # worker at the enemy base. The separate scout-flow tool tests the trip.
    raw['teamEnemy']['roles'].append(unit(990,'station',33,25))
    provide_scout(raw)
    return raw


def task_frame(raw,number,outcomes):
    """Task2 -> Task1 -> Task2; repeated point refreshes 30 rounds after R4."""
    raw.update(roundNo=number,llmResp='',errors=[])
    raw['phaseTask'] = ('Local task2 first fixture visit' if number in (2,3)
        else 'Local task1 fixture visit' if number in (5,6)
        else 'Local task2 fixture visit revisited' if number in (35,36) else '')
    if number in (3,6,36):
        raw['llmResp'] = json.dumps({'action':'final_answer','answer':'fixture-result-'+str(number)})
    task_one,task_two = raw['teamOur']['playerTasks']
    if number>=4:
        refresh = 34 if number<37 else 67
        task_two.update(isValid=number>=refresh,coldDownRounds=max(0,refresh-number))
    if number>=7:
        task_one.update(isValid=number>=37,coldDownRounds=max(0,37-number))
    if number in (4,7,37):
        outcome = outcomes[(4,7,37).index(number)]
        index = 0 if number==7 else 1
        if outcome:
            raw['teamOur']['goldNum'] += 100
            raw['teamOur']['totalScore'] += 51-index
        else:
            raw['errors'] = [{'errorCode':2}]


def apply_commands(raw,commands,spawns=None):
    before = Turn.load(raw)
    actors = {str(u['id']):u for u in raw['teamOur']['roles']+raw['teamOur'].get('summonRobotList',[])}
    destinations = set()
    for uid,command in commands.items():
        actor = actors[uid]
        if command['action']=='move':
            point = Pos.load(command['targetPos'][0])
            assert distance(Pos.load(actor['pos']),point)==1
            assert point not in before.occupied_cells() and point not in destinations
            destinations.add(point)
    for uid,command in commands.items():
        actor = actors[uid]
        action = command['action']
        if action=='move':
            actor['pos'] = command['targetPos'][0]
        elif action=='buy':
            count = command.get('num',1)
            raw['teamOur']['goldNum'] -= before.shop_prices[command['name']]*count
            actor['backpack'] += [command['name']]*count
        elif action=='use':
            actor['backpack'].remove(command['name'])
            if command['name']=='BossRobotSummonOrder' and spawns is not None:
                point = command['targetPos'][0]
                assert point not in spawns
                spawns.append(copy.deepcopy(point))
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
        elif action=='remove':
            assert before.is_day
            target = next(u for u in raw['teamOur']['roles']
                          if u['roleType']=='wall' and u['pos']==command['targetPos'][0])
            raw['teamOur']['roles'].remove(target)
        elif action=='build':
            assert before.is_day and command['name']=='wall' and 'stone' in actor['backpack']
            point = Pos.load(command['targetPos'][0])
            assert point not in before.occupied_cells() and distance(Pos.load(actor['pos']),point)==1
            actor['backpack'].remove('stone')
            uid_new = max(u['id'] for u in raw['teamOur']['roles'])+1
            raw['teamOur']['roles'].append(unit(uid_new,'wall',point.x,point.y,health=1000))
        elif action=='attack' and uid in {str(r.robot_id) for r in before.summon_robots}:
            target = Pos.load(command['targetPos'][0])
            assert set(command)=={'action','targetPos'} and len(command['targetPos'])==1
            assert any(u.health>0 and target in before.footprint(u) for u in before.enemies)
            assert independent_planning_clear(raw,Pos.load(actor['pos']),target)
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
        for outcomes in product((False,True),repeat=3):
            case = ''.join('1' if flag else '0' for flag in outcomes)
            raw = fixture(case)
            starting_walls = {Pos.load(u['pos']) for u in raw['teamOur']['roles'] if u['roleType']=='wall'}
            possible_walls = starting_walls | {Pos(5,9)}
            truth = copy.deepcopy(raw['teamEnemy']['roles'])
            wanted = sum(outcomes)
            spawns = []
            upgrade_seen = False
            buyer_walked = False
            for number in range(1,72):
                task_frame(raw,number,outcomes)
                reveal(raw,truth)
                if number==71:
                    walls = {Pos.load(u['pos']) for u in raw['teamOur']['roles']
                             if u['roleType']=='wall' and u['health']>0}
                    assert starting_walls <= walls <= possible_walls
                    occupied = Turn.load(raw).occupied_cells()
                    assert all(Pos.load(p) not in occupied for p in spawns)
                    raw['teamOur']['summonRobotList'] = [robot(30005+i,p['x'],p['y'],
                        roleType='bossRobot',health=800) for i,p in enumerate(spawns)]
                    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
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
                    if number<37 and commands.get('501',{}).get('action')=='move':
                        buyer_walked = True
                    if number in (1,4,34):
                        assert commands['502']['action']=='acceptTask',(case,number,commands)
                    if number in (3,6,36):
                        assert commands['502']['action']=='submitAnswer',(case,number,commands)
                    if number<37:
                        assert not any(c.get('name')=='BossRobotSummonOrder' for c in commands.values())
                        assert not any(c.get('action')=='buy' and c.get('name','').startswith('WeaponUpgradeVoucher')
                                       for c in commands.values())
                    assert not any(c.get('name')=='BossRobotSummonOrder'
                                   for uid,c in commands.items() if uid!='501'),commands
                    assert 'BossRobotSummonOrder' not in role(raw,502)['backpack']
                    if number==37:
                        if wanted:
                            assert commands['501']=={'action':'buy','name':'BossRobotSummonOrder','num':wanted},commands
                        else:
                            assert not any(c.get('name')=='BossRobotSummonOrder' for c in commands.values())
                    if number>=37 and any(c.get('action')=='buy' and c.get('name','').startswith('WeaponUpgradeVoucher')
                                         for c in commands.values()):
                        upgrade_seen = True
                    if number in range(38,38+wanted):
                        assert commands['501']['action']=='use' and commands['501']['name']=='BossRobotSummonOrder'
                    rows.append(dict(case=case,outcomes=outcomes,round=number,status=response.status,
                        elapsed_ms=round(elapsed,3),commands=commands,prompt_chars=len(result['prompt']),
                        wall_count=sum(u['roleType']=='wall' and u['health']>0 for u in raw['teamOur']['roles']),
                        boss_buyer={'id':501,'kind':'worker','pos':copy.deepcopy(role(raw,501)['pos']),
                                    'held_orders':role(raw,501)['backpack'].count('BossRobotSummonOrder')},
                        accepted_task_number={1:2,4:1,34:2}.get(number),
                        task1_cooldown=raw['teamOur']['playerTasks'][0]['coldDownRounds'],
                        task2_cooldown=raw['teamOur']['playerTasks'][1]['coldDownRounds']))
                    apply_commands(raw,commands,spawns)
                finally:
                    conn.close()
            assert len(spawns)==wanted and len({(p['x'],p['y']) for p in spawns})==wanted
            assert upgrade_seen,(case,'weapon purchases stayed locked after the order step')
            assert buyer_walked,(case,'buyer must actually walk from home to the shop')
            walls = {Pos.load(u['pos']) for u in raw['teamOur']['roles'] if u['roleType']=='wall' and u['health']>0}
            assert starting_walls <= walls <= possible_walls
    finally:
        process.terminate();process.wait(timeout=3)
        capture.seek(0);logs = capture.read().decode('utf-8',errors='replace');capture.close()
    assert 'action_rejected' not in logs
    report = dict(scope='Synthetic verdicts and LLM answers over a real HTTP process; no sandbox or official match',
        task_sequence=[2,1,2],accepted_rounds=[1,4,34],boss_buyer_id=501,scout_id=504,
        repeated_task_cooldown={'task':2,'finished_round':4,'next_accept_round':34,'rounds':30},
        requests=len(rows),results=rows,bind_verified=f'0.0.0.0:{port}' in logs,bash_executed=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'requests':len(rows),'cases':8,'quotas':[0,1,2,3],'all_http_200':True}))


if __name__=='__main__':
    main()
