"""Record local regression evidence and synthetic input stress, never a win rate."""
import argparse
import hashlib
import json
import platform
import random
import statistics
import sys
import time
import unittest
from collections import deque
from fractions import Fraction
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from agent.protocol import Pos, distance
from app.config import Settings
from app.service.turn_service import TurnService
from tests.fixtures import request, unit, robot


def independent_cell_interval(start, end, cell, interior=False):
    """Raw square/segment geometry; interior excludes edge and corner contact."""
    left, right = 0.0, 1.0
    for origin, finish, middle in ((start.x, end.x, cell.x), (start.y, end.y, cell.y)):
        delta = finish-origin
        if delta == 0:
            if abs(origin-middle) > .5 or (interior and abs(origin-middle) == .5):
                return None
        else:
            bounds = sorted(((middle-.5-origin)/delta, (middle+.5-origin)/delta))
            left, right = max(left,bounds[0]), min(right,bounds[1])
    return (left, right) if (left < right if interior else left <= right) else None


def independent_wall_blocks(start, end, wall):
    """Enumerate 45-degree diagonal cells; retain closed contact otherwise."""
    dx,dy = end.x-start.x,end.y-start.y
    if dx and abs(dx)==abs(dy):
        sx,sy = (1 if dx>0 else -1),(1 if dy>0 else -1)
        return wall in {Pos(start.x+sx*i,start.y+sy*i) for i in range(1,abs(dx))}
    return independent_cell_interval(start, end, wall) is not None


def independent_footprint(unit):
    point = Pos.load(unit['pos'])
    return ((point, Pos(point.x+1,point.y), Pos(point.x,point.y-1), Pos(point.x+1,point.y-1))
            if unit['roleType'] == 'station' else (point,))


def independent_occupied(raw):
    blocked = {Pos.load(z['pos']) for z in raw['mapInfo']['zones'] if z['neutralType'] != 'land'}
    all_units = (raw['teamOur']['roles'] + raw['teamEnemy']['roles'] + raw['robot']['roles']
                 + raw['teamOur'].get('summonRobotList', []))
    blocked.update(p for unit in all_units if unit['health'] > 0 for p in independent_footprint(unit))
    # A task may be supplied without its corresponding neutral map element.
    for task in raw['teamOur'].get('playerTasks', []):
        suffix = '2' if task['taskType'].endswith('2') else '1'
        name = raw['teamOur']['type'] + 'TaskPoint' + suffix
        cells = {Pos.load(z['pos']) for z in raw['mapInfo']['zones'] if z['neutralType'] == name}
        blocked.update(cells or {Pos.load(task['taskPosition'])})
    return blocked


def independent_robot_costs(raw, origin, reserved=()):
    """Eight-neighbour BFS derived only from observed raw occupancy."""
    blocked = independent_occupied(raw) | set(reserved)
    costs, frontier = {origin:0}, deque([origin])
    while frontier:
        here = frontier.popleft()
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                if not dx and not dy:
                    continue
                there = Pos(here.x+dx,here.y+dy)
                if not (0 <= there.x < 41 and 0 <= there.y < 32) or there in blocked or there in costs:
                    continue
                costs[there] = costs[here]+1
                frontier.append(there)
    return costs


def independent_planning_clear(raw, origin, target):
    """Wall legality plus a conservative building-interior planning assumption.

    This additional building/visible-hero test is a planning assumption, not an official projectile rule.
    It is independent of production clear_shot, wall_shelters and Routes.
    """
    if not 0 < distance(origin,target) <= 3:
        return False
    for unit in raw['teamOur']['roles'] + raw['teamEnemy']['roles']:
        if unit['health'] <= 0:
            continue
        if unit['roleType'] == 'wall':
            if Pos.load(unit['pos']) not in (origin,target) and independent_wall_blocks(origin,target,Pos.load(unit['pos'])):
                return False
        elif unit['roleType'] in ('gatling','railgun','rocket','station','worker','pioneer','imp'):
            if any(p not in (origin,target) and independent_cell_interval(origin,target,p,interior=True) is not None
                   for p in independent_footprint(unit)):
                return False
    return True


def independent_firing_cost(raw, target, costs):
    candidates = [cost for post,cost in costs.items() if independent_planning_clear(raw,post,target)]
    return min(candidates) if candidates else None


def independent_crew_opportunity(raw, boss, crews, budget=4, reserved=()):
    """Fresh-turn direct, short walk and cheap wall opportunities, without history."""
    origin = Pos.load(boss['pos'])
    direct = [u for u in crews if independent_planning_clear(raw,origin,Pos.load(u['pos']))]
    costs = independent_robot_costs(raw,origin,reserved)
    walks = {u['id']:independent_firing_cost(raw,Pos.load(u['pos']),costs) for u in crews}
    cheap_walls = set()
    all_walls = [u for u in raw['teamOur']['roles']+raw['teamEnemy']['roles']
                 if u['health'] > 0 and u['roleType'] == 'wall']
    enemy_wall_ids = {u['id'] for u in raw['teamEnemy']['roles'] if u['health'] > 0 and u['roleType'] == 'wall'}
    for crew in crews:
        if walks[crew['id']] is not None and walks[crew['id']] <= budget:
            continue
        target = Pos.load(crew['pos'])
        intersections = [(interval[0],wall['id']) for wall in all_walls
                         if Pos.load(wall['pos']) not in (origin,target)
                         and (interval := independent_cell_interval(origin,target,Pos.load(wall['pos']))) is not None]
        nearest = min(intersections)[1] if intersections else None
        for wall in all_walls:
            if wall['id'] not in enemy_wall_ids:
                continue
            if wall['id'] != nearest and distance(Pos.load(wall['pos']),target) > 1:
                continue
            walk = independent_firing_cost(raw,Pos.load(wall['pos']),costs)
            if walk is not None and walk+(wall['health']+39)//40 <= budget:
                cheap_walls.add(wall['id'])
    return {'direct':direct, 'walks':walks, 'cheap_walls':cheap_walls,
            'efficient':bool(direct or cheap_walls or any(w is not None and w <= budget for w in walks.values()))}


def independent_base_ray_guns(raw, origin):
    """Visible first guns on stationary base rays, using raw square geometry.

    This audit never calls the production raider or projectile planner. A clear
    in-range base footprint cell rules out destroying any other ray's gun.
    Walls use closed contact (and the special exact-45-degree cell rule), while
    other observed buildings/roles block when the segment enters their interior.
    """
    enemy = raw['teamEnemy']['roles']
    base_cells = [p for u in enemy if u['health'] > 0 and u['roleType']=='station'
                  for p in independent_footprint(u) if 0 < distance(origin,p) <= 3]
    gun_ids = {u['id'] for u in enemy if u['health'] > 0
               and u['roleType'] in ('gatling','railgun','rocket')}
    guns = set()
    for target in base_cells:
        hits = []
        for u in raw['teamOur']['roles']+enemy:
            if u['health'] <= 0:
                continue
            for cell in independent_footprint(u):
                if cell in (origin,target):
                    continue
                if u['roleType']=='wall':
                    interval = (independent_cell_interval(origin,target,cell)
                                if independent_wall_blocks(origin,target,cell) else None)
                elif u['roleType'] in ('station','gatling','railgun','rocket','worker','pioneer','imp'):
                    interval = independent_cell_interval(origin,target,cell,interior=True)
                else:
                    continue
                if interval is not None:
                    hits.append((interval[0],u['id'],cell))
        if not hits:
            return set()
        _, uid, cell = min(hits)
        if uid in gun_ids:
            guns.add(cell)
    return guns


def independent_contract(raw, response, controller_budget=4, known_weapon_sites=None, base_focus=False):
    """Audit fresh observations; the stress service has no failed-shot history."""
    assert set(response) == {"roleCommandMap", "prompt", "executeCmd"}
    assert isinstance(response["prompt"], str) and isinstance(response["executeCmd"], str)
    assert not response["executeCmd"] or raw["phaseTask"]
    units = {str(r["id"]): r for r in raw["teamOur"]["roles"]}
    owned = {str(r['id']): r for r in raw['teamOur'].get('summonRobotList', [])}
    units.update(owned)
    enemy_roles = raw['teamEnemy']['roles']
    enemy_weapons = [u for u in enemy_roles if u['health'] > 0
                     and u['roleType'] in ('gatling', 'railgun', 'rocket')]
    weapon_sites=dict(known_weapon_sites or {})
    weapon_sites.update((Pos.load(w['pos']),w['roleType']) for w in enemy_weapons)
    three_rockets = len(weapon_sites)==3 and all(kind=='rocket' for kind in weapon_sites.values())
    cannon_crews = [u for u in enemy_roles if u['health'] > 0
                   and u['roleType'] in (('worker','pioneer','imp') if three_rockets else ('worker','pioneer'))
                   and (all(distance(Pos.load(u['pos']),site)<=1 for site in weapon_sites)
                        if three_rockets else
                        any(distance(Pos.load(u['pos']),Pos.load(w['pos']))<=1 for w in enemy_weapons))]
    crew_cells = {Pos.load(u['pos']) for u in cannon_crews}
    base_cells={p for u in enemy_roles if u['health']>0 and u['roleType']=='station'
                for p in independent_footprint(u)}
    static={p for u in raw['teamOur']['roles']+enemy_roles if u['health']>0
            and u['roleType'] not in ('worker','pioneer','imp') for p in independent_footprint(u)}
    static.update(weapon_sites)
    neutral={Pos.load(z['pos']) for z in raw['mapInfo']['zones'] if z['neutralType']!='land'}
    positions={p for site in weapon_sites for p in site.neighbours()
               if 0<=p.x<41 and 0<=p.y<32 and p not in static|neutral}
    counts={p:sum(distance(p,site)<=1 for site in weapon_sites) for p in positions}
    best={p for p,n in counts.items() if n==max(counts.values(),default=0)}
    bosses=[r for r in owned.values() if r['roleType']=='bossRobot' and r['health']>0]
    group_ready=bool(bosses and any(Pos.load(r['pos']) in best for r in bosses)
                     and all(r.get('abnormalState')!='dizzy' and any(
                         independent_planning_clear(raw,Pos.load(r['pos']),p) for p in base_cells) for r in bosses))
    enemy_wall_cells = {Pos.load(u['pos']) for u in enemy_roles
                        if u['health'] > 0 and u['roleType'] == 'wall'}
    active_bosses=[r for r in bosses if r.get('abnormalState')!='dizzy']
    shared_crew=None
    if len(active_bosses)>1 and not group_ready and not base_focus:
        crew_hits={Pos.load(u['pos']) for u in cannon_crews}
        chosen={Pos.load(c['targetPos'][0]) for key,c in response['roleCommandMap'].items()
                if key in owned and c['action']=='attack' and Pos.load(c['targetPos'][0]) in crew_hits}
        assert len(chosen)<=1, 'BOSS group must not split its cannon-crew fire'
        if chosen:
            shared_crew=next(iter(chosen))
            count=lambda p: sum(independent_planning_clear(raw,Pos.load(r['pos']),p) for r in active_bosses)
            assert count(shared_crew)==max(count(p) for p in crew_hits), 'prefer a jointly hittable observed crew'
    for key, boss in owned.items():
        if (boss['roleType'] != 'bossRobot' or boss['health'] <= 0
                or boss.get('abnormalState') == 'dizzy' or not 71 <= raw['roundNo'] <= 130):
            continue
        origin = Pos.load(boss['pos'])
        if group_ready:
            command=response['roleCommandMap'].get(key,{})
            assert command.get('action')=='attack' and Pos.load(command['targetPos'][0]) in base_cells, 'ready occupied group must focus the base'
            continue
        if base_focus:
            continue
        if shared_crew is not None:
            if independent_planning_clear(raw,origin,shared_crew):
                assert response['roleCommandMap'].get(key)==dict(action='attack',targetPos=[shared_crew.dump()]), 'available group shot must share its target'
            continue
        direct = [u for u in cannon_crews if independent_planning_clear(raw,origin,Pos.load(u['pos']))]
        if direct:
            command = response['roleCommandMap'].get(key, {})
            assert command.get('action') == 'attack', 'visible cannon crew must be attacked before movement'
            assert len(command.get('targetPos', [])) == 1
            target = Pos.load(command['targetPos'][0])
            weakest = min(u['health'] for u in direct)
            assert target in {Pos.load(u['pos']) for u in direct if u['health'] == weakest}, \
                'fresh BOSS attack must target a lowest-current-HP direct cannon crew'
    blocked = independent_occupied(raw)
    used, destinations, caught = set(), set(), set()
    for key, command in response["roleCommandMap"].items():
        assert key in units and units[key]["health"] > 0
        if key in owned:
            assert command.get('action') in ('move','attack') and set(command) == {'action','targetPos'}
            assert len(command['targetPos']) == 1 and owned[key].get('abnormalState') != 'dizzy'
            assert (raw['roundNo']-1) % 130 >= 70
        actor = command.get("controllerId", key)
        assert isinstance(actor, str) and actor in units and actor not in used
        used.add(actor)
        if "targetPos" in command:
            assert isinstance(command["targetPos"], list)
            assert all(0 <= p["x"] < 41 and 0 <= p["y"] < 32 for p in command["targetPos"])
        if command['action'] == 'catch':
            assert key not in owned and units[key]['roleType'] in ('pioneer','worker','imp')
            assert set(command) == {'action','targetPos'} and len(command['targetPos']) == 1
            target = Pos.load(command['targetPos'][0])
            victim = next((u for u in enemy_roles if u['roleType']=='imp'
                           and u['health']>0 and Pos.load(u['pos'])==target),None)
            assert victim is not None and distance(Pos.load(units[key]['pos']),target)==1
            assert victim['id'] not in caught, 'duplicate capture of one enemy imp'
            caught.add(victim['id'])
        if command["action"] == "move":
            daylight = (raw['roundNo'] - 1) % 130 < 70
            driving = (key not in owned and daylight and units[key].get('isDriving') is True)
            points = command['targetPos']
            assert 1 <= len(points) <= (2 if driving else 1)
            # Parked friendly cars are enterable only by ordinary heroes.
            # Keep actual unit occupancy even when a car occupies that cell.
            friendly_cars = ({Pos.load(z['pos']) for z in raw['mapInfo']['zones']
                              if z['neutralType'] == raw['teamOur']['type'] + 'Vehicle'}
                             if key not in owned and daylight else set())
            actor_cells = {p for group in ('teamOur', 'teamEnemy', 'robot')
                           for u in raw[group]['roles'] if u['health'] > 0
                           for p in independent_footprint(u)}
            actor_cells.update(p for u in raw['teamOur'].get('summonRobotList', [])
                               if u['health'] > 0 for p in independent_footprint(u))
            task_cells = set()
            for task in raw['teamOur'].get('playerTasks', []):
                suffix = '2' if task['taskType'].endswith('2') else '1'
                name = raw['teamOur']['type'] + 'TaskPoint' + suffix
                cells = {Pos.load(z['pos']) for z in raw['mapInfo']['zones'] if z['neutralType'] == name}
                task_cells.update(cells or {Pos.load(task['taskPosition'])})
            movement_blocked = (blocked - friendly_cars) | actor_cells | task_cells
            origin = Pos.load(units[key]['pos'])
            movement_blocked.discard(origin)
            previous = origin
            for point in points:
                target = Pos.load(point)
                assert distance(previous, target) == 1
                assert target not in destinations
                assert target not in movement_blocked
                destinations.add(target)
                previous = target
        if command['action'] == 'build':
            target = Pos.load(command['targetPos'][0])
            assert target not in destinations
            assert not any(z['pos'] == target.dump() and z['neutralType'].endswith('Vehicle')
                           for z in raw['mapInfo']['zones'])
            destinations.add(target)
        if command["action"] == "attack":
            assert (raw["roundNo"] - 1) % 130 >= 70
            if key in owned:
                assert set(command) == {'action', 'targetPos'}
                assert len(command['targetPos']) == 1 and owned[key].get('abnormalState') != 'dizzy'
                target = Pos.load(command['targetPos'][0]); origin = Pos.load(owned[key]['pos'])
                assert 0 < distance(origin,target) <= 3
                if owned[key]['roleType'] == 'bossRobot':
                    if base_focus:
                        assert target not in {Pos.load(u['pos']) for u in enemy_roles
                            if u['health']>0 and u['roleType'] in ('worker','pioneer','imp')}, 'committed wall/base assault must not target people'
                    if three_rockets and target in {Pos.load(u['pos']) for u in enemy_roles
                            if u['health']>0 and u['roleType'] in ('worker','pioneer','imp')}:
                        assert target in crew_cells, 'three-rocket BOSS may attack roles only at shared control cells'
                    base_cells = {p for u in enemy_roles if u['health'] > 0 and u['roleType'] == 'station'
                                  for p in independent_footprint(u)}
                    weapon_cells = {Pos.load(u['pos']) for u in enemy_weapons}
                    if target in weapon_cells:
                        assert target in independent_base_ray_guns(raw,origin), \
                            'BOSS weapon target must be first obstacle on a stationary base ray with no clear base cell'
                    if cannon_crews:
                        assert target in crew_cells | enemy_wall_cells | base_cells | weapon_cells, \
                            'BOSS target must be crew, breach wall, base or a base-ray weapon'
                    if cannon_crews and target in base_cells | weapon_cells and not (base_focus or group_ready):
                        opportunity = independent_crew_opportunity(raw,owned[key],cannon_crews,controller_budget,destinations)
                        assert not opportunity['efficient'], 'fresh BOSS may siege the base or weapon only when cannon crew access exceeds its budget'
                enemy_cells = set()
                for enemy in raw['teamEnemy']['roles']:
                    if enemy['health'] > 0:
                        p = Pos.load(enemy['pos']); enemy_cells.add(p)
                        if enemy['roleType'] == 'station':
                            enemy_cells.update((Pos(p.x+1,p.y),Pos(p.x,p.y-1),Pos(p.x+1,p.y-1)))
                assert target in enemy_cells
                walls = [Pos.load(u['pos']) for u in raw['teamOur']['roles']+raw['teamEnemy']['roles']
                         if u['health'] > 0 and u['roleType'] == 'wall' and Pos.load(u['pos']) != target]
                assert not any(independent_wall_blocks(origin,target,p) for p in walls)
                if owned[key]['roleType'] == 'bossRobot':
                    assert independent_planning_clear(raw,origin,target), 'BOSS planning must avoid observed building interiors'
                continue
            assert units[key]["roleType"] in ("gatling", "railgun", "rocket")
            assert units[actor]["roleType"] == "pioneer"
            assert units[key].get("cooldown", 0) == 0
            assert distance(Pos.load(units[key]["pos"]), Pos.load(units[actor]["pos"])) <= 1
            if units[key]['roleType'] == 'rocket':
                targets = [Pos.load(p) for p in command['targetPos']]
                live = [r for r in raw['robot']['roles'] if r['health'] > 0 and str(r['id']) not in owned]
                level = max(1,min(3,units[key].get('level',1)))
                limit = {1:10,2:15,3:10**9}[level]
                observed = units[key].get('attackRange',0)
                if observed > 0:
                    limit = min(limit,observed)
                origin = Pos.load(units[key]['pos'])
                centres = {Pos.load(r['pos']) for r in live
                           if 0 < distance(origin,Pos.load(r['pos'])) <= limit}
                own = {p for p in centres if 40*p.y >= 31*p.x}
                enemies = centres-own
                assert len(targets) == level
                if level == 3:
                    pools = [own,own,enemies] if own and enemies else [own or enemies]*3
                else:
                    pools = [centres]*level
                points = {'smallRobot':1,'middleRobot':2,'largeRobot':4,'bossRobot':10}
                totals = {p:sum((Fraction(points[r['roleType']],r['health']) for r in live
                          if distance(p,Pos.load(r['pos'])) <= 1),Fraction(0)) for p in centres}
                for target, pool in zip(targets,pools):
                    assert target in pool
                    assert totals[target] == max(totals[p] for p in pool)
        if command["action"] == "destroy":
            assert units[key]["roleType"] == "imp"
            assert len(command["targetPos"]) == 1
            target = Pos.load(command["targetPos"][0])
            assert distance(Pos.load(units[key]["pos"]), target) == 1
            assert any(z["pos"] == target.dump() and z["neutralType"] in ('stone','iron','copper')
                       for z in raw["mapInfo"]["zones"])
            # Synthetic fixtures below have their own base in the upper half.
            assert 40*target.y < 31*target.x


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "reports" / "validation.json")
    parser.add_argument("--cases", type=int, default=80)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    timings, failures = [], []
    loadout_cases = {"three_rockets": 0, "mixed_compatibility": 0}
    role_cases = {"with_imp": 0, "legacy_three_roles": 0}
    imp_actions = {"move": 0, "destroy": 0, "wait": 0}
    controlled_cases = 0
    controlled_dual_cases = 0
    controlled_units = 0
    controlled_priority_cases = 0
    controlled_actions = {'move': 0, 'attack': 0, 'wait': 0}
    seeds = [17, 20260917]
    count = 0
    for seed in seeds:
        rng = random.Random(seed)
        for team in ("challenger", "defender"):
            for index in range(args.cases):
                raw = request(rng.randint(1, 1300))
                raw["teamOur"].update(type=team, teamId=f"stress-{seed}-{team}-{index}", goldNum=rng.randint(0, 300))
                raw["teamOur"]["playerTasks"] = []
                raw["teamOur"]["roles"] = [unit(803, "station", 10, 24), unit(800, "worker", 8, 23),
                    unit(801, "pioneer", 10, 26), unit(802, "worker", 12, 23)]
                robot_exclusions = set()
                if index % 4 == 0:
                    raw['roundNo'] = 71 + index % 60
                    raw['teamEnemy']['roles'] = [unit(850,'station',30,8),unit(851,'rocket',32,8),
                                               unit(852,'pioneer',33,8,health=500)]
                    if index % 8 == 0:
                        raw['teamEnemy']['roles'].append(unit(853,'wall',34,8))
                    else:
                        raw['teamEnemy']['roles'] += [unit(854,'gatling',33,10),
                                                     unit(855,'worker',34,10,health=40)]
                        controlled_priority_cases += 1
                    boss_x = 37 if index % 8 == 0 else 36
                    boss = robot(30000+index,boss_x,8,health=800,roleType='bossRobot')
                    raw['teamOur']['summonRobotList'] = [boss]
                    robot_exclusions = {(30,8),(31,8),(30,7),(31,7),(32,8),(33,8),(34,8),(boss_x,8)}
                    if index % 8 == 0:
                        second = robot(31000+index,boss_x,9,health=800,roleType='bossRobot')
                        raw['teamOur']['summonRobotList'].append(second)
                        robot_exclusions.add((boss_x,9))
                        controlled_dual_cases += 1
                    controlled_units += len(raw['teamOur']['summonRobotList'])
                    if index % 8 != 0:
                        robot_exclusions.update(((33,10),(34,10)))
                    controlled_cases += 1
                if index % 2 == 0:
                    imp_pos = (8,24) if index % 4 == 0 else (29,6)
                    raw["teamOur"]["roles"].append(unit(805,"imp",*imp_pos,health=500,level=0))
                    raw["mapInfo"]["zones"] += [{'neutralType':'iron','pos':{'x':30,'y':5}},
                                                 {'neutralType':'stone','pos':{'x':28,'y':9}}]
                    role_cases["with_imp"] += 1
                else:
                    role_cases["legacy_three_roles"] += 1
                loadout = ("rocket", "rocket", "rocket") if index % 2 == 0 else ("gatling", "railgun", "rocket")
                loadout_cases["three_rockets" if index % 2 == 0 else "mixed_compatibility"] += 1
                raw["teamOur"]["roles"] += [unit(810+i, kind, x, y, level=rng.randint(1, 3), cooldown=rng.randint(0, 3) if kind == "rocket" else 0)
                    for i, (kind, x, y) in enumerate((kind, 9+i, 25) for i, kind in enumerate(loadout))]
                if not (raw["roundNo"] - 1) % 130 < 70:
                    excluded = robot_exclusions | ({imp_pos,(30,5),(28,9)} if index % 2 == 0 else set())
                    cells = [(x, y) for x in range(41) for y in range(32)
                             if (x < 6 or x > 16 or y < 18 or y > 28) and (x,y) not in excluded]
                    raw["robot"]["roles"] = [robot(900+i, x, y, health=rng.choice([40, 60, 500, 800]), targetTeam=team)
                        for i, (x, y) in enumerate(rng.sample(cells, rng.randint(0, 150)))]
                    raw['robot']['roles'] += raw['teamOur'].get('summonRobotList', [])
                started = time.perf_counter()
                try:
                    response = TurnService(Settings(enable_news=False)).decide(raw)
                    independent_contract(raw, response)
                    if index % 2 == 0:
                        imp_actions[response['roleCommandMap'].get('805',{}).get('action','wait')] += 1
                    if index % 4 == 0:
                        for controlled in raw['teamOur']['summonRobotList']:
                            controlled_actions[response['roleCommandMap'].get(str(controlled['id']),{}).get('action','wait')] += 1
                except Exception as exc:
                    failures.append({"seed": seed, "team": team, "index": index, "error": repr(exc)})
                timings.append((time.perf_counter() - started) * 1000)
                count += 1
    hashes = {}
    for path in sorted(ROOT.rglob("*.py")):
        if not any(part in ("build", "dist", ".venv") for part in path.parts):
            hashes[path.relative_to(ROOT.parent).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in [ROOT / "pyproject.toml", ROOT / "config.example.json", ROOT / "run.sh", ROOT.parent / "run.sh"]:
        hashes[path.relative_to(ROOT.parent).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    baseline = {name: hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest()
                for name in ("DEVELOPMENT_RULES.md", "任务书.md", "接口文档.md", "request.txt", "response.txt")}
    round32 = {p.relative_to(ROOT.parent).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((ROOT.parent / '32_docs').glob('*')) if p.is_file()}
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "platform": platform.platform(), "rules_baseline": "legacy v1.0 plus v2.0 imp/destroy and owned robot move/attack/summon; user rocket ratio, legal wall rings, cannon-crew-first BOSS raid with bounded chase then base siege, and a frozen zero/one/two/three BOSS quota from independently recorded Task1/Task2/Task1 attempts after all three end; weapon purchases follow the order attempt; use waits for actual worker survey and live normal-unit sight; inferred common cannon control cells guide placement, not attacks; scouted single-wall breach work is not chase walking; rear spawn pad 2; day-one hero sight mission and worker departure after observed defense completion; summoned robots supply no sight per user staff clarification; remembered static buildings and visible-hero interior LOS are conservative planning assumptions; persistent static-shot feedback and close base recovery; user-confirmed footprint distance-one weapons/distance-two walls, no detours; 17-wall mirrored home layout with an actual daytime removed wall and interior dusk resealing, reserved stone and restored level two; visible weapon-on-base-ray clearance and stationary no-gun base-neighbour sweep; worker/imp gap relay, BOSS budget before first-night supplies, guard and scout catch avoidance; other v2 features pending",
              "round32_rule_hashes": round32,
              "tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)},
              "synthetic_input_stress": {"seeds": seeds, "teams": ["challenger", "defender"], "cases": count,
                  "pressure": "0..150 robots on night observations; no simulated match outcomes", "failures": failures,
                  "loadout_cases": loadout_cases, "role_cases": role_cases, "imp_actions": imp_actions,
                  "controlled_robot_cases": controlled_cases, "controlled_robot_actions": controlled_actions,
                  "controlled_dual_cases": controlled_dual_cases, "controlled_robot_units": controlled_units,
                  "controlled_robot_priority_cases": controlled_priority_cases,
                  "median_ms": round(statistics.median(timings), 3), "max_ms": round(max(timings), 3)},
              "source_hashes": hashes, "baseline_hashes": baseline,
              "construction_policy": "user-confirmed ring geometry: weapons at footprint Chebyshev distance one, walls distance two; configured layouts are filtered by these rings; 17-wall mirrored blueprint, one actual daytime entrance and night restoration; no door building or wall traversal introduced",
              "unverified": ["D01 complete official construction coordinates; rear spawn pad 2 is user-screenshot evidence, not official region data", "D07 non-45-degree trajectory boundaries and round conventions; exact-45 side-wall corners are excluded per user clarification",
                             "hidden heroes cannot be attacked or inferred dead; remembered static buildings support planning and visible-crew recognition, not attack target invention",
                             "scout observation neighbourhood and travel ETA are planning heuristics; actual official sight, collisions and raid damage require match validation",
                             "full matches and held-out maps", "official LLM/sandbox/judger integration", "Linux bash entry on target runtime"],
              "scope": "protocol and rule regression plus synthetic observation stress; not official certification or win rate"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tests": report["tests"], "stress": report["synthetic_input_stress"]}, ensure_ascii=True))
    raise SystemExit(not result.wasSuccessful() or bool(failures))


if __name__ == "__main__":
    main()
