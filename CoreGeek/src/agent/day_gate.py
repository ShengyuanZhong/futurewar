"""One temporary daytime entrance in the otherwise sealed 17-wall drawing."""
from .grid import Routes, adjacent_cells
from .protocol import CONTROLLABLE_TYPES, Pos, build_command, distance
from .upgrade_policy import wall_target_level


class DayGate:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.day_gate
        base = self.turn.station()
        offset = 2 if self.s.settings.mirrored_layout(self.turn) else -1
        self.pos = Pos(base.pos.x + offset, base.pos.y + 2) if base else None
        self.enabled = bool(base and self.s.settings.default_operator_position(self.turn) is not None
                            and self.pos in self.s.settings.build_cells(self.turn, 'wall'))
        workers = self.turn.workers()
        alive = {w.unit_id for w in workers}
        viable = {w.unit_id for w in workers if 'stone' in w.backpack or not w.backpack_full}
        preferred = (self.s.gap_guard.worker_id, self.s.first_defense.worker_id,
                     self.state.get('worker_id'), self.s.guard.worker_id)
        self.worker_id = next((uid for uid in preferred if uid in alive and uid in viable), None)
        if self.worker_id is None and workers:
            scout = self.memory.raid_scouts.get('worker_id')
            candidates = [w for w in workers if w.unit_id != scout and w.unit_id in viable]
            candidates = candidates or [w for w in workers if w.unit_id != scout] or list(workers)
            self.worker_id = min(candidates, key=lambda w: w.unit_id).unit_id
        self.state.update(enabled=self.enabled, round=self.turn.round_no,
                          worker_id=self.worker_id, pos=self.pos.dump() if self.pos else None)
        observed = self.wall()
        if observed is not None and self.state.get('status') in ('sealing', 'upgrading_gate'):
            self.state['status'] = 'sealed_level2' if observed.level >= 2 else 'sealed'
        elif observed is None and self.state.get('status') == 'opening':
            self.state['status'] = 'open'

    def role(self):
        return next((w for w in self.turn.workers() if w.unit_id == self.worker_id), None)

    def wall(self):
        return next((w for w in self.turn.walls() if w.pos == self.pos), None)

    def inner_posts(self):
        return {p for p in self.s.guard.inner_cells() if distance(p, self.pos) == 1}

    def access_route(self, role):
        # Never reserve the unbuilt entrance itself: the opening requires this
        # route even before any walls physically exist.
        reserved = (set(self.plan.reserved) | set(self.s.layout.tower_sites)
                    | set(self.s.settings.build_cells(self.turn, 'wall'))) - {self.pos}
        if self.s.layout.operator_pos is not None:
            reserved.add(self.s.layout.operator_pos)
        return Routes(self.turn, role, reserved, self.s.danger)

    def closing(self):
        if not self.enabled or not self.turn.is_day:
            return False
        if self.turn.day == 1:
            return False  # No first-day worker is recalled to reserve a seal trip.
        if not self.memory.opening_complete and not self.other_ready(self.s.gap_guard.gaps):
            return False  # A lone door is no reason to abandon an unfinished opening.
        role = self.role()
        if role is None:
            return False
        route = self.access_route(role)
        home = route.nearest(self.inner_posts())
        cost = route.cost.get(home, 0)
        # Return, reserve time for a teammate to enter, then spend one distinct
        # action sealing from inside. Gap body duty needs a few more steps.
        margin = max(12 if self.s.guard.full_time else 9 if self.s.gap_guard.gaps else 8,
                     self.s.settings.return_margin + 4)
        return self.turn.daylight_left <= cost + margin

    def other_ready(self, ignore=()):
        if not self.enabled or len(self.turn.weapons()) < 3:
            return False
        standing = {w.pos for w in self.turn.walls()}
        required = set(self.s.settings.build_cells(self.turn, 'wall')) - {self.pos} - set(ignore)
        return bool(required) and required <= standing

    def day_ready(self, ignore=()):
        """Controlled entrance is construction-ready, never physically closed."""
        if not self.enabled or not self.turn.is_day or not self.other_ready(ignore):
            return False
        if self.wall() is not None:
            return True
        role = self.role()
        if role is None or 'stone' not in role.backpack:
            return False
        if self.pos in set(ignore):
            # An opponent occupying the door is the existing body-gap case,
            # not permission to invent extra walls or force an impossible seal.
            route = self.s.gap_guard.route(role)
            post = route.nearest(self.s.gap_guard.posts())
            return post is not None and route.cost[post] <= self.turn.daylight_left
        route = self.access_route(role)
        post = route.nearest(self.inner_posts())
        return post is not None and route.cost[post] + 1 <= self.turn.daylight_left

    def dispatch_ready(self, ignore=()):
        """Construction permits dispatch without reserving a buyer's return trip.

        The daytime entrance stays open while the two workers are away. All
        other legal sites must really exist, apart from observed occupied gaps,
        and the entrance owner keeps the stone needed to seal after returning.
        """
        occupied = {u.pos for u in self.turn.enemies if u.health>0 and u.kind in CONTROLLABLE_TYPES}
        ignore = set(ignore) & occupied
        if not self.enabled or not self.turn.is_day or not self.other_ready(ignore):
            return False
        if self.wall() is not None:
            return True
        role = self.role()
        return bool(role and 'stone' in role.backpack)

    def reserve_stone(self, role):
        return int(self.enabled and role.unit_id == self.worker_id and self.turn.is_day)

    def non_gate_upgrades_complete(self):
        return bool(self.turn.day > 1 and self.other_ready()
                    and len(self.turn.weapons()) >= 3 and all(w.level >= 3 for w in self.turn.weapons())
                    and all(w.level >= wall_target_level(self.s, w)
                            for w in self.turn.walls() if w.pos != self.pos))

    def prepare_coupon(self, role):
        """After the normal upgrade sequence, reserve one level-2 door coupon."""
        name = 'WallUpgradeVoucher1'
        if (not self.non_gate_upgrades_complete() or name in role.backpack
                or role.backpack_full or not self.s.boss_raid.weapon_upgrades_ready()):
            return False
        price = self.turn.shop_prices.get(name)
        reserve = max(0, 3 - self.plan.tower_count) * 25 + self.s.boss_raid.budget_reserve()
        if price is None or self.plan.gold - reserve < price:
            return False
        shops = [p for p, k in self.turn.zones.items() if k == 'weaponShop']
        trip = self.s.first_defense.trip(role, adjacent_cells(self.turn, shops), interactions=3)
        if trip is None or trip[0] + 4 > self.turn.daylight_left:
            return False
        if self.plan.near_zone(role, 'weaponShop'):
            if self.plan.add(role.unit_id, {'action': 'buy', 'name': name, 'num': 1}):
                self.s.coordinator.assign(role, 'gate_supply', name, role.pos)
                self.state['status'] = 'buying_gate_coupon'
                return True
        elif self.s.coordinator.move_to(role, {trip[2]}, 'gate_supply', name):
            self.state['status'] = 'fetching_gate_coupon'
            return True
        return False

    def required_inside(self):
        roles = self.turn.workers() if self.s.guard.full_time else (self.role(),)
        return [r for r in roles if r is not None
                and r.unit_id != self.memory.raid_scouts.get('worker_id')]

    def can_seal(self, role):
        seal_now = self.closing() or (self.turn.day == 1 and self.turn.daylight_left == 1)
        return bool(self.enabled and self.turn.is_day and seal_now
                    and role.unit_id == self.worker_id and 'stone' in role.backpack
                    and role.pos in self.inner_posts()
                    and all(w.pos in self.s.guard.inner_cells() for w in self.required_inside())
                    and self.pos not in self.turn.blocked(role) | self.plan.reserved)

    def hold(self, role, reason):
        self.state['status'] = reason
        self.s.coordinator.assign(role, 'day_gate', self.pos, role.pos)
        self.plan.used.add(role.unit_id)
        return True

    def worker(self, role):
        if not self.enabled or not self.turn.is_day:
            return False
        if self.pos in self.s.gap_guard.gaps:
            return False  # Preserve the worker/imp body relay for an occupied door.
        owner = role.unit_id == self.worker_id
        wall = self.wall()
        if wall is not None:
            if not owner:
                return False
            if self.closing():
                name = 'WallUpgradeVoucher1'
                if (wall.level == 1 and name in role.backpack and self.non_gate_upgrades_complete()
                        and role.pos in self.inner_posts()):
                    if self.plan.add(role.unit_id, {'action': 'use', 'name': name,
                                                  'targetPos': [self.pos.dump()]}):
                        self.state['status'] = 'upgrading_gate'
                        return True
                return False
            # Reopen the entrance every morning; this also lets a stocked
            # repairer reach shops and prevents permanent trapping after dusk.
            command = {'action': 'remove', 'targetPos': [self.pos.dump()]}
            if self.s.interact(role, self.pos, command):
                self.state['status'] = 'opening' if self.plan.commands.get(str(role.unit_id), {}).get('action') == 'remove' else 'approaching_entrance'
                return True
            return False
        ignored = self.s.gap_guard.gaps
        if owner and self.other_ready(ignored) and 'stone' not in role.backpack:
            if self.s.mine(role, need_stone=True):
                self.state['status'] = 'collecting_seal_stone'
                return True
            return False
        if self.turn.day == 1 and self.can_seal(role):
            # Only an already present builder may seal on R70. No return move
            # or planned future arrival is treated as somebody being inside.
            if self.plan.add(role.unit_id, build_command(self.pos, 'wall')):
                self.s.coordinator.assign(role, 'build:wall', self.pos, role.pos)
                self.state['status'] = 'sealing'
                return True
        if not self.closing():
            if owner and 'stone' in role.backpack and self.prepare_coupon(role):
                return True
            return False
        required = self.required_inside()
        if not any(w.unit_id == role.unit_id for w in required):
            return False
        if not owner:
            posts = self.inner_posts()
            entry_lane = posts | {p for post in posts for p in self.s.guard.inner_cells()
                                  if distance(p, post) == 1}
            goals = self.s.guard.inner_cells() - entry_lane
            if role.pos in goals:
                return False
            self.state['status'] = 'returning_teammate'
            if self.s.coordinator.move_to(role, goals, 'gate_return', self.pos, allow_risk=True):
                return True
            return self.hold(role, 'waiting_for_entry')
        posts = self.inner_posts()
        # The only inside entrance neighbour must remain free until the other
        # guard passes. Holding on it would recreate a one-worker deadlock.
        entry_lane = posts | {p for post in posts for p in self.s.guard.inner_cells()
                              if distance(p, post) == 1}
        waiting = [w for w in required if w.unit_id != role.unit_id
                   and (w.pos not in self.s.guard.inner_cells() or w.pos in entry_lane)]
        if waiting and role.pos in self.s.guard.inner_cells():
            base = self.turn.station()
            relief = Pos(base.pos.x + (-1 if self.s.settings.mirrored_layout(self.turn) else 2),
                         base.pos.y + 1)
            if role.pos != relief and self.s.coordinator.move_to(role, {relief}, 'gate_clear', self.pos, allow_risk=True):
                self.state['status'] = 'clearing_entry_lane'
                return True
            return self.hold(role, 'waiting_for_teammate_inside')
        if role.pos not in posts:
            self.state['status'] = 'returning_to_seal'
            if self.s.coordinator.move_to(role, posts, 'gate_close', self.pos, allow_risk=True):
                return True
            return self.hold(role, 'seal_route_blocked')
        if self.can_seal(role):
            if self.plan.add(role.unit_id, build_command(self.pos, 'wall')):
                self.s.coordinator.assign(role, 'build:wall', self.pos, role.pos)
                self.state['status'] = 'sealing'
                return True
        return self.hold(role, 'waiting_to_seal')

    def diagnostic(self):
        role = self.role()
        sites = set(self.s.settings.build_cells(self.turn, 'wall'))
        return dict(self.state, closing=self.closing(), wall_present=self.wall() is not None,
                    controlled_open=self.wall() is None and self.day_ready(self.s.gap_guard.gaps),
                    construction_ready=self.day_ready(self.s.gap_guard.gaps),
                    dispatch_ready=self.dispatch_ready(self.s.gap_guard.gaps),
                    all_planned_walls_present=bool(sites and sites <= {w.pos for w in self.turn.walls()}),
                    non_gate_upgrades_done=self.non_gate_upgrades_complete(),
                    stone_held=role.backpack.count('stone') if role else 0,
                    coupon_held=role.backpack.count('WallUpgradeVoucher1') if role else 0)
