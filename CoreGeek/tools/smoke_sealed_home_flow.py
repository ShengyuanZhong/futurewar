"""First-day HTTP construction: collect actual stone, evacuate and seal 17 walls.

The initial three rockets are a local isolation assumption. The finite ore
and explicit refresh observations implement a small construction test driver,
not an official match engine. No private memory or executeCmd is executed.
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
from agent.grid import Routes, adjacent_cells
from agent.protocol import Pos, Turn, distance
from tests.test_sealed_home import WALLS, position, scene
from tools.smoke_first_day_flow import apply_commands
from tools.smoke_worker_buyer_flow import post
from tools.validate import independent_contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    capture = tempfile.TemporaryFile()
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    process = subprocess.Popen([sys.executable,str(ROOT/'main3.py'),str(port)],cwd=ROOT.parent,
        stdout=subprocess.DEVNULL,stderr=capture,creationflags=flags)
    rows,cases,failure = [],[],None
    try:
        deadline=time.monotonic()+5
        while True:
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
            try:
                conn.request('GET','/health');response=conn.getresponse();response.read()
                if response.status==200:
                    break
            except (OSError,http.client.HTTPException):
                if time.monotonic()>=deadline:
                    raise RuntimeError('CLI did not start')
                time.sleep(.05)
            finally:
                conn.close()
        for mirrored in (False,True):
            for starts_inside in (False,True):
                raw,_,_ = scene(mirrored,missing=WALLS,inside_worker=starts_inside,round_no=1)
                dy = 1 if mirrored else 17
                for u in raw['teamOur']['roles']:
                    u['pos']['y']+=dy
                    if u['roleType']=='station':
                        u['health']=1500
                    elif u['roleType']=='worker':
                        u['backpack']=[];u['backPackCapability']=100
                    elif u['roleType']=='pioneer':
                        u['backPackCapability']=40
                for z in raw['mapInfo']['zones']:
                    z['pos']['y']+=dy
                case=f'{"lower-right" if mirrored else "upper-left"}-{int(starts_inside)}'
                raw['teamOur']['teamId']='sealed-home-'+case
                expected={Pos(position(x,y,mirrored).x,y+dy) for x,y in WALLS}
                shops=[Pos.load(z['pos']) for z in raw['mapInfo']['zones'] if z['neutralType']=='weaponShop']
                ore_sites=[Pos(position(x,y,mirrored).x,y+dy) for x,y in ((3,9),(3,3),(1,9))]
                raw['mapInfo']['zones']=[z for z in raw['mapInfo']['zones'] if z['neutralType']!='stone']
                raw['mapInfo']['zones'] += [dict(neutralType='stone',pos=p.dump(),remain=10) for p in ore_sites[:2]]
                ore_remaining={p:10 for p in ore_sites[:2]};ore_index=1
                collected,built={},{}
                construction_mines={}
                first_closed=None;collection_at_closure=None
                for number in range(1,72):
                    raw['roundNo']=number
                    before=Turn.load(raw)
                    real_walls={u.pos for u in before.walls()}
                    if real_walls==expected:
                        if first_closed is None:
                            first_closed=number;collection_at_closure=sum(collected.values())
                        for worker in before.workers():
                            assert Routes(before,worker).nearest(adjacent_cells(before,shops)) is not None
                    result,elapsed=post(port,raw)
                    independent_contract(raw,result)
                    commands=result['roleCommandMap']
                    assert not any(c['action']=='remove' for c in commands.values()),commands
                    construction=[c for c in commands.values() if c['action']=='build' and c['name']=='wall']
                    trial=copy.deepcopy(raw)
                    for i,c in enumerate(construction):
                        p=Pos.load(c['targetPos'][0]);assert p in expected
                        assert number<=70
                        from tests.fixtures import unit
                        trial['teamOur']['roles'].append(unit(9000+i,'wall',p.x,p.y,health=1000))
                    # Check both builds together against the same actual worker
                    # positions, never use their scheduled future destinations.
                    projected=Turn.load(trial)
                    for worker in projected.workers():
                        assert Routes(projected,worker).nearest(adjacent_cells(projected,shops)) is not None
                    for uid,c in commands.items():
                        if c['action']=='collect':
                            name=before.zones[Pos.load(c['targetPos'][0])]
                            assert name=='stone'
                            if first_closed is None:
                                construction_mines.setdefault(uid,set()).add(Pos.load(c['targetPos'][0]))
                            collected[uid]=collected.get(uid,0)+1
                            ore_remaining[Pos.load(c['targetPos'][0])]-=1
                        elif c['action']=='build':
                            assert c['name']=='wall'
                            built[uid]=built.get(uid,0)+1
                    rows.append(dict(case=case,round=number,status=200,elapsed_ms=round(elapsed,3),
                        walls=len(real_walls),worker_positions={str(w.unit_id):w.pos.dump() for w in before.workers()},
                        worker_stone={str(w.unit_id):w.backpack.count('stone') for w in before.workers()},
                        ore_remaining_before={f'{p.x},{p.y}':before.mine_remaining[p] for p in ore_remaining},
                        commands=commands))
                    apply_commands(raw,commands,[])
                    for exhausted in [p for p,remaining in ore_remaining.items() if remaining<=0]:
                        # Each mine is finite. A final shared extraction may
                        # credit both workers, as allowed by the official rule.
                        raw['mapInfo']['zones']=[z for z in raw['mapInfo']['zones'] if Pos.load(z['pos'])!=exhausted]
                        del ore_remaining[exhausted]
                        occupied=Turn.load(raw).occupied_cells()
                        for offset in range(1,len(ore_sites)+1):
                            candidate=ore_sites[(ore_index+offset)%len(ore_sites)]
                            if candidate not in occupied and candidate not in ore_remaining:
                                ore_index=(ore_index+offset)%len(ore_sites)
                                raw['mapInfo']['zones'].append(dict(neutralType='stone',pos=candidate.dump(),remain=10))
                                ore_remaining[candidate]=10
                                break
                        else:
                            raise AssertionError('No legal synthetic ore refresh site')
                    for zone in raw['mapInfo']['zones']:
                        point=Pos.load(zone['pos'])
                        if point in ore_remaining:
                            zone['remain']=ore_remaining[point]
                assert first_closed is not None and first_closed<=70,(case,'failed to seal',rows[-1])
                assert sum(built.values())==17 and set(built)=={'501','504'},built
                assert collection_at_closure==17,(case,'redundant construction stone',collection_at_closure)
                assert set(collected)=={'501','504'},collected
                assert set(construction_mines)=={'501','504'}
                assert all(len(sites)==1 for sites in construction_mines.values()),construction_mines
                assert len(set().union(*construction_mines.values()))==2,construction_mines
                assert {u.pos for u in Turn.load(raw).walls()}==expected
                cases.append(dict(case=case,starts_inside=starts_inside,closed_round=first_closed,
                    construction_stone=collection_at_closure,built=built,collected_first_day=collected,
                    construction_mines={uid:[p.dump() for p in sorted(sites)] for uid,sites in construction_mines.items()},
                    initial_three_rockets=True,night_reopens=False))
    except Exception as error:
        failure=error
    finally:
        process.terminate();process.wait(timeout=3)
        capture.seek(0);logs=capture.read().decode('utf-8',errors='replace');capture.close()
    if failure is None and 'action_rejected' in logs:
        failure=AssertionError('HTTP process logged action_rejected')
    traces=[]
    for line in logs.splitlines():
        if 'home_construction ' in line:
            traces.append(json.loads(line.split('home_construction ',1)[1]))
    report=dict(scope='First-day R1..71 local construction observations over real HTTP, not official matches',
        assumptions='Three rockets already observed; zero wall/stone; two initially visible mines with real remain10 and explicit local refresh; no enemies/tasks; both base orientations and one initial inner worker',
        requests=len(rows),cases=cases,results=rows,construction_diagnostics=traces,
        no_private_memory_seed=True,execute_cmd_executed=False,
        bind_verified=f'0.0.0.0:{port}' in logs,failure=repr(failure) if failure else None)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if failure:
        raise failure
    print(json.dumps(dict(requests=len(rows),all_http_200=True,cases=cases)))


if __name__=='__main__':
    main()
