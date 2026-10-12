"""Vehicle movement follows the same collision-aware route as walking."""
from .protocol import CONTROLLABLE_TYPES, Pos, Turn, Unit
from .grid import Routes


def move_targets(turn: Turn, role: Unit, route: Routes, goals) -> tuple[Pos, ...]:
    """Take two searched neighbour steps only while already driving by day.

    Passing one cell intentionally follows the official dismount semantics.
    Entering a parked friendly car remains a one-cell walking command; the
    next observation, rather than a local assumption, confirms isDriving.
    """
    limit = 2 if turn.is_day and role.is_driving and role.kind in CONTROLLABLE_TYPES else 1
    return route.path(goals, limit=limit)
