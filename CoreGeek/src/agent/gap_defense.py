"""Build the remaining legal walls; a worker and reserve imp hold an occupied gap."""
from .grid import Routes
from .protocol import CONTROLLABLE_TYPES, IMP, build_command, distance, move_command


class WallGapDefense:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.wall_gap_defense
        if self.turn.day != 1:
            self.gaps = {}
            self.worker_id = self.imp_id = self.gap = None
            self.state.clear()
            return  # Later breaches use the established daytime rebuilding schedule.
        missing = set(self.s.settings.build_cells(self.turn, 'wall')) - {w.pos for w in self.turn.walls()}
        # Every planned wall is now permanent, including the former entrance.
        # Keep a previously observed hostile gap until it is actually rebuilt.
        gaps = {p:record for p,record in self.state.get('gaps',{}).items() if p in missing}
        for enemy in self.turn.enemies:
            if enemy.health>0 and enemy.kind in CONTROLLABLE_TYPES and enemy.pos in missing:
                gaps.setdefault(enemy.pos,dict(first_seen=self.turn.round_no))
                gaps[enemy.pos].update(enemy_id=enemy.unit_id,last_seen=self.turn.round_no)
        self.gaps = gaps
        self.worker_id, self.imp_id, self.gap = None,None,None
        if not gaps or not self.turn.station():
            self.gaps = {}
            self.state.clear()
            for uid,job in list(self.memory.worker_tasks.items()):
                if job.get('kind','').startswith('gap_'):
                    self.memory.worker_tasks.pop(uid)
            return
        self.state.update(gaps=gaps,round=self.turn.round_no)
        self.gap = min(gaps,key=lambda p:(self.priority(p),p!=self.state.get('gap'),p))
        self.state['gap'] = self.gap

    def priority(self, gap):
        base = self.turn.station()
        front = base.pos.x + (-2 if self.s.settings.mirrored_layout(self.turn) else 3)
        return 0 if gap.x==front and gap.y-base.pos.y in (0,-1) else 1 if gap.x==front else 2

    def choose_responders(self):
        if not self.gaps:
            return
        workers = self.turn.workers()
        live = {w.unit_id for w in workers}
        previous = self.state.get('worker_id')
        # During the night a fallen worker is replaced by the imp, not the miner/scout.
        if previous is not None and not self.turn.is_day:
            self.worker_id = previous
        else:
            home = self.memory.raid_scouts.get('home_worker_id')
            scout = self.memory.raid_scouts.get('worker_id')
            choices = [w for w in workers if w.unit_id != scout] or list(workers)
            preferred = next((uid for uid in (previous,home,self.memory.first_night_defense.get('worker_id'))
                              if uid in live and any(w.unit_id==uid for w in choices)),None)
            if preferred is not None:
                self.worker_id = preferred
            elif choices:
                self.worker_id = min(choices,key=lambda w:(self.post_cost(w),'stone' not in w.backpack,w.unit_id)).unit_id
        imps = self.turn.imps()
        self.imp_id = next((u.unit_id for u in imps if u.unit_id==self.state.get('imp_id')),
                           imps[0].unit_id if imps else None)
        self.state.update(worker_id=self.worker_id,imp_id=self.imp_id)

    def posts(self, gap=None, role=None):
        gap = gap or self.gap
        if gap is None:
            return set()
        excluded = set(self.s.settings.build_cells(self.turn,'wall')) | set(self.s.layout.tower_sites)
        excluded.add(self.s.layout.operator_pos)
        return {p for p in self.s.guard.duty_cells(role) if distance(p,gap)==1 and p not in excluded}

    def route(self, role):
        reserved = self.s.movement_reserved(role)
        if self.enter_gap(role) and self.gap not in self.plan.reserved:
            reserved.discard(self.gap)
        return Routes(self.turn,role,reserved)

    def enter_gap(self, role):
        if not self.active_role(role) or self.turn.is_day:
            return False
        return (role.unit_id==self.worker_id or (role.unit_id==self.imp_id
                and self.backup_needed()))

    def backup_needed(self):
        """Cover a dead guard or the dispatched buyer until it really returns."""
        if self.turn.is_day or not self.gaps:
            return False
        primary = next((w for w in self.turn.workers() if w.unit_id==self.worker_id),None)
        if primary is None:
            return True
        raid = self.memory.boss_raid
        return bool(self.turn.day==1 and raid.get('buyer_id')==self.worker_id and raid.get('buyer_departed')
                    and distance(primary.pos,self.gap)>1)

    def post_cost(self, role):
        route = self.route(role)
        return min((route.cost[p] for p in self.posts(role=role) if p in route.cost),default=10_000)

    def other_walls_ready(self):
        gate = getattr(self.s, 'day_gate', None)
        if gate is not None and gate.enabled and self.turn.is_day:
            return gate.day_ready(self.gaps)
        return bool(self.s.settings.build_cells(self.turn,'wall') and len(self.turn.weapons())>=3
                    and set(self.s.missing_walls()) <= set(self.gaps))

    def active_role(self, role):
        return bool(self.gaps and role.unit_id in (self.worker_id,self.imp_id))

    def is_waiting(self, role):
        return (self.active_role(role) and (not self.turn.is_day or self.preparing(role)))

    def preparing(self, role):
        if self.turn.day == 1 and self.turn.is_day:
            return False  # Begin body defence at night, without a return budget.
        return self.turn.daylight_left <= max(10,self.post_cost(role)+self.s.settings.return_margin+1)

    def move_or_hold(self, role, goals, kind):
        route = self.route(role)
        old = self.state.setdefault('posts',{}).get(role.unit_id)
        choices = [p for p in goals if p in route.cost and p not in self.plan.reserved]
        if role.kind==IMP:
            claimed = self.s.coordinator.claimed_goals(role)
            if kind=='gap_backup' and self.backup_needed():
                # A far returning buyer's future destination is not a current
                # movement reservation. Keep every other worker's claim and
                # all actual destinations already reserved in ActionPlan.
                claimed = {job.get('goal') for uid,job in self.memory.worker_tasks.items()
                           if uid!=role.unit_id and job.get('round',0)>=self.turn.round_no-1
                           and not (uid==self.worker_id and job.get('goal')==self.gap)}
            choices = [p for p in choices if p not in claimed]
        goal = min(choices,key=lambda p:(p!=old,route.cost[p],p)) if choices else None
        if goal is not None and goal != role.pos:
            step = route.step({goal})
            if step is not None and self.plan.add(role.unit_id,move_command(step)):
                self.state['posts'][role.unit_id] = goal
                if role.kind=='worker':
                    self.s.coordinator.assign(role,kind,self.gap,goal,True)
                return True
        if goal is not None:
            self.state['posts'][role.unit_id] = goal
        if role.kind=='worker':
            self.s.coordinator.assign(role,kind,self.gap,role.pos)
        self.plan.used.add(role.unit_id)
        return True

    def repair_here(self, role):
        if 'WallFixer' not in role.backpack:
            return False
        walls = [w for w in self.turn.walls() if distance(role.pos,w.pos)==1
                 and w.health*100 < self.s.building_max_health(w)*self.s.settings.repair_threshold_percent
                 and w.unit_id not in self.plan.upgrade_targets | self.s.maintenance_claims]
        if not walls:
            return False
        wall = min(walls,key=lambda w:(w.health/self.s.building_max_health(w),w.unit_id))
        if self.plan.add(role.unit_id,{'action':'use','name':'WallFixer','targetPos':[wall.pos.dump()]}):
            self.s.maintenance_claims.add(wall.unit_id)
            self.s.coordinator.assign(role,'gap_repair',self.gap,role.pos)
            return True
        return False

    def worker(self, role):
        if not self.gaps or role.unit_id != self.worker_id:
            return False
        if self.turn.is_day:
            if role.pos in self.gaps:
                return self.move_or_hold(role,self.posts(role=role),'gap_clear')
            if any(u.health>0 and u.pos==self.gap for u in self.turn.ours):
                # The reserve is leaving the site this round. Wait for a new
                # observation instead of mining away before the wall is legal.
                return self.move_or_hold(role,self.posts(role=role),'gap_rebuild_wait')
            if (self.gap not in self.turn.occupied_cells() and 'stone' in role.backpack
                    and distance(role.pos,self.gap)==1 and self.s.wall_keeps_exit(role,self.gap)):
                if self.plan.add(role.unit_id,build_command(self.gap,'wall')):
                    self.s.coordinator.assign(role,'build:wall',self.gap,role.pos)
                    return True
            if self.turn.day==1:
                # Vacated historical sites are ordinary daytime construction
                # work. Do not hijack a builder's sweep for a remote gap trip.
                return False
            if self.gap not in self.turn.occupied_cells():
                if ('stone' in role.backpack and self.post_cost(role)>=10_000
                        and any(u.health>0 and u.kind==IMP and u.pos in self.posts(role=role)
                                                    for u in self.turn.ours)):
                    self.s.coordinator.assign(role,'gap_rebuild_wait',self.gap,role.pos)
                    self.plan.used.add(role.unit_id)
                    return True
                if 'stone' in role.backpack and self.post_cost(role)+1 <= self.turn.daylight_left:
                    return self.move_or_hold(role,self.posts(role=role),'gap_rebuild')
                if not role.backpack_full and self.s.mine(role,need_stone=True,return_cells=self.posts(role=role)):
                    return True
            # Finish all other legal wall sites before scheduling the body guard.
            if not self.other_walls_ready() or not self.preparing(role):
                return False
            if 'stone' not in role.backpack and not role.backpack_full:
                if self.s.mine(role,need_stone=True,return_cells=self.posts(role=role)):
                    return True
            return self.move_or_hold(role,self.posts(role=role),'gap_wait')
        if role.pos==self.gap:
            if 'Medicine' in role.backpack and role.health<=250:
                return self.plan.add(role.unit_id,{'action':'use','name':'Medicine'})
            if self.repair_here(role):
                return True
            return self.move_or_hold(role,{self.gap},'gap_body')
        goals = {self.gap} if self.gap not in self.turn.occupied_cells() else self.posts(role=role)
        return self.move_or_hold(role,goals,'gap_body' if goals=={self.gap} else 'gap_wait')

    def imp(self, role):
        if not self.gaps or role.kind!=IMP or role.unit_id!=self.imp_id:
            return False
        self.memory.imp_tasks.pop(role.unit_id,None)
        primary = next((w for w in self.turn.workers() if w.unit_id==self.worker_id),None)
        # Inspect current alive units each frame; do not predict death from attacks.
        takeover = self.backup_needed()
        if takeover and (role.pos==self.gap or self.gap not in self.turn.occupied_cells()):
            self.state['imp_status'] = 'holding_gap'
            if role.pos==self.gap and 'Medicine' in role.backpack and role.health<=250:
                return self.plan.add(role.unit_id,{'action':'use','name':'Medicine'})
            return self.move_or_hold(role,{self.gap},'gap_backup')
        self.state['imp_status'] = 'standby'
        route = self.route(role)
        claimed = self.s.coordinator.claimed_goals(role)
        adjacent = {p for p in self.posts(role=role) if p in route.cost and p not in self.plan.reserved | claimed}
        # Stand by in the actual repair region. The worker's construction post
        # must remain clear; no route may assume the closed ring is passable.
        near = {p for p in self.s.guard.duty_cells(role) if distance(p,self.gap)<=2}
        if self.turn.is_day and primary is not None:
            waiting = near - self.posts(role=primary) - {primary.pos}
            return self.move_or_hold(role,waiting or adjacent,'gap_standby')
        return self.move_or_hold(role,adjacent or near,'gap_standby')

    def diagnostic(self):
        return dict(self.state,other_walls_ready=self.other_walls_ready(),
                    backup_needed=self.backup_needed(),
                    worker_alive=any(w.unit_id==self.worker_id for w in self.turn.workers()),
                    imp_alive=any(u.unit_id==self.imp_id for u in self.turn.imps()))
