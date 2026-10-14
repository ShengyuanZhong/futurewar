"""First-day public HTTP scouting legs and group combat; no official replay."""
import argparse
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from agent.protocol import Pos,Turn,distance
from tests.test_flank_focus import scout_scene,group_scene,IMP_ID,FIRST,SECOND
from tests.test_layout_survey import reveal
from tests.test_boss_formation import reflected,reflected_cell
from tools.smoke_imp_defense_flow import wait_server
from tools.smoke_worker_buyer_flow import post
from tools.smoke_scout_flow import apply
from tools.validate import independent_contract


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    capture=tempfile.TemporaryFile()
    process=subprocess.Popen([sys.executable,str(ROOT/'main3.py'),str(port)],cwd=ROOT.parent,
        stdout=subprocess.DEVNULL,stderr=capture,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    rows=[];cases=[];failure=None
    try:
        wait_server(port)
        for right in (False,True):
            raw,truth=scout_scene(right)
            raw['teamOur'].update(teamId=f'flank-{right}',summonRobotList=[])
            path=[];spawns=[];done=None;layout_positions={Pos.load(u['pos']) for u in truth if u['roleType']=='rocket'}
            for number in range(1,71):
                raw['roundNo']=number
                reveal(raw,truth)
                origins=[Pos.load(u['pos']) for u in raw['teamOur']['roles'] if u['health']>0]
                if all(any(distance(p,origin)<=4 for origin in origins) for p in layout_positions):
                    done=number
                    break
                result,elapsed=post(port,raw)
                independent_contract(raw,result)
                command=result['roleCommandMap'].get(str(IMP_ID),{})
                assert command.get('action')=='move', ('opening scout stalled',number,result)
                point=Pos.load(command['targetPos'][0])
                # Central transit would expose the IMP to task/shop traffic.
                # Actual obstacles/visibility still come only from this frame.
                enemy_base=next(u for u in Turn.load(raw).enemies if u.kind=='station')
                approach=min(distance(point,p) for p in Turn.load(raw).footprint(enemy_base))<=6
                assert approach or not (13<=point.x<=25 and 13<=point.y<=20), ('central crossing',point)
                path.append(point.dump())
                rows.append(dict(case=f'flank-{right}',round=number,status=200,
                    elapsed_ms=round(elapsed,3),commands=result['roleCommandMap']))
                assert not result['executeCmd']
                apply(raw,truth,result['roleCommandMap'],spawns)
            assert done is not None and done<70
            cases.append(dict(case=f'flank-{right}',survey_all_guns_round=done,
                              path=path,gun_sites=[p.dump() for p in sorted(layout_positions)]))
        for mx,my in ((False,False),(True,False),(False,True),(True,True)):
            raw=group_scene()
            # A real stationary base supplies ordinary sight in this isolated
            # geometry; an economic worker must be free to leave its post.
            raw['teamOur']['roles']=[u for u in raw['teamOur']['roles'] if u['roleType']=='station']
            raw['teamOur']['roles'][0]['pos']=Pos(9,20).dump()
            raw=reflected(raw,mx,my)
            raw['teamOur']['teamId']=f'focus-{mx}-{my}'
            truth=copy.deepcopy(raw['teamEnemy']['roles'])
            common=reflected_cell(Pos(12,19),mx,my)
            shots=[];spawns=[]
            for number in range(71,76):
                raw['roundNo']=number
                reveal(raw,truth)
                result,elapsed=post(port,raw)
                independent_contract(raw,result)
                commands=result['roleCommandMap']
                if number<=73:
                    assert all(commands.get(str(uid))==dict(action='attack',targetPos=[common.dump()])
                               for uid in (FIRST,SECOND)), (number,commands)
                    shots.append(dict(round=number,target=common.dump(),robots=[FIRST,SECOND]))
                elif number==74:
                    assert all(c.get('targetPos')!=[common.dump()] for c in commands.values() if c['action']=='attack')
                rows.append(dict(case=raw['teamOur']['teamId'],round=number,status=200,
                    elapsed_ms=round(elapsed,3),commands=commands,
                    observed_heroes=[dict(id=u['id'],hp=u['health'],pos=u['pos']) for u in truth
                                     if u['roleType'] in ('worker','pioneer')]))
                assert not result['executeCmd']
                apply(raw,truth,commands,spawns)
                raw['robot']['roles']=copy.deepcopy(raw['teamOur']['summonRobotList'])
            cases.append(dict(case=raw['teamOur']['teamId'],common_shots=shots,
                              common_health_final=next(u['health'] for u in truth if u['id']==41001)))
    except Exception as error:
        failure=repr(error)
    finally:
        process.terminate();process.wait(timeout=3)
        capture.seek(0);logs=capture.read().decode('utf-8',errors='replace');capture.close()
    if failure is None and any(marker in logs for marker in ('action_rejected','decision_failed','protocol_error')):
        failure='server reported rejection or failure'
    report=dict(scope='First day public synthetic observations over real localhost HTTP; not official matches',
        assumptions='Prebuilt observation fixtures; stationary enemy guns and crews; 40 simultaneous BOSS damage; no enemy return fire',
        no_private_memory_seed=True,execute_cmd_executed=False,requests=len(rows),cases=cases,
        results=rows,failure=failure,bind_verified=f'0.0.0.0:{port}' in logs)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if failure is not None:
        raise AssertionError(failure)
    print(json.dumps(dict(requests=len(rows),cases=len(cases),all_http_200=True)))


if __name__=='__main__':
    main()
