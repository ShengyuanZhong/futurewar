"""Robot attacks: observed enemy units, range three, and user-confirmed wall LOS."""
from .combat import segment_entry
from .protocol import CONTROLLABLE_TYPES, TOWER_TYPES, distance
from .worker_safety import wall_shelters


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


def planning_building_blocker(turn, start, end):
    """Conservatively avoid firing through observed buildings, not a rule gate.

    Exposed base cells are separate endpoints. Mere corner contact is ignored;
    official building projectile details still require match verification.
    """
    hits = []
    for unit in turn.ours + turn.enemies:
        if unit.health <= 0 or unit.kind not in TOWER_TYPES + ('station',):
            continue
        for cell in turn.footprint(unit):
            if cell not in (start, end) and wall_shelters(start, end, (cell,)):
                hits.append((segment_entry(start, end, cell), unit.unit_id, cell, unit))
    return min(hits, key=lambda h:h[:3])[2:] if hits else None


def clear_attack(turn, robot, pos, audit=None):
    gap = distance(robot.pos,pos)
    in_range = 0 < gap <= robot.range_of_attack()
    victim = enemy_at(turn,pos) if in_range else None
    wall = blocking_wall(turn,robot.pos,pos) if victim is not None else None
    clear = in_range and victim is not None and wall is None
    if audit is not None:
        audit.update(distance=gap, attack_range=robot.range_of_attack(), in_range=in_range,
                     target_lookup_evaluated=in_range, target_id=victim.unit_id if victim else None,
                     wall_evaluated=victim is not None,
                     wall={'id':wall.unit_id,'pos':wall.pos.dump(),'hp':wall.health} if wall else None,
                     clear=clear, blocked_by='out_of_range' if not in_range else
                     'no_visible_enemy' if victim is None else 'wall' if wall else None)
    return clear
