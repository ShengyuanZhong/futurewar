"""Permanent wall construction from outside, with observed evacuation first."""
from collections import deque
from dataclasses import replace

from .grid import Routes, adjacent_cells
from .first_day_tasks import FIRST_DAY_LIMIT, finished_count
from .protocol import PIONEER, TOWER_TYPES, Pos, distance, move_command


class SealedHome:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.sealed_home
        self.walls = set(strategy.settings.build_cells(self.turn,'wall'))
        self.enabled = bool(self.turn.station() and self.walls)
        self.static = set(self.walls) | set(strategy.layout.tower_sites)
        self.static.update(p for u in self.turn.ours+self.turn.enemies if u.health>0
                           and u.kind in TOWER_TYPES+('station','wall') for p in self.turn.footprint(u))
        self.static.update(p for p in self.turn.zones if not self.turn.walkable(p))
        self.static.update(p for task in self.turn.tasks for p in self.turn.task_cells(task))
        # Classify the fully built geometry, ignoring all movable units. Distant
        # land also seeds exterior components when the map edges are water.
        base = self.turn.station()
        land = {Pos(x,y) for x in range(self.turn.width) for y in range(self.turn.height)
                if self.turn.walkable(Pos(x,y)) and Pos(x,y) not in self.static}
        seeds = {p for p in land if p.x in (0,self.turn.width-1) or p.y in (0,self.turn.height-1)
                 or (base and min(distance(p,b) for b in self.turn.footprint(base))>4)}
        self.outside = set(seeds)
        queue = deque(seeds)
        while queue:
            here = queue.popleft()
            for there in here.neighbours():
                if there in land and there not in self.outside:
                    self.outside.add(there);queue.append(there)
        self.inside = land-self.outside
        self.state.update(round=self.turn.round_no,enabled=self.enabled,
                          missing=len(self.walls-{w.pos for w in self.turn.walls()}))

    def builder_posts(self, goals):
        return set(goals)&self.outside if self.enabled else set(goals)

    def safe_wall(self, target):
        if not self.enabled:
            return True
        future = set(self.plan.build_targets)|{target}
        for role in self.turn.controllable():
            reserved = set(self.plan.reserved)
            command = self.plan.commands.get(str(role.unit_id),{})
            if command.get('action')=='move':
                reserved.difference_update(Pos.load(p) for p in command['targetPos'])
            after = Routes(self.turn,role,reserved|future)
            if role.kind=='worker' and role.pos not in self.outside:
                if after.nearest(self.outside) is None:
                    self.state.update(reason='worker_still_inside',blocked_worker=role.unit_id,
                                      deferred_wall=target)
                    return False
            if role.kind==PIONEER and self.s.layout.operator_pos is not None:
                before = Routes(self.turn,role,reserved)
                control = self.s.layout.operator_pos
                if control in before.cost and control not in after.cost:
                    self.state.update(reason='pioneer_control_route',deferred_wall=target)
                    return False
        return True

    def evacuate(self, role):
        if (not self.enabled or not self.turn.is_day or role.kind!='worker'
                or len(self.turn.weapons())<3 or role.pos in self.outside):
            return False
        if role.pos not in self.inside and self.s.stone_planner.needs_material(role):
            return False  # A miner passing an unbuilt perimeter cell can finish its batch.
        # Do not interpret a move command as arrival before the next request.
        route = self.s.route(role)
        goals = self.outside-self.s.coordinator.claimed_goals(role)
        goal = route.nearest(goals)
        if goal is None:
            relaxed = self.s.coordinator.diagnostic_route(role)
            goal = relaxed.nearest(goals)
        if goal is None:
            self.state.update(reason='trapped_preexisting',blocked_worker=role.unit_id)
            return False  # Keep on-site repairs available, never auto-remove.
        self.state.update(reason='evacuating_worker',blocked_worker=role.unit_id,exit_goal=goal)
        return self.s.coordinator.move_to(role,{goal},'construction_exit',goal)

    def repair_cells(self, role=None):
        if not self.enabled:
            return self.s.guard.inner_cells()
        cells = self.outside & adjacent_cells(self.turn,self.walls)
        cells -= self.static | {self.s.layout.operator_pos}
        if role is not None and role.pos in self.inside:
            if Routes(self.turn,role,set(self.plan.reserved)).nearest(cells) is None:
                return set(self.inside)  # A legacy trapped worker can repair here.
        return cells

    def needs_operator(self, worker):
        """A carried upgrade may need the cannon's sole exterior interaction cell."""
        control = self.s.layout.operator_pos
        if (not self.enabled or not self.turn.is_day or worker.kind!='worker' or control is None
                or distance(worker.pos,control)>2):
            return False
        for gun in self.s.upgrade_candidates():
            if gun.kind not in TOWER_TYPES or self.s.upgrade_name(gun) not in worker.backpack:
                continue
            posts = self.outside & adjacent_cells(self.turn,self.turn.footprint(gun))
            if posts=={control}:
                return True
        return False

    def pioneer_yield(self, role):
        """Let a real courier upgrade the otherwise unreachable bottom cannon."""
        if not self.turn.is_day or role.kind!=PIONEER:
            return False
        if (self.turn.day==1 and self.s.settings.enable_tasks
                and (self.turn.phase_task or finished_count(self.memory)<FIRST_DAY_LIMIT)):
            return False
        workers = [w for w in self.turn.workers() if self.needs_operator(w)]
        if not workers:
            return False
        control = self.s.layout.operator_pos
        if role.pos!=control:
            self.plan.used.add(role.unit_id)
            self.state['operator_status'] = 'waiting_for_upgrade_courier'
            return True
        blocked = self.turn.blocked(role) | self.plan.reserved | self.s.coordinator.claimed_goals(role)
        options = [p for p in role.pos.neighbours() if p in self.outside and p not in blocked
                   and p!=control and not self.s.danger.get(p,0)]
        for post in sorted(options):
            # This forecast checks that yielding does not block the courier;
            # the worker still waits for the real next-turn position update.
            simulated = replace(self.turn,ours=tuple(replace(u,pos=post) if u.unit_id==role.unit_id else u
                                                     for u in self.turn.ours))
            if not any(control in Routes(simulated,w,self.s.movement_reserved(w)|{post}).cost for w in workers):
                continue
            if self.plan.add(role.unit_id,move_command(post)):
                self.state['operator_status'] = 'yielding_for_upgrade_courier'
                return True
        return False

    def wait_for_operator(self, role):
        if not self.needs_operator(role):
            return False
        control = self.s.layout.operator_pos
        pioneer = next((u for u in self.turn.alive((PIONEER,)) if u.pos==control),None)
        if pioneer is None:
            return False
        command = self.plan.commands.get(str(pioneer.unit_id),{})
        if command.get('action')!='move':
            return False
        self.s.coordinator.assign(role,'weapon_access',control,role.pos)
        self.plan.used.add(role.unit_id)
        self.state['operator_status'] = 'courier_waiting_for_observed_yield'
        return True

    def diagnostic(self):
        return dict(self.state,inside_workers=[w.unit_id for w in self.turn.workers() if w.pos in self.inside],
            permanent_walls=len(self.walls),physical_closed=bool(self.walls and
                self.walls<={w.pos for w in self.turn.walls()}),outside_repair_cells=len(self.repair_cells()))
