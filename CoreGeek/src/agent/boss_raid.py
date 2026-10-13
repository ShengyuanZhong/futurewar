"""At most three first-day BOSS orders, confirmed from inventory and feedback."""
from dataclasses import replace
from .grid import Routes, adjacent_cells
from .protocol import PIONEER, WORKER, MINERALS, Pos, distance
from .first_day_tasks import FIRST_DAY_LIMIT, task_attempts, finished_count, success_count
from .summoning import (rear_spawn_position, scouted_spawn_position,
                       enemy_base_position, summon_cell_legal)


BOSS_ORDER = 'BossRobotSummonOrder'


class BossRaid:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.boss_raid
        self.prior_history = bool(self.state)
        self.buyer_id = self.select_buyer()
        self.trip = {}
        self.spawn_cache = {}
        self.observe()

    def select_buyer(self):
        """Keep one non-scout worker's identity and inventory for the whole raid."""
        previous = self.state.get('buyer_id')
        if previous is not None:
            return previous  # Death retains the bag; never silently migrate it.
        workers = self.turn.workers()
        scout = self.memory.raid_scouts.get('worker_id')
        candidates = [w for w in workers if w.unit_id != scout]
        if not candidates:
            return None
        ids = {w.unit_id for w in candidates}
        preferred = (self.memory.raid_scouts.get('home_worker_id'),self.s.gap_guard.worker_id,
                     self.s.day_gate.worker_id,self.s.first_defense.worker_id,self.s.guard.worker_id)
        buyer = next((uid for uid in preferred if uid in ids),min(ids))
        self.state['buyer_id'] = buyer
        return buyer

    def buyer_role(self, alive=False):
        return next((u for u in self.turn.ours if u.unit_id==self.buyer_id and u.kind==WORKER
                     and (not alive or u.health>0)),None)

    def dispatch_ready(self):
        gate = self.s.day_gate
        if gate.enabled:
            return gate.dispatch_ready(self.s.gap_guard.gaps)
        occupied = {u.pos for u in self.turn.enemies if u.health>0 and u.kind in (WORKER,PIONEER,'imp')}
        ignored = set(self.s.gap_guard.gaps) & occupied
        required = set(self.s.settings.build_cells(self.turn,'wall'))-ignored
        return bool(required) and len(self.turn.weapons())>=3 and required<={w.pos for w in self.turn.walls()}

    def worker_mission_active(self, role):
        approved_departure = self.state.get('departure_authorized') or (
            self.state.get('mission_started') and self.state.get('buyer_departed'))
        if (not self.s.settings.enable_boss_raid or self.turn.day!=1 or not self.turn.is_day
                or role.kind!=WORKER or role.health<=0 or role.unit_id!=self.buyer_id
                or role.unit_id==self.memory.raid_scouts.get('worker_id')
                or BOSS_ORDER not in self.turn.shop_prices
                or (not self.dispatch_ready() and not approved_departure and not self.departure_due(role))
                or self.state.get('summon_window_closed')):
            return False
        target = self.target_orders()
        if target is not None and (target==0 or self.state.get('deployed_count',0)>=target):
            return False
        return not self.state.get('purchase_closed') or bool(self.held_orders(role))

    def departure_budget(self, role):
        """Reserve actual outbound actions; no first-day return-home allowance.

        Three orders are the worst case until the task ledger settles. A sealed
        entrance is removed only in this forecast, never in the live map. Two
        spare rounds cover ordinary coworker yielding and route changes.
        """
        key = ('departure',role.unit_id,role.pos)
        if key in self.trip:
            return self.trip[key]
        target = self.target_orders()
        target = FIRST_DAY_LIMIT if target is None else target
        uses = max(0,target-self.state.get('deployed_count',0))
        needed = max(0,target-self.state.get('acquired_count',0))
        drops = max(0,len(role.backpack)+needed-role.capacity)
        buying = int(needed>0)
        shops = [p for p,k in self.turn.zones.items() if k=='weaponShop']
        goals = adjacent_cells(self.turn,shops)-self.s.coordinator.claimed_goals(role)
        options = []
        def offer(route, opening=0, approach=0, mode='actual_route', driving=None):
            post = route.nearest(goals)
            if post is None:
                return
            steps = route.cost[post]
            driving = role.is_driving if driving is None else driving
            travel = (steps+1)//2 if self.turn.is_day and driving else steps
            travel += approach
            total = travel+opening+drops+buying+uses+2
            options.append(dict(total=total,travel=travel,opening=opening,drop=drops,
                buy=buying,use=uses,slack=2,post=post,route_mode=mode,
                latest_departure=self.turn.round_no+self.turn.daylight_left-total))
        route = self.s.route(role)
        offer(route)
        if not options:
            offer(self.s.coordinator.diagnostic_route(role),mode='coworker_yield')
        gate = self.s.day_gate
        wall = gate.wall() if gate.enabled else None
        if not options and wall is not None and gate.worker_id==role.unit_id:
            entries = adjacent_cells(self.turn,[gate.pos])
            if distance(role.pos,gate.pos)<=1:
                entries.add(role.pos)
            entry = route.nearest(entries)
            if entry is not None:
                before = route.cost[entry]
                driving_after = role.is_driving and before%2==0
                moved = replace(role,pos=entry,is_driving=driving_after)
                simulated = replace(self.turn,ours=tuple(moved if u.unit_id==role.unit_id else u
                    for u in self.turn.ours if u.unit_id!=wall.unit_id))
                reserved = self.s.movement_reserved(role)-{gate.pos}
                after = Routes(simulated,moved,reserved)
                approach = (before+1)//2 if role.is_driving else before
                offer(after,opening=1,approach=approach,mode='remove_entrance',driving=driving_after)
        self.trip[key] = min(options,key=lambda p:(p['total'],p['post'])) if options else None
        return self.trip[key]

    def departure_due(self, role):
        budget = self.departure_budget(role)
        # No reachable shop is a reason to start diagnosing the route now,
        # rather than spend the remaining window on lower-priority wall work.
        return (budget is None or self.turn.daylight_left<=budget['total'])

    def observe(self):
        # A dead buyer's preserved bag is evidence, although it cannot act.
        role = self.buyer_role()
        if not role:
            self.state.setdefault('deployed_count',0)
            self.state.setdefault('spawns',[])
            self.state.setdefault('acquired_count',0)
            return
        held = role.backpack.count(BOSS_ORDER)
        legacy = self.prior_history
        self.state.setdefault('history_known', legacy or self.turn.round_no == 1
            or self.memory.last_round > 0 or bool(self.memory.task_points_attempted)
            or bool(self.memory.task_points_succeeded))
        if not self.state['history_known']:
            # The public request cannot reconstruct orders consumed before a
            # process restart. Do not buy another pair with unknown history.
            self.state['purchase_closed'] = True
            self.state['status'] = 'unknown_prior_deployment'
        if 'acquired_count' not in self.state:
            old_deployed = 1 if self.state.get('status') == 'deployed' else 0
            self.state['deployed_count'] = self.state.get('deployed_count', old_deployed)
            self.state['acquired_count'] = min(FIRST_DAY_LIMIT, max(held + self.state['deployed_count'],
                int(bool(self.state.get('order_acquired')))))
            self.state.setdefault('spawns', [])
            if old_deployed and self.state.get('spawn') is not None:
                self.state['spawns'].append(self.state['spawn'])
            if old_deployed:
                self.state['purchase_locked'] = True
        self.state.setdefault('deployed_count', 0)
        self.state.setdefault('spawns', [])
        self.state.setdefault('deployment_ledger_confirmed', self.state['deployed_count'] == 0)
        if held:
            self.state['order_acquired'] = True
        pending_buy = self.state.get('pending_buy')
        pending_use = self.state.get('pending_use')
        accounted_use = False
        if pending_buy and self.turn.round_no > pending_buy['round']:
            result = self.feedback(pending_buy)
            gain = held - pending_buy['held']
            if gain > 0:
                acquired = min(gain, pending_buy['num'])
                self.state['acquired_count'] = min(FIRST_DAY_LIMIT, self.state['acquired_count'] + acquired)
                self.state['bought_count'] = self.state.get('bought_count', 0) + acquired
                if gain != pending_buy['num'] or result is False:
                    self.state['purchase_closed'] = True
                    self.state['inventory_warning'] = 'unexpected_purchase_quantity_or_feedback'
                self.state['status'] = 'summoning'
            elif result is False and gain == 0:
                self.state['status'] = 'shopping'
            else:
                self.state['purchase_closed'] = True
                self.state['status'] = 'order_missing'
                self.state['inventory_warning'] = 'purchase_not_confirmed_by_inventory'
            self.state.pop('pending_buy', None)
        if pending_use and self.turn.round_no > pending_use['round']:
            result = self.feedback(pending_use)
            spent = pending_use['held'] - held
            if result is False:
                self.release_failed_use(pending_use['spawn'])
                self.state.setdefault('failed_positions', set()).add(pending_use['spawn'])
                if spent:
                    self.state['purchase_closed'] = True
                    self.state['inventory_warning'] = 'failed_use_lost_order'
                    self.state['status'] = 'order_missing'
                else:
                    self.state['status'] = 'summoning'
                self.state.pop('pending_use', None)
                accounted_use = True
            elif result is True or spent == 1:
                if pending_use['spawn'] not in self.state['spawns']:
                    self.state['spawns'].append(pending_use['spawn'])
                    self.state['deployed_count'] = min(FIRST_DAY_LIMIT, self.state['deployed_count'] + 1)
                self.state['status'] = 'deployed'
                self.state['deployment_ledger_confirmed'] = True
                if pending_use.get('scouted'):
                    scouted = self.state.setdefault('scouted_spawns',[])
                    if pending_use['spawn'] not in scouted:
                        scouted.append(pending_use['spawn'])
                if spent != 1:
                    self.state['inventory_warning'] = 'use_feedback_inventory_disagree'
                    # A valid use still consumes one managed order even if the
                    # observed bag is stale. It must never be used repeatedly.
                    self.state['purchase_closed'] = True
                self.state.pop('pending_use', None)
                accounted_use = True
            elif spent > 1:
                self.state['purchase_closed'] = True
                self.state['status'] = 'order_missing'
                self.state['inventory_warning'] = 'multiple_orders_disappeared'
                self.state.pop('pending_use', None)
                accounted_use = True
        if not pending_buy and not accounted_use and not self.state.get('pending_use'):
            previous = self.state.get('held_last')
            if previous is not None and held < previous:
                self.state['purchase_closed'] = True
                self.state['status'] = 'order_missing'
                self.state['inventory_warning'] = 'order_disappeared_without_use'
            if held > max(0, self.state['acquired_count'] - self.state['deployed_count']):
                self.state['acquired_count'] = min(FIRST_DAY_LIMIT, held + self.state['deployed_count'])
        self.state['held_last'] = held

    def feedback(self, pending):
        if (pending['round'] == self.turn.round_no-1
                and self.memory.last_round == pending['round']):
            command = self.memory.last_commands.get(str(pending['actor_id']), {})
            if (command.get('name') != BOSS_ORDER or
                    command.get('action') != ('buy' if 'num' in pending else 'use')):
                return None
            return self.turn.action_results.get(str(pending['actor_id']))
        return None

    def release_failed_use(self, spawn):
        # memory.observe normally performs this rollback first. Membership
        # makes direct policy calls safe without subtracting the same use twice.
        if spawn in self.memory.pending_summon_positions:
            self.memory.pending_summon_positions.discard(spawn)
            self.memory.summon_attempts = max(0, self.memory.summon_attempts-1)
        if spawn in self.plan.summon_positions:
            self.plan.summon_positions.discard(spawn)
            self.plan.summon_used = max(0, self.plan.summon_used-1)

    def tasks_finished(self):
        return (self.turn.day==1 and self.turn.is_day and not self.turn.phase_task
                and (finished_count(self.memory)>=FIRST_DAY_LIMIT
                     or not self.s.settings.enable_tasks))

    def successful_tasks(self):
        return success_count(self.memory)

    def tasks_succeeded(self):
        return self.successful_tasks()==FIRST_DAY_LIMIT

    def target_orders(self):
        if not self.tasks_finished():
            return None
        return self.state.get('target_count',0) if 'order_decision_round' in self.state else self.successful_tasks()

    def decide_orders(self):
        if not self.tasks_finished():
            return False
        if 'order_decision_round' not in self.state:
            self.state.update(order_decision_round=self.turn.round_no,
                              target_count=self.successful_tasks())
        if self.state['target_count']==0:
            self.state.update(status='no_successful_tasks',purchase_stage_done=True)
        return True

    def weapon_upgrades_ready(self):
        if not self.s.settings.enable_boss_raid or self.turn.day!=1 or not self.turn.is_day:
            # The first-day purchase window has ended; retain the existing
            # unified night economy rather than locking vouchers until dawn.
            return True
        if self.state.get('purchase_stage_done') or self.state.get('purchase_attempt_round'):
            return True
        if not self.tasks_finished():
            return False
        target = self.target_orders()
        return (target==0 or self.state.get('purchase_stage_done',False)
                or bool(self.state.get('purchase_attempt_round'))
                or self.state.get('acquired_count',0)>=target)

    def day_available(self):
        return self.s.settings.enable_boss_raid and self.tasks_finished()

    def diagnostic(self):
        role = next(iter(self.turn.alive((PIONEER,))),None)
        buyer = self.buyer_role()
        return dict(round=self.turn.round_no,team_id=self.turn.team_id,is_day=self.turn.is_day,
            pioneer=dict(id=role.unit_id,pos=role.pos,health=role.health,
                command=self.plan.commands.get(str(role.unit_id))) if role else None,
            buyer_id=self.buyer_id,
            buyer=dict(id=buyer.unit_id,pos=buyer.pos,health=buyer.health,
                held=buyer.backpack.count(BOSS_ORDER),command=self.plan.commands.get(str(buyer.unit_id))) if buyer else None,
            dispatch_ready=self.dispatch_ready(),buyer_departed=self.state.get('buyer_departed',False),
            construction_approved_round=self.state.get('construction_approved_round'),
            departure_authorized=self.state.get('departure_authorized',False),
            departure_reason=self.state.get('departure_reason'),
            departure_round=self.state.get('departure_round'),
            departure_budget_at_start=self.state.get('departure_budget_at_start'),
            departure_budget=self.departure_budget(buyer) if buyer and self.turn.day==1 and self.turn.is_day else None,
            tasks=[dict(kind=t.kind,pos=t.pos,valid=t.valid,cooldown=t.cooldown,timeout=t.timeout) for t in self.turn.tasks],
            task_itinerary_closed=self.memory.task_schedule.get('itinerary_closed',False),
            attempted_tasks=len(task_attempts(self.memory)),
            finished_tasks=finished_count(self.memory),task_schedule=self.memory.task_schedule,
            successful_tasks=self.successful_tasks(),active_task=bool(self.turn.phase_task),
            target_orders=self.state.get('target_count') if 'order_decision_round' in self.state else None,
            decision_round=self.state.get('order_decision_round'),
            purchase_attempt_round=self.state.get('purchase_attempt_round'),
            purchase_stage_done=self.state.get('purchase_stage_done',False),
            weapon_upgrades_ready=self.weapon_upgrades_ready(),boss_budget=self.budget_reserve(),
            summon_window_closed=self.state.get('summon_window_closed',False),
            scout_ready=getattr(self.s,'raid_scouts',None).summon_ready() if hasattr(self.s,'raid_scouts') else False,
            last_buyer_decision=self.state.get('decision'),last_pioneer_decision=self.state.get('decision'))

    def available_gold(self):
        return max(0, self.plan.gold - max(0, 3-self.plan.tower_count)*25)

    def held_orders(self, role):
        if role.unit_id!=self.buyer_id or role.kind!=WORKER:
            return 0
        return min(role.backpack.count(BOSS_ORDER),
                   max(0, self.state['acquired_count']-self.state['deployed_count']))

    def shop_trip(self, role, use_count=1, start=None):
        """Budget the route to the shop, purchase and remaining daytime uses.

        ``start`` forecasts the final task's completion position without
        modifying the live actor or the strategy's current-position route cache.
        """
        key = (role.unit_id,role.pos if start is None else start,use_count,start is not None)
        if key in self.trip:
            return self.trip[key]
        shops = [p for p, kind in self.turn.zones.items() if kind == 'weaponShop']
        if start is None:
            route = self.s.route(role)
        else:
            moved = replace(role,pos=start)
            simulated = replace(self.turn,ours=tuple(moved if u.unit_id==role.unit_id else u for u in self.turn.ours))
            route = Routes(simulated,moved,self.s.movement_reserved(role))
        options = []
        for post in adjacent_cells(self.turn, shops):
            if post!=role.pos and post in self.s.coordinator.claimed_goals(role):
                continue
            if post not in route.cost:
                continue
            travel = (route.cost[post]+1)//2 if self.turn.is_day and role.is_driving else route.cost[post]
            total = travel + 1 + use_count
            if start is not None or total <= self.turn.daylight_left:
                options.append((total, route.cost[post], post))
        self.trip[key] = min(options) if options else None
        return self.trip[key]

    def budget_reserve(self):
        role = self.buyer_role(alive=True)
        price = self.turn.shop_prices.get(BOSS_ORDER)
        if (not role or not self.s.settings.enable_boss_raid or self.turn.day!=1 or not self.turn.is_day
                or self.state.get('purchase_closed') or self.state.get('summon_window_closed') or price is None
                or (self.state['deployed_count'] and not self.state['deployment_ledger_confirmed'])
                or self.state.get('pending_buy')):
            return 0
        # Before all three attempts end this is a potential three-order reserve, not a
        # purchase decision. After settlement it follows the frozen success quota.
        target = self.target_orders()
        if target is None:
            target = FIRST_DAY_LIMIT
        elif target==0 or self.preparation(role) is None:
            return 0
        return max(0,target-self.state['acquired_count'])*price

    def spawn_position(self):
        positions = self.spawn_positions(1)
        return positions[0] if positions else None

    def spawn_positions(self, count, scouted=False):
        used = set(self.plan.summon_positions) | set(self.state['spawns'])
        failed = self.state.get('failed_positions', set())
        key = (count, scouted, frozenset(used), frozenset(failed))
        if key not in self.spawn_cache:
            positions = []
            for _ in range(count):
                if scouted:
                    pos = scouted_spawn_position(self.turn,self.s.settings,
                        self.memory.enemy_structures.values(),used,failed,
                        self.memory.raid_scouts.get('surveyed',()),self.memory.enemy_weapon_sites)
                else:
                    # Purchase feasibility only. Actual use must wait for the
                    # scout and use the observed layout, never this template.
                    pos = rear_spawn_position(self.turn,self.s.settings,used,failed)
                    if pos is None:
                        base = enemy_base_position(self.turn)
                        legal = [Pos(x,y) for x in range(self.turn.width) for y in range(self.turn.height)
                                 if Pos(x,y) not in failed
                                 and summon_cell_legal(self.turn,self.s.settings,Pos(x,y),used)] if base else []
                        pos = min(legal,key=lambda p:(distance(p,base),p)) if legal else None
                if pos is None:
                    break
                positions.append(pos); used.add(pos)
            self.spawn_cache[key] = positions
        return self.spawn_cache[key]

    def proposal(self, role):
        if role.unit_id!=self.buyer_id or role.kind!=WORKER:
            return None
        target = self.target_orders()
        deployed = self.state['deployed_count']
        if target is None or target<=deployed:
            return None
        uses = target-deployed
        held = self.held_orders(role)
        buy_num = max(0,uses-held)
        # An anomalous partial inventory closes additional purchases, but the
        # genuinely held orders can still be used without changing the quota.
        if buy_num and self.state.get('purchase_closed') and held:
            uses,buy_num = min(uses,held),0
        if uses>10-self.plan.summon_used:
            return None
        if buy_num:
            price = self.turn.shop_prices.get(BOSS_ORDER)
            if (self.state.get('purchase_closed') or price is None
                    or (deployed and not self.state['deployment_ledger_confirmed'])
                    or self.state['acquired_count']+buy_num>target
                    or len(role.backpack)+buy_num>role.capacity
                    or self.available_gold()<buy_num*price):
                return None
            trip = self.shop_trip(role,uses)
            if trip is None:
                return None
        else:
            trip = None
            if uses>self.turn.daylight_left:
                return None
        positions = self.spawn_positions(uses)
        if len(positions)!=uses:
            return None
        return dict(total=target,uses=uses,buy_num=buy_num,trip=trip,positions=positions)

    def preparation(self, role):
        if role.unit_id!=self.buyer_id or role.kind!=WORKER:
            return None
        target = self.target_orders()
        if target is None or target<=self.state['acquired_count'] or self.state.get('purchase_closed'):
            return None
        uses = target-self.state['deployed_count']
        buy_num = target-self.state['acquired_count']
        if (BOSS_ORDER not in self.turn.shop_prices or len(role.backpack)+buy_num>role.capacity
                or uses>10-self.plan.summon_used or len(self.spawn_positions(uses))!=uses):
            return None
        trip = self.shop_trip(role,uses)
        return dict(total=target,trip=trip) if trip is not None else None

    def return_home(self, role):
        if role.kind==WORKER:
            return False  # Resume the existing gate/gap/first-night worker duties.
        if self.state.get('returned'):
            return False
        if role.pos == self.s.control_position(role):
            self.state['returned'] = True
            return False
        return self.s.move_to_control(role)

    def pioneer(self, role):
        """Compatibility entry: the pioneer never purchases or uses raid orders."""
        return False

    def hold_worker(self, role, status):
        self.state['status'] = status
        self.s.coordinator.assign(role,'boss_shop_wait',BOSS_ORDER,role.pos)
        self.plan.used.add(role.unit_id)
        return True

    def approach_shop(self, role, post=None):
        if post is None and self.plan.near_zone(role,'weaponShop'):
            return self.hold_worker(role,'waiting_at_shop')
        route = self.s.route(role)
        goals = {post} if post is not None else adjacent_cells(self.turn,
            [p for p,k in self.turn.zones.items() if k=='weaponShop'])
        goals -= self.s.coordinator.claimed_goals(role)
        goal = route.nearest(goals)
        if goal is not None:
            if goal==role.pos:
                return self.hold_worker(role,'waiting_at_shop')
            return self.s.coordinator.move_to(role,{goal},'boss_shop',BOSS_ORDER)
        if self.s.coordinator.move_to(role,goals,'boss_shop',BOSS_ORDER):
            return True  # Diagnose/yield a real coworker blocking the entrance.
        # A full enclosure must really open before an interior buyer can exit.
        # Do not keep issuing an impossible route while suppressing DayGate.
        gate = self.s.day_gate
        if gate.enabled and gate.worker_id==role.unit_id and gate.wall() is not None:
            if self.s.interact(role,gate.pos,{'action':'remove','targetPos':[gate.pos.dump()]}):
                self.state['status'] = 'opening_buyer_exit'
                if self.plan.commands.get(str(role.unit_id),{}).get('action')=='remove':
                    gate.state['status'] = 'opening'
                return True
        self.state['decision']['reason'] = 'shop_route_blocked'
        return self.hold_worker(role,'shop_route_blocked')

    def free_capacity(self, role, needed):
        if len(role.backpack)+needed<=role.capacity:
            return False
        reserve = self.s.day_gate.reserve_stone(role)+int(bool(self.s.gap_guard.gaps)
                    and role.unit_id==self.s.gap_guard.worker_id)
        candidates = [name for name in MINERALS if name in role.backpack
                      and (name!='stone' or role.backpack.count(name)>reserve)]
        if candidates:
            name = min(candidates,key=lambda item:(self.turn.vendor_prices.get(item,0),item))
            if self.plan.add(role.unit_id,{'action':'drop','name':name}):
                self.s.coordinator.assign(role,'boss_capacity',name,role.pos)
                self.state['decision'].update(reason='freeing_capacity',dropped_item=name)
                return True
        self.state['decision']['reason'] = 'buyer_capacity_blocked'
        return self.hold_worker(role,'buyer_capacity_blocked')

    def worker(self, role):
        if role.unit_id!=self.buyer_id or role.kind!=WORKER or role.health<=0:
            return False
        self.state['decision'] = dict(round=self.turn.round_no,actor_id=role.unit_id,
            gold=self.plan.gold,available_gold=self.available_gold(),
            price=self.turn.shop_prices.get(BOSS_ORDER),held=role.backpack.count(BOSS_ORDER),reason='evaluating_worker')
        if self.tasks_finished():
            self.decide_orders()
        if not self.worker_mission_active(role):
            self.state['decision']['reason'] = ('disabled' if not self.s.settings.enable_boss_raid else
                'after_day_one' if self.turn.day!=1 else 'night' if not self.turn.is_day else
                'waiting_for_walls' if not self.dispatch_ready() else
                'summon_window_closed' if self.state.get('summon_window_closed') else
                'purchase_closed' if self.state.get('purchase_closed') else
                'no_successful_tasks' if self.target_orders()==0 else 'worker_mission_complete')
            return False
        if not self.state.get('mission_started'):
            ready = self.dispatch_ready()
            if ready:
                self.state['construction_approved_round'] = self.turn.round_no
            self.state.update(departure_authorized=True,departure_round=self.turn.round_no,
                departure_reason='walls_ready' if ready else 'shop_deadline',
                departure_budget_at_start=self.departure_budget(role))
        self.state['mission_started'] = True
        if role.pos not in self.s.guard.inner_cells():
            self.state['buyer_departed'] = True
        if not self.tasks_finished():
            self.state['decision']['reason'] = 'waiting_for_three_tasks_at_shop'
            if self.free_capacity(role,max(0,FIRST_DAY_LIMIT-self.state['acquired_count'])):
                return True
            return self.approach_shop(role)
        needed = max(0,self.target_orders()-self.state['acquired_count'])
        if needed and self.free_capacity(role,needed):
            return True
        if needed and not self.plan.near_zone(role,'weaponShop'):
            route = self.s.route(role)
            shops = adjacent_cells(self.turn,[p for p,k in self.turn.zones.items() if k=='weaponShop'])
            if route.nearest(shops) is None:
                return self.approach_shop(role)
        return self._deploy(role)

    def _deploy(self, role):
        self.state['decision'] = dict(round=self.turn.round_no,gold=self.plan.gold,
            available_gold=self.available_gold(),price=self.turn.shop_prices.get(BOSS_ORDER),
            held=role.backpack.count(BOSS_ORDER),acquired=self.state.get('acquired_count'),
            deployed=self.state.get('deployed_count'),purchase_closed=self.state.get('purchase_closed',False),
            actor_id=role.unit_id,missing_walls=len(self.s.missing_walls()),reason='evaluating')
        if not self.day_available():
            self.state['decision']['reason'] = ('disabled' if not self.s.settings.enable_boss_raid else
                'after_day_one' if self.turn.day!=1 else 'night' if not self.turn.is_day else 'active_task' if self.turn.phase_task else 'waiting_for_three_tasks')
            return False
        self.decide_orders()
        if self.state['target_count']==0:
            self.state['decision']['reason'] = 'no_successful_tasks'
            return False
        if self.state.get('summon_window_closed'):
            self.state['decision']['reason'] = 'summon_window_closed'
            return self.return_home(role)
        if self.state.get('pending_buy') or self.state.get('pending_use'):
            self.state['decision']['reason'] = 'awaiting_inventory_feedback'
            return self.hold_worker(role,'awaiting_inventory_feedback')
        proposal = self.proposal(role)
        if proposal is None:
            self.state['decision']['reason'] = ('purchase_history_unknown' if not self.state.get('history_known')
                else 'purchase_closed' if self.state.get('purchase_closed') else 'no_feasible_purchase_or_use')
            if self.state.get('order_acquired') or self.state.get('deployed_count'):
                if self.state['deployed_count'] and not self.state['deployment_ledger_confirmed']:
                    self.state['purchase_stage_done'] = True
                if self.held_orders(role) and not self.state.get('pending_use'):
                    # The use/return budget is no longer feasible. Preserve
                    # physical coupons instead of summoning without sight.
                    self.state.update(summon_window_closed=True,purchase_stage_done=True,
                                      status='scout_window_expired')
                    self.state['decision']['reason'] = 'scout_window_expired'
                return self.return_home(role)
            prepare = self.preparation(role)
            if prepare:
                self.state['decision']['reason'] = 'waiting_for_income_at_shop'
                self.state.update(status='shopping')
                return self.approach_shop(role,prepare['trip'][2])
            self.state['purchase_stage_done'] = True
            return False
        self.state['target_count'] = proposal['total']
        self.state['decision'].update(reason='using_order' if not proposal['buy_num'] else 'purchasing_order',
                                      buy_num=proposal['buy_num'],target_count=proposal['total'])
        buy_num = proposal['buy_num']
        if not buy_num:
            self.state['purchase_stage_done'] = True
            scout = self.s.raid_scouts
            if not scout.summon_ready():
                self.state['decision']['reason'] = 'waiting_for_scout:' + scout.state.get('readiness_reason','unavailable')
                self.state['status'] = 'waiting_for_scout'
                return self.hold_worker(role,'waiting_for_scout')
            positions = self.spawn_positions(proposal['uses'],scouted=True)
            if len(positions) != proposal['uses']:
                self.state['decision']['reason'] = 'no_scouted_spawn'
                return self.hold_worker(role,'no_scouted_spawn')
            spawn = positions[0]
            self.state['decision'].update(reason='using_scouted_order',spawn=spawn,
                layout_weapons=scout.state.get('weapons'),operator_cells=scout.state.get('operator_cells'))
            if self.plan.add(role.unit_id, {'action': 'use', 'name': BOSS_ORDER, 'targetPos': [spawn.dump()]}):
                self.state.pop('returned', None)
                self.state.update(status='summon_pending', spawn=spawn, summon_round=self.turn.round_no,
                    purchase_locked=True, pending_use={'round':self.turn.round_no,'spawn':spawn,
                        'held':role.backpack.count(BOSS_ORDER),'actor_id':role.unit_id,'scouted':True})
                return True
            return False
        trip = proposal['trip']
        self.state.pop('returned', None)
        self.state['status'] = 'shopping'
        if role.pos != trip[2]:
            return self.approach_shop(role,trip[2])
        self.state['purchase_attempt_round'] = self.turn.round_no
        if self.plan.add(role.unit_id, {'action': 'buy', 'name': BOSS_ORDER, 'num': buy_num}):
            self.state.update(status='buy_pending', buy_round=self.turn.round_no,
                pending_buy={'round':self.turn.round_no,'num':buy_num,
                    'held':role.backpack.count(BOSS_ORDER),'actor_id':role.unit_id})
            return True
        return False
