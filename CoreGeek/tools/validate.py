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
from fractions import Fraction
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from agent.protocol import Pos, distance
from app.config import Settings
from app.service.turn_service import TurnService
from tests.fixtures import request, unit, robot


def independent_wall_blocks(start, end, wall):
    """Slab intersection derived from raw cell squares, independent of combat.py."""
    left, right = 0.0, 1.0
    for origin, finish, middle in ((start.x, end.x, wall.x), (start.y, end.y, wall.y)):
        delta = finish-origin
        if delta == 0:
            if abs(origin-middle) > .5:
                return False
        else:
            bounds = sorted(((middle-.5-origin)/delta, (middle+.5-origin)/delta))
            left, right = max(left,bounds[0]), min(right,bounds[1])
    return left <= right


def independent_contract(raw, response):
    assert set(response) == {"roleCommandMap", "prompt", "executeCmd"}
    assert isinstance(response["prompt"], str) and isinstance(response["executeCmd"], str)
    assert not response["executeCmd"] or raw["phaseTask"]
    units = {str(r["id"]): r for r in raw["teamOur"]["roles"]}
    owned = {str(r['id']): r for r in raw['teamOur'].get('summonRobotList', [])}
    units.update(owned)
    blocked = {Pos.load(z["pos"]) for z in raw["mapInfo"]["zones"] if z["neutralType"] != "land"}
    for unit in raw["teamOur"]["roles"] + raw["teamEnemy"]["roles"] + raw["robot"]["roles"]:
        if unit["health"] <= 0:
            continue
        point = Pos.load(unit["pos"])
        blocked.add(point)
        if unit["roleType"] == "station":
            blocked.update((Pos(point.x + 1, point.y), Pos(point.x, point.y - 1), Pos(point.x + 1, point.y - 1)))
    blocked.update(Pos.load(r['pos']) for r in owned.values() if r['health'] > 0)
    used, destinations = set(), set()
    for key, command in response["roleCommandMap"].items():
        assert key in units and units[key]["health"] > 0
        actor = command.get("controllerId", key)
        assert isinstance(actor, str) and actor in units and actor not in used
        used.add(actor)
        if "targetPos" in command:
            assert isinstance(command["targetPos"], list)
            assert all(0 <= p["x"] < 41 and 0 <= p["y"] < 32 for p in command["targetPos"])
        if command["action"] == "move":
            target = Pos.load(command["targetPos"][0])
            assert distance(Pos.load(units[key]["pos"]), target) == 1
            assert target not in destinations
            assert target not in blocked
            destinations.add(target)
        if command["action"] == "attack":
            assert (raw["roundNo"] - 1) % 130 >= 70
            if key in owned:
                assert set(command) == {'action', 'targetPos'}
                assert len(command['targetPos']) == 1 and owned[key].get('abnormalState') != 'dizzy'
                target = Pos.load(command['targetPos'][0]); origin = Pos.load(owned[key]['pos'])
                assert 0 < distance(origin,target) <= 3
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
                    boss_x = 37 if index % 8 == 0 else 36
                    boss = robot(30000+index,boss_x,8,health=800,roleType='bossRobot')
                    raw['teamOur']['summonRobotList'] = [boss]
                    robot_exclusions = {(30,8),(31,8),(30,7),(31,7),(32,8),(33,8),(34,8),(boss_x,8)}
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
                        controlled_actions[response['roleCommandMap'].get(str(30000+index),{}).get('action','wait')] += 1
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
              "platform": platform.platform(), "rules_baseline": "legacy v1.0 plus v2.0 imp/destroy and owned robot move/attack/summon; user rocket ratio, wall detours and first-night BOSS raid; other v2 features pending",
              "round32_rule_hashes": round32,
              "tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)},
              "synthetic_input_stress": {"seeds": seeds, "teams": ["challenger", "defender"], "cases": count,
                  "pressure": "0..150 robots on night observations; no simulated match outcomes", "failures": failures,
                  "loadout_cases": loadout_cases, "role_cases": role_cases, "imp_actions": imp_actions,
                  "controlled_robot_cases": controlled_cases, "controlled_robot_actions": controlled_actions,
                  "median_ms": round(statistics.median(timings), 3), "max_ms": round(max(timings), 3)},
              "source_hashes": hashes, "baseline_hashes": baseline,
              "construction_policy": "user-authorized base-surroundings fallback enabled by default; explicit verified layouts take precedence; not official geography",
              "unverified": ["D01 official construction coordinates and conservative summon exclusion margin", "D07 trajectory cell-boundary ties and round conventions",
                             "full matches and held-out maps", "official LLM/sandbox/judger integration", "Linux bash entry on target runtime"],
              "scope": "protocol and rule regression plus synthetic observation stress; not official certification or win rate"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tests": report["tests"], "stress": report["synthetic_input_stress"]}, ensure_ascii=True))
    raise SystemExit(not result.wasSuccessful() or bool(failures))


if __name__ == "__main__":
    main()
