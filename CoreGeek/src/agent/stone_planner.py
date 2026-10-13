"""Observed wall-material quotas and cooperative stone collection.

The wall count and backpacks are never changed by a submitted command.  The
next official observation must confirm both building and collecting.  Travel
appointments live in the existing per-worker memory; a departing BOSS buyer's
bag cannot pay for the builder who stays behind.
"""
from itertools import product
from .grid import adjacent_cells
from .protocol import Pos, collect_command, distance


class StonePlanner:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.stone_mining

    def targets(self) -> dict[int, int]:
        """Required actual bag counts, retaining an unfinished collection share.

        A remembered share is a preference for dividing an actual deficit, not
        additional demand.  Existing stones come first, then previous shares,
        then a balanced assignment of the remaining shortage.  No entrance
        stone is reserved: every stone may build an ordinary blueprint wall.
        """
        workers = self.turn.workers()
        raid = getattr(self.s, 'boss_raid', None)
        schedule = getattr(self.s,'wall_schedule',None)
        builders = (schedule.active_builders() if schedule is not None and schedule.enabled else
                    [w for w in workers if raid is None or not raid.worker_mission_active(w)])
        builder_ids = {w.unit_id for w in builders}
        remaining = len(set(self.s.construction_walls()))
        targets = {w.unit_id: 0 for w in workers}
        capacity = {}
        # Count only the material currently available to active builders.
        for worker in builders:
            held = worker.backpack.count('stone')
            targets[worker.unit_id] = held
            capacity[worker.unit_id] = held + max(0, worker.capacity - len(worker.backpack))
        shortage = max(0, remaining - sum(targets.values()))
        if schedule is not None and schedule.enabled:
            # Supply the actual assigned wall arcs before retaining a previous
            # mining batch. A 7/10 split must not keep the old 9/8 allocation.
            for worker in builders:
                amount = min(shortage,max(0,min(schedule.remaining(worker),capacity[worker.unit_id])
                                          - targets[worker.unit_id]))
                targets[worker.unit_id]+=amount
                shortage-=amount
        # Retain a miner's unfinished batch across the teammate's construction
        # actions, but never allocate past the genuine team shortage.
        for worker in sorted(builders, key=lambda w: w.unit_id):
            job = self.s.coordinator.job(worker)
            if job.get('kind') != 'collect:stone':
                continue
            previous = job.get('stone_quota', targets[worker.unit_id])
            if not isinstance(previous, int):
                continue
            amount = min(shortage, max(0, min(previous, capacity[worker.unit_id])
                                       - targets[worker.unit_id]))
            targets[worker.unit_id] += amount
            shortage -= amount
        while shortage:
            eligible = [uid for uid in builder_ids if targets[uid] < capacity[uid]]
            if not eligible:
                break
            uid = min(eligible, key=lambda key: (targets[key], key))
            targets[uid] += 1
            shortage -= 1
        for worker in workers:
            job = self.memory.worker_tasks.setdefault(worker.unit_id, {})
            job['stone_quota'] = targets[worker.unit_id]
        return targets

    def needs_material(self, role) -> bool:
        return role.backpack.count('stone') < self.targets().get(role.unit_id, 0)

    def can_build_now(self, role) -> bool:
        """A local wall can consume the held stone without a mining detour."""
        if not self.turn.is_day or 'stone' not in role.backpack:
            return False
        blocked = self.turn.blocked(role) | self.plan.reserved | self.s.goals
        candidates = self.s.construction_walls()
        schedule = getattr(self.s,'wall_schedule',None)
        if schedule is not None and schedule.enabled:
            candidates = schedule.targets(role,[p for p in candidates if p not in blocked
                and not self.s.coordinator.target_owned(role,p,'build:wall')],local_only=True)
        for target in candidates:
            if (distance(role.pos, target) != 1 or target in blocked
                    or target in self.turn.vehicle_cells() | self.turn.vehicle_cells(False)
                    or self.s.coordinator.target_owned(role, target, 'build:wall')):
                continue
            if self.s.wall_keeps_exit(role, target):
                return True
        return False

    def options(self, role, return_cells=None):
        """Reachable current stone sites, using real outside posts and sight."""
        job = self.s.coordinator.job(role)
        previous = job.get('target') if job.get('kind') == 'collect:stone' else None
        unavailable = (self.s.coordinator.claimed_goals(role) | self.plan.reserved
                       | self.s.movement_reserved(role))
        options = []
        for pos, kind in self.turn.zones.items():
            if kind != 'stone':
                continue
            if self.turn.mine_remaining.get(pos,10)<=0:
                continue
            if self.memory.failed_mines.get(f'{pos.x},{pos.y}', 0) > self.turn.round_no:
                continue
            if any(c['name'] == 'stone' and c['startDay'] <= self.turn.day <= c['endDay']
                   for c in self.memory.mine_closures):
                continue
            goals = adjacent_cells(self.turn, [pos]) - unavailable
            if not goals:
                continue
            route = self.s.route(role)
            if route.nearest(goals) is None:
                route = self.s.coordinator.diagnostic_route(role)
            if self.s.danger:
                goals = {p for p in goals if not self.s.danger.get(p, 0)
                         and route.exposure.get(p) == 0}
            if return_cells is not None and not (self.turn.day == 1 and self.turn.is_day):
                goals = {p for p in goals if p in route.cost and return_cells
                         and route.cost[p] + 1 + min(distance(p, home) for home in return_cells)
                         + self.s.settings.return_margin < self.turn.daylight_left}
            goal = route.nearest(goals)
            if goal is None:
                continue
            cost = route.cost[goal]
            options.append((role.pos not in goals, pos != previous, cost, pos, goals))
        return options

    def assignments(self):
        """Stable first-day mine ownership; distinct mines before shared fallback.

        The remaining field is an observation, never decremented by a submitted
        collect. An established valid trip stays even if other players reduce
        that mine's stock: collect the remainder, then reassign on disappearance.
        """
        quota=self.targets()
        workers=[w for w in self.turn.workers() if not w.backpack_full
                 and w.backpack.count('stone')<quota.get(w.unit_id,0)]
        options={w.unit_id:{entry[3]:entry for entry in self.options(w)} for w in workers}
        workers=[w for w in workers if options[w.unit_id]]
        previous=self.state.get('assignments',{}) if self.state.get('round',0)>=self.turn.round_no-1 else {}
        locks={}
        for worker in workers:
            job=self.s.coordinator.job(worker)
            target=previous.get(worker.unit_id)
            if target not in options[worker.unit_id]:
                target=job.get('target') if job.get('kind')=='collect:stone' else None
            if target in options[worker.unit_id] and job.get('stalled',0)<2:
                locks[worker.unit_id]=target
        def score(sites):
            demands={}
            for worker,pos in zip(workers,sites):
                demands[pos]=demands.get(pos,0)+quota[worker.unit_id]-worker.backpack.count('stone')
            deficit=sum(max(0,need-self.turn.mine_remaining.get(pos,10)) for pos,need in demands.items())
            changes=sum(uid in locks and pos!=locks[uid] for uid,pos in zip((w.unit_id for w in workers),sites))
            costs=sum(options[w.unit_id][pos][2] for w,pos in zip(workers,sites))
            return len(sites)-len(set(sites)),changes,deficit,costs,sites
        combinations=product(*(options[w.unit_id] for w in workers))
        chosen=min(combinations,key=score) if workers else ()
        assignments={w.unit_id:pos for w,pos in zip(workers,chosen)}
        self.state.update(round=self.turn.round_no,assignments=assignments,
            shortage={w.unit_id:quota[w.unit_id]-w.backpack.count('stone') for w in workers},
            shared_fallback=len(set(chosen))<len(chosen))
        return assignments

    def diagnostic(self):
        return dict(self.state,remaining={p:self.turn.mine_remaining.get(p) for p,kind in self.turn.zones.items()
                                         if kind=='stone'},unknown_remaining_fallback=10)

    def mine(self, role, return_cells: set[Pos] | None = None) -> bool:
        """Collect a personal share; first day gives each miner its own site."""
        if role.backpack_full or not self.needs_material(role):
            return False
        options=self.options(role,return_cells)
        if self.turn.day==1 and self.turn.is_day:
            target=self.assignments().get(role.unit_id)
            options=[entry for entry in options if entry[3]==target]
        for _, _, _, pos, goals in sorted(options, key=lambda entry: entry[:4]):
            if role.pos in goals and self.plan.add(role.unit_id, collect_command(pos)):
                self.s.coordinator.assign(role, 'collect:stone', pos, role.pos)
                return True
            if self.s.coordinator.move_to(role, goals, 'collect:stone', pos):
                return True
        return False
