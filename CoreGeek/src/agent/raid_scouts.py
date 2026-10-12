"""Actual first-day layout survey and continuous hero sight; robots have none."""
from dataclasses import replace
from .protocol import CONTROLLABLE_TYPES, IMP, TOWER_TYPES, Pos, distance, move_command, station_footprint
from .grid import Routes
from .worker_safety import wall_shelters
from .summoning import (enemy_base_position, enemy_weapon_cells, enemy_layout_weapons,
                       enemy_layout_ready, layout_operator_positions)


SIGHT = 4


class RaidScouts:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.raid_scouts
        self.vehicle_routes = {}
        self.vehicle_options = {}
        self.base = enemy_base_position(self.turn)
        alive_boss = any(r.kind == 'bossRobot' and r.health > 0 for r in self.turn.summon_robots)
        if alive_boss:
            self.state['seen_boss'] = True
        enemy = next((u for u in self.turn.enemies if u.kind == 'station'), None)
        no_orders = (self.memory.boss_raid.get('order_decision_round') is not None
                     and self.memory.boss_raid.get('target_count') == 0)
        pending_raid = (self.memory.boss_raid.get('deployed_count',0) > 0
                        or self.memory.boss_raid.get('status') in ('summon_pending','deployed'))
        self.active = (self.s.settings.enable_boss_raid and self.turn.day == 1
                       and self.base is not None and not self.state.get('finished') and not no_orders
                       and (not self.memory.boss_raid.get('summon_window_closed') or alive_boss or pending_raid)
                       and not (enemy and enemy.health <= 0)
                       and (self.turn.is_day or alive_boss or
                            (not self.state.get('seen_boss') and pending_raid)))
        if not self.active:
            finished = (self.turn.day == 1 and self.s.settings.enable_boss_raid
                        and (self.state.get('finished') or no_orders
                             or (self.state.get('seen_boss') and not alive_boss)
                             or (enemy and enemy.health <= 0)))
            self.release(finished)
            return
        if self.state.get('base') not in (None, self.base):
            self.state.pop('surveyed', None)
            self.state.pop('posts', None)
        self.state.update(base=self.base, round=self.turn.round_no)
        live = {u.unit_id for u in self.turn.controllable()}
        self.state['posts'] = {uid:job for uid,job in self.state.get('posts', {}).items() if uid in live}
        self.state['walls_ready'] = self.walls_ready()
        self.update_survey()
        workers = self.turn.workers()
        self.state['worker_status'] = ('assigned' if self.state.get('worker_id') is not None else
                                      'waiting_for_walls' if not self.state['walls_ready'] else
                                      'not_enough_workers' if len(workers) < 2 else 'waiting_for_route')
        # Real wall completion is enough: L2/repair procurement cannot delay sight.
        # Never take the home/gap worker, or replace a dead scout with the sole guard.
        if (self.state.get('worker_id') is None and len(workers) >= 2
                and self.dispatch_granted() and self.turn.is_day):
            candidates = [w for w in workers if w.unit_id not in
                          (self.s.gap_guard.worker_id,self.s.first_defense.worker_id,
                           self.memory.boss_raid.get('buyer_id'),
                           self.s.day_gate.worker_id if self.s.day_gate.enabled else None)]
            choices = []
            for worker in candidates:
                post = self.post(worker)
                if post is not None:
                    cost = self.travel_budget(worker,post,self.scout_route(worker))[0]
                    if cost <= self.turn.daylight_left:
                        choices.append((cost,worker.unit_id))
            if choices:
                self.state['worker_id'] = min(choices)[1]
                self.state['home_worker_id'] = next(w.unit_id for w in workers
                                                   if w.unit_id != self.state['worker_id'])
                self.state['worker_status'] = 'assigned'
            else:
                self.state['worker_status'] = 'unreachable_or_too_late'
        self.refresh_readiness()

    def release(self, finished=False):
        for uid, job in list(self.memory.worker_tasks.items()):
            if job.get('kind','').startswith('raid_scout'):
                self.memory.worker_tasks.pop(uid)
        self.state.clear()
        if finished:
            self.state.update(finished=True,round=self.turn.round_no)

    def walls_ready(self):
        gate = getattr(self.s, 'day_gate', None)
        if gate is not None and gate.enabled and self.turn.is_day:
            return gate.dispatch_ready(self.s.gap_guard.gaps)
        if self.s.gap_guard.gaps:
            return self.s.gap_guard.other_walls_ready()
        if self.s.first_defense.enabled:
            return self.s.first_defense.closed()
        cells = self.s.settings.build_cells(self.turn,'wall')
        return bool(cells) and len(self.turn.weapons()) >= 3 and not self.s.construction_walls()

    def is_worker(self, role):
        return (self.active and role.unit_id == self.state.get('worker_id')
                and len(self.turn.workers()) >= 2 and role.unit_id != self.s.gap_guard.worker_id
                and role.unit_id != self.memory.boss_raid.get('buyer_id')
                and not (self.s.day_gate.enabled and role.unit_id==self.s.day_gate.worker_id)
                and (not self.turn.is_day or self.dispatch_granted()))

    def dispatch_granted(self):
        # Construction is verified before the buyer departs. A camper leaving
        # its unfinished site afterwards must not make both outgoing workers
        # abandon shopping/sight and restart unrelated economic trips.
        raid = self.memory.boss_raid
        return bool(self.active and (self.state.get('walls_ready') or
                    (raid.get('mission_started') and raid.get('buyer_departed'))))

    def known_weapons(self):
        return enemy_layout_weapons(self.turn,self.memory.enemy_structures.values())

    def seen(self, cell):
        # Do not use global enemy base/wall visibility or any summoned robot.
        return any(u.health > 0 and u.kind in CONTROLLABLE_TYPES + TOWER_TYPES + ('station','wall')
                   and distance(u.pos,cell) <= SIGHT
                   for u in self.turn.ours)

    def update_survey(self):
        cells = enemy_weapon_cells(self.turn)
        self.state.setdefault('surveyed',set()).update(p for p in cells if self.seen(p))
        self.state['weapon_cells'] = len(cells)
        self.state['surveyed_count'] = len(self.state['surveyed'] & cells)
        guns = self.known_weapons()
        self.state['weapons'] = [(w.unit_id,w.kind,w.pos) for w in guns]
        self.state['weapon_sites'] = sorted(self.memory.enemy_weapon_sites)
        # Buildings cannot be removed as walls can: confirmed locations remain
        # useful even after sight is lost or a destroyed cannon is rebuilt.
        # Keep this separate from live buildings used for obstruction/attacks.
        self.state['layout_ready'] = enemy_layout_ready(self.turn,
            self.memory.enemy_structures.values(),self.state['surveyed'],self.memory.enemy_weapon_sites)

    def operator_cells(self):
        guns = self.known_weapons()
        visible = {u.pos for u in self.turn.enemies if u.health > 0 and u.kind in ('worker','pioneer')
                   and any(distance(u.pos,w.pos) <= 1 for w in guns)}
        return visible | set(layout_operator_positions(self.turn,self.memory.enemy_structures.values()))

    def refresh_readiness(self):
        worker = next((w for w in self.turn.workers() if w.unit_id == self.state.get('worker_id')),None)
        cells = self.operator_cells()
        if not cells:
            cells = set(station_footprint(self.base))
        worker_near = bool(worker and any(distance(worker.pos,p) <= SIGHT for p in enemy_weapon_cells(self.turn)))
        worker_available = bool(worker and len(self.turn.workers()) >= 2
            and worker.unit_id != self.s.gap_guard.worker_id
            and worker.unit_id != self.memory.boss_raid.get('buyer_id')
            and not (self.s.day_gate.enabled and worker.unit_id==self.s.day_gate.worker_id))
        catchers = [u for u in self.turn.enemies if u.health>0 and u.kind in CONTROLLABLE_TYPES]
        imps = [u for u in self.turn.imps()
                if u.unit_id != self.s.gap_guard.imp_id
                and all(distance(u.pos,enemy.pos) >= 3 for enemy in catchers)
                and any(distance(u.pos,p)<=SIGHT for p in enemy_weapon_cells(self.turn))]
        # The IMP is already a genuine shared sight source. Do not wait for a
        # travelling worker when the safe IMP covers the real operator cells.
        imp_ready = any(all(distance(imp.pos,p)<=SIGHT for p in cells) for imp in imps)
        observer_ready = bool(worker_available and worker_near or imp_ready)
        uncovered = {p for p in cells if not self.seen(p)}
        base_visible = any(u.kind=='station' and u.health>0 for u in self.turn.enemies)
        reason = ('enemy_base_unconfirmed' if not base_visible else
                  'waiting_for_walls' if not self.dispatch_granted() else
                  'no_live_scout' if not worker_available and not imps else
                  'scout_travelling' if not observer_ready else
                  'layout_incomplete' if not self.state['layout_ready'] else
                  'operator_out_of_sight' if uncovered else 'ready')
        self.state.update(operator_cells=sorted(cells),uncovered_operators=sorted(uncovered),
                          worker_near=worker_near,imp_ready=imp_ready,
                          observer_ids=([worker.unit_id] if worker_available and worker_near else [])
                              + ([imp.unit_id for imp in imps if all(distance(imp.pos,p)<=SIGHT for p in cells)]),
                          summon_ready=reason=='ready',readiness_reason=reason)

    def summon_ready(self):
        return bool(self.active and self.state.get('summon_ready'))

    def watch_cells(self):
        if not self.state.get('layout_ready'):
            # Move around the real build ring until all guns, or all empty sites, are known.
            return set(enemy_weapon_cells(self.turn))-self.state.get('surveyed',set())
        return self.operator_cells() or set(station_footprint(self.base))

    def preferred(self, role):
        # Historical rear bias is only a tie-breaker; layouts can be on any side.
        right = 2*self.base.x + 1 > self.turn.width-1
        return Pos(self.base.x+(5 if right else -4),self.base.y+(2 if role.kind==IMP else -2))

    def spawn_cells(self):
        cells = set(self.memory.pending_summon_positions) | set(self.plan.summon_positions)
        cells.update(self.memory.boss_raid.get('spawns',()))
        if self.memory.boss_raid.get('spawn') is not None:
            cells.add(self.memory.boss_raid['spawn'])
        return cells

    def attack_lanes(self):
        targets = self.operator_cells()
        if not targets:
            return set()
        origins = self.spawn_cells() | {r.pos for r in self.turn.summon_robots if r.health>0}
        lanes = set()
        for origin in origins:
            for target in targets:
                for x in range(min(origin.x,target.x),max(origin.x,target.x)+1):
                    for y in range(min(origin.y,target.y),max(origin.y,target.y)+1):
                        p = Pos(x,y)
                        if p not in (origin,target) and wall_shelters(origin,target,(p,)):
                            lanes.add(p)
        return lanes

    def post(self, role):
        targets = self.watch_cells()
        old_job = self.state.get('posts',{}).get(role.unit_id,{})
        old = old_job.get('goal')
        mode = 'watch' if self.state.get('layout_ready') else 'survey'
        claimed = {job['goal'] for uid,job in self.state.get('posts',{}).items() if uid != role.unit_id}
        excluded = self.spawn_cells() | self.attack_lanes()
        route = self.scout_route(role)
        catchers = [u for u in self.turn.enemies if u.health>0 and u.kind in CONTROLLABLE_TYPES]
        options = []
        for p in route.cost:
            if p in excluded or p in claimed or p in self.plan.reserved or not self.turn.land(p):
                continue
            # Observe from outside the enemy construction square: do not stand
            # in the cannon crew's gap or block the planned BOSS firing lane.
            if min(distance(p,cell) for cell in station_footprint(self.base)) <= 2:
                continue
            rounds = self.travel_budget(role,p,route)[0]
            if role.kind != IMP and self.turn.is_day and rounds > self.turn.daylight_left:
                continue
            coverage = sum(distance(p,target) <= SIGHT for target in targets)
            catch_distance = min((distance(p,u.pos) for u in catchers),default=10_000)
            if not coverage or (role.kind==IMP and catch_distance<=1):
                continue
            # Keep a travelling scan goal while it can still reveal unseen cells.
            # At a holding post use actual current coverage, not a future move.
            if (p == old and role.pos != p and old_job.get('mode')==mode
                    and (role.kind != IMP or catch_distance >= 3)):
                return p
            options.append((role.kind==IMP and catch_distance<3,-coverage,
                            self.s.danger.get(p,0),p!=old,p!=role.pos,
                            rounds,distance(p,self.preferred(role)),p))
        return min(options)[-1] if options else None

    def travel_budget(self, role, goal, route):
        """Return travel rounds and a worthwhile, actually observed parked car.

        Boarding costs the walking route to the car. Subsequent two-step moves
        cost one round each; a final single step dismounts at the lookout. A
        missing/occupied car never creates a waiting or pursuit mission.
        """
        steps = route.cost.get(goal,10_000)
        driving = role.kind != IMP and self.turn.is_day and role.is_driving
        direct = (steps+1)//2 if driving else steps
        if (role.kind == IMP or not self.turn.is_day or driving or not steps
                or not self.turn.vehicle_cells(own=True)):
            return direct,None
        avoided = frozenset(self.state.get('avoided_vehicle_sites',set()))
        option_key = (role.unit_id,role.pos,frozenset(self.plan.reserved),avoided)
        if option_key not in self.vehicle_options:
            occupied = (self.turn.blocked(role) | self.plan.reserved
                        | self.s.coordinator.claimed_goals(role)
                        | self.spawn_cells() | self.attack_lanes())
            options = []
            for cell in self.turn.vehicle_cells(own=True):
                if (cell==role.pos or cell in occupied or cell in avoided
                        or cell not in route.cost or route.cost[cell]>=self.turn.daylight_left):
                    continue
                key = (role.unit_id,cell,frozenset(self.plan.reserved))
                if key not in self.vehicle_routes:
                    self.vehicle_routes[key] = self.scout_route(replace(role,pos=cell,is_driving=True))
                options.append((cell,route.cost[cell],self.vehicle_routes[key]))
            self.vehicle_options[option_key] = options
        best = (direct,None)
        for cell,boarding,driven in self.vehicle_options[option_key]:
            after = driven.cost.get(goal,10_000)
            rounds = boarding+(after+1)//2
            # A one-round theoretical gain can disappear after shared movement;
            # take the car only when it gives a meaningful route improvement.
            if rounds+1 < best[0] and rounds<=self.turn.daylight_left:
                best = (rounds,cell)
        return best

    def scout_route(self, role):
        reserved = self.s.movement_reserved(role)
        reserved.update(self.spawn_cells() | self.attack_lanes())
        # Previously seen hidden weapons still block paths until real sight clears them.
        reserved.update(p for u in self.memory.enemy_structures.values() if u.health>0
                        for p in self.turn.footprint(u))
        if role.kind==IMP:
            # Keep two cells from catchers along the entire route, not merely
            # at the final post. A visible enemy can move one cell next turn.
            catchers = [u for u in self.turn.enemies if u.health>0 and u.kind in CONTROLLABLE_TYPES]
            risk = min((distance(role.pos,u.pos) for u in catchers),default=10_000)
            # An enemy may approach an established post, or the IMP may revive
            # beside one. Allow only an immediate step that strictly increases
            # the closest-catcher distance: 1 -> 2, then next frame 2 -> 3.
            # Do not remove building/spawn/lane reservations with this exception.
            exits = {p for p in role.pos.neighbours()
                     if risk<3 and min((distance(p,u.pos) for u in catchers),default=10_000)>max(1,risk)}
            reserved.update(Pos(x,y) for u in catchers
                for x in range(max(0,u.pos.x-2),min(self.turn.width,u.pos.x+3))
                for y in range(max(0,u.pos.y-2),min(self.turn.height,u.pos.y+3))
                if Pos(x,y) not in exits)
        return Routes(self.turn,role,reserved,self.s.danger if role.kind!=IMP else None)

    def observe_from(self, role):
        post = self.post(role)
        if post is None:
            self.state.setdefault('posts',{})[role.unit_id] = dict(goal=None,status='unreachable',round=self.turn.round_no)
            if role.kind==IMP:
                enemies = [u for u in self.turn.enemies if u.health>0 and u.kind in CONTROLLABLE_TYPES]
                risk = min((distance(role.pos,u.pos) for u in enemies),default=10_000)
                excluded = self.s.movement_reserved(role) | self.spawn_cells() | self.attack_lanes()
                excluded.update(p for u in self.memory.enemy_structures.values() if u.health>0
                                for p in self.turn.footprint(u))
                cells = [p for p in role.pos.neighbours() if self.turn.land(p)
                         and p not in self.turn.blocked(role) | self.plan.reserved | excluded
                         and min((distance(p,u.pos) for u in enemies),default=10_000)>max(1,risk)]
                if risk<3 and cells:
                    self.plan.add(role.unit_id,move_command(max(cells,key=lambda p:
                        (min(distance(p,u.pos) for u in enemies),-distance(p,self.preferred(role)),p))))
            self.plan.used.add(role.unit_id)
            return True
        route = self.scout_route(role)
        old = self.s.coordinator.job(role) if role.kind=='worker' else {}
        if (old.get('kind')=='raid_scout_vehicle' and old.get('stalled',0)>=2
                and isinstance(old.get('goal'),Pos)):
            self.state.setdefault('avoided_vehicle_sites',set()).add(old['goal'])
        rounds,car = self.travel_budget(role,post,route)
        self.state.setdefault('posts',{})[role.unit_id] = dict(goal=post,
            status='holding' if post==role.pos else 'travelling',round=self.turn.round_no,
            mode='watch' if self.state.get('layout_ready') else 'survey',
            steps=route.cost[post],travel_rounds=rounds,vehicle=car,
            is_driving=role.is_driving,
            ready_by_night=rounds<=self.turn.daylight_left if self.turn.is_day else None,
            coverage=sum(distance(post,p)<=SIGHT for p in self.watch_cells()))
        if role.kind==IMP:
            self.memory.imp_tasks.pop(role.unit_id,None)
            if post==role.pos:
                self.plan.used.add(role.unit_id)
                return True
            step = route.step({post})
            if step is not None:
                self.plan.add(role.unit_id,move_command(step))
            return True
        self.s.coordinator.job(role).pop('yield_until',None)
        if post==role.pos:
            self.s.coordinator.assign(role,'raid_scout',self.base,post)
            self.plan.used.add(role.unit_id)
            return True
        if car is not None:
            self.state['posts'][role.unit_id]['status'] = 'collecting_vehicle'
            self.s.coordinator.move_to(role,{car},'raid_scout_vehicle',self.base,
                                       allow_risk=True,route=route)
        else:
            self.s.coordinator.move_to(role,{post},'raid_scout',self.base,
                                       allow_risk=True,route=route)
        # No fallback mining can interrupt an active view mission.
        self.plan.used.add(role.unit_id)
        return True

    def imp(self, role):
        return self.active and self.observe_from(role)

    def worker(self, role):
        if not self.active or role.unit_id != self.state.get('worker_id'):
            return False
        if (len(self.turn.workers())<2 or role.unit_id==self.s.gap_guard.worker_id
                or role.unit_id==self.memory.boss_raid.get('buyer_id')
                or (self.s.day_gate.enabled and role.unit_id==self.s.day_gate.worker_id)
                or (self.turn.is_day and not self.dispatch_granted())):
            self.state.get('posts',{}).pop(role.unit_id,None)
            self.state['worker_status'] = 'home_defense' if len(self.turn.workers())<2 else 'paused_for_walls_or_gap'
            return False
        return self.observe_from(role)

    def diagnostic(self):
        return {key:self.state.get(key) for key in ('round','worker_id','home_worker_id','worker_status',
            'walls_ready','surveyed_count','weapon_cells','weapons','weapon_sites','layout_ready','operator_cells',
            'worker_near','imp_ready','observer_ids','uncovered_operators','summon_ready','readiness_reason','posts')}
