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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from agent.protocol import Pos, distance
from app.config import Settings
from app.service.turn_service import TurnService
from tests.fixtures import request, unit, robot


def independent_contract(raw, response):
    assert set(response) == {"roleCommandMap", "prompt", "executeCmd"}
    assert isinstance(response["prompt"], str) and isinstance(response["executeCmd"], str)
    assert not response["executeCmd"] or raw["phaseTask"]
    units = {str(r["id"]): r for r in raw["teamOur"]["roles"]}
    blocked = {Pos.load(z["pos"]) for z in raw["mapInfo"]["zones"] if z["neutralType"] != "land"}
    for unit in raw["teamOur"]["roles"] + raw["teamEnemy"]["roles"] + raw["robot"]["roles"]:
        if unit["health"] <= 0:
            continue
        point = Pos.load(unit["pos"])
        blocked.add(point)
        if unit["roleType"] == "station":
            blocked.update((Pos(point.x + 1, point.y), Pos(point.x, point.y - 1), Pos(point.x + 1, point.y - 1)))
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
            assert units[key]["roleType"] in ("gatling", "railgun", "rocket")
            assert units[actor]["roleType"] == "pioneer"
            assert units[key].get("cooldown", 0) == 0
            assert distance(Pos.load(units[key]["pos"]), Pos.load(units[actor]["pos"])) <= 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "reports" / "validation.json")
    parser.add_argument("--cases", type=int, default=80)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    timings, failures = [], []
    loadout_cases = {"three_rockets": 0, "mixed_compatibility": 0}
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
                loadout = ("rocket", "rocket", "rocket") if index % 2 == 0 else ("gatling", "railgun", "rocket")
                loadout_cases["three_rockets" if index % 2 == 0 else "mixed_compatibility"] += 1
                raw["teamOur"]["roles"] += [unit(810+i, kind, x, y, level=rng.randint(1, 3), cooldown=rng.randint(0, 3) if kind == "rocket" else 0)
                    for i, (kind, x, y) in enumerate((kind, 9+i, 25) for i, kind in enumerate(loadout))]
                if not (raw["roundNo"] - 1) % 130 < 70:
                    cells = [(x, y) for x in range(41) for y in range(32)
                             if x < 6 or x > 16 or y < 18 or y > 28]
                    raw["robot"]["roles"] = [robot(900+i, x, y, health=rng.choice([40, 60, 500, 800]), targetTeam=team)
                        for i, (x, y) in enumerate(rng.sample(cells, rng.randint(0, 150)))]
                started = time.perf_counter()
                try:
                    response = TurnService(Settings(enable_news=False)).decide(raw)
                    independent_contract(raw, response)
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
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "platform": platform.platform(), "rules_baseline": "local v1.0 2026-09-09; upstream commit recorded in DEVELOPMENT_RULES.md",
              "tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)},
              "synthetic_input_stress": {"seeds": seeds, "teams": ["challenger", "defender"], "cases": count,
                  "pressure": "0..150 robots on night observations; no simulated match outcomes", "failures": failures,
                  "loadout_cases": loadout_cases,
                  "median_ms": round(statistics.median(timings), 3), "max_ms": round(max(timings), 3)},
              "source_hashes": hashes, "baseline_hashes": baseline,
              "construction_policy": "user-authorized base-surroundings fallback enabled by default; explicit verified layouts take precedence; not official geography",
              "unverified": ["D01 official construction coordinates", "D07 trajectory cell-boundary ties and round conventions",
                             "full matches and held-out maps", "official LLM/sandbox/judger integration", "Linux bash entry on target runtime"],
              "scope": "protocol and rule regression plus synthetic observation stress; not official certification or win rate"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tests": report["tests"], "stress": report["synthetic_input_stress"]}, ensure_ascii=True))
    raise SystemExit(not result.wasSuccessful() or bool(failures))


if __name__ == "__main__":
    main()
