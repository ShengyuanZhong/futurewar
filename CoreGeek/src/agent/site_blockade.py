"""Observe hostile site camping; detour walls and a stocked dawn builder."""
from .protocol import CONTROLLABLE_TYPES, build_command, distance


OCCUPATION_LIMIT = 5  # Strictly more than five consecutive observed rounds.


class SiteBlockade:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.memory, self.plan = strategy.turn, strategy.memory, strategy.plan
        self.worker_id = None
        self.watch_gap = None
        self.temporary_needed = set()
        self.cleanup_sites = set()
        self.observe_sites()
        required = set()
        for gap in self.memory.wall_blockades:
            self.plan.authorize_wall_detour(gap)
            required.update(self.s.settings.wall_detour_cells(self.turn, gap))
        standing = {w.pos for w in self.turn.walls()}
        self.temporary_needed = required - standing
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

    def posts(self, gap):
        # Outward detours leave the original inner repair lane free for a builder.
        return {p for p in self.s.guard.inner_cells() if distance(p, gap) == 1}

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
        if not self.turn.is_day or self.turn.daylight_left <= prepare:
            self.memory.blockade_watch = True
        if self.memory.blockade_watch:
            self.worker_id, self.watch_gap = worker.unit_id, gap

    def is_waiting(self, role):
        return role.unit_id == self.worker_id and role.pos in self.posts(self.watch_gap)

    def watch(self, role):
        if role.unit_id != self.worker_id:
            return False
        gap = self.watch_gap
        posts = self.posts(gap)
        self.s.coordinator.job(role).pop('yield_until', None)
        if (self.turn.is_day and 'stone' in role.backpack and distance(role.pos, gap) == 1
                and gap not in self.turn.blocked(role) and gap not in self.plan.reserved
                and self.s.wall_keeps_exit(role, gap)):
            if self.plan.add(role.unit_id, build_command(gap, 'wall')):
                self.s.coordinator.assign(role, 'build:wall', gap, role.pos)
                self.s.goals.add(gap)
                return True
        if self.turn.is_day and 'stone' not in role.backpack:
            if role.backpack_full:
                if self.s.sell(role):
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
        if role.pos in posts:
            self.s.coordinator.assign(role, 'blockade_watch', gap, role.pos)
            self.plan.used.add(role.unit_id)
            return True
        self.s.coordinator.move_to(role, posts, 'blockade_watch', gap,
            allowed=self.s.guard.inner_cells() if role.pos in self.s.guard.inner_cells() else None, allow_risk=True)
        return True

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
