"""Target selection estimates damage, but never simulates authoritative results."""
from itertools import permutations
import time
from .grid import Routes, adjacent_cells
from .protocol import Pos, Turn, Unit, distance


def pair_weapons(turn: Turn, roles: tuple[Unit, ...]) -> tuple[tuple[Unit, Unit], ...]:
    weapons = turn.weapons()
    if not roles or not weapons:
        return ()
    routes = {r.unit_id: Routes(turn, r) for r in roles}
    costs = {}
    for role in roles:
        for tower in weapons:
            route = routes[role.unit_id]
            stand = route.nearest(adjacent_cells(turn, [tower.pos]))
            costs[role.unit_id, tower.unit_id] = route.cost.get(stand, 10_000)
    size = min(len(roles), len(weapons))
    best, best_score = (), None
    for actors in permutations(roles, size):
        for towers in permutations(weapons, size):
            pairs = tuple(zip(actors, towers))
            values = [costs[r.unit_id, t.unit_id] for r, t in pairs]
            score = (sum(v >= 10_000 for v in values), sum(values), tuple((r.unit_id, t.unit_id) for r, t in pairs))
            if best_score is None or score < best_score:
                best, best_score = pairs, score
    return tuple((r, t) for r, t in best if costs[r.unit_id, t.unit_id] < 10_000)


def segment_entry(start: Pos, end: Pos, cell: Pos) -> float | None:
    """Center-to-center segment vs closed cell square; boundary ties are D07."""
    lo, hi = 0.0, 1.0
    for origin, delta, middle in ((start.x, end.x - start.x, cell.x), (start.y, end.y - start.y, cell.y)):
        if not delta:
            if abs(origin - middle) > .5:
                return None
            continue
        a, b = (middle - .5 - origin) / delta, (middle + .5 - origin) / delta
        lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
        if lo > hi:
            return None
    return lo


def damage_for(turn: Turn, tower: Unit, target: Pos, health: dict[int, int]) -> dict[int, int]:
    if tower.kind == "rocket":
        return {r.robot_id: min(health.get(r.robot_id, r.health), 20 if r.pos == target else 10)
                for r in turn.robots if r.health > 0 and distance(r.pos, target) <= 1}
    hits = []
    for robot in turn.robots:
        if robot.health <= 0 or health.get(robot.robot_id, robot.health) <= 0:
            continue
        entry = segment_entry(tower.pos, target, robot.pos)
        if entry is not None:
            hits.append((entry, robot.robot_id, robot))
    hits.sort(key=lambda hit: (hit[0], hit[1]))
    energy = 10 * max(1, tower.level) if tower.kind == "railgun" else 10
    result = {}
    for _, rid, robot in hits:
        hit = min(energy, health.get(rid, robot.health))
        result[rid] = hit
        energy -= hit
        if tower.kind == "gatling" or energy <= 0:
            break
    return result


def choose_targets(turn: Turn, tower: Unit, expected_health: dict[int, int], deadline=float("inf")) -> list[Pos]:
    robots = [r for r in turn.robots if r.health > 0]
    candidates = {r.pos for r in robots}
    if tower.kind == "rocket":
        candidates.update(p for r in robots for p in r.pos.neighbours())
    candidates = sorted(p for p in candidates if turn.in_bounds(p) and 0 < distance(tower.pos, p) <= tower.range_of_attack())
    targets = []
    count = 1 if tower.kind == "railgun" else max(1, min(3, tower.level))
    health = dict(expected_health)
    station = turn.station()
    for _ in range(count):
        choices = []
        for target in candidates:
            if time.monotonic() >= deadline:
                return []
            if tower.kind == "gatling" and any((p.x - tower.pos.x) * (target.x - tower.pos.x) + (p.y - tower.pos.y) * (target.y - tower.pos.y) < 0 for p in targets):
                continue
            damage = damage_for(turn, tower, target, health)
            score = 0.0
            for robot in robots:
                weight = 1.5 if robot.target_team == turn.team_type else 1.0
                if station:
                    weight += 3 / (1 + min(distance(robot.pos, p) for p in turn.footprint(station)))
                score += damage.get(robot.robot_id, 0) * weight
            choices.append((score, -distance(tower.pos, target), target, damage))
        if not choices:
            return []
        score, _, target, damage = max(choices, key=lambda c: (c[0], c[1], c[2]))
        if score <= 0 and not targets:
            return []
        if score <= 0:
            target = targets[0]
            damage = damage_for(turn, tower, target, health)
        targets.append(target)
        for rid, amount in damage.items():
            health[rid] = max(0, health.get(rid, 0) - amount)
    expected_health.update(health)
    return targets
