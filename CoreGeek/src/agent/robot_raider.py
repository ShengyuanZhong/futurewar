"""First-night BOSS controllers: find cannon operators, then siege their base."""
import math
import time
from .grid import Routes
from .protocol import CONTROLLABLE_TYPES, TOWER_TYPES, Pos, distance, move_command
from .robot_combat import blocking_wall, clear_attack
from .summoning import enemy_rear_position


class RobotRaider:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        live = {r.robot_id for r in self.turn.summon_robots if r.health > 0}
        self.memory.robot_raids = {uid: job for uid, job in self.memory.robot_raids.items()
                                   if uid in live and not self.turn.is_day and self.turn.day == 1}

    def firing_plan(self, robot, points, route):
        options = []
        old = self.memory.robot_raids.get(robot.robot_id, {})
        for target in points:
            for x in range(max(0, target.x-3), min(self.turn.width, target.x+4)):
                for y in range(max(0, target.y-3), min(self.turn.height, target.y+4)):
                    if time.monotonic() >= self.s.deadline:
                        return None
                    post = Pos(x, y)
                    if (post == target or post not in route.cost
                            or (target, post) in old.get('failed_firing', {})
                            or blocking_wall(self.turn, post, target) is not None):
                        continue
                    options.append((route.cost[post], post != old.get('goal'), post, target))
        return min(options) if options else None

    def issue(self, robot, action, target, goal, stage, **extra):
        command = ({'action': 'attack', 'targetPos': [target.dump()]} if action == 'attack'
                   else move_command(target))
        if not self.plan.add(robot.robot_id, command):
            return False
        old = self.memory.robot_raids.get(robot.robot_id, {})
        self.memory.robot_raids[robot.robot_id] = dict(old, round=self.turn.round_no, stage=stage,
            position=robot.pos, target=target, goal=goal, action=action, **extra)
        return True

    def pursue(self, robot, points, route, stage, **extra):
        failed = self.memory.robot_raids.get(robot.robot_id, {}).get('failed_firing', {})
        direct = [p for p in points if clear_attack(self.turn, robot, p) and (p, robot.pos) not in failed]
        if direct:
            target = min(direct, key=lambda p: (distance(robot.pos, p), p))
            return self.issue(robot, 'attack', target, robot.pos, stage, **extra)
        firing = self.firing_plan(robot, points, route)
        if firing:
            _, _, post, target = firing
            step = route.step({post})
            if step is not None:
                return self.issue(robot, 'move', step, post, stage, **extra)
        # A completely screened target may require breaking an observed enemy wall.
        walls = [u for u in self.turn.enemies if u.health > 0 and u.kind == 'wall']
        nearest = blocking_wall(self.turn, robot.pos, min(points, key=lambda p: distance(robot.pos, p)))
        options = []
        for wall in walls:
            if time.monotonic() >= self.s.deadline:
                return False
            firing = self.firing_plan(robot, [wall.pos], route)
            if firing is not None:
                cost = firing[0] + math.ceil(wall.health / max(1, robot.attack_power))
                options.append((wall != nearest, min(distance(wall.pos, p) for p in points), cost,
                                wall.unit_id, wall, firing))
        if not options:
            return False
        _, _, _, _, wall, firing = min(options, key=lambda entry: entry[:4])
        if clear_attack(self.turn, robot, wall.pos) and (wall.pos, robot.pos) not in failed:
            return self.issue(robot, 'attack', wall.pos, robot.pos, 'breach', **extra)
        step = route.step({firing[2]})
        return step is not None and self.issue(robot, 'move', step, firing[2], 'breach', **extra)

    def scout(self, robot, rear, route, **extra):
        goals = {p for p in (rear,) + rear.neighbours() if p in route.cost}
        if distance(robot.pos, rear) <= 2:
            old = self.memory.robot_raids.setdefault(robot.robot_id, {})
            old['scouted'] = True
            return False
        goal = route.nearest(goals)
        if goal is not None:
            step = route.step({goal})
            if step is not None:
                return self.issue(robot, 'move', step, goal, 'scout', **extra)
        # Walls can also prevent a rear search: use the same observed-wall fallback.
        return self.pursue(robot, [rear], route, 'scout', **extra)

    def decide(self, robot):
        if (not self.s.settings.enable_boss_raid or self.turn.day != 1 or self.turn.is_day
                or robot.health <= 0 or robot.kind != 'bossRobot' or robot.abnormal_state == 'dizzy'):
            return False
        route = Routes(self.turn, robot, self.plan.reserved)
        old = self.memory.robot_raids.setdefault(robot.robot_id, {})
        failed = {key: until for key, until in old.get('failed_firing', {}).items() if until > self.turn.round_no}
        if (old.get('round') == self.turn.round_no-1 and old.get('action') == 'attack'
                and old.get('position') == robot.pos
                and self.turn.action_results.get(str(robot.robot_id)) is False):
            failed[old['target'], robot.pos] = self.turn.round_no+4
        old['failed_firing'] = failed
        rear = enemy_rear_position(self.turn)
        weapons = [u for u in self.turn.enemies if u.health > 0 and u.kind in TOWER_TYPES]
        heroes = [u for u in self.turn.enemies if u.health > 0 and u.kind in CONTROLLABLE_TYPES]
        operators = [u for u in heroes if any(distance(u.pos, w.pos) <= 1 for w in weapons)
                     or (u.kind == 'pioneer' and rear is not None and distance(u.pos, rear) <= 4)]
        known = next((u for u in self.turn.enemies if u.unit_id == old.get('controller_id')), None)
        if known is not None and known.health > 0 and known.kind in CONTROLLABLE_TYPES and known not in operators:
            operators.append(known)
        if operators:
            target = min(operators, key=lambda u: (u.unit_id != old.get('controller_id'),
                not any(distance(u.pos, w.pos) <= 1 for w in weapons), u.kind != 'pioneer',
                distance(robot.pos, u.pos), u.health, u.unit_id))
            return self.pursue(robot, [target.pos], route, 'controller', controller_id=target.unit_id,
                                controller_pos=target.pos, last_seen=self.turn.round_no)
        if old.get('controller_id') is not None and known is None and self.turn.round_no - old.get('last_seen', 0) <= 3:
            if self.scout(robot, old['controller_pos'], route):
                return True
        killed = known is not None and known.health <= 0
        if rear is not None and not killed and not old.get('scouted'):
            if self.scout(robot, rear, route):
                return True
        base = next((u for u in self.turn.enemies if u.health > 0 and u.kind == 'station'), None)
        return base is not None and self.pursue(robot, [base.pos], route, 'base')
