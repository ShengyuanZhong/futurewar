"""First-day perimeter sweeps ending towards each builder's next real job.

The blueprint and arc assignment are stable; legal outside interaction posts,
occupancy, material and departing coworkers are evaluated every observation.
This module ranks choices only. SealedHome and ActionPlan still authorize each
actual wall and never treat a submitted command as a completed building.
"""
from math import atan2, hypot

from .grid import adjacent_cells
from .protocol import CONTROLLABLE_TYPES, Pos, distance


class WallSchedule:

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
        self.post_cache.clear()  # Scoring used the old/no arc; corners now follow the assigned segment.

    def active_builders(self):
        raid = self.s.boss_raid
        scouts = self.s.raid_scouts
        return [w for w in self.turn.workers()
                if w.unit_id not in self.state.get('released', {})
                and not raid.worker_mission_active(w) and not scouts.is_worker(w)]

    def departed_ids(self):
        """Read confirmed mission state only; never call dispatch predicates."""
        departed = set(self.state.get('released', {}))
        raid = self.memory.boss_raid
        if raid.get('departure_authorized') or raid.get('mission_started'):
            departed.add(raid.get('buyer_id'))
        scout = self.memory.raid_scouts
        if (scout.get('personal_dispatch_round') is not None
                and not scout.get('paused_for_construction')):
            departed.add(scout.get('worker_id'))
        return departed

    def assigned_missing(self, role, ignore_enemy_occupied=False):
        """Real unbuilt own walls plus walls abandoned by a dead/departed peer.

        This is independent of ``active_builders`` to avoid recursion through
        shopping/scout eligibility. A submitted build is not an observed wall.
        Only a currently visible hostile controllable unit can defer a gap.
        """
        if not self.enabled or role.unit_id not in self.state.get('arcs', {}):
            return set()
        missing = set(self.s.construction_walls())
        arcs = self.state['arcs']
        builders = {w.unit_id for w in self.turn.workers()} - self.departed_ids()
        owned = set().union(*(set(arc) for uid, arc in arcs.items() if uid in builders))
        assigned = (set(arcs[role.unit_id]) | (missing - owned)) & missing
        if len(builders) == 1 and role.unit_id in builders:
            assigned = missing
        if ignore_enemy_occupied:
            occupied = {u.pos for u in self.turn.enemies
                        if u.health > 0 and u.kind in CONTROLLABLE_TYPES}
            assigned -= occupied
        return assigned

    def construction_ready(self, role):
        """The worker's actual assigned construction is done, or hostile-held."""
        return bool(self.enabled and self.state.get('arcs', {}).get(role.unit_id)
                    and len(self.turn.weapons()) >= 3
                    and not self.assigned_missing(role, ignore_enemy_occupied=True))

    def release(self, role, mission):
        """Commit the next job so the completed worker never borrows walls back."""
        if not self.enabled:
            return
        unfinished = sorted(self.assigned_missing(role))
        self.state.setdefault('released', {}).setdefault(role.unit_id,
            dict(round=self.turn.round_no, mission=mission,
                 unfinished=unfinished))
        job = self.memory.worker_tasks.get(role.unit_id, {})
        if job.get('kind') in ('build:wall', 'collect:stone'):
            self.memory.worker_tasks.pop(role.unit_id, None)

    def reclaim(self, role):
        """A paused, sole surviving scout must resume the abandoned construction."""
        self.state.get('released', {}).pop(role.unit_id, None)

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
            occupied=self.s.coordinator.claimed_goals(role)|self.plan.reserved
            terrain=self.s.sealed_home.builder_posts(adjacent_cells(self.turn,[target])
                                                    -self.walls-set(self.s.layout.tower_sites))
            legal=terrain-occupied
            if not self.enabled:
                self.post_cache[key]=legal
            else:
                # Face a straight edge from its exterior normal. At a corner
                # follow the next segment (or the previous one at its end).
                xmin,xmax=min(p.x for p in self.walls),max(p.x for p in self.walls)
                ymin,ymax=min(p.y for p in self.walls),max(p.y for p in self.walls)
                horizontal=[Pos(target.x,target.y-1)] if target.y==ymin else []
                if target.y==ymax:
                    horizontal.append(Pos(target.x,target.y+1))
                vertical=[Pos(target.x-1,target.y)] if target.x==xmin else []
                if target.x==xmax:
                    vertical.append(Pos(target.x+1,target.y))
                arcs=self.state.get('arcs',{})
                arc=next((a for a in [arcs.get(role.unit_id,())]+list(arcs.values()) if target in a),())
                index=arc.index(target) if target in arc else -1
                neighbour=arc[index+1] if index>=0 and index+1<len(arc) else arc[index-1] if index>0 else None
                choices=(vertical+horizontal if neighbour is not None and neighbour.x==target.x
                         else horizontal+vertical)
                preferred=next((p for p in choices if p in terrain),None)
                cardinal={p for p in terrain if abs(p.x-target.x)+abs(p.y-target.y)==1}
                # A temporary reservation must not rotate a free straight rail
                # into a diagonal stance. Static terrain may require a detour.
                self.post_cache[key]=({preferred}&legal if preferred is not None else
                                      (cardinal&legal if cardinal else legal))
        return self.post_cache[key]

    def straight_steps(self, role, goal):
        """Use the clear exterior rail, rather than an equal-cost diagonal zigzag.

        Remote approaches, corners and real obstructions keep normal eight-way
        routing. Submitted moves never change occupancy or advance a wall.
        """
        if not self.enabled or (role.pos.x!=goal.x and role.pos.y!=goal.y):
            return ()
        dx=(goal.x>role.pos.x)-(goal.x<role.pos.x)
        dy=(goal.y>role.pos.y)-(goal.y<role.pos.y)
        blocked=self.turn.blocked(role)|self.s.movement_reserved(role)
        points=tuple(Pos(role.pos.x+dx*i,role.pos.y+dy*i) for i in range(1,distance(role.pos,goal)+1))
        if not points or any(p not in self.s.sealed_home.outside or p in blocked for p in points):
            return ()
        return points[:2 if role.is_driving and self.turn.is_day else 1]

    def cost(self, role, target):
        allowed = self.s.sealed_home.outside if role.pos in self.s.sealed_home.outside else None
        key = role.unit_id,frozenset(self.s.movement_reserved(role)),allowed is not None
        if key not in self.routes:
            self.routes[key] = self.s.route(role,allowed=allowed)
        route = self.routes[key]
        goal = route.nearest(self.posts(role, target))
        return route.cost[goal] if goal is not None else 10000

    def targets(self, role, candidates, local_only=False):
        """Finish actual holes in arc order; only blocked/unreachable sites defer."""
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
        abandoned = self.assigned_missing(role) - set(own)
        if len(active)==1:
            abandoned=set(self.s.construction_walls())-set(own)
        inherited=[p for arc in arcs.values() for p in arc if p in abandoned and p in candidates]
        available=personal+inherited
        if not set(own)&set(self.s.construction_walls()) and not abandoned:
            available += [p for p in candidates if p not in available]
        # Actual outgoing missions are excluded by active_builders/released.
        # An ordinary builder with no next mission can help finish the peer's
        # last wall, including scenarios with the BOSS workflow disabled.
        costs = {p: self.cost(role, p) for p in available}
        reachable = [p for p in available if costs[p] < 10000]
        if not reachable:
            return []
        first=reachable[0]
        self.state.setdefault('frontier', {})[role.unit_id] = first
        if local_only:
            return [first] if role.pos in self.posts(role,first) else []
        return reachable

    def diagnostic(self):
        return dict(self.state, enabled=self.enabled,
                    remaining={w.unit_id: self.remaining(w) for w in self.turn.workers()} if self.enabled else {})
