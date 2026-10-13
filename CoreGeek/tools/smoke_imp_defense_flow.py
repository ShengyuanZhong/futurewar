"""First-day public HTTP evidence for adjacent catches and returning defenders.

Task verdicts, the completed home and the passive enemy IMP are synthetic
inputs. Ordinary friendly range-four sight filters every frame; no server
memory is injected, no executeCmd is executed, and walls are never removed
to make a defender's route work.
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
from tests.fixtures import unit
from tests.test_layout_survey import reveal
from tests.test_worker_boss_buyer import BUYER, ORDER, PIONEER, SCOUT, SHOP, actor
from tools.smoke_first_day_flow import task_frame
from tools.smoke_scout_flow import apply, ordinary_sight
from tools.smoke_worker_buyer_flow import fixture, post
from tools.validate import independent_contract

ENEMY_IMP = 906


def public_fixture(lower_right):
    raw, truth, summary = fixture(lower_right)
    # The shared historical fixture used enlarged role/base HP. This focused
    # catch flow uses the v2.0 level-one values; only the opening is prebuilt.
    maximum={'station':1500,'pioneer':200,'worker':220,'imp':500}
    for item in raw['teamOur']['roles']+truth:
        if item['roleType'] in maximum:
            item['health']=maximum[item['roleType']]
    return raw,truth,summary


def apply_public(raw, truth, commands, spawns):
    """Extend the existing simultaneous driver with documented catch feedback."""
    before = Turn.load(raw)
    caught = set()
    for key, command in commands.items():
        assert command['action'] != 'remove', 'defenders must preserve the real walls'
        if command['action'] != 'catch':
            continue
        source = next(u for u in before.ours if str(u.unit_id) == key)
        target = Pos.load(command['targetPos'][0])
        victim = next(u for u in before.enemies
                      if u.kind == 'imp' and u.health > 0 and u.pos == target)
        assert source.kind in ('pioneer', 'worker', 'imp')
        assert 0 < distance(source.pos, target) <= 1
        assert any(distance(p, target) <= 4 for p in ordinary_sight(raw))
        assert victim.unit_id not in caught, 'duplicate catches waste the turn'
        caught.add(victim.unit_id)
    apply(raw, truth, {key: command for key, command in commands.items()
                      if command['action'] != 'catch'}, spawns)
    for victim in truth:
        if victim['id'] in caught:
            victim['health'] = 0
            raw['teamOur']['goldNum'] += 20
    raw['lastRoundRoleActionResults'] = {key: True for key in commands}
    return sorted(caught)


def wait_server(port):
    deadline = time.monotonic() + 5
    while True:
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
        try:
            conn.request('GET', '/health')
            response = conn.getresponse()
            response.read()
            if response.status == 200:
                return
        except (OSError, http.client.HTTPException):
            if time.monotonic() >= deadline:
                raise RuntimeError('CLI did not start')
            time.sleep(.05)
        finally:
            conn.close()


def compact(raw, result, elapsed, name):
    return dict(case=name, round=raw['roundNo'], status=200,
        elapsed_ms=round(elapsed, 3),
        positions={str(u['id']): u['pos'] for u in raw['teamOur']['roles']
                   if u['roleType'] in ('worker', 'pioneer')},
        visible_imps=[dict(id=u['id'], pos=u['pos'], hp=u['health'])
                      for u in raw['teamEnemy']['roles'] if u['roleType']=='imp'],
        commands=result['roleCommandMap'], gold=raw['teamOur']['goldNum'])


def catch_scenarios(port, rows, cases):
    """Workers catch immediately; unfinished pioneer tasks keep their action."""
    for lower_right in (False, True):
        for who, number, context in ((PIONEER, 1, 'day'), (BUYER, 71, 'night'),
                                     (PIONEER, 3, 'task'), (BUYER, 40, 'shop')):
            raw, truth, _ = public_fixture(lower_right)
            name = f'adjacent-{context}-{"right" if lower_right else "left"}'
            raw['teamOur'].update(teamId=name, playerTasks=[])
            raw.update(roundNo=number, phaseTask='', llmResp='')
            source = Pos(17, 13) if context=='shop' else Pos(16, 11)
            actor(raw, who)['pos'] = source.dump()
            other = BUYER if who==PIONEER else PIONEER
            actor(raw, other)['pos'] = Pos(19, 16).dump()
            actor(raw, SCOUT)['pos'] = Pos(25, 17).dump()
            if context=='shop':
                actor(raw, who)['backpack'] += [ORDER]
            if context=='task':
                raw['phaseTask']='Synthetic active task; unfinished pioneer must keep working'
                raw['llmResp']=json.dumps(dict(action='final_answer', answer='fixture-answer'))
            target = Pos(source.x+1, source.y+1)
            truth.append(unit(ENEMY_IMP, 'imp', target.x, target.y, health=500))
            reveal(raw, truth)
            result, elapsed = post(port, raw)
            independent_contract(raw, result)
            if who == PIONEER:
                assert result['roleCommandMap'].get(str(who),{}).get('action')!='catch', (name,result)
                if context == 'task':
                    assert result['prompt'], (name,'active pioneer task must continue')
            else:
                assert result['roleCommandMap'].get(str(who))==dict(
                    action='catch', targetPos=[target.dump()]), (name,result)
            assert not result['executeCmd']
            rows.append(compact(raw,result,elapsed,name))
            gold = raw['teamOur']['goldNum']
            captured=apply_public(raw, truth, result['roleCommandMap'], [])
            if who==PIONEER:
                assert not captured, (name,'unfinished tasks must not spend a capture turn')
            else:
                assert captured==[ENEMY_IMP] and raw['teamOur']['goldNum'] >= gold+20
            cases.append(dict(case=name, actor=who, captured=captured,
                              pioneer_task_priority=who==PIONEER, diagonal_neighbour=True))


def return_flow(port, lower_right, mode, rows, cases):
    raw, truth, summary = public_fixture(lower_right)
    name=f'return-{mode}-{"right" if lower_right else "left"}'
    raw['teamOur']['teamId']=name
    base=Pos.load(actor(raw,503)['pos'])
    mirrored=lower_right
    imp_pos=Pos(base.x+(4 if mirrored else -3), base.y-2)
    imp=unit(ENEMY_IMP,'imp',imp_pos.x,imp_pos.y,health=500)
    spawns=[]; buys=[];uses=[];accepts=[];defenders=set(); catches=[]; resumed=[]
    ended_round=None; escape_trace=[]; no_current_target_rounds=[]
    initial_walls={u['id']:u['pos'] for u in raw['teamOur']['roles'] if u['roleType']=='wall'}
    for number in range(1,101):
        task_frame(raw,number,(True,True,True))
        if number==41:
            truth.append(imp)
        if 47<=number<=52 and mode in ('escaped','lost-sight') and imp['health']>0:
            # A real one-cell enemy step on each frame, never a teleport.
            # The escaped case stops just outside the home radius, still
            # visible from the outer walls. The lost-sight case goes further.
            old=Pos.load(imp['pos'])
            limit=3 if mode=='escaped' else 6
            if number-47<limit:
                target=Pos(old.x+(1 if mirrored else -1),old.y)
                if 0<=target.x<41:
                    assert distance(old,target)==1 and target not in Turn.load(raw).occupied_cells()
                    imp['pos']=target.dump()
                    escape_trace.append(dict(round=number,pos=target.dump()))
        reveal(raw,truth)
        result,elapsed=post(port,raw)
        independent_contract(raw,result)
        commands=result['roleCommandMap']
        assert not result['executeCmd']
        if number in (1,4,34):
            assert commands.get(str(PIONEER),{}).get('action')=='acceptTask', (name,number,commands)
            accepts.append({1:2,4:1,34:2}[number])
        buyer=commands.get(str(BUYER),{})
        if buyer.get('action')=='buy' and buyer.get('name')==ORDER:
            assert number>=37 and distance(Pos.load(actor(raw,BUYER)['pos']),SHOP)<=1
            buys.append(dict(round=number,num=buyer.get('num',1)))
        if buyer.get('action')=='use' and buyer.get('name')==ORDER:
            uses.append(number)
        if number>=41:
            assert not any(command['action']=='remove' for command in commands.values())
            home_imp=next((u for u in Turn.load(raw).enemies
                           if u.kind=='imp' and u.health>0),None)
            for uid in (PIONEER,BUYER):
                command=commands.get(str(uid),{})
                if command.get('action')=='catch':
                    defenders.add(uid);catches.append(dict(round=number,actor=uid))
                elif command.get('action')=='move' and home_imp is not None and number<49:
                    # Both returning actors must reach the home vicinity;
                    # paths may skirt an actual wall rather than be straight.
                    source=Pos.load(actor(raw,uid)['pos'])
                    target=Pos.load(command['targetPos'][-1])
                    if distance(target,home_imp.pos)<distance(source,home_imp.pos):
                        defenders.add(uid)
            protected={p for u in Turn.load(raw).ours if u.kind in ('station','rocket','gatling','railgun')
                       for p in Turn.load(raw).footprint(u)}
            active=home_imp is not None and min(distance(home_imp.pos,p) for p in protected)<=4
            if not active and ended_round is None:
                ended_round=number
            if ended_round is not None and commands.get(str(PIONEER),{}).get('action')=='move':
                resumed.append(dict(round=number,actor=PIONEER,
                                    target=commands[str(PIONEER)]['targetPos'][-1]))
            if not active:
                no_current_target_rounds.append(number)
        rows.append(compact(raw,result,elapsed,name))
        apply_public(raw,truth,commands,spawns)
        # Real static barriers remain throughout the sequence, and no private
        # home entry is opened just to satisfy the expected return result.
        assert all(any(u['id']==uid and u['pos']==pos and u['health']>0
                       for u in raw['teamOur']['roles']) for uid,pos in initial_walls.items())
    assert accepts==[2,1,2] and buys==[dict(round=37,num=3)] and uses==[38,39,40], (name,accepts,buys,uses)
    assert len(spawns)==3 and ORDER not in actor(raw,BUYER)['backpack']
    assert defenders=={PIONEER,BUYER}, (name,'both returning actors must participate',defenders)
    if mode=='captured':
        assert imp['health']==0 and catches, (name,catches,imp)
    else:
        assert imp['health']>0 and not catches and escape_trace and no_current_target_rounds, (name,imp,catches)
        if mode=='lost-sight':
            assert not any(distance(p,Pos.load(imp['pos']))<=4 for p in ordinary_sight(raw)), (name,'fixture must actually lose sight')
    assert resumed, (name,'pioneer must resume return/control after intruder ends')
    cases.append(dict(case=name,base=base.dump(),task_sequence=accepts,buys=buys,use_rounds=uses,
        actual_feedback_after_use_round=41,buyer_orders_final=actor(raw,BUYER)['backpack'].count(ORDER),
        participating_defenders=sorted(defenders),catches=catches,
        enemy_imp_health_final=imp['health'],pioneer_final=actor(raw,PIONEER)['pos'],
        buyer_final=actor(raw,BUYER)['pos'],preserved_wall_count=len(initial_walls),
        imp_escape_trace=escape_trace,current_target_ended_round=ended_round,
        resume_first_round=resumed[0]['round']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    capture=tempfile.TemporaryFile()
    process=subprocess.Popen([sys.executable,str(ROOT/'main3.py'),str(port)],cwd=ROOT.parent,
        stdout=subprocess.DEVNULL,stderr=capture,creationflags=flags)
    rows=[];cases=[];failure=None
    try:
        wait_server(port)
        catch_scenarios(port,rows,cases)
        for lower_right,mode in ((False,'captured'),(True,'captured'),
                                 (False,'escaped'),(True,'lost-sight')):
            return_flow(port,lower_right,mode,rows,cases)
    except Exception as error:
        failure=repr(error)
    finally:
        process.terminate();process.wait(timeout=3)
        capture.seek(0);logs=capture.read().decode('utf-8',errors='replace');capture.close()
    if failure is None and any(marker in logs for marker in ('action_rejected','decision_failed','protocol_error')):
        failure='HTTP server reported rejected action or decision/protocol failure'
    diagnostics=[]
    for line in logs.splitlines():
        if 'imp_defense ' in line:
            try:
                diagnostics.append(json.loads(line.split('imp_defense ',1)[1]))
            except json.JSONDecodeError:
                pass
    if failure is None:
        for case in cases:
            if not case['case'].startswith('return-'):
                continue
            observed=[entry for entry in diagnostics if entry.get('team_id')==case['case']]
            chasing={int(uid) for entry in observed for uid, detail in entry.get('roles',{}).items()
                     if detail.get('reason') in ('chase_home_imp','catch_neighbour')}
            if chasing!={PIONEER,BUYER}:
                failure=repr((case['case'],'actual diagnostic must confirm both defenders',chasing))
                break
            end=case['current_target_ended_round']
            if any(detail.get('reason')=='chase_home_imp' for entry in observed if entry['round']>=end
                   for detail in entry.get('roles',{}).values()):
                failure=repr((case['case'],'no ghost pursuit after caught/outside home'))
                break
            case['verified_chasing_defenders']=sorted(chasing)
            case['no_ghost_chase_after_round']=end
    report=dict(scope='First-day synthetic public observations over real localhost HTTP; not official matches',
        assumptions='Prebuilt17walls/3guns; synthetic task verdicts and ordinary visibility; passive enemy IMP; no enemy return fire or official wave simulation',
        visibility='Alive ordinary friendly range4; enemy base/wall globally visible; summoned robots supply no sight',
        no_private_memory_seed=True,execute_cmd_executed=False,
        capture_settlement='Actual visible eight-neighbour catch kills IMP and adds20gold; next frame explicit success feedback',
        wall_policy='All actual fixture walls retained; no removal/ghost movement allowed',
        bind_verified=f'0.0.0.0:{port}' in logs,requests=len(rows),cases=cases,results=rows,
        diagnostics=diagnostics,failure=failure)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if failure is not None:
        raise AssertionError(failure)
    print(json.dumps(dict(requests=len(rows),all_http_200=True,cases=len(cases))))


if __name__=='__main__':
    main()
