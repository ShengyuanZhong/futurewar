"""Local settings, never additions to the official request schema."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from agent.protocol import Pos, TOWER_TYPES, station_footprint


def base_surrounding_offsets(kind: str, mirrored: bool = False) -> tuple[Pos, ...]:
    """User drawing relative to the 2x2 base's top-left: rear guns and a U wall.

    Reflection is about the base centre x=0.5, so dx becomes 1-dx.
    The open rear and the one-cell inner repair lane are never wall sites.
    """
    if kind == "wall":
        cells = [Pos(x, y) for y in (2, -3) for x in range(4)]
        cells += [Pos(3, y) for y in range(-2, 2)]
    else:
        cells = [Pos(-1, y) for y in (1, 0, -1)]
    return tuple(Pos(1 - p.x, p.y) if mirrored else p for p in cells)


@dataclass(frozen=True)
class Settings:
    layouts: dict = field(default_factory=dict)
    allow_base_surroundings: bool = True
    loadout: tuple[str, ...] = ("rocket", "rocket", "rocket")
    sell_batch: int = 12
    return_margin: int = 4
    repair_start_day: int = 3
    repair_stock: int = 5
    repair_stock_per_day: int = 3
    repair_threshold_percent: int = 30
    enable_tasks: bool = True
    enable_news: bool = True
    max_body_bytes: int = 2 * 1024 * 1024

    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        path = path or os.environ.get("FUTUREWAR_CONFIG")
        if not path:
            return cls()
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        allowed = set(cls.__dataclass_fields__)
        if set(raw) - allowed:
            raise ValueError(f"unknown config fields: {sorted(set(raw) - allowed)}")
        if "loadout" in raw:
            raw["loadout"] = tuple(raw["loadout"])
        settings = cls(**raw)
        if len(settings.loadout) != 3 or any(k not in TOWER_TYPES for k in settings.loadout):
            raise ValueError("loadout must contain exactly three official weapon names")
        for key in ("sell_batch", "return_margin", "max_body_bytes", "repair_start_day", "repair_stock", "repair_threshold_percent"):
            if type(getattr(settings, key)) is not int or getattr(settings, key) <= 0:
                raise ValueError(f"{key} must be a positive integer")
        if settings.repair_start_day > 10 or settings.repair_stock > 100 or settings.repair_threshold_percent > 100:
            raise ValueError("repair settings exceed days, worker capacity or percentage")
        if type(settings.repair_stock_per_day) is not int or not 0 <= settings.repair_stock_per_day <= 100:
            raise ValueError("repair_stock_per_day must be an integer in 0..100")
        for key in ("allow_base_surroundings", "enable_tasks", "enable_news"):
            if type(getattr(settings, key)) is not bool:
                raise ValueError(f"{key} must be boolean")
        for team, layout in settings.layouts.items():
            if team not in ("challenger", "defender") or set(layout) != {"verified", "source", "weapons", "walls"}:
                raise ValueError("invalid layout structure")
            if type(layout["verified"]) is not bool or not isinstance(layout["source"], str):
                raise ValueError("layout verification and source must be explicit")
            if layout["verified"] and not layout["source"].strip():
                raise ValueError("verified layouts require a source")
            weapons = [Pos.load(p) for p in layout["weapons"]]
            walls = [Pos.load(p) for p in layout["walls"]]
            if len(set(weapons + walls)) != len(weapons + walls):
                raise ValueError("layout cells must be distinct and nonoverlapping")
            if any(abs(p.x) > 40 or abs(p.y) > 31 for p in weapons + walls):
                raise ValueError("layout offset exceeds the map")
        return settings

    def build_cells(self, turn, kind: str) -> tuple[Pos, ...]:
        station = turn.station()
        layout = self.layouts.get(turn.team_type, {})
        if not station:
            return ()
        if layout.get("verified") is True:
            offsets = tuple(Pos.load(p) for p in layout["walls" if kind == "wall" else "weapons"])
        elif self.allow_base_surroundings:
            offsets = base_surrounding_offsets(kind, self.mirrored_layout(turn))
        else:
            return ()
        base = set(station_footprint(station.pos))
        cells = (Pos(station.pos.x + p.x, station.pos.y + p.y) for p in offsets)
        return tuple(p for p in cells if turn.land(p) and p not in base)

    def mirrored_layout(self, turn) -> bool:
        """Choose by actual base centre versus map centre, independent of team label."""
        station = turn.station()
        return station is not None and 2 * station.pos.x + 1 > turn.width - 1

    def default_operator_position(self, turn) -> Pos | None:
        """Drawing's P; custom verified layouts retain their own stand selection."""
        station = turn.station()
        if (not station or not self.allow_base_surroundings
                or self.layouts.get(turn.team_type, {}).get("verified") is True):
            return None
        offset_x = 3 if self.mirrored_layout(turn) else -2
        pos = Pos(station.pos.x + offset_x, station.pos.y)
        return pos if turn.land(pos) else None
