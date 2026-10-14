"""Capture real neighbouring imps; first-day returners deny home vision."""
from .boss_raid import BOSS_ORDER
from .first_day_tasks import FIRST_DAY_LIMIT, finished_count
from .grid import adjacent_cells
from .protocol import IMP, PIONEER, WORKER, Pos, distance, move_command


HOME_RADIUS = 4  # Shared vision, not an additional official catch distance.


class ImpDefense:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.imp_defense
        self.state.update(round=self.turn.round_no, roles={})
        base = self.turn.station()
        self.protected_cells = (set(self.turn.footprint(base)) if base else set())
        if base:
            self.protected_cells.update(w.pos for w in self.turn.weapons())

    def home_distance(self, pos):
        return min((distance(pos, p) for p in self.protected_cells), default=10_000)

    def note(self, role, reason, **extra):
        self.state['roles'][role.unit_id] = dict(position=role.pos, reason=reason, **extra)

    def catch_near(self, role):
        if self.turn.day != 1:
            return False  # First-night sight denial must not preempt later economy/tasks.
        if role.kind not in (PIONEER, WORKER) or role.health <= 0 or role.unit_id in self.plan.used:
            return False
        if role.kind == PIONEER and self.turn.day == 1 and not self.pioneer_ready():
            return False  # Finish all three attempts before spending a task turn on capture.
        targets = [u for u in self.turn.enemies if u.kind == IMP and u.health > 0
                   and distance(role.pos, u.pos) == 1 and u.unit_id not in self.plan.catch_targets]
        if not targets:
            return False
        target = min(targets, key=lambda u: (self.home_distance(u.pos), u.unit_id))
        if not self.plan.add(role.unit_id, dict(action='catch', targetPos=[target.pos.dump()])):
            return False
        self.note(role, 'catch_neighbour', target_id=target.unit_id, target=target.pos)
        if role.kind == WORKER:
            self.s.coordinator.assign(role, 'catch:imp', target.pos, role.pos)
        return True

    def catch_available(self):
        # Run before task commands and before cooperative yielding can claim a
        # neighbour's action. Expected death/gold never changes the live turn.
        for role in sorted(self.turn.alive((PIONEER, WORKER)), key=lambda u: (u.kind != PIONEER, u.unit_id)):
            self.catch_near(role)

    def tasks_done(self):
        return not self.turn.phase_task and (not self.s.settings.enable_tasks
                or finished_count(self.memory) >= FIRST_DAY_LIMIT)

    def pioneer_ready(self):
        return not self.turn.phase_task and finished_count(self.memory) >= FIRST_DAY_LIMIT

    def buyer_ready(self, role):
        raid = self.s.boss_raid
        state = raid.state
        if (not self.s.settings.enable_boss_raid or role.unit_id != raid.buyer_id
                or state.get('pending_buy') or state.get('pending_use')
                or BOSS_ORDER in role.backpack):
            return False
        if not self.turn.is_day:
            return True  # The actual daytime purchase/use window has ended.
        if not self.tasks_done():
            return False
        target = state.get('target_count', raid.successful_tasks())
        return (state.get('summon_window_closed') or state.get('purchase_closed')
                or state.get('deployed_count', 0) >= target)

    def defend(self, role):
        if (self.turn.day != 1 or not self.protected_cells or role.health <= 0
                or role.unit_id in self.plan.used):
            return False
        eligible = (self.pioneer_ready() if role.kind == PIONEER else
                    self.buyer_ready(role) if role.kind == WORKER else False)
        if not eligible:
            return False
        if self.catch_near(role):
            return True
        targets = [u for u in self.turn.enemies if u.kind == IMP and u.health > 0
                   and self.home_distance(u.pos) <= HOME_RADIUS
                   and u.unit_id not in self.plan.catch_targets]
        # A defender already near home stays local. A returning role may travel
        # from its actual shop/task position, without a nightfall time budget.
        region = {Pos(x, y) for x in range(self.turn.width) for y in range(self.turn.height)
                  if self.home_distance(Pos(x, y)) <= HOME_RADIUS + 1}
        route = self.s.route(role, region if role.pos in region else None) if targets else None
        choices = []
        for target in targets:
            goals = adjacent_cells(self.turn, [target.pos]) & region
            if role.kind == WORKER:
                goals -= self.s.coordinator.claimed_goals(role)
            goal = route.nearest(goals)
            if goal is not None:
                choices.append((route.exposure[goal], route.cost[goal], target.unit_id, target, goal))
        if choices:
            _, _, _, target, goal = min(choices, key=lambda row: row[:3])
            self.note(role, 'chase_home_imp', target_id=target.unit_id, target=target.pos, goal=goal)
            if role.kind == WORKER:
                if self.s.coordinator.move_to(role, {goal}, 'imp_chase', target.pos, route=route):
                    return True
            elif (step := route.step({goal})) is not None and self.plan.add(role.unit_id, move_command(step)):
                return True
            self.note(role, 'chase_no_legal_step', target_id=target.unit_id, target=target.pos)
        else:
            self.note(role, 'home_imp_unreachable' if targets else 'no_current_home_imp')
        # The buyer returns once after deployment, then the established supply
        # and repair schedule may resume. Repeatedly forcing home would make a
        # supply trip bounce between the base and shop on consecutive turns.
        raid = self.s.boss_raid.state
        returned_mission = raid.get('deployed_count', 0) > 0 or raid.get('mission_started')
        if role.kind == WORKER and returned_mission and not self.state.get('buyer_home_arrived'):
            goals = set(self.s.guard.duty_cells(role))
            if role.pos in goals:
                self.state['buyer_home_arrived'] = self.turn.round_no
                self.note(role, 'buyer_home_arrived')
            elif goals and self.s.coordinator.move_to(role, goals, 'imp_return_home', self.turn.station().pos):
                self.note(role, 'buyer_returning_home')
                return True
        return False

    def diagnostic(self):
        return dict(round=self.turn.round_no, team_id=self.turn.team_id, home_radius=HOME_RADIUS,
                    protected_cells=sorted(self.protected_cells),
                    buyer_id=self.s.boss_raid.buyer_id,
                    buyer_home_arrived=self.state.get('buyer_home_arrived'),
                    targets=[dict(id=u.unit_id, pos=u.pos, home_distance=self.home_distance(u.pos))
                             for u in self.turn.enemies if u.kind == IMP and u.health > 0],
                    roles={uid:dict(job, last_action_ok=self.turn.action_results.get(str(uid)),
                                    last_command=self.memory.last_commands.get(str(uid)))
                           for uid,job in self.state['roles'].items()})
