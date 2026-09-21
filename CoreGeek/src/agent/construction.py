"""Choose positions inside configured or user-authorized zones; prefer a shared operator cell."""
from dataclasses import dataclass
from .protocol import CONTROLLABLE_TYPES, Pos, Turn, distance


@dataclass(frozen=True)
class DefenseLayout:
    tower_sites: tuple[Pos, ...] = ()
    operator_pos: Pos | None = None
    shared_control: bool = False


def select_defense_layout(turn: Turn, settings, previous: DefenseLayout | None = None) -> DefenseLayout:
    existing = tuple(w.pos for w in turn.weapons())
    buildings = {p for u in turn.ours + turn.enemies if u.health > 0 and u.kind not in CONTROLLABLE_TYPES
                 for p in turn.footprint(u)}
    allowed = set(settings.build_cells(turn, "rocket"))
    candidates = allowed - buildings
    walls = set(settings.build_cells(turn, "wall"))
    count = min(3, len(existing) + len(candidates))
    preferred = settings.default_operator_position(turn)
    # Fix P as well as the three rear sites from the user drawing. Ignore moving
    # roles here; temporary occupancy must not change the planned geometry.
    if (count and preferred is not None and preferred not in buildings | walls | candidates
            and set(existing) <= allowed
            and all(distance(preferred, p) <= 1 for p in candidates | set(existing))):
        return DefenseLayout(tuple(sorted(candidates | set(existing))), preferred, True)
    if (previous and previous.tower_sites and set(existing) <= set(previous.tower_sites)
            and len(previous.tower_sites) == count
            and set(previous.tower_sites) <= allowed | set(existing)
            and not (set(previous.tower_sites) - set(existing)) & buildings
            and previous.operator_pos not in buildings | walls):
        return previous
    if not count:
        return DefenseLayout()
    workers = turn.workers()
    pioneer = next(iter(turn.alive(("pioneer",))), None)
    base = turn.station()
    origin = pioneer.pos if pioneer else base.pos if base else existing[0] if existing else min(candidates)
    best = None
    stands = {p for site in candidates | set(existing) for p in site.neighbours()
              if turn.land(p) and p not in buildings | walls}
    for stand in sorted(stands):
        # At most eight neighbours can share a controller. Fill remaining slots nearby.
        options = sorted(candidates - {stand}, key=lambda p: (
            distance(p, stand), min((distance(w.pos, p) for w in workers), default=0), p))
        chosen = tuple(sorted(existing + tuple(options[:max(0, count-len(existing))])))
        coverage = sum(distance(stand, p) <= 1 for p in chosen)
        build_distance = sum(min((max(0, distance(w.pos, p)-1) for w in workers), default=0)
                             for p in chosen if p not in existing)
        score = (-len(chosen), -coverage, build_distance, distance(origin, stand), chosen, stand)
        if best is None or score < best[0]:
            best = score, DefenseLayout(chosen, stand, coverage == len(chosen))
    if best:
        return best[1]
    return DefenseLayout(tuple(sorted(existing + tuple(sorted(candidates)[:max(0, count-len(existing))]))))
