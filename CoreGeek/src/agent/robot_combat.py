"""Robot attacks: observed enemy units, range three, and user-confirmed wall LOS."""
from .combat import segment_entry
from .protocol import CONTROLLABLE_TYPES, TOWER_TYPES, distance


def blocking_wall(turn, start, end):
    walls = [u for u in turn.ours + turn.enemies if u.health > 0 and u.kind == 'wall'
             and u.pos not in (start, end)]
    hits = [(entry, w.unit_id, w) for w in walls
            if (entry := segment_entry(start, end, w.pos)) is not None]
    return min(hits, key=lambda hit: hit[:2])[2] if hits else None


def enemy_at(turn, pos):
    return next((u for u in turn.enemies if u.health > 0
                 and u.kind in CONTROLLABLE_TYPES + TOWER_TYPES + ('station', 'wall')
                 and pos in turn.footprint(u)), None)


def clear_attack(turn, robot, pos):
    return (0 < distance(robot.pos, pos) <= robot.range_of_attack()
            and enemy_at(turn, pos) is not None and blocking_wall(turn, robot.pos, pos) is None)
