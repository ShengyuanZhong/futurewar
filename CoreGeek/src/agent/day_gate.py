"""Compatibility facade: all planned walls are permanent, with no day gate."""
from .grid import Routes
from .protocol import CONTROLLABLE_TYPES


class DayGate:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.day_gate
        self.enabled = False
        self.worker_id = None
        self.pos = None
        self.state.clear()
        self.state.update(enabled=False,worker_id=None,pos=None,round=self.turn.round_no,
                          status='retired_permanent_walls')

    def role(self):
        return None

    def wall(self):
        return None

    def inner_posts(self):
        return set()

    def access_route(self, role):
        return Routes(self.turn,role,self.s.movement_reserved(role),self.s.danger)

    def other_ready(self, ignore=()):
        occupied = {u.pos for u in self.turn.enemies if u.health>0 and u.kind in CONTROLLABLE_TYPES}
        required = set(self.s.settings.build_cells(self.turn,'wall'))-(set(ignore)&occupied)
        return bool(required and len(self.turn.weapons())>=3
                    and required<={w.pos for w in self.turn.walls()})

    def day_ready(self, ignore=()):
        return self.turn.is_day and self.other_ready(ignore)

    def dispatch_ready(self, ignore=()):
        return self.day_ready(ignore)

    def reserve_stone(self, role):
        return 0

    def closing(self):
        return False

    def can_seal(self, role):
        return False

    def prepare_coupon(self, role):
        return False

    def non_gate_upgrades_complete(self):
        return False

    def required_inside(self):
        return []

    def worker(self, role):
        return False

    def diagnostic(self):
        return dict(self.state,closing=False,controlled_open=False,
                    construction_ready=self.other_ready(),dispatch_ready=self.other_ready(),
                    all_planned_walls_present=self.other_ready(),stone_held=0,coupon_held=0)
