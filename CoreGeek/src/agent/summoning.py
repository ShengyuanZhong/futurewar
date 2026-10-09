"""Rear spawn cells just outside the six-by-six region in the user's image."""
from .protocol import CONTROLLABLE_TYPES, LAND, MINERALS, Pos, distance, station_footprint


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
