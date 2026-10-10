"""Observe hostile site camping; detour walls and a stocked dawn builder."""
from .grid import adjacent_cells
from .protocol import CONTROLLABLE_TYPES, Pos, build_command, distance, move_command


OCCUPATION_LIMIT = 5  # Strictly more than five consecutive observed rounds.


class SiteBlockade:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.memory, self.plan = strategy.turn, strategy.memory, strategy.plan
        self.worker_id = None
        self.watch_gap = None
        self.temporary_needed = set()
        self.cleanup_sites = set()
        self.detours = {}
        self.seal_assignments = {}
        self.observe_sites()
        required = set()
        for gap in self.memory.wall_blockades:
            self.plan.authorize_wall_detour(gap)
            self.detours[gap] = set(self.s.settings.wall_detour_cells(self.turn, gap))
            required.update(self.detours[gap])
        self.observe_build_feedback()
        self.required = required
        standing = {w.pos for w in self.turn.walls()}
        self.temporary_needed = required - standing
        for gap, record in self.memory.wall_blockades.items():
            record['temporary_needed'] = sorted(self.detours[gap] & self.temporary_needed)
            record['sealed_observed'] = bool(self.detours[gap]) and not (self.detours[gap] & self.temporary_needed)
        self.cleanup_sites = (self.memory.temporary_wall_sites & standing) - required
        # Forget destroyed/removed temporary walls once no breach needs them.
        self.memory.temporary_wall_sites &= standing | required

    def observe_sites(self):
        walls = set(self.s.settings.build_cells(self.turn, 'wall'))
        sites = set(self.s.missing_walls()) | (set(self.s.layout.tower_sites)
                 - {w.pos for w in self.turn.weapons()})
        old = self.memory.site_occupations
        observed = {}
        for enemy in self.turn.enemies:
            if enemy.health <= 0 or enemy.kind not in CONTROLLABLE_TYPES or enemy.pos not in sites:
                continue
            previous = old.get(enemy.pos, {})
            same = previous.get('enemy_id') == enemy.unit_id
            last = previous.get('last_round', -1)
            count = (previous['count'] if same and last == self.turn.round_no else
                     previous['count'] + 1 if same and last == self.turn.round_no - 1 else 1)
            observed[enemy.pos] = {'enemy_id': enemy.unit_id, 'count': count, 'last_round': self.turn.round_no}
            if count > OCCUPATION_LIMIT and enemy.pos in walls:
                self.memory.wall_blockades.setdefault(enemy.pos,
                    {'enemy_id': enemy.unit_id, 'confirmed_round': self.turn.round_no})
        self.memory.site_occupations = observed
        missing = set(self.s.missing_walls())
        # A vanished occupant is not proof that the missing original wall was built.
        self.memory.wall_blockades = {p: record for p, record in self.memory.wall_blockades.items()
                                     if p in missing}

    def observe_build_feedback(self):
        if self.memory.last_round != self.turn.round_no - 1:
            return
        permanent = set(self.s.settings.build_cells(self.turn, 'wall'))
        for actor, command in self.memory.last_commands.items():
            if (command.get('action') != 'build' or command.get('name') != 'wall'
                    or self.turn.action_results.get(str(actor)) is not False):
                continue
            points = command.get('targetPos', [])
            if len(points) != 1:
                continue
            target = Pos.load(points[0])
            if target in permanent:
                continue
            for gap, record in self.memory.wall_blockades.items():
                if target not in self.detours[gap] and distance(target, gap) > 1:
                    continue
                failed = record.setdefault('failed_sites', {})
                previous = failed.get(target, {})
                if previous.get('round') == self.turn.round_no:
                    continue
                failed[target] = dict(count=previous.get('count', 0) + 1,
                                      round=self.turn.round_no, actor_id=str(actor))

    def failed(self, target):
        # A rejected location stays excluded for this incident. Observing the
        # original wall rebuilt retires its incident and the failure record.
        return any(target in record.get('failed_sites', {})
                   for record in self.memory.wall_blockades.values())

    def sealed(self, gap=None):
        """Only walls in this turn's observation can close a known incident."""
        if gap is None:
            return bool(self.detours) and all(self.sealed(site) for site in self.detours)
        cells = self.detours.get(gap, set())
        return bool(cells) and not (cells & self.temporary_needed)

    def posts(self, gap):
        targets = self.detours.get(gap) or {gap}
        excluded = self.required | set(self.s.settings.build_cells(self.turn, 'wall'))
        inner = {p for p in self.s.guard.inner_cells() if p not in excluded
                 and any(distance(p, target) == 1 for target in targets)}
        return inner or (adjacent_cells(self.turn, targets) - excluded
                        - set(self.s.layout.tower_sites) - {self.s.layout.operator_pos})

    def build_posts(self, target):
        return (adjacent_cells(self.turn, [target]) - self.required
                - set(self.s.settings.build_cells(self.turn, 'wall'))
                - set(self.s.layout.tower_sites) - {self.s.layout.operator_pos})

    def assign_sealers(self, workers):
        self.seal_assignments = {w.unit_id: set() for w in workers}
        if not self.turn.is_day or len(self.turn.weapons()) < 3:
            return
        for target in sorted(self.temporary_needed):
            if self.failed(target):
                continue
            options = []
            for worker in workers:
                route = self.s.route(worker)
                post = route.nearest(self.build_posts(target))
                if post is None:
                    continue
                reserve = int(worker.unit_id == self.memory.blockade_worker_id)
                extra = worker.backpack.count('stone') - reserve
                gather = 0
                if extra <= len(self.seal_assignments[worker.unit_id]):
                    mines = [p for p, kind in self.turn.zones.items() if kind == 'stone']
                    mine_cost = self.s.cost(worker, mines) if mines else 10_000
                    if mine_cost >= 10_000:
                        continue
                    gather = mine_cost + 1
                old = self.s.coordinator.job(worker)
                options.append((route.cost[post] + gather,
                                old.get('target') != target,
                                len(self.seal_assignments[worker.unit_id]), worker.unit_id))
            if options:
                self.seal_assignments[min(options)[-1]].add(target)
        for gap, record in self.memory.wall_blockades.items():
            record['seal_assignments'] = {uid: sorted(cells & self.detours[gap])
                                          for uid, cells in self.seal_assignments.items()
                                          if cells & self.detours[gap]}

    def choose_watcher(self):
        workers = self.turn.workers()
        if self.turn.day == 1 and self.s.settings.enable_boss_raid and len(workers) >= 2:
            scout = self.memory.raid_scouts.get('worker_id')
            workers = tuple(w for w in workers if w.unit_id != scout)
        gaps = [gap for gap in self.memory.wall_blockades if self.posts(gap)]
        if not workers or not gaps:
            self.memory.blockade_worker_id = None
            self.memory.blockade_watch = False
            return
        pairs = []
        for worker in workers:
            route = self.s.coordinator.diagnostic_route(worker)
            for gap in gaps:
                post = route.nearest(self.posts(gap))
                if post is not None:
                    pairs.append((worker, gap, route.cost[post]))
        if not pairs:
            self.memory.blockade_worker_id = None
            self.memory.blockade_watch = False
            return
        occupied = self.turn.occupied_cells()
        worker, gap, cost = min(pairs, key=lambda entry: (
            entry[0].unit_id != self.memory.blockade_worker_id,
            'stone' not in entry[0].backpack, self.turn.is_day and entry[1] in occupied,
            self.s.guard.is_guard(entry[0]),
            entry[1] != self.s.coordinator.job(entry[0]).get('target'),
            entry[2], entry[1].x if self.s.settings.mirrored_layout(self.turn) else -entry[1].x,
            entry[0].unit_id, entry[1]))
        self.memory.blockade_worker_id = worker.unit_id
        self.watch_gap = gap
        self.assign_sealers(workers)
        gather = 0
        if 'stone' not in worker.backpack:
            mines = [p for p, kind in self.turn.zones.items() if kind == 'stone']
            cost_to_mine = self.s.cost(worker, mines) if mines else 10_000
            if cost_to_mine < 10_000:
                gather = cost_to_mine + 1 + min(
                    max(0, distance(mine, post) - 1) for mine in mines for post in self.posts(gap))
        # Leave enough time for one collection and the return, rather than
        # waiting until the final daytime round to discover an empty bag.
        prepare = max(10, cost + self.s.settings.return_margin,
                      gather + self.s.settings.return_margin)
        occupant = any(u.health > 0 and u.pos == gap for u in self.turn.enemies)
        if self.turn.is_day and self.turn.daylight_left > prepare and occupant:
            self.memory.blockade_watch = False
        if (not self.turn.is_day or self.turn.daylight_left <= prepare
                or (self.turn.is_day and not occupant)):
            self.memory.blockade_watch = True
        if self.memory.blockade_watch:
            self.worker_id, self.watch_gap = worker.unit_id, gap

    def is_waiting(self, role):
        return role.unit_id == self.worker_id and role.pos in self.posts(self.watch_gap)

    def watch(self, role):
        if role.unit_id not in self.seal_assignments and role.unit_id != self.worker_id:
            return False
        if self.rebuild_original(role):
            return True
        if self.turn.is_day and role.pos in self.temporary_needed and self.clear_temporary_site(role):
            return True
        needed = self.seal_assignments.get(role.unit_id, set()) - self.plan.build_targets
        if self.turn.is_day and needed:
            self.s.coordinator.job(role).pop('yield_until', None)
            reserve = int(role.unit_id == self.memory.blockade_worker_id)
            if role.backpack.count('stone') > reserve:
                if self.build_temporary(role, needed):
                    return True
            elif role.backpack_full:
                if self.s.sell(role, keep_stone=True):
                    return True
            elif self.s.mine(role, need_stone=True):
                return True
            # Sealing is pending; never silently turn this worker into an iron miner.
            self.s.coordinator.assign(role, 'blockade_materials', tuple(sorted(needed)), role.pos)
            self.plan.used.add(role.unit_id)
            return True
        if (self.turn.is_day and self.temporary_needed
                and role.unit_id == self.memory.blockade_worker_id
                and role.backpack.count('stone') <= 1):
            self.s.coordinator.assign(role, 'blockade_reserve', self.watch_gap, role.pos)
            self.plan.used.add(role.unit_id)
            return True
        if role.unit_id != self.worker_id:
            return False
        gap = self.watch_gap
        posts = self.posts(gap)
        self.s.coordinator.job(role).pop('yield_until', None)
        if self.turn.is_day and 'stone' not in role.backpack:
            if role.backpack_full:
                if self.s.sell(role, keep_stone=True):
                    return True
            elif self.s.mine(role, need_stone=True, return_cells=posts):
                return True
        # Waiting does not prevent an immediate repair from this exact post.
        if role.pos in posts and 'WallFixer' in role.backpack:
            critical = [w for w in self.turn.walls() if distance(role.pos, w.pos) == 1
                        and w.health * 100 < self.s.building_max_health(w) * self.s.settings.repair_threshold_percent
                        and w.unit_id not in self.plan.upgrade_targets | self.s.maintenance_claims]
            if critical:
                wall = min(critical, key=lambda w: (w.health / self.s.building_max_health(w), w.unit_id))
                if self.plan.add(role.unit_id, {'action': 'use', 'name': 'WallFixer', 'targetPos': [wall.pos.dump()]}):
                    self.s.coordinator.assign(role, 'blockade_repair', gap, role.pos)
                    self.s.maintenance_claims.add(wall.unit_id)
                    return True
        first = getattr(self.s, 'first_defense', None)
        if first is not None and first.worker_id == role.unit_id:
            occupied = any(u.health > 0 and u.pos == gap for u in self.turn.enemies)
            supply = getattr(first, 'needs_supply', None)
            if (not self.turn.is_day or (self.turn.day == 1 and occupied and self.sealed(gap)
                                         and callable(supply) and supply(role))):
                return False
        if role.pos in posts:
            self.s.coordinator.assign(role, 'blockade_watch', gap, role.pos)
            self.plan.used.add(role.unit_id)
            return True
        self.s.coordinator.move_to(role, posts, 'blockade_watch', gap,
            allowed=self.s.guard.inner_cells() if role.pos in self.s.guard.inner_cells() else None, allow_risk=True)
        return True

    def clear_temporary_site(self, role):
        cells = [p for p in role.pos.neighbours() if self.turn.land(p)
                 and p not in self.turn.blocked(role) | self.plan.reserved
                 and p not in self.required
                 and p not in self.s.settings.build_cells(self.turn, 'wall')
                 and p not in self.s.layout.tower_sites and p != self.s.layout.operator_pos]
        if not cells:
            return False
        post = min(cells, key=lambda p: (p not in self.s.guard.inner_cells(), p))
        if self.plan.add(role.unit_id, move_command(post)):
            self.s.coordinator.assign(role, 'blockade_clear', role.pos, post, True)
            return True
        return False

    def rebuild_original(self, role):
        if not self.turn.is_day or 'stone' not in role.backpack:
            return False
        gaps = [p for p in self.memory.wall_blockades if p not in self.turn.blocked(role)
                and p not in self.plan.reserved and p not in self.s.goals]
        for gap in sorted(gaps, key=lambda p: (self.s.cost(role, [p]), p)):
            if distance(role.pos, gap) == 1 and self.s.wall_keeps_exit(role, gap):
                if self.plan.add(role.unit_id, build_command(gap, 'wall')):
                    self.s.coordinator.assign(role, 'build:wall', gap, role.pos)
                    self.s.goals.add(gap)
                    return True
            goals = self.build_posts(gap)
            route = self.s.route(role)
            post = route.nearest(goals)
            if post is None or route.cost[post] + 1 > self.turn.daylight_left:
                continue
            if self.s.coordinator.move_to(role, goals, 'blockade_rebuild', gap, allow_risk=True):
                self.s.goals.add(gap)
                return True
        return False

    def build_temporary(self, role, needed):
        route = self.s.route(role)
        old = self.s.coordinator.job(role)
        options = []
        for target in needed:
            if self.failed(target) or target in self.turn.blocked(role) | self.plan.reserved | self.s.goals:
                continue
            post = route.nearest(self.build_posts(target))
            if post is not None and route.cost[post] + 1 <= self.turn.daylight_left:
                options.append((target != old.get('target'), route.cost[post], target, post))
        for _, _, target, post in sorted(options):
            if role.pos == post:
                if not self.s.wall_keeps_exit(role, target):
                    continue
                if self.plan.add(role.unit_id, build_command(target, 'wall')):
                    self.s.coordinator.assign(role, 'blockade_build', target, post)
                    self.memory.temporary_wall_sites.add(target)
                    self.s.goals.add(target)
                    return True
            elif self.s.coordinator.move_to(role, self.build_posts(target), 'blockade_build', target,
                                            allow_risk=True):
                return True
        return False

    def cleanup(self, role):
        if not self.turn.is_day:
            return False
        candidates = {p for p in self.cleanup_sites - self.s.goals
                      if not self.s.coordinator.target_owned(role, p, 'remove:')}
        job = self.s.coordinator.job(role)
        previous = job.get('target') if job.get('kind') == 'remove:' else None
        for target in sorted(candidates, key=lambda p: (p != previous, self.s.cost(role, [p]), p)):
            if self.s.interact(role, target, {'action': 'remove', 'targetPos': [target.dump()]}):
                self.s.goals.add(target)
                return True
        return False
