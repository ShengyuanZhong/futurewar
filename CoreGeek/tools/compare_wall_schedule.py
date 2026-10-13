"""Local construction-only comparison against our v1.2.15 policy snapshot.

Input geometry and 9/8 bags derive from build_bug; the shop body (24,20)
is synthetic because the log only records a shop approach (24,19). Tasks,
shopping and combat are disabled to isolate wall movement and the next-trip
estimate. Trusted local Git source is loaded; no log command is executed.
"""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.grid import Routes,adjacent_cells
from agent.protocol import Pos,Turn,distance
from app.service.memory import GameMemory
from tests.fixtures import unit
from tests.test_wall_schedule import scene
from tools.smoke_first_day_flow import apply_commands


def previous_strategy():
    namespaces={}
    for name in ('sealed_home','worker_coordinator','gap_defense','stone_planner','brain'):
        path=f'CoreGeek/src/agent/{name}.py'
        code=subprocess.check_output(['git','show',f'6283eb8:{path}'],cwd=ROOT.parent).decode('utf-8-sig')
        namespace=dict(__name__='agent._comparison_'+name,__package__='agent')
        exec(compile(code,path,'exec'),namespace)
        namespaces[name]=namespace
    namespaces['brain']['WallGapDefense']=namespaces['gap_defense']['WallGapDefense']
    namespaces['brain']['StonePlanner']=namespaces['stone_planner']['StonePlanner']
    namespaces['brain']['SealedHome']=namespaces['sealed_home']['SealedHome']
    namespaces['brain']['WorkerCoordinator']=namespaces['worker_coordinator']['WorkerCoordinator']
    return namespaces['brain']['Strategy']


def simulate(factory,upper):
    raw,_,settings=scene(upper=upper,round_no=29)
    memory=GameMemory()
    initial=copy.deepcopy(raw)
    rows=[];closed=None;movements={501:0,504:0};built={501:[],504:[]}
    for number in range(29,71):
        raw['roundNo']=number
        if not upper:
            # A one-frame actual observed occupant creates the logged historical
            # top gap; it leaves in the next observation. Other inputs unchanged.
            raw['teamEnemy']['roles']=[u for u in raw['teamEnemy']['roles'] if u['id']!=999]
            if number==36 and not any(u['roleType']=='wall' and u['pos']==Pos(28,11).dump()
                                      for u in raw['teamOur']['roles']):
                raw['teamEnemy']['roles'].append(unit(999,'imp',28,11,health=500))
        turn=Turn.load(raw)
        if len(turn.walls())==17:
            closed=number;break
        plan=ActionPlan(turn,settings)
        strategy=factory(turn,plan,memory)
        strategy.run()
        assert not plan.rejections,plan.rejections
        assert not any(c['action']=='remove' for c in plan.commands.values())
        trial=copy.deepcopy(raw)
        for index,c in enumerate(plan.commands.values()):
            if c['action']=='build':
                p=Pos.load(c['targetPos'][0])
                trial['teamOur']['roles'].append(unit(9000+index,'wall',p.x,p.y,health=1000))
        projected=Turn.load(trial)
        shop=Pos(24,20)
        for worker in projected.workers():
            assert Routes(projected,worker).nearest(adjacent_cells(projected,[shop])) is not None
        for worker in turn.workers():
            c=plan.commands.get(str(worker.unit_id),{})
            if c.get('action')=='move':
                movements[worker.unit_id]+=len(c['targetPos'])
            elif c.get('action')=='build':
                built[worker.unit_id].append(dict(round=number,pos=c['targetPos'][0]))
        rows.append(dict(round=number,walls=len(turn.walls()),positions={str(w.unit_id):w.pos.dump() for w in turn.workers()},
            stones={str(w.unit_id):w.backpack.count('stone') for w in turn.workers()},commands=copy.deepcopy(plan.commands),
            jobs={str(uid):dict(kind=job.get('kind'),target=job.get('target').dump() if isinstance(job.get('target'),Pos) else job.get('target'))
                  for uid,job in memory.worker_tasks.items()}))
        memory.record(turn,plan)
        apply_commands(raw,plan.commands,[])
        raw['roundNo']=number+1
        memory.observe(Turn.load(raw))
    final=Turn.load(raw)
    next_trips={}
    for worker in final.workers():
        route=Routes(final,worker)
        if worker.unit_id==501:
            goals=adjacent_cells(final,[Pos(24,20)])
        else:
            base=next(u for u in final.enemies if u.kind=='station')
            goals={p for p in route.cost if 2<min(distance(p,b) for b in final.footprint(base))<=4}
        post=route.nearest(goals)
        next_trips[worker.unit_id]=route.cost[post] if post is not None else None
    assert closed is not None,(factory.__name__,upper,'unfinished at R70')
    return dict(base=initial['teamOur']['roles'][0]['pos'],closed_round=closed,
        movement_steps=movements,estimated_next_trip=next_trips,
        total_movement_and_next_trip=sum(movements.values())+sum(next_trips.values()),
        walls_built=built,final_positions={str(w.unit_id):w.pos.dump() for w in final.workers()},rows=rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    old=previous_strategy()
    cases=[]
    for upper in (False,True):
        before=simulate(old,upper)
        after=simulate(Strategy,upper)
        cases.append(dict(upper=upper,previous=before,current=after))
    report=dict(scope='First-day R29..70 local construction-only policy comparison; not official replay',
        previous_revision='6283eb8',shop_assumption=dict(x=24,y=20),
        initial_conditions='Three observed rockets, zero walls, actual bags9/8, no mines; historical one-frame occupant in lower case; tasks/shopping/combat disabled',
        next_trip_scope='Actual shop-neighbour path and nearest legal exterior range-four enemy-base lookout, not a full layout survey',cases=cases)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([dict(upper=c['upper'],previous_closed=c['previous']['closed_round'],
        current_closed=c['current']['closed_round'],previous_steps=c['previous']['total_movement_and_next_trip'],
        current_steps=c['current']['total_movement_and_next_trip']) for c in cases]))


if __name__=='__main__':
    main()
