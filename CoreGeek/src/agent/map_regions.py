"""Shared diagonal half-map classification for sabotage and rocket targeting."""
from .protocol import STATION, Pos, Turn


def diagonal_side(pos: Pos, width: int, height: int) -> int:
    """Side of (0,0)->(width-1,height-1): upper=1, lower=-1, boundary=0."""
    value = pos.y * (width-1) - pos.x * (height-1)
    return (value > 0) - (value < 0)


def base_side(turn: Turn) -> int:
    """Use our 2x2 base centre, or the opposite of the visible enemy base."""
    base = next((u for u in turn.ours if u.kind == STATION and turn.in_bounds(u.pos)), None)
    enemy = next((u for u in turn.enemies if u.kind == STATION and turn.in_bounds(u.pos)), None)
    reference = base or enemy
    if reference is None:
        return 0
    value = (2*reference.pos.y-1)*(turn.width-1) - (2*reference.pos.x+1)*(turn.height-1)
    side = (value > 0) - (value < 0)
    return side if base is not None else -side
