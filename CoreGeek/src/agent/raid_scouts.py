"""Day-one hero observers for a summoned BOSS that supplies no sight."""
from .protocol import IMP, Pos, distance, move_command, station_footprint
from .summoning import enemy_base_position


SIGHT = 4


class RaidScouts:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.raid_scouts
        self.base = enemy_base_position(self.turn)
        alive_boss = any(r.kind == 'bossRobot' and r.health > 0 for r in self.turn.summon_robots)
        if alive_boss:
            self.state['seen_boss'] = True
        enemy = next((u for u in self.turn.enemies if u.kind == 'station'), None)
        self.active = (self.s.settings.enable_boss_raid and self.turn.day == 1
                       and self.base is not None and not self.state.get('finished')
                       and not (enemy and enemy.health <= 0)
                       and (self.turn.is_day or alive_boss or
                            (not self.state.get('seen_boss') and self.memory.boss_raid.get('status')
                             in ('summon_pending', 'deployed'))))
        if not self.active:
            finished = (self.turn.day == 1 and self.s.settings.enable_boss_raid
                        and (self.state.get('finished') or (self.state.get('seen_boss') and not alive_boss)
                             or (enemy and enemy.health <= 0)))
            self.release(finished)
            return
        self.state['base'] = self.base
        self.state['round'] = self.turn.round_no
        live = {u.unit_id for u in self.turn.controllable()}
        self.state['posts'] = {uid:job for uid,job in self.state.get('posts', {}).items() if uid in live}
        self.state['walls_ready'] = self.walls_ready()
        workers = self.turn.workers()
        self.state['worker_status'] = ('assigned' if self.state.get('worker_id') is not None else
                                      'waiting_for_walls' if not self.state['walls_ready'] else
                                      'not_enough_workers' if len(workers) < 2 else 'waiting_for_route')
        # Assign only once, and never replace a dead observer with the sole home worker.
        if (self.state.get('worker_id') is None and len(workers) >= 2
                and self.state['walls_ready'] and self.turn.is_day):
            candidates = [w for w in workers if w.unit_id != self.memory.blockade_worker_id]
            if candidates:
                choices = []
                for worker in candidates:
                    post = self.post(worker)
                    if post is not None:
                        cost = self.s.route(worker).cost[post]
                        # A new mission must reach the observation area by the first night.
                        if cost <= self.turn.daylight_left:
                            choices.append((cost, worker.unit_id))
                if choices:
                    self.state['worker_id'] = min(choices)[1]
                    self.state['home_worker_id'] = next(w.unit_id for w in workers
                                                       if w.unit_id != self.state['worker_id'])
                    self.state['worker_status'] = 'assigned'
                else:
                    self.state['worker_status'] = 'unreachable_or_too_late'

    def release(self, finished=False):
        for uid, job in list(self.memory.worker_tasks.items()):
            if job.get('kind') == 'raid_scout':
                self.memory.worker_tasks.pop(uid)
        self.state.clear()
        if finished:
            self.state.update(finished=True, round=self.turn.round_no)

    def walls_ready(self):
        cells = self.s.settings.build_cells(self.turn, 'wall')
        return bool(cells) and len(self.turn.weapons()) >= 3 and not self.s.construction_walls()

    def is_worker(self, role):
        return (self.active and role.unit_id == self.state.get('worker_id')
                and len(self.turn.workers()) >= 2 and role.unit_id != self.memory.blockade_worker_id
                and (not self.turn.is_day or self.state['walls_ready']))

    def watch_cells(self):
        right = 2*self.base.x + 1 > self.turn.width - 1
        gun_x = self.base.x + (2 if right else -1)
        guns = {Pos(gun_x, self.base.y+dy) for dy in (-1, 0, 1)}
        # Template cells guide positioning only; no hidden enemies are invented.
        guns.update(w.pos for w in self.turn.enemies if w.health > 0
                    and w.kind in ('rocket', 'gatling', 'railgun'))
        footprint = set(station_footprint(self.base))
        # Logs show opponents placing guns on the front side too. This local
        # observation neighbourhood is a heuristic, not a construction-zone rule.
        cells = {Pos(x, y) for x in range(self.base.x-2, self.base.x+4)
                 for y in range(self.base.y-3, self.base.y+3)}
        cells.update(p for gun in guns for p in gun.neighbours())
        return {p for p in cells if self.turn.in_bounds(p) and p not in footprint}

    def preferred(self, role):
        right = 2*self.base.x + 1 > self.turn.width - 1
        return Pos(self.base.x + (5 if right else -4), self.base.y + (2 if role.kind == IMP else -2))

    def post(self, role):
        right = 2*self.base.x + 1 > self.turn.width - 1
        preferred = self.preferred(role)
        targets = self.watch_cells()
        old = self.state.get('posts', {}).get(role.unit_id, {}).get('goal')
        claimed = {job['goal'] for uid, job in self.state.get('posts', {}).items() if uid != role.unit_id}
        spawn_x = self.base.x + (4 if right else -3)
        excluded = {Pos(spawn_x, self.base.y), Pos(spawn_x, self.base.y-1)}
        excluded.update(self.memory.pending_summon_positions)
        if self.memory.boss_raid.get('spawn') is not None:
            excluded.add(self.memory.boss_raid['spawn'])
        route = self.s.route(role)
        options = []
        upper = min(self.turn.height-1, self.base.y+2)
        lower = max(0, self.base.y-2)
        # Separate upper/lower sectors also keep observers out of the BOSS's forward lane.
        for p in route.cost:
            if (p in excluded or p in claimed or p in self.plan.reserved or not self.turn.land(p)
                    or not (p.x > self.base.x+1 if right else p.x < self.base.x)
                    or not (p.y >= upper if role.kind == IMP else p.y <= lower)
                    or (role.kind != IMP and self.turn.is_day and route.cost[p] > self.turn.daylight_left)):
                continue
            coverage = sum(distance(p, target) <= SIGHT for target in targets)
            if coverage:
                options.append((-coverage, self.s.danger.get(p, 0), p != old,
                                distance(p, preferred), route.cost[p], p))
        return min(options)[-1] if options else None

    def observe_from(self, role):
        post = self.post(role)
        if post is None:
            self.state.setdefault('posts', {})[role.unit_id] = dict(goal=None, status='unreachable',
                                                                  round=self.turn.round_no)
            # Do not fall through to a distant mine while a first-night sight mission is active.
            self.plan.used.add(role.unit_id)
            return True
        route = self.s.route(role)
        self.state.setdefault('posts', {})[role.unit_id] = dict(goal=post,
            status='holding' if post == role.pos else 'travelling', round=self.turn.round_no,
            steps=route.cost[post], ready_by_night=route.cost[post] <= self.turn.daylight_left if self.turn.is_day else None,
            coverage=sum(distance(post, p) <= SIGHT for p in self.watch_cells()))
        if role.kind == IMP:
            self.memory.imp_tasks.pop(role.unit_id, None)
            if post == role.pos:
                self.plan.used.add(role.unit_id)
                return True
            step = route.step({post})
            if step is not None:
                self.plan.add(role.unit_id, move_command(step))
            return True
        self.s.coordinator.job(role).pop('yield_until', None)
        if post == role.pos:
            self.s.coordinator.assign(role, 'raid_scout', self.base, post)
            self.plan.used.add(role.unit_id)
            return True
        self.s.coordinator.move_to(role, {post}, 'raid_scout', self.base, allow_risk=True)
        return True

    def imp(self, role):
        return self.active and self.observe_from(role)

    def worker(self, role):
        if not self.active or role.unit_id != self.state.get('worker_id'):
            return False
        if (len(self.turn.workers()) < 2 or role.unit_id == self.memory.blockade_worker_id
                or (self.turn.is_day and not self.state['walls_ready'])):
            self.state.get('posts', {}).pop(role.unit_id, None)
            self.state['worker_status'] = 'home_defense' if len(self.turn.workers()) < 2 else 'paused_for_walls_or_blockade'
            return False
        return self.observe_from(role)
