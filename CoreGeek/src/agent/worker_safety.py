"""Worker risk and user-observed wall cover; not a robot damage simulator."""
from .protocol import Pos, Turn, distance

ROBOT_DAMAGE = {"smallRobot": 5, "middleRobot": 10, "largeRobot": 20, "bossRobot": 40}


def wall_shelters(start: Pos, end: Pos, walls) -> bool:
    """User-observed cover policy: a live wall must cross the open sight segment.

    Mere corner contact is not cover. This is a routing policy, not a change to
    the official damage engine; gaps and enemies already behind the wall matter.
    """
    for cell in walls:
        if cell in (start, end):
            continue
        lo, hi = 0.0, 1.0
        for origin, delta, middle in ((start.x, end.x-start.x, cell.x), (start.y, end.y-start.y, cell.y)):
            if not delta:
                if abs(origin-middle) >= .5:
                    hi = -1
                    break
                continue
            a, b = (middle-.499999-origin)/delta, (middle+.499999-origin)/delta
            lo, hi = max(lo, min(a,b)), min(hi, max(a,b))
        if lo < hi and hi > 0 and lo < 1:
            return True
    return False


def robot_danger(turn: Turn) -> dict[Pos, int]:
    """Range 3 plus one caution cell, discounting live intervening wall cover.

    All observed live robots contribute, including dizzy robots whose remaining
    stun duration is unknown. Values are path penalties, not simulated damage.
    """
    danger = {}
    walls = [w.pos for w in turn.walls()]
    for robot in turn.robots:
        if robot.health <= 0:
            continue
        weight = ROBOT_DAMAGE.get(robot.kind, 40)
        nearby_walls = [p for p in walls if distance(p, robot.pos) <= 4]
        for x in range(max(0, robot.pos.x - 4), min(turn.width, robot.pos.x + 5)):
            for y in range(max(0, robot.pos.y - 4), min(turn.height, robot.pos.y + 5)):
                p = Pos(x, y)
                if wall_shelters(robot.pos, p, nearby_walls):
                    continue
                d = distance(p, robot.pos)
                penalty = weight * (1 if d == 4 else (5 - d) * 10)
                danger[p] = danger.get(p, 0) + penalty
    return danger
