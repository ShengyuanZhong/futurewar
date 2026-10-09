"""Day-one task completion -> one BOSS order -> remote rear summon -> return."""
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
        self.trip = None
        self.spawn_checked = False
        self.spawn = None
        self.observe()

    def observe(self):
        role = next(iter(self.turn.alive((PIONEER,))), None)
        if not role:
            return
        if BOSS_ORDER in role.backpack:
            self.state['order_acquired'] = True
        status = self.state.get('status')
        if status == 'buy_pending' and self.turn.round_no > self.state['buy_round']:
            self.state['status'] = 'summoning' if BOSS_ORDER in role.backpack else 'shopping'
        if status == 'summon_pending' and self.turn.round_no > self.state['summon_round']:
            consecutive = self.state['summon_round'] == self.turn.round_no-1 and self.memory.last_round == self.turn.round_no-1
            result = self.turn.action_results.get(str(role.unit_id)) if consecutive else None
            if result is False:
                failed = self.state.setdefault('failed_positions', set())
                failed.add(self.state['spawn'])
                self.memory.pending_summon_positions.discard(self.state['spawn'])
                self.plan.summon_positions.discard(self.state['spawn'])
                self.state['status'] = 'summoning'
            elif result is True or BOSS_ORDER not in role.backpack:
                self.state['status'] = 'deployed'
            else:
                self.state['status'] = 'summoning'

    def tasks_finished(self):
        points = {(x, y) for day, x, y in self.memory.task_points_attempted if day == 1}
        return (self.s.settings.enable_boss_raid and self.turn.day == 1 and self.turn.is_day
                and len(points) >= 2 and not self.turn.phase_task)

    def shop_trip(self, role):
        if self.trip is not None:
            return self.trip
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
            total = route.cost[post] + 2 + back + self.s.settings.return_margin
            if total <= self.turn.daylight_left:
                options.append((total, route.cost[post], post))
        self.trip = min(options) if options else None
        return self.trip

    def budget_reserve(self):
        role = next(iter(self.turn.alive((PIONEER,))), None)
        if (not role or not self.tasks_finished() or BOSS_ORDER in role.backpack
                or self.state.get('status') in ('buy_pending', 'summon_pending', 'deployed')
                or self.state.get('order_acquired')
                or role.backpack_full or self.shop_trip(role) is None or self.spawn_position() is None):
            return 0
        return self.turn.shop_prices.get(BOSS_ORDER, 0)

    def spawn_position(self):
        if not self.spawn_checked:
            self.spawn = rear_spawn_position(self.turn, self.s.settings, self.plan.summon_positions,
                                             self.state.get('failed_positions', ()))
            self.spawn_checked = True
        return self.spawn

    def pioneer(self, role):
        if not self.tasks_finished():
            return False
        if (self.state.get('status') in ('summon_pending', 'deployed')
                or (self.state.get('order_acquired') and BOSS_ORDER not in role.backpack)):
            if self.state.get('status') not in ('summon_pending', 'deployed'):
                self.state['status'] = 'order_missing'
            if self.state.get('returned'):
                return False
            if role.pos == self.s.control_position(role):
                self.state['returned'] = True
                return False
            return self.s.move_to_control(role)
        if BOSS_ORDER in role.backpack:
            control = self.s.control_position(role)
            cost = self.s.route(role).cost.get(control, 10_000)
            margin = self.s.settings.return_margin if cost else 0
            if cost + 1 + margin > self.turn.daylight_left:
                return False
            spawn = self.spawn_position()
            if spawn is None:
                return False
            command = {'action': 'use', 'name': BOSS_ORDER, 'targetPos': [spawn.dump()]}
            if self.plan.add(role.unit_id, command):
                self.state.update(status='summon_pending', spawn=spawn, summon_round=self.turn.round_no)
                return True
            return False
        price = self.turn.shop_prices.get(BOSS_ORDER)
        trip = self.shop_trip(role)
        if price is None or role.backpack_full or trip is None or self.spawn_position() is None:
            return False
        self.state['status'] = 'shopping'
        if role.pos != trip[2]:
            step = self.s.route(role).step({trip[2]})
            if step is not None:
                return self.plan.add(role.unit_id, {'action': 'move', 'targetPos': [step.dump()]})
            return False
        reserve = max(0, 3 - self.plan.tower_count) * 25
        if self.plan.gold - reserve >= price:
            if self.plan.add(role.unit_id, {'action': 'buy', 'name': BOSS_ORDER, 'num': 1}):
                self.state.update(status='buy_pending', buy_round=self.turn.round_no)
                return True
        self.plan.used.add(role.unit_id)
        return True
