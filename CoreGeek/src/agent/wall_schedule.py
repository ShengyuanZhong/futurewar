"""First-day perimeter sweeps ending towards each builder's next real job.

The blueprint and arc assignment are stable; legal outside interaction posts,
occupancy, material and departing coworkers are evaluated every observation.
This module ranks choices only. SealedHome and ActionPlan still authorize each
actual wall and never treat a submitted command as a completed building.
"""
from math import atan2, hypot

from .grid import adjacent_cells
from .protocol import Pos, distance


class WallSchedule:
    LOCAL_DETOUR = 2

    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.walls = set(strategy.settings.build_cells(self.turn, 'wall'))
        self.enabled = bool(self.turn.day == 1 and self.turn.is_day
                            and self.turn.station() and len(self.walls)>=2 and strategy.sealed_home.enabled)
        self.state = self.memory.sealed_home.setdefault('wall_schedule', {})
        self.routes = {}
        self.post_cache = {}
        if self.enabled:
            self.prepare()

    def destinations(self, workers):
        """Use actual NPC/base cells. Missing data defaults towards map centre."""
        base = self.turn.station().pos
        fallback = Pos(self.turn.width // 2, self.turn.height // 2)
        shops = [p for p, kind in self.turn.zones.items() if kind == 'weaponShop']
        shop = min(shops, key=lambda p: (distance(base, p), p)) if shops else fallback
        enemy = next((u.pos for u in self.turn.enemies if u.kind == 'station'), fallback)
        buyer = self.memory.boss_raid.get('buyer_id')
        scout = self.memory.raid_scouts.get('worker_id')
        return {w.unit_id: shop if w.unit_id == buyer and w.unit_id != scout else enemy
                for w in workers}

    def prepare(self):
        workers = sorted(self.turn.workers(), key=lambda w: w.unit_id)
        signature = tuple(sorted(self.walls))
        destinations = self.destinations(workers)
        if (self.state.get('blueprint') == signature and self.state.get('arcs')
                and all(self.state.get('destinations',{}).get(w.unit_id)==destinations[w.unit_id] for w in workers)):
            return
        if not workers or not self.walls:
            return
        base = self.turn.station().pos
        cx, cy = base.x + .5, base.y - .5
        dx = dy = 0.
        for goal in destinations.values():
            vx, vy = goal.x - cx, goal.y - cy
            length = hypot(vx, vy) or 1.
            dx += vx / length
            dy += vy / length
        if hypot(dx, dy) < .01:
            dx, dy = self.turn.width / 2 - cx, self.turn.height / 2 - cy
        projection = lambda p: (p.x - cx) * dx + (p.y - cy) * dy
        ring = sorted(self.walls, key=lambda p: (atan2(p.y - cy, p.x - cx), p))
        finish = max(ring, key=lambda p: (projection(p), p))
        i = ring.index(finish)
        ring = ring[i:] + ring[:i]
        # The two arcs start at the far side and approach opposite edges of the
        # departure sector. The cannon gap is simply an absent perimeter wall.
        split = min(range(len(ring)), key=lambda j: (projection(ring[j]), j))
        split = max(1, min(len(ring) - 1, split))
        paired = len(workers) > 1 and len(ring) > 1
        arcs = [list(reversed(ring[:split])), ring[split:]] if paired else [
            sorted(ring, key=lambda p: (projection(p), p))]
        if paired:
            first, second = workers[:2]

            def estimate(worker, arc):
                start = self.cost(worker, arc[0])
                if start >= 10000:
                    start = distance(worker.pos, arc[0])
                return start + sum(distance(a, b) for a, b in zip(arc, arc[1:])) + distance(
                    arc[-1], destinations[worker.unit_id])

            def score(order):
                times = [estimate(w, a) for w, a in zip((first, second), order)]
                return sum(times), max(times)

            if score(list(reversed(arcs))) < score(arcs):
                arcs.reverse()
            missing=set(self.s.construction_walls())
            if (missing and all('stone' in w.backpack for w in (first,second))
                    and sum(w.backpack.count('stone') for w in (first,second))>=len(missing)):
                # A mid-opening observation may already contain the old 9/8
                # batches. Keep the direction but split the work to use those
                # real bags, rather than requiring another mining excursion.
                choices=[]
                for pivot in range(1,len(ring)):
                    pair=[list(reversed(ring[:pivot])),ring[pivot:]]
                    for order in (pair,list(reversed(pair))):
                        deficit=sum(max(0,len(set(arc)&missing)-w.backpack.count('stone'))
                                    for w,arc in zip((first,second),order))
                        choices.append(((deficit,*score(order),abs(pivot-split)),order))
                arcs=min(choices,key=lambda entry:entry[0])[1]
        self.state.clear()
        self.state.update(blueprint=signature, destinations=destinations, departure=finish,
                          arcs={w.unit_id: arc for w, arc in zip(workers, arcs)},
                          assigned_round=self.turn.round_no)

    def active_builders(self):
        raid = self.s.boss_raid
        scouts = self.s.raid_scouts
        return [w for w in self.turn.workers()
                if not raid.worker_mission_active(w) and not scouts.is_worker(w)]

    def remaining(self, role):
        """Actual unfinished personal work; callers may transfer spare material."""
        missing = set(self.s.construction_walls())
        active = {w.unit_id for w in self.active_builders()}
        arcs = self.state.get('arcs', {})
        own = set(arcs.get(role.unit_id, ())) & missing
        orphaned = missing - set().union(*(set(arc) for uid, arc in arcs.items() if uid in active))
        if len(active) == 1 and role.unit_id in active:
            return len(missing)
        return len(own | orphaned) if role.unit_id in active else 0

    def posts(self, role, target):
        key = (role.unit_id,target,frozenset(self.plan.reserved),
               frozenset(self.s.coordinator.claimed_goals(role)))
        if key not in self.post_cache:
            blocked = (self.s.coordinator.claimed_goals(role) | self.plan.reserved
                       | self.walls | set(self.s.layout.tower_sites))
            self.post_cache[key] = self.s.sealed_home.builder_posts(
                adjacent_cells(self.turn, [target]) - blocked)
        return self.post_cache[key]

    def cost(self, role, target):
        allowed = self.s.sealed_home.outside if role.pos in self.s.sealed_home.outside else None
        key = role.unit_id,frozenset(self.s.movement_reserved(role)),allowed is not None
        if key not in self.routes:
            self.routes[key] = self.s.route(role,allowed=allowed)
        route = self.routes[key]
        goal = route.nearest(self.posts(role, target))
        return route.cost[goal] if goal is not None else 10000

    def targets(self, role, candidates, local_only=False):
        """Rank the same frontier for immediate builds and travel decisions.

        A directed next wall may cost two extra steps over the nearest legal
        wall. Larger detours permit a local insertion. A valid travel appointment
        persists. Unreachable/occupied sites never hold up the rest of an arc.
        """
        candidates = list(candidates)
        if not self.enabled or not self.state.get('arcs'):
            job = self.s.coordinator.job(role)
            previous = job.get('target') if job.get('kind') == 'build:wall' else None
            ordered = sorted(candidates, key=lambda p: (p != previous, self.s.cost(role, [p]), p))
            return [p for p in ordered if not local_only or distance(role.pos, p) == 1]
        active = {w.unit_id: w for w in self.active_builders()}
        if role.unit_id not in active:
            return []
        arcs = self.state['arcs']
        own = list(arcs.get(role.unit_id, ()))
        personal = [p for p in own if p in candidates]
        job = self.s.coordinator.job(role)
        previous = job.get('target') if job.get('kind') == 'build:wall' else None
        # A peer with no stone cannot perform an immediate local build; release
        # that frontier rather than keeping a material-carrying worker idle.
        released = {p for uid, arc in arcs.items()
                    if uid not in active or 'stone' not in active[uid].backpack for p in arc}
        available = personal + [p for p in candidates if p not in personal and (
            p in released or not personal)]
        if previous in candidates and previous not in available:
            available.append(previous)  # Preserve a real trip across a policy handoff.
        costs = {p: self.cost(role, p) for p in available}
        reachable = [p for p in available if costs[p] < 10000]
        if not reachable:
            return []
        nearest = min(costs[p] for p in reachable)
        rank = {p: i for i, p in enumerate(own)}
        feasible = [p for p in reachable if costs[p] <= nearest + self.LOCAL_DETOUR]
        if (previous in reachable and job.get('stalled', 0) < 2
                and (job.get('moving') or isinstance(job.get('goal'),Pos) or distance(role.pos,previous)==1)
                and job.get('round', 0) >= self.turn.round_no - 1):
            first = previous
        else:
            first = min(feasible, key=lambda p: (p not in rank, rank.get(p, 10000), costs[p], p))
        self.state.setdefault('frontier', {})[role.unit_id] = first
        if local_only:
            return [first] if distance(role.pos, first) == 1 else []
        return [first] + sorted([p for p in reachable if p != first],
            key=lambda p: (p not in rank, rank.get(p, 10000), costs[p], p))

    def diagnostic(self):
        return dict(self.state, enabled=self.enabled,
                    remaining={w.unit_id: self.remaining(w) for w in self.turn.workers()} if self.enabled else {})
