"""Conservative worker risk estimates; not a prediction of robot target selection."""
from .protocol import Pos, Turn, distance

ROBOT_DAMAGE = {"smallRobot": 5, "middleRobot": 10, "largeRobot": 20, "bossRobot": 40}


def robot_danger(turn: Turn) -> dict[Pos, int]:
    """Range 3 plus a one-cell caution buffer; walls are not assumed to stop shots.

    All observed live robots contribute, including dizzy robots whose remaining
    stun duration is unknown. Values are path penalties, not simulated damage.
    """
    danger = {}
    for robot in turn.robots:
        if robot.health <= 0:
            continue
        weight = ROBOT_DAMAGE.get(robot.kind, 40)
        for x in range(max(0, robot.pos.x - 4), min(turn.width, robot.pos.x + 5)):
            for y in range(max(0, robot.pos.y - 4), min(turn.height, robot.pos.y + 5)):
                p = Pos(x, y)
                d = distance(p, robot.pos)
                penalty = weight * (1 if d == 4 else (5 - d) * 10)
                danger[p] = danger.get(p, 0) + penalty
    return danger
