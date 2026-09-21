"""Official v1.0 observations. No simulator-only fields are required."""
from dataclasses import dataclass, field
from typing import Any

DAY_ROUNDS, NIGHT_ROUNDS = 70, 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS
WEAPON_BUILD_COST = 25
WALL_MATERIAL = "stone"
LAND, STATION, WALL, WORKER, PIONEER = "land", "station", "wall", "worker", "pioneer"
TOWER_TYPES = ("gatling", "railgun", "rocket")
CONTROLLABLE_TYPES = (WORKER, PIONEER)
MINERALS = ("stone", "iron", "copper")
TOWER_RANGE_BY_LEVEL = {"gatling": (3, 5, 7), "railgun": (6, 8, 10), "rocket": (10, 15, 10**9)}
STEPS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def integer(raw: Any, name: str) -> int:
    if type(raw) is not int:
        raise ValueError(f"{name} must be an integer")
    return raw


@dataclass(frozen=True, slots=True, order=True)
class Pos:
    x: int
    y: int

    @classmethod
    def load(cls, raw: Any) -> "Pos":
        return cls(integer(raw["x"], "x"), integer(raw["y"], "y"))

    def dump(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}

    def neighbours(self) -> tuple["Pos", ...]:
        return tuple(Pos(self.x + dx, self.y + dy) for dx, dy in STEPS)


def distance(first: Pos, second: Pos) -> int:
    return max(abs(first.x - second.x), abs(first.y - second.y))


def station_footprint(pos: Pos) -> tuple[Pos, ...]:
    return (pos, Pos(pos.x + 1, pos.y), Pos(pos.x, pos.y - 1), Pos(pos.x + 1, pos.y - 1))


@dataclass(frozen=True, slots=True)
class Unit:
    unit_id: int
    pos: Pos
    kind: str
    health: int
    level: int = 0
    cooldown: int = 0
    attack_range: int = 0
    capacity: int = 0
    backpack: tuple[str, ...] = ()

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Unit":
        kind = str(raw["roleType"])
        return cls(integer(raw["id"], "id"), Pos.load(raw["pos"]), kind,
                   integer(raw["health"], "health"), int(raw.get("level") or 0),
                   int(raw.get("cooldown") or 0), int(raw.get("attackRange") or 0),
                   int(raw.get("backPackCapability", {WORKER: 100, PIONEER: 40}.get(kind, 0))),
                   tuple(raw.get("backpack") or ()))

    @property
    def backpack_full(self) -> bool:
        return len(self.backpack) >= self.capacity

    def range_of_attack(self) -> int:
        table = TOWER_RANGE_BY_LEVEL.get(self.kind)
        if table is None:
            return 0
        official = table[min(max(self.level, 1), 3) - 1]
        # D02: do not expand the rule table to match the conflicting sample.
        return min(official, self.attack_range) if self.attack_range > 0 else official


@dataclass(frozen=True, slots=True)
class Robot:
    robot_id: int
    pos: Pos
    health: int
    kind: str = "smallRobot"
    target_team: str = ""
    abnormal_state: str = ""

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Robot":
        return cls(integer(raw["id"], "id"), Pos.load(raw["pos"]), integer(raw["health"], "health"),
                   str(raw.get("roleType", "smallRobot")), str(raw.get("targetTeam", "")),
                   str(raw.get("abnormalState", "")))


@dataclass(frozen=True, slots=True)
class PlayerTask:
    kind: str
    pos: Pos
    cooldown: int
    valid: bool
    timeout: int
    score: int
    gold: int

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "PlayerTask":
        return cls(str(raw["taskType"]), Pos.load(raw["taskPosition"]),
                   int(raw.get("coldDownRounds", 0)), raw.get("isValid") is True,
                   int(raw.get("timeoutRounds", 0)), int(raw.get("scoreReward", 0)),
                   int(raw.get("goldReward", 0)))


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Keep raw feedback; timeout and judger failure are not successful exits."""
    raw: str
    status: str
    exit_code: int | None
    output: str
    truncated: bool

    @classmethod
    def load(cls, raw: str) -> "CommandResult":
        header, _, output = raw.partition("\n")
        code = None
        status = "empty" if not raw else "unknown"
        if header.startswith("[exitCode:") and header.endswith("]"):
            try:
                code = int(header[10:-1])
                status = "exited"
            except ValueError:
                pass
        elif header in ("[TIMEOUT]", "[JUDGER_ERROR]"):
            status = header[1:-1].lower()
        return cls(raw, status, code, output, raw.rstrip().endswith("[TRUNCATED]"))


@dataclass(frozen=True, slots=True)
class Turn:
    round_no: int
    is_day: bool
    gold: int
    width: int
    height: int
    zones: dict[Pos, str]
    ours: tuple[Unit, ...]
    robots: tuple[Robot, ...]
    enemies: tuple[Unit, ...] = ()
    team_id: str = ""
    team_type: str = "challenger"
    tasks: tuple[PlayerTask, ...] = ()
    phase_task: str = ""
    llm_response: str = ""
    command_result: CommandResult = field(default_factory=lambda: CommandResult.load(""))
    official_news: str = ""
    folk_legends: str = ""
    vendor_prices: dict[str, int] = field(default_factory=dict)
    shop_prices: dict[str, int] = field(default_factory=dict)
    action_results: dict[str, bool] = field(default_factory=dict)
    treasure_result: int = 0
    errors: tuple[dict[str, Any], ...] = ()

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "Turn":
        round_no = integer(payload["roundNo"], "roundNo")
        info, team = payload["mapInfo"], payload["teamOur"]
        width, height = integer(info["width"], "width"), integer(info["height"], "height")
        if not 1 <= round_no <= 1300 or (width, height) != (41, 32):
            raise ValueError("official mode requires rounds 1..1300 and a 41x32 map")
        if team["type"] not in ("challenger", "defender"):
            raise ValueError("unknown team type")
        news = payload.get("worldNews") or {}
        def prices(name: str) -> dict[str, int]:
            return {str(item["name"]): integer(item["price"], "price")
                    for item in payload.get(name) or () if item["price"] >= 0}
        turn = cls(round_no, (round_no - 1) % ROUNDS_PER_DAY < DAY_ROUNDS,
                   integer(team["goldNum"], "goldNum"), width, height,
                   {Pos.load(z["pos"]): str(z["neutralType"]) for z in info.get("zones") or ()},
                   tuple(Unit.load(r) for r in team.get("roles") or ()),
                   tuple(Robot.load(r) for r in (payload.get("robot") or {}).get("roles") or ()),
                   tuple(Unit.load(r) for r in (payload.get("teamEnemy") or {}).get("roles") or ()),
                   str(team["teamId"]), team["type"],
                   tuple(PlayerTask.load(t) for t in team.get("playerTasks") or ()),
                   str(payload.get("phaseTask") or ""), str(payload.get("llmResp") or ""),
                   CommandResult.load(str(payload.get("lastCmdResult") or "")),
                   str(news.get("officialNews") or ""), str(news.get("folkLegends") or ""),
                   prices("vendorShopList"), prices("weaponShopList"),
                   {str(k): v for k, v in (payload.get("lastRoundRoleActionResults") or {}).items()},
                   int(payload.get("lastSummonTreasureResult") or 0), tuple(payload.get("errors") or ()))
        ids = [u.unit_id for u in turn.ours + turn.enemies] + [r.robot_id for r in turn.robots]
        if len(ids) != len(set(ids)):
            raise ValueError("unit IDs must be globally unique")
        live = [u.pos for u in turn.ours + turn.enemies if u.health > 0]
        live += [r.pos for r in turn.robots if r.health > 0]
        if any(not turn.in_bounds(p) for p in list(turn.zones) + live):
            raise ValueError("observation contains an out-of-bounds position")
        return turn

    @property
    def day(self) -> int:
        return (self.round_no - 1) // ROUNDS_PER_DAY + 1

    @property
    def daylight_left(self) -> int:
        return max(0, DAY_ROUNDS - (self.round_no - 1) % ROUNDS_PER_DAY)

    def station(self) -> Unit | None:
        return next(iter(self.alive((STATION,))), None)

    def alive(self, kinds: tuple[str, ...]) -> tuple[Unit, ...]:
        return tuple(sorted((u for u in self.ours if u.kind in kinds and u.health > 0), key=lambda u: u.unit_id))

    def controllable(self) -> tuple[Unit, ...]:
        return self.alive(CONTROLLABLE_TYPES)

    def workers(self) -> tuple[Unit, ...]:
        return self.alive((WORKER,))

    def weapons(self) -> tuple[Unit, ...]:
        return self.alive(TOWER_TYPES)

    def walls(self) -> tuple[Unit, ...]:
        return self.alive((WALL,))

    def footprint(self, unit: Unit) -> tuple[Pos, ...]:
        return station_footprint(unit.pos) if unit.kind == STATION else (unit.pos,)

    def task_cells(self, task: PlayerTask) -> tuple[Pos, ...]:
        suffix = "2" if task.kind.endswith("2") else "1"
        name = self.team_type + "TaskPoint" + suffix
        cells = tuple(p for p, k in self.zones.items() if k == name)
        return cells or (task.pos,)

    def in_bounds(self, pos: Pos) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def land(self, pos: Pos) -> bool:
        return self.in_bounds(pos) and self.zones.get(pos, LAND) == LAND

    def occupied_cells(self) -> frozenset[Pos]:
        return frozenset(p for u in self.ours + self.enemies if u.health > 0 for p in self.footprint(u))

    def blocked(self, moving: Unit) -> frozenset[Pos]:
        cells = {p for p, k in self.zones.items() if k != LAND}
        cells.update(p for t in self.tasks for p in self.task_cells(t))
        cells.update(self.occupied_cells())
        cells.update(r.pos for r in self.robots if r.health > 0)
        cells.discard(moving.pos)
        return frozenset(cells)


def move_command(pos: Pos) -> dict[str, Any]:
    return {"action": "move", "targetPos": [pos.dump()]}


def collect_command(pos: Pos) -> dict[str, Any]:
    return {"action": "collect", "targetPos": [pos.dump()]}


def build_command(pos: Pos, name: str) -> dict[str, Any]:
    return {"action": "build", "targetPos": [pos.dump()], "name": name}


def attack_command(controller_id: int, targets: Pos | list[Pos]) -> dict[str, Any]:
    points = [targets] if isinstance(targets, Pos) else targets
    return {"action": "attack", "targetPos": [p.dump() for p in points], "controllerId": str(controller_id)}
