"""Persistent enemy-half mineral destruction, independent of worker schedules."""
from .grid import adjacent_cells
from .map_regions import base_side, diagonal_side
from .protocol import MINERALS, Pos, destroy_command, distance, move_command


class ImpController:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        side = base_side(self.turn)
        if side:
            self.memory.imp_home_side = side
        live = {u.unit_id:u for u in self.turn.imps()}
        self.memory.imp_tasks = {uid:job for uid,job in self.memory.imp_tasks.items()
            if uid in live and job.get('round') == self.turn.round_no-1
            and isinstance(job.get('position'), Pos)
            and distance(live[uid].pos, job['position']) <= 1
            and not (job.get('kind') == 'destroy' and live[uid].pos != job['position'])}

    def decide(self, role) -> bool:
        own_side = self.memory.imp_home_side
        old = self.memory.imp_tasks.get(role.unit_id, {})
        route = self.s.route(role)  # No worker danger penalties or night escape.
        options = []
        for target, mineral in self.turn.zones.items():
            if mineral not in MINERALS or diagonal_side(target, self.turn.width, self.turn.height)*own_side >= 0:
                continue
            goals = adjacent_cells(self.turn, [target])
            goal = old.get('goal') if old.get('target') == target else None
            if distance(role.pos, target) == 1:
                goal = role.pos
            elif goal not in goals or goal not in route.cost:
                goal = route.nearest(goals)
            if goal is not None:
                options.append((target != old.get('target'), route.cost[goal], target, goal))
        if not options:
            self.memory.imp_tasks.pop(role.unit_id, None)
            return False
        _, _, target, goal = min(options, key=lambda option: option[:3])
        if distance(role.pos, target) == 1:
            command = destroy_command(target)
        else:
            step = route.step([goal])
            if step is None:
                return False
            command = move_command(step)
        if not self.plan.add(role.unit_id, command):
            return False
        consecutive = (old.get('kind') == 'destroy' and old.get('target') == target
                       and old.get('position') == role.pos
                       and self.turn.action_results.get(str(role.unit_id)) is not False)
        issued = min(4, old.get('issued_streak',0)+1) if consecutive else 1
        self.memory.imp_tasks[role.unit_id] = dict(kind=command['action'], target=target, goal=goal,
            position=role.pos, round=self.turn.round_no,
            issued_streak=issued if command['action'] == 'destroy' else 0)
        # The engine, not this counter, decides when the mineral disappears.
        return True
