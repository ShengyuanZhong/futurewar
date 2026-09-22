"""Night repair duty; after all target upgrades, both workers guard and resupply."""
from .protocol import Pos, distance


class WallGuard:
    def __init__(self, strategy):
        self.strategy = strategy
        self.turn, self.plan = strategy.turn, strategy.plan
        self.settings, self.memory = strategy.settings, strategy.memory
        self.worker_id = None
        complete = strategy.upgrades_complete()
        self.memory.dual_repair_active = self.memory.dual_repair_active or complete
        # A night breach does not turn the second repairer into a fleeing miner.
        self.full_time = complete or (self.memory.dual_repair_active and not self.turn.is_day)
        self.stock_targets = {}
        if (not self.full_time and self.turn.day < self.settings.repair_start_day) or not self.turn.station():
            return
        workers = self.turn.workers()
        if not workers:
            return
        if self.memory.repair_worker_id not in {w.unit_id for w in workers}:
            # Prefer already stocked workers, then stable IDs; do not swap every round.
            self.memory.repair_worker_id = min(workers, key=lambda w: (-w.backpack.count("WallFixer"), w.unit_id)).unit_id
        self.worker_id = self.memory.repair_worker_id
        if self.full_time:
            self.stock_targets = self.final_stock_targets(workers)
            supplier = next((w for w in workers if w.unit_id == self.memory.repair_supplier_id), None)
            # Finish the return trip before sending the other worker out.
            if supplier is None or (supplier.pos in self.inner_cells() and self.stock_missing(supplier) == 0):
                candidates = [w for w in workers if self.stock_missing(w) > 0]
                supplier = min(candidates, key=lambda w: (w.backpack.count('WallFixer'), w.unit_id), default=None)
                self.memory.repair_supplier_id = supplier.unit_id if supplier else None
        else:
            self.memory.repair_supplier_id = None

    def is_guard(self, role) -> bool:
        return role.kind == 'worker' and (self.full_time or role.unit_id == self.worker_id)

    def final_stock_targets(self, workers) -> dict[int, int]:
        """Distribute affordable kits across bags, respecting individual capacity."""
        targets = {w.unit_id: w.backpack.count('WallFixer') for w in workers}
        capacities = {w.unit_id: targets[w.unit_id] + max(0, w.capacity-len(w.backpack)) for w in workers}
        if 'WallFixer' not in self.turn.shop_prices:
            return targets
        price = self.turn.shop_prices['WallFixer']
        free = sum(capacities[i]-targets[i] for i in targets)
        demands = {w.unit_id:self.daily_stock(w) for w in workers}
        budget = min(free, self.plan.gold // price) if price else free
        for _ in range(budget):
            uid = min((i for i in targets if targets[i] < capacities[i]),
                      key=lambda i: (min(0,targets[i]-demands[i]),targets[i],i))
            targets[uid] += 1
        return targets

    def inner_cells(self) -> set[Pos]:
        base = self.turn.station()
        if not base:
            return set()
        offsets = [Pos(x, y) for y in (1, -2) for x in range(3)] + [Pos(2, 0), Pos(2, -1)]
        mirrored = self.settings.mirrored_layout(self.turn)
        cells = {Pos(base.pos.x + (1 - p.x if mirrored else p.x), base.pos.y + p.y) for p in offsets}
        excluded = set(self.settings.build_cells(self.turn, "wall")) | set(self.strategy.layout.tower_sites)
        excluded.add(self.strategy.layout.operator_pos)
        return {p for p in cells if self.turn.land(p) and p not in excluded}

    def stock_missing(self, worker=None) -> int:
        worker = worker or next((w for w in self.turn.workers() if w.unit_id == self.worker_id), None)
        if worker is None:
            return 0
        held = worker.backpack.count("WallFixer")
        command = self.plan.commands.get(str(worker.unit_id), {})
        if command.get("name") == "WallFixer":
            held += command.get("num", 1) if command.get("action") == "buy" else -1 if command.get("action") == "use" else 0
        target = self.stock_targets.get(worker.unit_id, held) if self.full_time else self.daily_stock(worker)
        return max(0, target - held)

    def daily_stock(self, worker):
        growth = max(0,self.turn.day-self.settings.repair_start_day)*self.settings.repair_stock_per_day
        observed = self.memory.repair_usage_previous.get(worker.unit_id,0)
        return min(worker.capacity,max(self.settings.repair_stock+growth,observed+2 if observed else 0))

    def home(self, role):
        cells = self.inner_cells()
        base = self.turn.station()
        if not cells or not base:
            return None
        workers = sorted(self.turn.workers(),key=lambda w:w.unit_id)
        upper = not self.full_time or role.unit_id == workers[0].unit_id
        y = base.pos.y if upper else base.pos.y-1
        x = base.pos.x + (-1 if self.settings.mirrored_layout(self.turn) else 2)
        return min(cells,key=lambda p:(distance(p,Pos(x,y)),p))

    def owns_wall(self, role, wall):
        if not self.full_time:
            return True
        workers = sorted(self.turn.workers(),key=lambda w:w.unit_id)
        base = self.turn.station()
        if len(workers)<2 or not base:
            return True
        owner = workers[0] if wall.pos.y >= base.pos.y else workers[1]
        return (owner.unit_id == role.unit_id or 'WallFixer' not in owner.backpack
                or owner.pos not in self.inner_cells())

    def budget_reserve(self) -> int:
        return self.stock_missing() * self.turn.shop_prices.get("WallFixer", 0)

    def daytime(self, role) -> bool:
        """Return before dusk; otherwise replenish stock and resume normal work."""
        if self.full_time:
            self.final_daytime(role)
            return True
        if role.unit_id != self.worker_id:
            return False
        s = self.strategy
        cells = self.inner_cells()
        route = s.route(role)
        target = route.nearest(cells)
        if target is None:
            route = s.coordinator.diagnostic_route(role)
            target = route.nearest(cells)
            if target is None:
                return self.turn.daylight_left <= self.settings.return_margin
        if self.turn.daylight_left <= route.cost[target] + self.settings.return_margin:
            s.coordinator.move_to(role,cells,'return_guard',self.home(role),allow_risk=True)
            return True
        missing = self.stock_missing()
        shops = [p for p, k in self.turn.zones.items() if k == "weaponShop"]
        if not missing or "WallFixer" not in self.turn.shop_prices or not shops:
            return False
        price = self.turn.shop_prices["WallFixer"]
        reserve = max(0, 3 - self.plan.tower_count) * 25 if self.settings.build_cells(self.turn, "rocket") else 0
        count = min(missing, role.capacity - len(role.backpack), missing if price == 0 else max(0, self.plan.gold - reserve) // price)
        if count <= 0:
            return s.sell(role, keep_stone=bool(s.missing_walls()))
        if self.plan.near_zone(role, "weaponShop"):
            return self.plan.add(role.unit_id, {"action": "buy", "name": "WallFixer", "num": count})
        # Include the trip back from the shop, plus the purchasing turn.
        return_cost = min(max(0, distance(shop, p) - 1) for shop in shops for p in cells)
        if s.cost(role, shops) + 1 + return_cost + self.settings.return_margin >= self.turn.daylight_left:
            s.coordinator.move_to(role,cells,'return_guard',self.home(role),allow_risk=True)
            return True
        return s.travel(role, shops, 'repair_supply')

    def final_daytime(self, role) -> None:
        """Repair first; only one supplier may leave, and only with return time."""
        s = self.strategy
        if self.nighttime(role, urgent_only=True):
            return
        missing = self.stock_missing(role)
        if role.unit_id == self.memory.repair_supplier_id and missing:
            shops = [p for p,k in self.turn.zones.items() if k == 'weaponShop']
            cells = self.inner_cells()
            if shops and cells:
                return_cost = min(max(0, distance(shop,p)-1) for shop in shops for p in cells)
                if s.cost(role, shops) + 1 + return_cost + self.settings.return_margin < self.turn.daylight_left:
                    if self.plan.near_zone(role, 'weaponShop'):
                        price = self.turn.shop_prices['WallFixer']
                        count = min(missing, role.capacity-len(role.backpack), self.plan.gold//price if price else missing)
                        if count > 0 and self.plan.add(role.unit_id, {'action':'buy','name':'WallFixer','num':count}):
                            return
                    elif s.travel(role, shops, 'repair_supply'):
                        return
        self.nighttime(role)

    def nighttime(self, role, urgent_only=False) -> bool:
        s = self.strategy
        cells = self.inner_cells()
        # Once inside, all subsequent patrol paths stay inside, even with breaches.
        route = s.route(role, allowed=cells if role.pos in cells else None)
        reachable = cells & set(route.cost)
        if not reachable:
            # Stay assigned to the wall: a blocked entrance calls for yielding,
            # never an unbounded escape to distant zero-risk map cells.
            return False if urgent_only else s.coordinator.move_to(role,cells,'return_guard',self.home(role),allow_risk=True)
        if "WallFixer" in role.backpack:
            critical = [w for w in self.turn.walls()
                        if w.health * 100 < s.building_max_health(w) * self.settings.repair_threshold_percent
                        and self.owns_wall(role,w)
                        and w.unit_id not in self.plan.upgrade_targets | s.maintenance_claims]
            critical.sort(key=lambda w: (w.health / s.building_max_health(w), s.wall_depth(w), w.unit_id))
            for wall in critical:
                goals = {p for p in reachable if distance(p, wall.pos) == 1}
                if role.pos in goals:
                    if self.plan.add(role.unit_id, {"action": "use", "name": "WallFixer", "targetPos": [wall.pos.dump()]}):
                        s.coordinator.assign(role,'repair',wall.pos,role.pos)
                        s.maintenance_claims.add(wall.unit_id)
                        return True
                if s.coordinator.move_to(role,{p for p in cells if distance(p,wall.pos)==1},'repair',wall.pos,
                                         allowed=cells if role.pos in cells else None,allow_risk=True):
                    s.maintenance_claims.add(wall.unit_id)
                    return True
        if urgent_only:
            return False
        # No urgent repair / no kits: hold inside; relocate only to a safer lane cell.
        home = self.home(role)
        if home is not None and not s.danger.get(home,0):
            goals = {home}
        elif role.pos in reachable:
            safer = {p for p in reachable if s.danger.get(p, 0) < s.danger.get(role.pos, 0)}
            goals = safer or {role.pos}
        else:
            goals = reachable
        return s.coordinator.move_to(role,goals,'guard_post',home,
                                     allowed=cells if role.pos in cells else None,allow_risk=True)
