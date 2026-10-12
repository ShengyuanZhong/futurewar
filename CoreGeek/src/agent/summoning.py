"""Legal summon cells and placement planned from actually scouted enemy guns.

Operator positions below are hypotheses for placement and observer coverage.
They are never observations and must not be used as robot attack targets.
"""
from collections import deque
from dataclasses import replace
from math import ceil

from .combat import segment_entry
from .protocol import CONTROLLABLE_TYPES, LAND, MINERALS, TOWER_TYPES, Pos, distance, station_footprint
from .robot_combat import blocking_wall, planning_building_blocker


def enemy_base_position(turn):
    enemy = next((u for u in turn.enemies if u.kind == 'station'), None)
    if enemy:
        return enemy.pos
    ours = turn.station()
    # Reflect all four base cells through the map centre, then take top-left.
    return Pos(turn.width - 2 - ours.pos.x, turn.height - ours.pos.y) if ours else None


def enemy_rear_position(turn):
    base = enemy_base_position(turn)
    if base is None:
        return None
    right = 2 * base.x + 1 > turn.width - 1
    return Pos(base.x + (3 if right else -2), base.y)


def summon_cell_legal(turn, settings, pos, pending=()):
    if not turn.in_bounds(pos) or pos in pending:
        return False
    if turn.zones.get(pos, LAND) not in MINERALS + (LAND,):
        return False
    if any(pos in turn.task_cells(t) for t in turn.tasks):
        return False
    bases = [u.pos for u in turn.ours + turn.enemies if u.kind == 'station']
    inferred = enemy_base_position(turn)
    if inferred is not None and inferred not in bases:
        bases.append(inferred)
    # User image: base (9,22), full coloured region x=7..12, y=19..24.
    # Extra configured margin may enlarge it, never shrink this two-cell floor.
    for base in bases:
        if min(distance(pos, p) for p in station_footprint(base)) <= max(2, settings.summon_build_margin):
            return False
    if pos in settings.build_cells(turn, 'wall') or pos in settings.build_cells(turn, 'rocket'):
        return False
    enemy = next((u for u in turn.enemies if u.kind == 'station'), None)
    layout = settings.layouts.get('defender' if turn.team_type == 'challenger' else 'challenger', {})
    if enemy and layout.get('verified') is True:
        if any(pos == Pos(enemy.pos.x+p['x'], enemy.pos.y+p['y'])
               for p in layout.get('walls', []) + layout.get('weapons', [])):
            return False
    return not any(u.health > 0 and u.kind not in CONTROLLABLE_TYPES and pos in turn.footprint(u)
                   for u in turn.ours + turn.enemies)


def rear_spawn_position(turn, settings, pending=(), failed=()):
    base = enemy_base_position(turn)
    rear = enemy_rear_position(turn)
    if base is None or rear is None:
        return None
    right = 2 * base.x + 1 > turn.width - 1
    x = base.x + (4 if right else -3)
    preferred = (Pos(x,base.y), Pos(x,base.y-1))
    occupied = turn.occupied_cells() | {r.pos for r in turn.robots if r.health > 0}
    candidates = [Pos(x, y) for x in range(turn.width) for y in range(turn.height)
                  if (x > base.x + 1 if right else x < base.x)
                  and abs(2*y-(2*base.y-1)) <= 5
                  and Pos(x, y) not in failed and summon_cell_legal(turn, settings, Pos(x, y), pending)]
    return min(candidates, key=lambda p: (p in occupied or not turn.land(p),
                                        preferred.index(p) if p in preferred else len(preferred), distance(p, rear),
                                        abs(2*p.y-(2*base.y-1)), p)) if candidates else None


def enemy_weapon_cells(turn):
    """The twelve weapon-ring cells around the enemy's two-by-two base."""
    base = enemy_base_position(turn)
    if base is None:
        return frozenset()
    footprint = set(station_footprint(base))
    return frozenset(p for cell in footprint for p in cell.neighbours()
                     if p not in footprint and turn.in_bounds(p))


def enemy_layout_weapons(turn, remembered=()):
    """Merge real static sightings; current death/replacement overrides memory.

    The caller owns visibility-based invalidation of hidden remembered guns.
    No weapon is inferred from a template, wall position or missing sighting.
    """
    known = {u.unit_id: u for u in remembered if u.health > 0 and u.kind in TOWER_TYPES}
    for unit in turn.enemies:
        known.pop(unit.unit_id, None)
        if unit.health > 0 and unit.kind in TOWER_TYPES:
            # A rebuilt gun can use a different id at an old static position.
            known = {uid: old for uid, old in known.items() if old.pos != unit.pos}
            known[unit.unit_id] = unit
    return tuple(sorted(known.values(), key=lambda u: (u.pos, u.unit_id)))


def enemy_layout_ready(turn, remembered=(), surveyed=(), confirmed_sites=()):
    """Three observed guns exhaust the cap; fewer require a surveyed ring.

    ``surveyed`` contains cells that actually entered ordinary friendly sight,
    not robot sight or cells assumed visible merely because walls are global.
    ``confirmed_sites`` preserves real weapon-site knowledge across destruction
    and rebuilding; those historical sites are not live guns or obstructions.
    Continued live coverage is separately checked by the observer controller.
    """
    cells = enemy_weapon_cells(turn)
    weapons = enemy_layout_weapons(turn, remembered)
    confirmed = set(confirmed_sites) & cells
    return bool(cells) and (len(weapons) >= 3 or len(confirmed) >= 3 or cells <= set(surveyed))


def layout_operator_positions(turn, remembered=()):
    """Possible free cells with maximal shared control of observed guns.

    Buildings and known neutral obstacles cannot be operator positions. An
    actually visible worker/pioneer is allowed to occupy a potential position.
    """
    guns = enemy_layout_weapons(turn, remembered)
    if not guns:
        return ()
    base = enemy_base_position(turn)
    occupied = {p for u in turn.ours + turn.enemies if u.health > 0
                and u.kind not in CONTROLLABLE_TYPES for p in turn.footprint(u)}
    occupied.update(g.pos for g in guns)
    if base is not None:
        occupied.update(station_footprint(base))
    tasks = {p for task in turn.tasks for p in turn.task_cells(task)}
    candidates = {p for g in guns for p in g.pos.neighbours()
                  if turn.land(p) and p not in occupied and p not in tasks}
    counts = {p: sum(distance(p, g.pos) <= 1 for g in guns) for p in candidates}
    most = max(counts.values(), default=0)
    return tuple(sorted(p for p, count in counts.items() if count == most))


def _firing_clear(turn, start, target, remembered):
    return (0 < distance(start, target) <= 3
            and blocking_wall(turn, start, target) is None
            and planning_building_blocker(turn, start, target, remembered) is None)


def _approach_costs(turn, target, blocked, remembered):
    """Reverse eight-way BFS to a real clear, range-three firing position."""
    goals = {Pos(x, y) for x in range(max(0, target.x-3), min(turn.width, target.x+4))
             for y in range(max(0, target.y-3), min(turn.height, target.y+4))
             if Pos(x, y) not in blocked and turn.land(Pos(x, y))
             and _firing_clear(turn, Pos(x, y), target, remembered)}
    costs = {p: 0 for p in goals}
    frontier = deque(sorted(goals))
    while frontier:
        here = frontier.popleft()
        for there in here.neighbours():
            # Side-corner obstacles do not block diagonal movement.
            if there in costs or there in blocked or not turn.land(there):
                continue
            costs[there] = costs[here] + 1
            frontier.append(there)
    return costs


def _breach_cost(turn, wall_free, start, target, remembered):
    """Only a wall-only line may be budgeted as a BOSS wall breach.

    Bases/guns on the line cannot be silently counted as walls or walked
    through. Estimated turns are placement heuristics, not simulated damage.
    """
    if not 0 < distance(start, target) <= 3:
        return None
    if planning_building_blocker(wall_free, start, target, remembered) is not None:
        return None
    dx, dy = target.x-start.x, target.y-start.y
    walls = [u for u in turn.ours + turn.enemies if u.health > 0 and u.kind == 'wall'
             and u.pos not in (start, target)]
    if dx and abs(dx) == abs(dy):
        walls = [w for w in walls if (w.pos.x-start.x)*dy == (w.pos.y-start.y)*dx]
    hits = [w for w in walls if segment_entry(start, target, w.pos) is not None]
    return sum(ceil(w.health / 40) for w in hits) if hits else None


def scouted_spawn_candidates(turn, settings, remembered=(), pending=(), failed=(), surveyed=(), confirmed_sites=()):
    """Rank legal cells using observed layout, including mirror/rotation cases.

    Prefer a stationary shot at a visible cannon crew or an inferred common
    control cell. Otherwise choose the shortest route to a clear firing cell
    or a wall-only breach. A base shot is the fallback when crew positions are
    enclosed by guns/base or cannot be reached. Dynamic occupants are legal
    summon cells but are ranked last because the spawn would be displaced.
    """
    remembered = tuple(remembered)
    if not enemy_layout_ready(turn, remembered, surveyed, confirmed_sites):
        return ()
    base = enemy_base_position(turn)
    if base is None:
        return ()
    guns = enemy_layout_weapons(turn, remembered)
    static = guns + tuple(u for u in remembered if u.kind == 'station' and u.health > 0)
    crews = tuple(u.pos for u in turn.enemies if u.health > 0 and u.kind in ('worker', 'pioneer')
                  and any(distance(u.pos, g.pos) <= 1 for g in guns))
    targets = tuple(sorted(set(crews))) or layout_operator_positions(turn, remembered)
    base_cells = station_footprint(base)
    blocked = {p for p, kind in turn.zones.items() if kind != LAND}
    blocked.update(p for task in turn.tasks for p in turn.task_cells(task))
    blocked.update(turn.occupied_cells())
    blocked.update(r.pos for r in turn.robots if r.health > 0)
    blocked.update(g.pos for g in guns)
    blocked.update(base_cells)
    # Selected robots will appear together at night. A later BOSS must not
    # price a walk or firing post through an earlier stationary spawn.
    blocked.update(pending)
    routes = {target: _approach_costs(turn, target, blocked, static)
              for target in set(targets) | set(base_cells)}
    wall_free = replace(turn, ours=tuple(u for u in turn.ours if u.kind != 'wall'),
                        enemies=tuple(u for u in turn.enemies if u.kind != 'wall'))
    occupied = turn.occupied_cells() | {r.pos for r in turn.robots if r.health > 0}
    failed, pending = set(failed), set(pending)
    scored = []
    for x in range(max(0, base.x-6), min(turn.width, base.x+8)):
        for y in range(max(0, base.y-7), min(turn.height, base.y+7)):
            pos = Pos(x, y)
            if (pos in failed or pos in {g.pos for g in guns}
                    or not summon_cell_legal(turn, settings, pos, pending)):
                continue
            def engagement(points):
                options = []
                for target in points:
                    cost = routes[target].get(pos)
                    breach = _breach_cost(turn, wall_free, pos, target, static)
                    if breach is not None:
                        cost = min(cost, breach) if cost is not None else breach
                    if cost is not None:
                        options.append((cost, -sum(distance(target, g.pos) <= 1 for g in guns),
                                        distance(pos, target), target))
                return min(options) if options else None
            crew = engagement(targets)
            base_attack = engagement(base_cells)
            selected = crew or base_attack
            if selected is None:
                # No legal approach: remain near the base instead of inventing
                # hidden buildings/units or a permissive path through walls.
                score = (pos in occupied or not turn.land(pos), 2, 10**6, 0, 0,
                         min(distance(pos, cell) for cell in base_cells), 0, pos)
            else:
                cost, controls, gap, target = selected
                wall = blocking_wall(turn, pos, target)
                shared_wall = (wall is not None and any(
                    (other := blocking_wall(turn, old, target)) is not None
                    and other.unit_id == wall.unit_id for old in pending))
                # Two BOSS robots should share a required breach rather than
                # spend their opening attacks on two otherwise equivalent walls.
                separate_breach = bool(pending and wall is not None and not shared_wall)
                dx, dy = target.x-pos.x, target.y-pos.y
                alignment = 0 if not dx or not dy else 1 if abs(dx) == abs(dy) else 2
                score = (pos in occupied or not turn.land(pos), 0 if crew else 1,
                         cost, controls, separate_breach, gap, alignment, pos)
            scored.append((score, pos))
    return tuple(pos for _, pos in sorted(scored))


def scouted_spawn_position(turn, settings, remembered=(), pending=(), failed=(), surveyed=(), confirmed_sites=()):
    """First ranked scouted cell; callers pass pending first-BOSS cells."""
    candidates = scouted_spawn_candidates(turn, settings, remembered, pending, failed, surveyed, confirmed_sites)
    return candidates[0] if candidates else None
