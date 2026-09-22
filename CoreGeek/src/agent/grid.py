"""Eight-way paths with optional worker risk costs and an allowed patrol region."""
from collections import deque
from heapq import heappop, heappush
from .protocol import Pos, Turn, Unit


class Routes:
    def __init__(self, turn: Turn, role: Unit, reserved: set[Pos] | None = None,
                 danger: dict[Pos, int] | None = None, allowed: set[Pos] | None = None,
                 ignore_workers: frozenset[int] = frozenset()):
        self.start = role.pos
        # Used only to diagnose a friendly worker blockage; ActionPlan still
        # forbids moving into every currently occupied cell.
        ignored = {w.pos for w in turn.workers() if w.unit_id in ignore_workers}
        blocked = (turn.blocked(role) - ignored) | frozenset(reserved or ())
        self.cost = {role.pos: 0}
        self.exposure = {role.pos: 0}
        self.first: dict[Pos, Pos] = {}
        if danger:
            frontier = [(0, 0, role.pos)]
            while frontier:
                risk, steps, here = heappop(frontier)
                if (risk, steps) != (self.exposure[here], self.cost[here]):
                    continue
                for there in here.neighbours():
                    if (not turn.land(there) or there in blocked
                            or (allowed is not None and there not in allowed)):
                        continue
                    score = (risk + danger.get(there, 0), steps + 1)
                    if there in self.cost and score >= (self.exposure[there], self.cost[there]):
                        continue
                    self.exposure[there], self.cost[there] = score
                    self.first[there] = there if here == role.pos else self.first[here]
                    heappush(frontier, (*score, there))
            return
        frontier = deque([role.pos])
        while frontier:
            here = frontier.popleft()
            for there in here.neighbours():
                if (not turn.land(there) or there in blocked or there in self.cost
                        or (allowed is not None and there not in allowed)):
                    continue
                self.cost[there] = self.cost[here] + 1
                self.exposure[there] = 0
                self.first[there] = there if here == role.pos else self.first[here]
                frontier.append(there)

    def nearest(self, goals) -> Pos | None:
        reachable = [p for p in goals if p in self.cost]
        return min(reachable, key=lambda p: (self.exposure[p], self.cost[p], p)) if reachable else None

    def step(self, goals) -> Pos | None:
        return self.first.get(self.nearest(goals))


def adjacent_cells(turn: Turn, targets) -> set[Pos]:
    targets = set(targets)
    return {p for t in targets for p in t.neighbours() if p not in targets and turn.land(p)}


def next_step(turn: Turn, moving: Unit, goal: Pos) -> Pos | None:
    return Routes(turn, moving).step([goal])
