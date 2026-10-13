"""Static enemy-layout geometry for a shared BOSS wall breach.

Remembered weapon sites are placement knowledge, never hidden attack targets.
Wave exposure is ranked from the current observation; future wave spawns and
their AI are not specified well enough to promise an absolutely safe flank.
"""
from collections import deque

from .protocol import CONTROLLABLE_TYPES, TOWER_TYPES, Pos, distance, station_footprint
from .robot_combat import blocking_wall
from .summoning import (enemy_base_position, enemy_layout_weapons, layout_operator_positions,
                        layout_weapon_sites, summon_cell_legal)
from .worker_safety import wall_shelters


def _geometry(turn, remembered, confirmed_sites):
    base = enemy_base_position(turn)
    if base is None:
        return None
    sites = layout_weapon_sites(turn, remembered, confirmed_sites)
    if not sites:
        return None
    posts = layout_operator_positions(turn, remembered, confirmed_sites)
    guns = enemy_layout_weapons(turn, remembered)
    types = {p: kind for p, kind in confirmed_sites.items() if p in sites
             and kind in TOWER_TYPES} if isinstance(confirmed_sites, dict) else {}
    types.update((g.pos, g.kind) for g in guns)
    three_rockets = len(types) == 3 and all(kind == 'rocket' for kind in types.values())
    crew = tuple(u.pos for u in turn.enemies if u.health > 0
                 and u.kind in CONTROLLABLE_TYPES
                 and (u.pos in posts if three_rockets else
                      any(distance(u.pos, p) <= 1 for p in sites)))
    return base, sites, posts, crew


def _line_buildings(turn, start, end, sites, base_cells):
    """Planning obstruction only; moving people do not become static layout."""
    blocks = set(sites) | set(base_cells)
    blocks.update(p for u in turn.ours + turn.enemies if u.health > 0
                  and u.kind not in CONTROLLABLE_TYPES + ('wall',)
                  for p in turn.footprint(u))
    return wall_shelters(start, end, blocks - {start, end})


def _reachable_firing_cells(turn, settings, sites, base_cells):
    """Static eight-way reachability from free legal exterior spawn cells.

    A temporary moving occupant must not convert an open door into evidence
    that a wall must be destroyed. Walls, remembered weapon sites, bases and
    neutral cells remain actual movement obstructions.
    """
    blocked = set(sites) | set(base_cells)
    blocked.update(p for u in turn.ours + turn.enemies if u.health > 0
                   and u.kind not in CONTROLLABLE_TYPES for p in turn.footprint(u))
    blocked.update(p for task in turn.tasks for p in turn.task_cells(task))
    free = {Pos(x, y) for x in range(turn.width) for y in range(turn.height)
            if turn.land(Pos(x, y)) and Pos(x, y) not in blocked}
    reachable = {p for p in free if summon_cell_legal(turn, settings, p)}
    frontier = deque(reachable)
    while frontier:
        here = frontier.popleft()
        for there in here.neighbours():
            if there in free and there not in reachable:
                reachable.add(there)
                frontier.append(there)
    return reachable


def protected_layout(turn, settings, remembered=(), confirmed_sites=()):
    """Whether all best posts or an observed cannon crew need a wall breach.

    Check range-three firing origins reachable from legal exterior spawn cells,
    including open doors into the construction area. A wall-free walk to a
    clear shot retains the ordinary operator strategy even without a direct
    shot from the legal spawn cells themselves.
    A legal 45-degree gap is enough to retain the normal operator strategy.
    A layout blocked solely by its guns/base is not called wall-protected.
    """
    geometry = _geometry(turn, remembered, confirmed_sites)
    if geometry is None:
        return False
    base, sites, posts, crew = geometry
    if not posts and not crew:
        return False
    base_cells = station_footprint(base)
    reachable = _reachable_firing_cells(turn, settings, sites, base_cells)
    def shielded(target):
        wall_line = False
        for x in range(max(0, target.x - 3), min(turn.width, target.x + 4)):
            for y in range(max(0, target.y - 3), min(turn.height, target.y + 4)):
                origin = Pos(x, y)
                if origin == target:
                    continue
                if _line_buildings(turn, origin, target, sites, base_cells):
                    continue
                wall = blocking_wall(turn, origin, target)
                if wall is None and origin in reachable:
                    return False
                if wall is not None and summon_cell_legal(turn, settings, origin):
                    wall_line = True
        return wall_line
    return (bool(posts) and all(shielded(p) for p in posts)
            or any(shielded(p) for p in crew))


def _side(pos, base):
    dx, dy = 2 * pos.x - (2 * base.x + 1), 2 * pos.y - (2 * base.y - 1)
    if abs(dy) >= abs(dx):
        return 'north' if dy > 0 else 'south'
    return 'east' if dx > 0 else 'west'


def _outward(pos, wall, side):
    return (pos.y > wall.y if side == 'north' else pos.y < wall.y if side == 'south'
            else pos.x > wall.x if side == 'east' else pos.x < wall.x)


def _wave_risk(turn, pos):
    return sum(robot.attack_power for robot in turn.hostile_robots()
               if robot.health > 0 and distance(robot.pos, pos) <= robot.range_of_attack()
               and blocking_wall(turn, robot.pos, pos) is None)


def _preferred_position(preferred):
    if isinstance(preferred, Pos):
        return preferred
    if isinstance(preferred, dict) and 'x' in preferred and 'y' in preferred:
        return Pos.load(preferred)
    return getattr(preferred, 'pos', None)


def plan_assault(turn, settings, count, remembered=(), confirmed_sites=(),
                 pending=(), failed=(), preferred_wall=None):
    """Plan ``count`` additional unique spawns firing at one observed wall.

    ``pending`` and ``failed`` are excluded cells; ``preferred_wall`` accepts a
    position, a real wall id, or a wall object and keeps later purchases on the
    selected breach. Return ``None`` rather than split fire or invent a wall.
    Runtime control must continue checking actual attack lines after spawning.
    """
    if count < 1:
        return None
    geometry = _geometry(turn, remembered, confirmed_sites)
    if geometry is None:
        return None
    base, sites, posts, crew = geometry
    targets = tuple(sorted(set(posts) | set(crew)))
    base_cells = station_footprint(base)
    excluded_sides = {_side(p, base) for p in targets}
    # Vertical flanks keep the raid away from the usual central approach.
    # Prefer the vertical flank opposite the observed gun mass, not a template.
    gun_y = sum(2 * p.y - (2 * base.y - 1) for p in sites)
    preferred_side = ('south' if gun_y > 0 else 'north' if gun_y < 0
                      else 'north' if 2 * base.y >= turn.height else 'south')
    occupied = set(turn.occupied_cells()) | {r.pos for r in turn.robots if r.health > 0}
    excluded = set(pending) | set(failed) | occupied | set(sites)
    preferred_pos = _preferred_position(preferred_wall)
    walls = [u for u in turn.enemies if u.kind == 'wall' and u.health > 0
             and (preferred_wall is None or u.pos == preferred_pos
                  or u.unit_id == preferred_wall)]
    options = []
    for wall in walls:
        side = _side(wall.pos, base)
        if side in excluded_sides:
            continue
        candidates = []
        for x in range(max(0, wall.pos.x - 3), min(turn.width, wall.pos.x + 4)):
            for y in range(max(0, wall.pos.y - 3), min(turn.height, wall.pos.y + 4)):
                pos = Pos(x, y)
                if (pos in excluded or not turn.land(pos) or not _outward(pos, wall.pos, side)
                        or not summon_cell_legal(turn, settings, pos, pending)
                        or blocking_wall(turn, pos, wall.pos) is not None
                        or _line_buildings(turn, pos, wall.pos, sites, base_cells)):
                    continue
                lateral = abs(pos.x - wall.pos.x) if side in ('north', 'south') else abs(pos.y - wall.pos.y)
                candidates.append(((_wave_risk(turn, pos), lateral,
                                    distance(pos, wall.pos), pos), pos))
        if len(candidates) < count:
            continue
        selected = tuple(pos for _, pos in sorted(candidates)[:count])
        cross_offset = abs(2 * wall.pos.x - (2 * base.x + 1)) if side in ('north', 'south') else abs(2 * wall.pos.y - (2 * base.y - 1))
        operator_offset = min((abs(wall.pos.x - p.x) if side in ('north', 'south')
                               else abs(wall.pos.y - p.y) for p in targets), default=0)
        score = (sum(_wave_risk(turn, p) for p in selected), side != preferred_side,
                 side not in ('north', 'south'), cross_offset, operator_offset,
                 min(distance(wall.pos, cell) for cell in base_cells),
                 wall.health, wall.pos)
        options.append((score, wall, side, selected))
    if not options:
        return None
    _, wall, side, spawns = min(options, key=lambda item: item[0])
    return {'wall_pos': wall.pos, 'wall_id': wall.unit_id, 'side': side,
            'spawns': list(spawns), 'base_cells': base_cells}
