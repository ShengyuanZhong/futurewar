"""Observed first-day closure, a level-two rocket and a stocked home repairer."""
from dataclasses import replace
from collections import Counter, deque
from .grid import Routes, adjacent_cells
from .protocol import MINERALS, WORKER, Pos, collect_command, distance


VOUCHER = 'WeaponUpgradeVoucher1'
FIXER = 'WallFixer'


class FirstNightDefense:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.settings = strategy.settings
        self.state = self.memory.first_night_defense
        self.return_cost_cache = {}
        self.enabled = bool(self.settings.enable_first_night_defense and self.turn.day == 1
                            and self.turn.station())
        self.worker_id = None
        if self.enabled:
            workers = self.turn.workers()
            alive = {w.unit_id for w in workers}
            # Only read memory here: BossRaid and RaidScouts do not exist yet.
            preferences = (self.s.gap_guard.worker_id,
                           self.memory.raid_scouts.get('home_worker_id'), self.state.get('worker_id'))
            self.worker_id = next((uid for uid in preferences if uid in alive), None)
            if self.worker_id is None and workers:
                self.worker_id = min(workers,key=lambda w:(-w.backpack.count(FIXER),w.unit_id)).unit_id
            if self.worker_id is not None:
                self.state['worker_id'] = self.worker_id
            self.state['permanent_plan'] = [p.dump() for p in self.settings.build_cells(self.turn,'wall')]
        self.state.update(round=self.turn.round_no,enabled=self.enabled)

    def guard_role(self):
        return next((w for w in self.turn.workers() if w.unit_id == self.worker_id),None)

    def closed(self):
        """Physical walls only. A body guard does not turn a gap into a building."""
        if not self.enabled or len(self.turn.weapons()) < 3:
            return False
        permanent = set(self.settings.build_cells(self.turn,'wall'))
        if not permanent:
            return False
        return permanent <= {w.pos for w in self.turn.walls()}

    def construction_ready(self):
        return self.closed() or (self.enabled and self.s.gap_guard.other_walls_ready())

    def stock_target(self, role=None):
        role = role or self.guard_role()
        return min(self.settings.first_night_repair_stock,role.capacity) if role else 0

    def planned_inventory(self, role=None):
        roles = (role,) if role is not None else self.turn.controllable()
        inventory = {VOUCHER:0,FIXER:0}
        for actor in roles:
            for name in inventory:
                inventory[name] += actor.backpack.count(name)
            command = self.plan.commands.get(str(actor.unit_id),{})
            name = command.get('name')
            if name in inventory:
                if command.get('action') == 'buy':
                    inventory[name] += command.get('num',1)
                elif command.get('action') == 'use':
                    inventory[name] -= 1
        return inventory

    def weapon_ready(self, planned=False):
        rockets = [w for w in self.turn.weapons() if w.kind == 'rocket']
        if any(w.level >= 2 for w in rockets):
            return True
        if planned:
            cells = {w.pos for w in rockets if w.level == 1}
            return any(c.get('action') == 'use' and c.get('name') == VOUCHER
                       and any(p.dump() in c.get('targetPos',[]) for p in cells)
                       for c in self.plan.commands.values())
        return False

    def reserve_gold(self):
        if not self.enabled:
            return 0
        worker = self.guard_role()
        if worker is None:
            return 0
        stock = self.planned_inventory(worker)[FIXER] if worker else 0
        kits = max(0,self.stock_target(worker)-stock)
        voucher = int(not self.weapon_ready(planned=True) and not self.planned_inventory()[VOUCHER])
        return (kits*self.turn.shop_prices.get(FIXER,0)
                + voucher*self.turn.shop_prices.get(VOUCHER,0))

    def prepared(self):
        role = self.guard_role()
        return bool(self.construction_ready() and role and self.weapon_ready()
                    and role.backpack.count(FIXER) >= self.stock_target(role))

    def needs_supply(self, role):
        return bool(self.enabled and self.turn.is_day and role.unit_id == self.worker_id
                    and self.construction_ready() and not self.prepared())

    def home_cells(self):
        return self.s.guard.inner_cells()

    def trip(self, role, goals, interactions=1):
        """Budget outbound, interactions and an actual return path, not distance."""
        route = self.s.route(role)
        homes = self.home_cells()
        if not homes:
            return None
        # Daylight normally has no robot risk. One reverse BFS provides actual
        # home distances for all mine/shop posts, avoiding a full BFS per ore.
        key = (role.unit_id,frozenset(self.s.movement_reserved(role)))
        if not self.s.danger and key not in self.return_cost_cache:
            blocked = self.turn.blocked(role) | key[1]
            seeds = {p for p in homes if self.turn.land(p) and (p not in blocked or p == role.pos)}
            costs,queue = {p:0 for p in seeds},deque(seeds)
            while queue:
                here = queue.popleft()
                for there in here.neighbours():
                    if not self.turn.land(there) or there in blocked or there in costs:
                        continue
                    costs[there] = costs[here]+1
                    queue.append(there)
            self.return_cost_cache[key] = costs
        options = []
        for post in (set(goals)-self.s.coordinator.claimed_goals(role)) & set(route.cost):
            lower = route.cost[post]+interactions+min(distance(post,p) for p in homes)+self.settings.return_margin
            if lower > self.turn.daylight_left:
                continue
            if not self.s.danger:
                returning = self.return_cost_cache[key].get(post)
            else:
                cache_key = (key,post)
                if cache_key not in self.return_cost_cache:
                    moved = replace(role,pos=post)
                    simulated = replace(self.turn,ours=tuple(moved if u.unit_id == role.unit_id else u
                                                           for u in self.turn.ours))
                    back = Routes(simulated,moved,self.s.movement_reserved(role),self.s.danger)
                    self.return_cost_cache[cache_key] = back.cost.get(back.nearest(homes))
                returning = self.return_cost_cache[cache_key]
            if returning is None:
                continue
            total = route.cost[post]+interactions+returning+self.settings.return_margin
            if total <= self.turn.daylight_left:
                options.append((total,route.cost[post],post))
        return min(options) if options else None

    def hold(self, role, reason):
        self.state['status'] = reason
        self.s.coordinator.assign(role,'first_night_guard',self.turn.station().pos,role.pos)
        self.plan.used.add(role.unit_id)
        return True

    def return_home(self, role, reason='returning'):
        self.state['status'] = reason
        if self.s.guard.nighttime(role,urgent_only=True):
            return True
        if self.s.gap_guard.active_role(role):
            self.state['status'] = 'gap_guard'
            return self.s.gap_guard.move_or_hold(role,self.s.gap_guard.posts(),'gap_wait')
        self.s.guard.nighttime(role)
        # A failed path or already holding must not fall through to distant mining.
        self.plan.used.add(role.unit_id)
        return True

    def deliver_voucher(self, role):
        if self.weapon_ready() or VOUCHER not in role.backpack:
            return False
        candidates = [w for w in self.turn.weapons() if w.kind == 'rocket' and w.level == 1
                      and w.unit_id not in self.plan.upgrade_targets | self.s.maintenance_claims]
        candidates.sort(key=lambda w:w.unit_id)
        for weapon in candidates:
            goals = adjacent_cells(self.turn,[weapon.pos])
            if not self.turn.is_day:
                goals &= self.home_cells()
                if role.pos not in self.home_cells():
                    continue
            elif self.trip(role,goals) is None:
                continue
            if self.plan.near(role,[weapon.pos]):
                if self.plan.add(role.unit_id,{'action':'use','name':VOUCHER,'targetPos':[weapon.pos.dump()]}):
                    self.s.maintenance_claims.add(weapon.unit_id)
                    self.s.coordinator.assign(role,'use:'+VOUCHER,weapon.pos,role.pos)
                    self.state['status'] = 'upgrading'
                    return True
            if self.s.coordinator.move_to(role,goals,'use:'+VOUCHER,weapon.pos,
                    allowed=self.home_cells() if not self.turn.is_day else None,allow_risk=True):
                self.s.maintenance_claims.add(weapon.unit_id)
                self.state['status'] = 'delivering_voucher'
                return True
        return False

    def supply(self, role):
        shops = [p for p,k in self.turn.zones.items() if k == 'weaponShop']
        posts = adjacent_cells(self.turn,shops)
        inventory = self.planned_inventory()
        needed = []
        missing = max(0,self.stock_target(role)-self.planned_inventory(role)[FIXER])
        if missing:
            needed.append((FIXER,missing))
        if not self.weapon_ready(planned=True) and inventory[VOUCHER] <= 0:
            needed.append((VOUCHER,1))
        interactions = len(needed)+int(not self.weapon_ready(planned=True))
        trip = self.trip(role,posts,interactions=interactions)
        if not shops or not needed or trip is None:
            return False
        free = max(0,role.capacity-len(role.backpack))
        construction = max(0,3-self.plan.tower_count)*25
        boss = getattr(self.s,'boss_raid',None)
        construction += boss.budget_reserve() if boss else 0
        for name,count in needed:
            price = self.turn.shop_prices.get(name)
            if price is None:
                continue
            count = min(count,free,count if not price else max(0,self.plan.gold-construction)//price)
            if count <= 0:
                continue
            if self.plan.near_zone(role,'weaponShop'):
                if self.plan.add(role.unit_id,{'action':'buy','name':name,'num':count}):
                    self.s.coordinator.assign(role,'first_night_supply',name,role.pos)
                    self.state['status'] = 'buying_'+name
                    return True
            elif self.s.coordinator.move_to(role,{trip[2]},'first_night_supply',name):
                self.state['status'] = 'fetching_'+name
                return True
        return False

    def sell(self, role):
        vendors = [p for p,k in self.turn.zones.items() if k == 'vendor']
        trip = self.trip(role,adjacent_cells(self.turn,vendors))
        if trip is None:
            return False
        keep_stone = bool(self.s.gap_guard.gaps)
        if self.plan.near_zone(role,'vendor'):
            return self.s.sell(role,keep_stone=keep_stone)
        minerals = Counter(name for name in role.backpack if name in MINERALS and name in self.turn.vendor_prices
                           and (name != 'stone' or not keep_stone))
        if not minerals or (not role.backpack_full and sum(minerals.values()) < self.settings.sell_batch):
            return False
        return self.s.coordinator.move_to(role,{trip[2]},'sell',tuple(vendors))

    def mine(self, role):
        if role.backpack_full:
            return False
        candidates = []
        job = self.s.coordinator.job(role)
        for target,kind in self.turn.zones.items():
            if (kind not in MINERALS or self.memory.failed_mines.get(f'{target.x},{target.y}',0)>self.turn.round_no
                    or any(c['name']==kind and c['startDay']<=self.turn.day<=c['endDay']
                           for c in self.memory.mine_closures)):
                continue
            goals = adjacent_cells(self.turn,[target])
            trip = self.trip(role,goals)
            if trip is None or self.turn.vendor_prices.get(kind,0) <= 0:
                continue
            value = self.turn.vendor_prices[kind]/(trip[1]+2)
            continuing = job.get('kind','').startswith('collect:') and job.get('target') == target
            candidates.append((continuing,not self.s.coordinator.target_owned(role,target),value,-trip[0],target,trip[2]))
        for _,_,_,_,target,post in sorted(candidates,reverse=True):
            kind = self.turn.zones[target]
            if role.pos == post and self.plan.add(role.unit_id,collect_command(target)):
                self.s.coordinator.assign(role,'collect:'+kind,target,role.pos)
                self.state['status'] = 'bounded_mining'
                return True
            if self.s.coordinator.move_to(role,{post},'collect:'+kind,target):
                self.state['status'] = 'bounded_mining'
                return True
        return False

    def worker(self, role):
        if not self.enabled or role.kind != WORKER or role.unit_id != self.worker_id:
            return False
        if not self.turn.is_day:
            if self.s.guard.nighttime(role,urgent_only=True) or self.on_site_upgrade(role):
                self.state['status'] = 'night_repair_or_upgrade'
                return True
            return self.return_home(role,'night_guard')
        if not self.construction_ready():
            self.state['status'] = 'waiting_for_closure'
            return False
        if self.s.guard.nighttime(role,urgent_only=True):
            self.state['status'] = 'urgent_repair'
            return True
        route = self.s.route(role)
        home = route.nearest(self.home_cells())
        if home is None or self.turn.daylight_left <= route.cost[home]+self.settings.return_margin:
            return self.return_home(role)
        # Stock the kit batch at the same shop stop before delivering the coupon.
        if self.supply(role) or self.deliver_voucher(role):
            return True
        if self.prepared():
            # Continue the established focused rocket-to-L3 strategy after the
            # minimum first-night loadout, with the same deadline for delivery.
            if self.s.consume(role,allow_travel=False):
                self.state['status'] = 'ordinary_upgrade'
                return True
            carried = [w for w in self.s.upgrade_candidates() if self.s.upgrade_name(w) in role.backpack]
            goals = {p for w in carried for p in adjacent_cells(self.turn,self.turn.footprint(w))}
            if self.trip(role,goals) is not None and self.s.consume(role):
                self.state['status'] = 'ordinary_upgrade_delivery'
                return True
            shops = [p for p,k in self.turn.zones.items() if k == 'weaponShop']
            if self.trip(role,adjacent_cells(self.turn,shops),interactions=2) is not None and self.s.buy_upgrade(role):
                self.state['status'] = 'ordinary_upgrade_purchase'
                return True
        if self.sell(role) or self.mine(role):
            return True
        return self.return_home(role,'prepared_guard' if self.prepared() else 'waiting_for_supply')

    def on_site_upgrade(self, role):
        # WallGuard is normally dormant before day three. Treat this worker as
        # its guard only for consume(), so noncritical walls cannot drain the
        # first-night minimum kits through the normal courier repair branch.
        previous = self.s.guard.worker_id
        self.s.guard.worker_id = self.worker_id
        try:
            return self.s.guard.on_site_upgrade(role)
        finally:
            self.s.guard.worker_id = previous

    def diagnostic(self):
        role = self.guard_role()
        base = next((u for u in self.turn.ours if u.kind == 'station'),None)
        walls = [w for w in self.turn.ours if w.kind == 'wall']
        standing = {w.pos for w in walls if w.health > 0}
        permanent = set(self.settings.build_cells(self.turn,'wall'))
        if not permanent:
            permanent = {Pos.load(p) for p in self.state.get('permanent_plan',())}
        def building(unit):
            return {'id':unit.unit_id,'pos':unit.pos.dump(),'hp':unit.health,'level':unit.level}
        snapshot = dict(self.state)
        snapshot['permanent_plan'] = snapshot.get('permanent_plan',[])[:32]
        return dict(snapshot,enabled=self.enabled,worker_id=self.worker_id,closed=self.closed(),
                    construction_ready=self.construction_ready(),
                    prepared=self.prepared(),reserve_gold=self.reserve_gold(),weapon_ready=self.weapon_ready(),
                    stock_target=self.stock_target(role),stock_held=role.backpack.count(FIXER) if role else 0,
                    station=building(base) if base else None,walls=[building(w) for w in walls[:32]],
                    guard=building(role) if role else None,
                    walls_count=len(walls),walls_omitted=max(0,len(walls)-32),
                    permanent_missing=[p.dump() for p in sorted(permanent-standing)[:32]],
                    permanent_missing_count=len(permanent-standing),
                    occupied_gaps=[p.dump() for p in sorted(self.s.gap_guard.gaps)[:32]])
