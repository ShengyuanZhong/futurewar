"""Observed wall-material quotas and cooperative stone collection.

The wall count and backpacks are never changed by a submitted command.  The
next official observation must confirm both building and collecting.  Travel
appointments live in the existing per-worker memory; a departing BOSS buyer's
bag cannot pay for the builder who stays behind.
"""
from .grid import adjacent_cells
from .protocol import Pos, collect_command, distance


class StonePlanner:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory

    def targets(self) -> dict[int, int]:
        """Required actual bag counts, retaining an unfinished collection share.

        A remembered share is a preference for dividing an actual deficit, not
        additional demand.  Existing stones come first, then previous shares,
        then a balanced assignment of the remaining shortage.  No entrance
        stone is reserved: every stone may build an ordinary blueprint wall.
        """
        workers = self.turn.workers()
        raid = getattr(self.s, 'boss_raid', None)
        builders = [w for w in workers if raid is None or not raid.worker_mission_active(w)]
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
        for target in self.s.construction_walls():
            if (distance(role.pos, target) != 1 or target in blocked
                    or target in self.turn.vehicle_cells() | self.turn.vehicle_cells(False)
                    or self.s.coordinator.target_owned(role, target, 'build:wall')):
                continue
            if self.s.wall_keeps_exit(role, target):
                return True
        return False

    def mine(self, role, return_cells: set[Pos] | None = None) -> bool:
        """Collect only the outstanding share at a legal, separately claimed post.

        An immediately usable stone mine wins over an old distant appointment.
        Otherwise keep a valid current destination to avoid mid-route reversals.
        Workers may share a mine; they may not share its collection position.
        """
        if role.backpack_full or not self.needs_material(role):
            return False
        job = self.s.coordinator.job(role)
        previous = job.get('target') if job.get('kind') == 'collect:stone' else None
        unavailable = (self.s.coordinator.claimed_goals(role) | self.plan.reserved
                       | self.s.movement_reserved(role))
        options = []
        for pos, kind in self.turn.zones.items():
            if kind != 'stone':
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
        for _, _, _, pos, goals in sorted(options, key=lambda entry: entry[:4]):
            if role.pos in goals and self.plan.add(role.unit_id, collect_command(pos)):
                self.s.coordinator.assign(role, 'collect:stone', pos, role.pos)
                return True
            if self.s.coordinator.move_to(role, goals, 'collect:stone', pos):
                return True
        return False
