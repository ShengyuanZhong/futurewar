"""At most two first-day BOSS orders, confirmed from inventory and feedback."""
from dataclasses import replace
from .grid import Routes, adjacent_cells
from .protocol import PIONEER
from .summoning import rear_spawn_position


BOSS_ORDER = 'BossRobotSummonOrder'


class BossRaid:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.boss_raid
        self.trip = {}
        self.spawn_cache = {}
        self.observe()

    def observe(self):
        # A dead pioneer's preserved bag is evidence, although it cannot act.
        role = next((u for u in self.turn.ours if u.kind == PIONEER), None)
        if not role:
            return
        held = role.backpack.count(BOSS_ORDER)
        legacy = bool(self.state)
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
            self.state['acquired_count'] = min(2, max(held + self.state['deployed_count'],
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
                self.state['acquired_count'] = min(2, self.state['acquired_count'] + acquired)
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
                    self.state['deployed_count'] = min(2, self.state['deployed_count'] + 1)
                self.state['status'] = 'deployed'
                self.state['deployment_ledger_confirmed'] = True
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
                self.state['acquired_count'] = min(2, held + self.state['deployed_count'])
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
        points = {(x, y) for day, x, y in self.memory.task_points_attempted if day == 1}
        return (self.s.settings.enable_boss_raid and self.turn.day == 1 and self.turn.is_day
                and len(points) >= 2 and not self.turn.phase_task)

    def tasks_succeeded(self):
        return len({(x, y) for day, x, y in self.memory.task_points_succeeded if day == 1}) >= 2

    def day_available(self):
        return (self.s.settings.enable_boss_raid and self.turn.day == 1
                and self.turn.is_day and not self.turn.phase_task)

    def available_gold(self):
        return max(0, self.plan.gold - max(0, 3-self.plan.tower_count)*25)

    def held_orders(self, role):
        return min(role.backpack.count(BOSS_ORDER),
                   max(0, self.state['acquired_count']-self.state['deployed_count']))

    def shop_trip(self, role, use_count=1):
        if use_count in self.trip:
            return self.trip[use_count]
        control = self.s.control_position(role)
        if control is None:
            return None
        shops = [p for p, kind in self.turn.zones.items() if kind == 'weaponShop']
        route = self.s.route(role)
        options = []
        for post in adjacent_cells(self.turn, shops):
            if post not in route.cost:
                continue
            moved = replace(role, pos=post)
            simulated = replace(self.turn, ours=tuple(moved if u.unit_id == role.unit_id else u for u in self.turn.ours))
            back = Routes(simulated, moved, self.s.movement_reserved(role)).cost.get(control, 10_000)
            total = route.cost[post] + 1 + use_count + back + self.s.settings.return_margin
            if total <= self.turn.daylight_left:
                options.append((total, route.cost[post], post))
        self.trip[use_count] = min(options) if options else None
        return self.trip[use_count]

    def budget_reserve(self):
        role = next(iter(self.turn.alive((PIONEER,))), None)
        if (not role or not self.day_available()
                or self.state.get('pending_buy') or self.state.get('pending_use')):
            return 0
        proposal = self.proposal(role)
        if proposal:
            return proposal['buy_num'] * self.turn.shop_prices[BOSS_ORDER] if proposal['buy_num'] else 0
        prepare = self.preparation(role)
        return prepare['total'] * self.turn.shop_prices[BOSS_ORDER] if prepare else 0

    def spawn_position(self):
        positions = self.spawn_positions(1)
        return positions[0] if positions else None

    def spawn_positions(self, count):
        used = set(self.plan.summon_positions) | set(self.state['spawns'])
        failed = self.state.get('failed_positions', set())
        key = (count, frozenset(used), frozenset(failed))
        if key not in self.spawn_cache:
            positions = []
            for _ in range(count):
                pos = rear_spawn_position(self.turn, self.s.settings, used, failed)
                if pos is None:
                    break
                positions.append(pos); used.add(pos)
            self.spawn_cache[key] = positions
        return self.spawn_cache[key]

    def proposal(self, role):
        held = self.held_orders(role)
        deployed = self.state['deployed_count']
        acquired = self.state['acquired_count']
        price = self.turn.shop_prices.get(BOSS_ORDER)
        needed_for_two = max(0, 2-acquired)
        wealthy = (price is not None and self.available_gold() >= price*needed_for_two)
        dual = (self.tasks_succeeded() or wealthy or acquired >= 2
                or self.state.get('target_count') == 2)
        permitted = self.tasks_finished() or dual or held > 0
        if not permitted:
            return None
        ceiling = 2 if dual else 1
        top_up = (deployed == 1 and acquired == 1 and held == 0
                  and self.state['history_known'] and self.state['deployment_ledger_confirmed']
                  and not self.state.get('purchase_closed'))
        if self.state.get('purchase_locked') and not top_up:
            ceiling = min(2, self.state.get('target_count', max(1, acquired)))
        for total in range(ceiling, deployed, -1):
            uses = total-deployed
            if uses > 10-self.plan.summon_used:
                continue
            buy_num = max(0, uses-held)
            if buy_num:
                if (self.state.get('purchase_closed') or (self.state.get('purchase_locked') and not top_up)
                        or price is None or acquired+buy_num > 2
                        or len(role.backpack)+buy_num > role.capacity
                        or self.available_gold() < buy_num*price):
                    continue
                trip = self.shop_trip(role, uses)
                if trip is None:
                    continue
            else:
                trip = None
                control = self.s.control_position(role)
                if control is None:
                    continue
                cost = self.s.route(role).cost.get(control, 10_000)
                if cost+uses+(self.s.settings.return_margin if cost else 0) > self.turn.daylight_left:
                    continue
            positions = self.spawn_positions(uses)
            if len(positions) == uses:
                return dict(total=total, uses=uses, buy_num=buy_num, trip=trip, positions=positions)
        return None

    def preparation(self, role):
        """Keep the old affordable-time shop wait while miners earn the price."""
        if (not (self.tasks_finished() or self.tasks_succeeded())
                or self.state['acquired_count'] or self.state.get('purchase_closed')
                or BOSS_ORDER not in self.turn.shop_prices):
            return None
        for total in range(2 if self.tasks_succeeded() else 1, 0, -1):
            if (len(role.backpack)+total > role.capacity or total > 10-self.plan.summon_used
                    or len(self.spawn_positions(total)) != total):
                continue
            trip = self.shop_trip(role, total)
            if trip is not None:
                return dict(total=total, trip=trip)
        return None

    def return_home(self, role):
        if self.state.get('returned'):
            return False
        if role.pos == self.s.control_position(role):
            self.state['returned'] = True
            return False
        return self.s.move_to_control(role)

    def pioneer(self, role):
        if not self.day_available():
            return False
        if self.state.get('pending_buy') or self.state.get('pending_use'):
            return self.return_home(role)
        proposal = self.proposal(role)
        if proposal is None:
            if self.state.get('order_acquired') or self.state.get('deployed_count'):
                return self.return_home(role)
            prepare = self.preparation(role)
            if prepare:
                self.state.update(status='shopping', target_count=prepare['total'])
                post = prepare['trip'][2]
                if role.pos != post:
                    step = self.s.route(role).step({post})
                    return step is not None and self.plan.add(role.unit_id, {'action':'move','targetPos':[step.dump()]})
                self.plan.used.add(role.unit_id)
                return True
            return False
        self.state['target_count'] = proposal['total']
        buy_num = proposal['buy_num']
        if not buy_num:
            spawn = proposal['positions'][0]
            if self.plan.add(role.unit_id, {'action': 'use', 'name': BOSS_ORDER, 'targetPos': [spawn.dump()]}):
                self.state.pop('returned', None)
                self.state.update(status='summon_pending', spawn=spawn, summon_round=self.turn.round_no,
                    purchase_locked=True, pending_use={'round':self.turn.round_no,'spawn':spawn,
                        'held':role.backpack.count(BOSS_ORDER),'actor_id':role.unit_id})
                return True
            return False
        trip = proposal['trip']
        self.state.pop('returned', None)
        self.state['status'] = 'shopping'
        if role.pos != trip[2]:
            step = self.s.route(role).step({trip[2]})
            if step is not None:
                return self.plan.add(role.unit_id, {'action': 'move', 'targetPos': [step.dump()]})
            return False
        if self.plan.add(role.unit_id, {'action': 'buy', 'name': BOSS_ORDER, 'num': buy_num}):
            self.state.update(status='buy_pending', buy_round=self.turn.round_no,
                pending_buy={'round':self.turn.round_no,'num':buy_num,
                    'held':role.backpack.count(BOSS_ORDER),'actor_id':role.unit_id})
            return True
        return False
