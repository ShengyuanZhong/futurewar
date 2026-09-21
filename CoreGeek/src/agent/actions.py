"""One gate for all twelve actions, shared spending and destination reservations."""
from collections import Counter
from typing import Any
from .protocol import (CONTROLLABLE_TYPES, MINERALS, PIONEER, TOWER_TYPES, WORKER,
                       Pos, Turn, Unit, distance)

SUMMON_ITEMS = {f"{kind}RobotSummonOrder" for kind in ("Small", "Middle", "Large", "Boss")}
UPGRADES = {f"{prefix}UpgradeVoucher{level}": (kinds, level)
            for prefix, kinds in (("Weapon", TOWER_TYPES), ("Station", ("station",)), ("Wall", ("wall",)))
            for level in (1, 2)}
ACTION_FIELDS = {
    "move": {"targetPos"}, "attack": {"controllerId", "targetPos"},
    "sell": {"name", "num"}, "buy": {"name", "num"}, "build": {"name", "targetPos"},
    "remove": {"targetPos"}, "acceptTask": set(), "submitAnswer": {"taskAnswer"},
    "summonTreasure": {"targetPos", "item"}, "use": {"name", "targetPos"},
    "drop": {"name"}, "collect": {"targetPos"},
}


class ActionPlan:
    def __init__(self, turn: Turn, settings, summon_used: int = 0):
        self.turn, self.settings = turn, settings
        self.commands: dict[str, dict[str, Any]] = {}
        self.used: set[int] = set()
        self.reserved: set[Pos] = set()
        self.gold = turn.gold
        self.tower_count = len(turn.weapons())
        self.summon_used = summon_used
        self.build_targets: set[Pos] = set()
        self.upgrade_targets: set[int] = set()
        self.units = {u.unit_id: u for u in turn.ours if u.health > 0}
        self.rejections: list[str] = []

    def near(self, role: Unit, cells) -> bool:
        return any(distance(role.pos, p) <= 1 for p in cells)

    def near_zone(self, role: Unit, kind: str) -> bool:
        return self.near(role, [p for p, k in self.turn.zones.items() if k == kind])

    def add(self, unit_id: int, command: dict[str, Any]) -> bool:
        try:
            self._add(unit_id, command)
            return True
        except (ValueError, KeyError, TypeError) as exc:
            self.rejections.append(f"{unit_id}: {exc}")
            return False

    def _add(self, unit_id: int, command: dict[str, Any]) -> None:
        def require(condition, message):
            if not condition:
                raise ValueError(message)
        action = command.get("action")
        require(action in ACTION_FIELDS, "unknown action")
        require(set(command) <= ACTION_FIELDS[action] | {"action"}, "unexpected command field")
        role = self.units[unit_id]
        require(unit_id not in self.used, "unit already acted")
        raw_points = command.get("targetPos", [])
        require(isinstance(raw_points, list), "targetPos must be an array")
        points = [Pos.load(p) for p in raw_points]
        require(all(self.turn.in_bounds(p) for p in points), "target outside map")
        target = points[0] if points else None
        if action in ("move", "build", "remove", "collect", "summonTreasure"):
            require(len(points) == 1, "exactly one target required")
        name = command.get("name", "")
        if action in ("buy", "sell", "build", "use", "drop"):
            require(isinstance(name, str) and bool(name), "name required")
        actor = role
        cost, new_tower, summon = 0, 0, 0
        if action == "attack":
            require(role.kind in TOWER_TYPES and not self.turn.is_day, "weapon attacks only at night")
            require(role.cooldown == 0, "weapon cooling down")
            controller = command.get("controllerId")
            require(isinstance(controller, str), "controllerId must be a string")
            actor = self.units[int(controller)]
            require(actor.kind in CONTROLLABLE_TYPES and actor.unit_id not in self.used, "controller unavailable")
            require(distance(actor.pos, role.pos) <= 1, "controller out of reach")
            count = 1 if role.kind == "railgun" else max(1, min(3, role.level))
            require(len(points) == count, "incorrect projectile count")
            require(all(0 < distance(role.pos, p) <= role.range_of_attack() for p in points), "target out of range")
            if role.kind == "gatling":
                vectors = [(p.x - role.pos.x, p.y - role.pos.y) for p in points]
                require(all(ax * bx + ay * by >= 0 for ax, ay in vectors for bx, by in vectors), "gatling cone exceeds 90 degrees")
        else:
            require(role.kind in CONTROLLABLE_TYPES, "unit is not controllable")
        if action == "move":
            require(distance(role.pos, target) == 1, "movement must be one of eight neighbours")
            require(self.turn.land(target) and target not in self.turn.blocked(role), "occupied destination")
            require(target not in self.reserved, "destination already reserved")
        elif action in ("buy", "sell"):
            num = command.get("num", 1)
            require(type(num) is int and num > 0, "num must be a positive integer")
            require(self.near_zone(role, "weaponShop" if action == "buy" else "vendor"), "not beside shop")
            if action == "sell":
                require(name in MINERALS and name in self.turn.vendor_prices, "mineral not purchased by vendor")
                require(role.backpack.count(name) >= num, "insufficient minerals")
                # Simultaneous sales cannot finance this turn's purchases.
            else:
                require(name in self.turn.shop_prices, "item not in current shop")
                require(len(role.backpack) + num <= role.capacity, "backpack full")
                cost = self.turn.shop_prices[name] * num
        elif action == "build":
            require(role.kind == WORKER and self.turn.is_day, "only workers build during day")
            require(name in TOWER_TYPES + ("wall",), "unknown building")
            require(distance(role.pos, target) == 1, "build out of reach")
            require(target in self.settings.build_cells(self.turn, name), "unverified or wrong build zone")
            require(target not in self.reserved, "build target reserved")
            existing = next((u for u in self.turn.ours if u.health > 0 and u.pos == target and u.kind in TOWER_TYPES), None)
            if existing and name in TOWER_TYPES:
                require(not any(u.health > 0 and u.pos == target and u.unit_id != existing.unit_id for u in self.turn.ours + self.turn.enemies), "build occupied")
            else:
                require(target not in self.turn.blocked(role), "build occupied")
            if name == "wall":
                require("stone" in role.backpack, "wall requires stone")
            else:
                new_tower = 0 if existing else 1
                require(self.tower_count + new_tower <= 3, "three weapons maximum in total")
                cost = 25
        elif action == "remove":
            require(role.kind == WORKER, "only workers remove walls")
            require(distance(role.pos, target) == 1, "wall out of reach")
            require(any(w.pos == target for w in self.turn.walls()), "not our wall")
        elif action == "collect":
            require(role.kind == WORKER and not role.backpack_full, "cannot collect")
            require(distance(role.pos, target) == 1 and self.turn.zones.get(target) in MINERALS, "not beside a mine")
        elif action == "acceptTask":
            require(role.kind == PIONEER and not self.turn.phase_task, "cannot accept a task")
            require(any(t.valid and t.cooldown == 0 and self.near(role, self.turn.task_cells(t)) for t in self.turn.tasks), "no available friendly task in reach")
        elif action == "submitAnswer":
            require(role.kind == PIONEER and bool(self.turn.phase_task), "no active task")
            require(isinstance(command.get("taskAnswer"), str) and bool(command["taskAnswer"]), "answer must be nonempty text")
        elif action == "summonTreasure":
            require(role.kind == PIONEER and distance(role.pos, target) <= 1, "treasure out of reach")
            items = command.get("item")
            require(isinstance(items, list) and all(isinstance(i, str) for i in items), "item array required")
            ordinary = set(MINERALS) | SUMMON_ITEMS | set(UPGRADES) | {"Medicine", "Bomb", "DizzyWeapon", "WallFixer"}
            require(all(i not in ordinary for i in items), "sacrifices must be task items")
            require(not (Counter(items) - Counter(role.backpack)), "missing sacrifice items")
        elif action in ("use", "drop"):
            require(name in role.backpack, "item not in backpack")
            if action == "use":
                if name in UPGRADES or name == "WallFixer":
                    require(len(points) == 1, "building target required")
                    building = next((u for u in self.units.values() if u.pos == target and u.kind in TOWER_TYPES + ("station", "wall")), None)
                    require(building is not None and self.near(role, self.turn.footprint(building)), "building out of reach")
                    require(building.unit_id not in self.upgrade_targets, "building already upgraded or repaired this round")
                    if name in UPGRADES:
                        kinds, level = UPGRADES[name]
                        require(building.kind in kinds and building.level == level, "voucher level or building mismatch")
                    else:
                        require(building.kind == "wall", "repair requires wall")
                elif name in ("Bomb", "DizzyWeapon"):
                    require(len(points) == 1, "area target required")
                elif name in SUMMON_ITEMS:
                    require(self.summon_used < 10, "daily summon allowance exhausted")
                    require(not points, "summon order takes no target")
                    summon = 1
                else:
                    require(name == "Medicine" and not points, "unknown consumable")
        require(cost <= self.gold, "shared gold budget exhausted")
        self.gold -= cost
        self.tower_count += new_tower
        self.summon_used += summon
        self.commands[str(unit_id)] = command
        self.used.update((unit_id, actor.unit_id))
        if action in ("move", "build"):
            self.reserved.add(target)
        if action == "build":
            self.build_targets.add(target)
        if action == "use" and (name in UPGRADES or name == "WallFixer"):
            self.upgrade_targets.add(building.unit_id)
