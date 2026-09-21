"""Deterministic baseline strategy, separated from transport and LLM execution."""
from collections import Counter
import time
from .actions import SUMMON_ITEMS, ActionPlan
from .combat import choose_targets
from .construction import select_defense_layout
from .grid import Routes, adjacent_cells
from .worker_safety import robot_danger
from .wall_guard import WallGuard
from .protocol import (MINERALS, PIONEER, TOWER_TYPES, Pos, Turn, Unit,
                       attack_command, build_command, collect_command, distance, move_command)


class Strategy:
    def __init__(self, turn: Turn, plan: ActionPlan, memory):
        self.turn, self.plan, self.memory = turn, plan, memory
        self.settings = plan.settings
        self.routes: dict[tuple, Routes] = {}
        self.goals: set[Pos] = set()
        self.maintenance_claims: set[int] = set()
        self.deadline = float("inf")
        self.layout = select_defense_layout(turn, self.settings, memory.defense_layout)
        memory.defense_layout = self.layout
        self.danger = robot_danger(turn)
        self.guard = WallGuard(self)

    def route(self, role: Unit, allowed: set[Pos] | None = None) -> Routes:
        reserved = set(self.plan.reserved)
        # Planned tower cells must stay clear even before the buildings are observed.
        reserved.update(self.layout.tower_sites)
        if role.kind != PIONEER and self.layout.operator_pos is not None:
            reserved.add(self.layout.operator_pos)
        key = (role.unit_id, frozenset(reserved), None if allowed is None else frozenset(allowed))
        if key not in self.routes:
            self.routes[key] = Routes(self.turn, role, reserved,
                                      self.danger if role.kind == "worker" else None, allowed)
        return self.routes[key]

    def travel(self, role: Unit, cells) -> bool:
        route = self.route(role)
        goal = route.nearest(adjacent_cells(self.turn, cells))
        if role.kind == "worker" and not self.turn.is_day and route.exposure.get(goal, 0) > 0:
            return False
        step = route.step([goal]) if goal is not None else None
        return step is not None and self.plan.add(role.unit_id, move_command(step))

    def cost(self, role: Unit, cells) -> int:
        route = self.route(role)
        return route.cost.get(route.nearest(adjacent_cells(self.turn, cells)), 10_000)

    def interact(self, role: Unit, target: Pos, command: dict, footprint=None) -> bool:
        cells = footprint or [target]
        if self.plan.near(role, cells):
            return self.plan.add(role.unit_id, command)
        return self.travel(role, cells)

    def run(self) -> None:
        # Resolve the pioneer first, so workers never claim its next step or control cell.
        available = sorted(self.turn.controllable(), key=lambda r: (r.kind != PIONEER, r.unit_id != self.guard.worker_id, r.unit_id))
        self.opening_stage()
        for role in available:
            if role.unit_id in self.plan.used:
                continue
            if time.monotonic() >= self.deadline:
                break
            maximum = 200 if role.kind == PIONEER else 220
            if role.health <= maximum // 2 and "Medicine" in role.backpack:
                self.plan.add(role.unit_id, {"action": "use", "name": "Medicine"})
                continue
            if role.kind == PIONEER:
                if self.pioneer_should_defend(role):
                    self.operate_weapons(role)
                    continue
                if self.clear_build_cell(role):
                    continue
                # Preserve the opening budget; tasks can earn money without spending it.
                if self.opening_stage() in ("complete", "unconfigured"):
                    if self.consume(role, allow_travel=False) or self.treasure(role):
                        continue
                if self.turn.is_day and (self.task(role) or self.sell(role)):
                    continue
                self.move_to_control(role)
            elif not self.turn.is_day:
                if role.unit_id == self.guard.worker_id:
                    self.guard.nighttime(role)
                else:
                    self.night_worker(role)
            else:
                if self.evade_worker(role):
                    continue
                if not self.clear_build_cell(role) and not self.opening_worker(role):
                    if not self.guard.daytime(role):
                        self.worker(role)

    def control_position(self, role: Unit) -> Pos | None:
        weapons = self.turn.weapons()
        if not weapons:
            return self.layout.operator_pos
        route = self.route(role)
        cells = adjacent_cells(self.turn, [w.pos for w in weapons])
        cells -= set(self.settings.build_cells(self.turn, "wall"))
        cells -= set(self.layout.tower_sites)
        reachable = [p for p in cells if p in route.cost]
        if not reachable:
            return None
        return min(reachable, key=lambda p: (
            -sum(distance(p, w.pos) <= 1 for w in weapons),
            p != self.layout.operator_pos, route.cost[p], p))

    def pioneer_should_defend(self, role: Unit) -> bool:
        if not self.turn.weapons():
            return False
        target = self.control_position(role)
        cost = self.route(role).cost.get(target, 10_000)
        return not self.turn.is_day or self.turn.daylight_left <= cost + self.settings.return_margin

    def move_to_control(self, role: Unit) -> bool:
        target = self.control_position(role)
        step = self.route(role).step([target]) if target is not None else None
        return step is not None and self.plan.add(role.unit_id, move_command(step))

    def operate_weapons(self, role: Unit) -> bool:
        if not self.turn.is_day:
            health = {r.robot_id: r.health for r in self.turn.robots}
            choices = []
            for tower in self.turn.weapons():
                if tower.cooldown != 0 or distance(role.pos, tower.pos) > 1:
                    continue
                predicted = dict(health)
                targets = choose_targets(self.turn, tower, predicted, self.deadline)
                if targets:
                    value = sum(health[rid] - remaining for rid, remaining in predicted.items())
                    choices.append((value, -tower.unit_id, tower, targets))
            if choices:
                _, _, tower, targets = max(choices, key=lambda entry: entry[:2])
                return self.plan.add(tower.unit_id, attack_command(role.unit_id, targets))
            # With separated towers, seek an accessible ready weapon with a target.
            ready = []
            for tower in self.turn.weapons():
                if tower.cooldown == 0 and choose_targets(self.turn, tower, dict(health), self.deadline):
                    ready.append(tower.pos)
            if ready and self.travel(role, ready):
                return True
        return self.move_to_control(role)

    def missing_walls(self) -> list[Pos]:
        standing = {w.pos for w in self.turn.walls()}
        return [p for p in self.settings.build_cells(self.turn, "wall") if p not in standing]

    def stone_targets(self) -> dict[int, int]:
        workers = self.turn.workers()
        remaining = len(self.missing_walls())
        targets = {}
        capacity = {}
        for role in workers:
            held = role.backpack.count("stone")
            targets[role.unit_id] = min(held, remaining)
            remaining -= targets[role.unit_id]
            capacity[role.unit_id] = max(held, role.capacity - len(role.backpack) + held)
        while remaining:
            eligible = [uid for uid, quota in targets.items() if quota < capacity[uid]]
            if not eligible:
                break
            uid = min(eligible, key=lambda key: (targets[key], key))
            targets[uid] += 1
            remaining -= 1
        return targets

    def opening_stage(self) -> str:
        if self.memory.opening_complete:
            return "complete"
        if not self.settings.build_cells(self.turn, "rocket"):
            return "unconfigured"
        if len(self.turn.weapons()) < 3:
            return "towers"
        if not self.missing_walls():
            self.memory.opening_complete = True
            return "complete"
        quota = self.stone_targets()
        if any(w.backpack.count("stone") < quota[w.unit_id] for w in self.turn.workers()):
            return "stockpile"
        return "walls"

    def clear_build_cell(self, role: Unit) -> bool:
        sites = set(self.layout.tower_sites) | set(self.missing_walls())
        if role.kind != PIONEER and self.layout.operator_pos is not None:
            sites.add(self.layout.operator_pos)
        if role.pos not in sites:
            return False
        blocked = self.turn.blocked(role) | self.plan.reserved | sites
        for target in sorted(role.pos.neighbours(), key=lambda p: (self.danger.get(p, 0) if role.kind == "worker" else 0, p)):
            if role.kind == "worker" and self.danger.get(target, 0) > self.danger.get(role.pos, 0):
                continue
            if self.turn.land(target) and target not in blocked:
                return self.plan.add(role.unit_id, move_command(target))
        return False

    def opening_worker(self, role: Unit) -> bool:
        stage = self.opening_stage()
        if stage in ("complete", "unconfigured"):
            return False
        if stage == "towers":
            if not self.build_weapon(role) and self.plan.gold < 25 and self.plan.tower_count < 3:
                if not self.sell(role):
                    self.mine(role)
            return True
        quota = self.stone_targets().get(role.unit_id, 0)
        if role.backpack.count("stone") < quota:
            if role.backpack_full:
                self.sell(role, keep_stone=True)
            else:
                self.mine(role, need_stone=True)
            return True
        if stage == "walls" and "stone" in role.backpack:
            self.build_wall(role)
        elif stage == "stockpile":
            # Carry a completed share back toward a wall while teammates finish mining.
            self.travel(role, self.missing_walls())
        elif role.backpack_full:
            self.sell(role, keep_stone=True)
        return True

    def night_worker(self, role: Unit) -> None:
        if self.evade_worker(role):
            return
        if self.clear_build_cell(role):
            return
        keep_stone = bool(self.missing_walls())
        quota = self.stone_targets().get(role.unit_id, 0) if keep_stone else 0
        need_stone = role.backpack.count("stone") < quota
        minerals = sum(i in MINERALS and (i != "stone" or not keep_stone) for i in role.backpack)
        if (role.backpack_full or minerals >= self.settings.sell_batch) and self.sell(role, keep_stone=keep_stone):
            return
        if not self.mine(role, need_stone=need_stone):
            # No safe mine: head to a safe reachable inner lane, otherwise wait.
            route = self.route(role)
            cells = {p for p in self.guard.inner_cells() if not self.danger.get(p, 0)
                     and route.exposure.get(p) == 0}
            step = route.step(cells)
            if step is not None:
                self.plan.add(role.unit_id, move_command(step))

    def evade_worker(self, role: Unit) -> bool:
        """Stop economic work in a threat zone; flee if a non-worsening step exists."""
        current = self.danger.get(role.pos, 0)
        if not current:
            return False
        route = self.route(role)
        safe = {p for p in route.cost if not self.danger.get(p, 0)}
        step = route.step(safe)
        if step is not None and self.danger.get(step, 0) <= current:
            self.plan.add(role.unit_id, move_command(step))
            return True
        neighbours = [p for p in role.pos.neighbours() if route.cost.get(p) == 1
                      and self.danger.get(p, 0) < current]
        if neighbours:
            target = min(neighbours, key=lambda p: (self.danger.get(p, 0), p))
            self.plan.add(role.unit_id, move_command(target))
        return True

    def build_wall(self, role: Unit) -> bool:
        walls = [p for p in self.missing_walls() if p not in self.turn.blocked(role)
                 and p not in self.plan.reserved and p not in self.goals and p != role.pos]
        for target in sorted(walls, key=lambda p: (self.cost(role, [p]), p)):
            if self.wall_keeps_exit(role, target) and self.interact(role, target, build_command(target, "wall")):
                self.goals.add(target)
                return True
        return False

    def consume(self, role: Unit, allow_travel: bool = True) -> bool:
        maximum = 200 if role.kind == PIONEER else 220
        if role.health <= maximum // 2 and "Medicine" in role.backpack:
            return self.plan.add(role.unit_id, {"action": "use", "name": "Medicine"})
        if not self.turn.is_day:
            for name in ("Bomb", "DizzyWeapon"):
                if name not in role.backpack:
                    continue
                robots = [r for r in self.turn.robots if r.health > 0 and (name == "Bomb" or r.abnormal_state != "dizzy")]
                candidates = {p for r in robots for p in (r.pos,) + r.pos.neighbours() if self.turn.in_bounds(p)}
                if candidates:
                    target = max(sorted(candidates), key=lambda p: sum(min(r.health, 100) if name == "Bomb" else 1 for r in robots if distance(r.pos, p) <= 1))
                    hit_count = sum(distance(r.pos, target) <= 1 for r in robots)
                    if hit_count >= 2:
                        return self.plan.add(role.unit_id, {"action": "use", "name": name, "targetPos": [target.dump()]})
        for name in sorted(set(role.backpack) & SUMMON_ITEMS):
            if self.plan.summon_used < 10:
                return self.plan.add(role.unit_id, {"action": "use", "name": name})
        # Purchase and use share one observed-state stage, regardless of bag order.
        candidates = self.upgrade_candidates()
        if candidates and candidates[0].kind == "wall":
            front = min(self.wall_depth(b) for b in candidates)
            candidates = [b for b in candidates if self.wall_depth(b) == front]
        candidates = [b for b in candidates if self.upgrade_name(b) in role.backpack]
        choices = [(self.upgrade_name(b), b) for b in sorted(candidates, key=lambda b: (
            b.kind != "rocket" if b.kind in TOWER_TYPES else False,
            b.health / self.building_max_health(b), self.cost(role, self.turn.footprint(b)), b.unit_id))]
        # An upgrade also heals the wall; only consider a carried fixer afterwards.
        if "WallFixer" in role.backpack and role.unit_id != self.guard.worker_id:
            repairs = [w for w in self.turn.walls() if w.health < self.building_max_health(w)]
            choices.extend(("WallFixer", w) for w in sorted(repairs, key=lambda w: (
                self.wall_depth(w), w.health / self.building_max_health(w), self.cost(role, [w.pos]), w.unit_id)))
        for name, building in choices:
            if building.unit_id in self.plan.upgrade_targets | self.maintenance_claims:
                continue
            if (not self.turn.is_day or not allow_travel) and not self.plan.near(role, self.turn.footprint(building)):
                continue
            if self.interact(role, building.pos, {"action": "use", "name": name, "targetPos": [building.pos.dump()]}, self.turn.footprint(building)):
                self.maintenance_claims.add(building.unit_id)
                return True
        return False

    def worker(self, role: Unit) -> None:
        if self.rebuild_wall(role) or self.consume(role) or self.build_weapon(role):
            return
        if self.sell(role, keep_stone=bool(self.missing_walls())) or self.buy_upgrade(role):
            return
        self.mine(role, need_stone=bool(self.missing_walls()) and "stone" not in role.backpack)

    def rebuild_wall(self, role: Unit) -> bool:
        """Repair a breach before economy; only build from actual observed stone."""
        if not self.turn.is_day or not self.missing_walls():
            return False
        if "stone" in role.backpack and self.build_wall(role):
            return True
        quota = self.stone_targets().get(role.unit_id, 0)
        if role.backpack.count("stone") < quota:
            if role.backpack_full:
                return self.sell(role, keep_stone=True)
            return self.mine(role, need_stone=True)
        return False

    @staticmethod
    def building_max_health(building: Unit) -> int:
        return 1500 * building.level if building.kind == "station" else 500 + 500 * building.level

    def wall_depth(self, building: Unit) -> int:
        """Smallest depth faces the enemy: rightmost for left bases, vice versa."""
        return building.pos.x if self.settings.mirrored_layout(self.turn) else -building.pos.x

    @staticmethod
    def upgrade_name(building: Unit) -> str:
        prefix = "Wall" if building.kind == "wall" else "Station" if building.kind == "station" else "Weapon"
        return f"{prefix}UpgradeVoucher{building.level}"

    def upgrade_candidates(self) -> list[Unit]:
        """First unfinished observed tier; never advance on a submitted use alone."""
        weapons = self.turn.weapons()
        walls = self.turn.walls()
        station = self.turn.station()
        if self.settings.build_cells(self.turn, "rocket") and len(weapons) < 3:
            return []
        for level in (1, 2):
            pending = [w for w in weapons if w.level == level]
            if pending:
                return pending
            if self.turn.day >= 2:
                if self.missing_walls():
                    return []
                pending = [w for w in walls if w.level == level]
                if pending:
                    return pending
        if self.turn.day >= 2 and station and station.level < 3:
            return [station]
        return []

    def wall_keeps_exit(self, role: Unit, target: Pos) -> bool:
        # Do not close a reachable route to a vendor/task point with this wall.
        if distance(role.pos, target) > 1:
            return True
        landmarks = [p for p, k in self.turn.zones.items() if k == "vendor" or k.startswith(self.turn.team_type + "TaskPoint")]
        goals = adjacent_cells(self.turn, landmarks)
        for actor in self.turn.controllable():
            before = Routes(self.turn, actor, self.plan.reserved)
            after = Routes(self.turn, actor, self.plan.reserved | {target})
            if before.nearest(goals) is not None and after.nearest(goals) is None:
                return False
            if (actor.kind == PIONEER and self.layout.operator_pos in before.cost
                    and self.layout.operator_pos not in after.cost):
                return False
        return True

    def build_weapon(self, role: Unit) -> bool:
        if self.plan.tower_count >= 3 or self.plan.gold < 25:
            return False
        sites = [p for p in self.layout.tower_sites if p in self.settings.build_cells(self.turn, "rocket")
                 if p not in self.turn.blocked(role) and p not in self.plan.reserved and p not in self.goals and p != role.pos]
        desired = Counter(self.settings.loadout)
        desired.subtract(t.kind for t in self.turn.weapons())
        desired.subtract(c["name"] for c in self.plan.commands.values() if c["action"] == "build" and c["name"] in TOWER_TYPES)
        kind = next((k for k in self.settings.loadout if desired[k] > 0), self.settings.loadout[0])
        for target in sorted(sites, key=lambda p: (self.cost(role, [p]), p)):
            if self.interact(role, target, build_command(target, kind)):
                self.goals.add(target)
                return True
        return False

    def sell(self, role: Unit, keep_stone: bool = False) -> bool:
        minerals = Counter(i for i in role.backpack if i in MINERALS and i in self.turn.vendor_prices
                           and (i != "stone" or not keep_stone))
        if not minerals:
            return False
        near = self.plan.near_zone(role, "vendor")
        if not near and not role.backpack_full and sum(minerals.values()) < self.settings.sell_batch:
            return False
        name = max(minerals, key=lambda n: (minerals[n] * self.turn.vendor_prices[n], n))
        vendors = [p for p, k in self.turn.zones.items() if k == "vendor"]
        if near:
            return self.plan.add(role.unit_id, {"action": "sell", "name": name, "num": minerals[name]})
        return self.travel(role, vendors)

    def buy_upgrade(self, role: Unit) -> bool:
        if role.backpack_full:
            return False
        shops = [p for p, k in self.turn.zones.items() if k == "weaponShop"]
        reserve = max(0, 3 - self.plan.tower_count) * 25 if self.settings.build_cells(self.turn, "rocket") else 0
        reserve += self.guard.budget_reserve()
        planned = Counter(i for r in self.turn.controllable() for i in r.backpack)
        for command in self.plan.commands.values():
            if command["action"] == "buy":
                planned[command["name"]] += command.get("num", 1)
            elif command["action"] == "use":
                planned[command["name"]] -= 1
        pending = self.upgrade_candidates()
        if not pending or not shops:
            return False
        name = self.upgrade_name(pending[0])
        demand = sum(b.unit_id not in self.plan.upgrade_targets for b in pending)
        if name not in self.turn.shop_prices:
            return False
        price = self.turn.shop_prices[name]
        missing = max(0, demand - planned[name])
        count = min(missing, role.capacity - len(role.backpack),
                    missing if price == 0 else max(0, self.plan.gold - reserve) // price)
        if count <= 0:
            return False
        if self.plan.near_zone(role, "weaponShop"):
            return self.plan.add(role.unit_id, {"action": "buy", "name": name, "num": count})
        if self.cost(role, shops) + self.settings.return_margin >= self.turn.daylight_left:
            return False
        return self.travel(role, shops)

    def mine(self, role: Unit, need_stone: bool = False) -> bool:
        if role.backpack_full:
            return False
        options = []
        for pos, kind in self.turn.zones.items():
            if kind not in MINERALS or (need_stone and kind != "stone"):
                continue
            if self.memory.failed_mines.get(f"{pos.x},{pos.y}", 0) > self.turn.round_no:
                continue
            if any(c["name"] == kind and c["startDay"] <= self.turn.day <= c["endDay"] for c in self.memory.mine_closures):
                continue
            route = self.route(role)
            goals = adjacent_cells(self.turn, [pos])
            if self.danger:
                goals = {p for p in goals if not self.danger.get(p, 0) and route.exposure.get(p) == 0}
            cost = route.cost.get(route.nearest(goals), 10_000)
            if cost >= 10_000:
                continue
            value = 1 if need_stone else self.turn.vendor_prices.get(kind, 0)
            if value <= 0:
                continue
            options.append((value / (cost + 2), -cost, pos, goals))
        for _, _, pos, goals in sorted(options, key=lambda entry: entry[:3], reverse=True):
            if role.pos in goals and self.plan.add(role.unit_id, collect_command(pos)):
                return True
            step = self.route(role).step(goals)
            if step is not None and self.plan.add(role.unit_id, move_command(step)):
                return True
        return False

    def task(self, role: Unit) -> bool:
        if not self.settings.enable_tasks or self.turn.phase_task:
            return False
        tasks = [t for t in self.turn.tasks if t.valid and t.cooldown == 0]
        tasks.sort(key=lambda t: (self.cost(role, self.turn.task_cells(t)), -t.gold - t.score, t.pos))
        for task in tasks:
            cells = self.turn.task_cells(task)
            travel = self.cost(role, cells)
            duration = task.timeout if task.timeout > 0 else 15
            control = self.control_position(role)
            return_trip = distance(task.pos, control) if control else 0
            if travel + duration + return_trip + self.settings.return_margin > self.turn.daylight_left:
                continue
            if self.plan.near(role, cells):
                return self.plan.add(role.unit_id, {"action": "acceptTask"})
            if self.travel(role, cells):
                return True
        return False

    def treasure(self, role: Unit) -> bool:
        clue = self.memory.treasure
        if not clue or self.memory.treasure_done:
            return False
        if self.turn.round_no > clue["endRound"]:
            self.memory.treasure = None
            return False
        target = Pos.load(clue["targetPos"])
        missing = Counter(clue["items"]) - Counter(role.backpack)
        travel = self.cost(role, [target])
        if missing:
            shops = [p for p, k in self.turn.zones.items() if k == "weaponShop"]
            travel = self.cost(role, shops) + min((distance(p, target) for p in shops), default=10_000) + len(missing)
        if self.turn.round_no + travel > clue["endRound"]:
            return False
        if clue["startRound"] - self.turn.round_no > travel + self.settings.return_margin:
            return False
        if missing:
            shops = [p for p, k in self.turn.zones.items() if k == "weaponShop"]
            required = sum(self.turn.shop_prices.get(name, 10**9) * count for name, count in missing.items())
            if required > self.plan.gold or len(role.backpack) + sum(missing.values()) > role.capacity:
                return False
            name, count = next(iter(missing.items()))
            if self.plan.near_zone(role, "weaponShop"):
                return self.plan.add(role.unit_id, {"action": "buy", "name": name, "num": count})
            return self.travel(role, shops)
        if distance(role.pos, target) <= 1:
            if self.turn.round_no >= clue["startRound"]:
                return self.plan.add(role.unit_id, {"action": "summonTreasure", "targetPos": [target.dump()], "item": clue["items"]})
            self.plan.used.add(role.unit_id)
            return True
        return self.travel(role, [target])


def decide(payload: dict) -> dict:
    """Legacy demo entry: one stateless tactical turn, returning only the command map."""
    from app.config import Settings
    from app.service.memory import GameMemory
    turn = Turn.load(payload)
    plan = ActionPlan(turn, Settings())
    memory = GameMemory()
    memory.observe(turn)
    strategy = Strategy(turn, plan, memory)
    if turn.phase_task:
        plan.used.update(role.unit_id for role in turn.alive((PIONEER,)) if not strategy.pioneer_should_defend(role))
    strategy.run()
    return plan.commands
