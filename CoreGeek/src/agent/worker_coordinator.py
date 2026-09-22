"""Per-worker task memory, distinct destinations and legal cooperative yielding."""
from .grid import Routes
from .protocol import Pos, distance, move_command


class WorkerCoordinator:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        live = {w.unit_id: w for w in self.turn.workers()}
        self.memory.worker_tasks = {uid: job for uid,job in self.memory.worker_tasks.items()
                                    if uid in live and job.get('round',0) >= self.turn.round_no-2}
        for uid,job in self.memory.worker_tasks.items():
            if job.get('round') == self.turn.round_no-1:
                job['stalled'] = min(8, job.get('stalled',0)+1) if job.get('moving') and live[uid].pos == job.get('position') else 0

    def job(self, role):
        return self.memory.worker_tasks.get(role.unit_id,{})

    def assign(self, role, kind, target, goal, moving=False):
        old = self.job(role)
        self.memory.worker_tasks[role.unit_id] = dict(old, kind=kind, target=target, goal=goal,
            round=self.turn.round_no, position=role.pos, moving=moving,
            stalled=old.get('stalled',0) if old.get('target') == target else 0)

    def claimed_goals(self, role):
        return {job.get('goal') for uid,job in self.memory.worker_tasks.items()
                if uid != role.unit_id and job.get('round',0) >= self.turn.round_no-1}

    def target_owned(self, role, target):
        return any(uid != role.unit_id and job.get('target') == target
                   and job.get('round',0) >= self.turn.round_no-1
                   for uid,job in self.memory.worker_tasks.items())

    def hold_for_yield(self, role):
        job = self.job(role)
        if 'WallFixer' in role.backpack and any(distance(role.pos,w.pos)<=1
                and w.health*100 < self.s.building_max_health(w)*self.s.settings.repair_threshold_percent
                for w in self.turn.walls()):
            job.pop('yield_until',None)
            return False
        if job.get('yield_until',0) >= self.turn.round_no:
            self.assign(role,'yield',job.get('target'),role.pos)
            self.plan.used.add(role.unit_id)
            return True
        return False

    def diagnostic_route(self, role, allowed=None):
        return Routes(self.turn,role,self.reserved(),self.s.danger,allowed,
                      frozenset(w.unit_id for w in self.turn.workers() if w.unit_id != role.unit_id))

    def reserved(self):
        return (set(self.plan.reserved) | set(self.s.layout.tower_sites)
                | ({self.s.layout.operator_pos} if self.s.layout.operator_pos else set()))

    def move_to(self, role, goals, kind='travel', target=None, allowed=None, allow_risk=False):
        goals = set(goals) - self.claimed_goals(role)
        if allowed is not None:
            goals &= allowed
        route = self.s.route(role,allowed)
        if not self.turn.is_day and not allow_risk:
            goals = {p for p in goals if not self.s.danger.get(p,0)}
        old = self.job(role)
        goal = old.get('goal') if old.get('target') == target and old.get('goal') in goals else None
        if (goal not in route.cost or old.get('stalled',0) >= 2
                or (goal is not None and route.exposure.get(goal,0) > min((route.exposure.get(p,10**9) for p in goals),default=0))):
            goal = route.nearest(goals)
        if goal is not None and (allow_risk or self.turn.is_day or route.exposure.get(goal,0) == 0):
            self.assign(role,kind,target,goal,role.pos != goal)
            if role.pos == goal:
                return False
            step = route.step({goal})
            if step is not None and self.plan.add(role.unit_id,move_command(step)):
                return True
        # A relaxed route is diagnostic only. Never step into the blocker's cell.
        ignore = frozenset(w.unit_id for w in self.turn.workers() if w.unit_id != role.unit_id)
        relaxed = Routes(self.turn,role,self.reserved(),self.s.danger,allowed,ignore)
        goal = relaxed.nearest(goals)
        self.assign(role,kind,target,goal,True)
        if goal is None or (not allow_risk and not self.turn.is_day and relaxed.exposure[goal] > 0):
            return False
        step = relaxed.step({goal})
        blocker = next((w for w in self.turn.workers() if w.pos == step and w.unit_id != role.unit_id),None)
        if blocker:
            self.yield_blocker(role,blocker,goal)
            # Reserve this worker's turn while the blocker moves aside.
            self.plan.used.add(role.unit_id)
            return True
        if step is not None and step not in self.turn.blocked(role) and step not in self.plan.reserved:
            return self.plan.add(role.unit_id,move_command(step))
        return False

    def yield_blocker(self, requester, blocker, goal):
        if blocker.unit_id in self.plan.used:
            return False
        guard = self.s.guard
        # Do not interrupt a worker who can immediately repair a critical wall.
        if 'WallFixer' in blocker.backpack and any(distance(blocker.pos,w.pos)<=1
                and w.health*100 < self.s.building_max_health(w)*self.s.settings.repair_threshold_percent
                for w in self.turn.walls()):
            return False
        allowed = guard.inner_cells() if guard.is_guard(blocker) and blocker.pos in guard.inner_cells() else None
        blocked = self.turn.blocked(blocker) | self.reserved() | self.claimed_goals(blocker)
        candidates = [p for p in blocker.pos.neighbours() if self.turn.land(p) and p not in blocked
                      and p != goal and (allowed is None or p in allowed)
                      and self.s.danger.get(p,0) <= self.s.danger.get(blocker.pos,0)]
        dx,dy=goal.x-requester.pos.x,goal.y-requester.pos.y
        candidates.sort(key=lambda p:(-abs(dx*(p.y-requester.pos.y)-dy*(p.x-requester.pos.x)),p))
        for p in candidates:
            after = Routes(self.turn,requester,self.reserved()|{p},self.s.danger,None,frozenset({blocker.unit_id}))
            if goal not in after.cost:
                continue
            if self.plan.add(blocker.unit_id,move_command(p)):
                self.assign(blocker,'yield',requester.unit_id,p,True)
                self.job(blocker)['yield_until']=self.turn.round_no+2
                return True
        return False
