"""Observed-state upgrade stages for the user's U-shaped defense drawing."""
from .protocol import TOWER_TYPES


def wall_group(strategy, wall) -> int:
    """0=two centre front walls; 1=other front walls; 2=side/rear walls."""
    base = strategy.turn.station()
    if not base:
        return 2
    dx = wall.pos.x - base.pos.x
    if strategy.settings.mirrored_layout(strategy.turn):
        dx = 1 - dx
    if dx != 3:
        return 2
    return 0 if wall.pos.y - base.pos.y in (0, -1) else 1


def wall_target_level(strategy, wall) -> int:
    return 3 if wall_group(strategy, wall) < 2 else 2


def focused_weapon(weapons):
    pending = [w for w in weapons if w.level < 3]
    # Continue an already started tower; stable ID prevents route-dependent switching.
    return sorted(pending, key=lambda w: (w.kind != 'rocket', -w.level, w.unit_id))[:1]


def second_weapon_pending(weapons):
    group = [w for w in weapons if w.kind == 'rocket'] or weapons
    if sum(w.level >= 2 for w in group) < min(2, len(group)):
        return focused_weapon([w for w in group if w.level < 2])
    return []


def pending_walls(strategy, group, target):
    pending = [w for w in strategy.turn.walls() if wall_group(strategy, w) == group and w.level < target]
    level = min((w.level for w in pending), default=target)
    return [w for w in pending if w.level == level]


def upgrade_candidates(strategy):
    turn, settings = strategy.turn, strategy.settings
    weapons = turn.weapons()
    if settings.build_cells(turn, 'rocket') and len(weapons) < 3:
        return []
    rockets = [w for w in weapons if w.kind == 'rocket']
    first_group = rockets or weapons  # Retain compatibility with existing mixed loadouts.
    if not any(w.level >= 3 for w in first_group):
        pending = focused_weapon(first_group)
        if pending:
            return pending
    if turn.day == 1:
        return []  # Keep day-one wall restriction without skipping the centre-wall stage.
    if strategy.missing_walls():
        return []
    pending = pending_walls(strategy, 0, 3)
    if pending:
        return pending
    pending = second_weapon_pending(weapons)
    if pending:
        return pending
    for target in (2, 3):
        pending = pending_walls(strategy, 1, target)
        if pending:
            return pending
    pending = focused_weapon(weapons)
    if pending:
        return pending
    return pending_walls(strategy, 2, 2)  # Base upgrades are intentionally excluded.


def upgrades_complete(strategy) -> bool:
    turn = strategy.turn
    base = turn.station()
    sites = strategy.settings.build_cells(turn, 'wall')
    return bool(base and sites and not strategy.missing_walls()
                and len(turn.weapons()) >= 3 and all(w.level >= 3 for w in turn.weapons())
                and all(w.level >= wall_target_level(strategy, w) for w in turn.walls()))


def purchase_needs(strategy) -> list[tuple[str, int]]:
    """Current tier first; pre-stock the focused tower's level-3 coupon at the shop."""
    pending = strategy.upgrade_candidates()
    if not pending:
        return []
    needs = [(strategy.upgrade_name(pending[0]),
              sum(w.unit_id not in strategy.plan.upgrade_targets for w in pending))]
    weapons = strategy.turn.weapons()
    group = [w for w in weapons if w.kind == 'rocket'] or weapons
    intermediate_tier = any(w.level >= 3 for w in group) and bool(second_weapon_pending(weapons))
    if (len(pending) == 1 and pending[0].kind in TOWER_TYPES and pending[0].level == 1
            and not intermediate_tier):
        needs.append(('WeaponUpgradeVoucher2', 1))
    return needs
