"""Deterministic baseline strategy, separated from transport and LLM execution."""
from collections import Counter
from dataclasses import replace
import time
from .actions import SUMMON_ITEMS, ActionPlan
from .combat import choose_targets
from .construction import select_defense_layout
from .grid import Routes, adjacent_cells
from .worker_safety import robot_danger
from .worker_coordinator import WorkerCoordinator
from .wall_guard import WallGuard
from .imp_policy import ImpController
from .imp_defense import ImpDefense
from .gap_defense import WallGapDefense
from .boss_raid import BOSS_ORDER, BossRaid
from .robot_raider import RobotRaider
from .raid_scouts import RaidScouts
from .first_night_defense import FirstNightDefense
from .day_gate import DayGate
from .sealed_home import SealedHome
from .operating_home import OperatingHome
from .stone_planner import StonePlanner
from .wall_schedule import WallSchedule
from .summoning import rear_spawn_position
from . import upgrade_policy
from .first_day_tasks import TASK_SEQUENCE, task_attempts, task_number, finished_count, finish_attempt
from .protocol import (IMP, MINERALS, PIONEER, TOWER_TYPES, Pos, Turn, Unit,
                       attack_command, build_command, collect_command, distance, move_command)


class Strategy:
    def __init__(self, turn: Turn, plan: ActionPlan, memory):
        self.turn, self.plan, self.memory = turn, plan, memory
        self.settings = plan.settings
        self.routes: dict[tuple, Routes] = {}
        self.goals: set[Pos] = set()
        self.maintenance_claims: set[int] = set()
        self.purchase_claims: set[str] = set()
        self.deadline = float("inf")
        self.layout = select_defense_layout(turn, self.settings, memory.defense_layout)
        memory.defense_layout = self.layout
        self.danger = robot_danger(turn)
        self.sealed_home = SealedHome(self)
        self.guard = WallGuard(self)
        self.coordinator = WorkerCoordinator(self)
        self.imp = ImpController(self)
        self.gap_guard = WallGapDefense(self)
        self.gap_guard.choose_responders()
        self.first_defense = FirstNightDefense(self)
        self.day_gate = DayGate(self)
        self.boss_raid = BossRaid(self)
        self.raider = RobotRaider(self)
        self.raid_scouts = RaidScouts(self)
        self.wall_schedule = WallSchedule(self)
        self.stone_planner = StonePlanner(self)
        self.operating_home = OperatingHome(self)
        self.imp_defense = ImpDefense(self)
        self.raid_scouts.refresh_dispatch()

    def movement_reserved(self, role: Unit | None = None) -> set[Pos]:
        """Reserve gun slots and actual construction appointments, not an empty wall ring."""
        reserved = set(self.plan.reserved)
        reserved.update(self.goals)
        reserved.update(self.layout.tower_sites)
        # The pioneer acts first: retain the workers' live construction
        # appointments from the last frame so it does not enter their targets.
        workers = {w.unit_id:w for w in self.turn.workers()}
        for uid, job in self.memory.worker_tasks.items():
            worker = workers.get(uid)
            target, kind = job.get('target'),job.get('kind','')
            if worker is None or job.get('round',0)<self.turn.round_no-1 or not isinstance(target,Pos):
                continue
            if ((kind=='build:wall' and 'stone' in worker.backpack and target in self.construction_walls())
                    or (kind=='build:rocket' and self.plan.gold>=25 and self.plan.tower_count<3
                        and target in self.layout.tower_sites)):
                reserved.add(target)
        guard = getattr(self,'gap_guard',None)
        if role is not None and guard and guard.gap is not None:
            if guard.enter_gap(role):
                if guard.gap not in self.plan.reserved:
                    reserved.discard(guard.gap)
            elif guard.active_role(role):
                # The standby IMP must not use the body worker's breach as a
                # shortcut before the actual takeover condition is observed.
                reserved.add(guard.gap)
        courier = role is not None and self.sealed_home.needs_operator(role)
        if (role is None or role.kind != PIONEER) and not courier and self.layout.operator_pos is not None:
            reserved.add(self.layout.operator_pos)
        if self.turn.day == 1 and role is not None and role.unit_id == self.memory.raid_scouts.get('worker_id'):
            reserved.update(p for u in self.memory.enemy_structures.values() if u.health > 0
                            for p in self.turn.footprint(u))
            scouts = getattr(self,'raid_scouts',None)
            if scouts is not None and scouts.active:
                reserved.update(scouts.spawn_cells() | scouts.attack_lanes())
        return reserved

    def worker_region(self, role: Unit, allowed=None):
        if (allowed is None and role.kind=='worker' and self.turn.day==1 and self.turn.is_day
                and len(self.turn.weapons())>=3 and self.sealed_home.enabled
                and role.pos in self.sealed_home.outside):
            return self.sealed_home.outside
        return allowed

    def route(self, role: Unit, allowed: set[Pos] | None = None) -> Routes:
        allowed = self.worker_region(role,allowed)
        reserved = self.movement_reserved(role)
        key = (role.unit_id, frozenset(reserved), None if allowed is None else frozenset(allowed))
        if key not in self.routes:
            self.routes[key] = Routes(self.turn, role, reserved,
                                      self.danger if role.kind == "worker" else None, allowed)
        return self.routes[key]

    def travel(self, role: Unit, cells, job: str = 'travel') -> bool:
        cells = tuple(cells)
        if role.kind == 'worker':
            return self.coordinator.move_to(role,adjacent_cells(self.turn,cells),job,cells)
        route = self.route(role)
        goal = route.nearest(adjacent_cells(self.turn, cells))
        step = route.step([goal]) if goal is not None else None
        return step is not None and self.plan.add(role.unit_id, move_command(step))

    def cost(self, role: Unit, cells) -> int:
        cells = tuple(cells)
        route = self.route(role)
        if role.kind == 'worker' and route.nearest(adjacent_cells(self.turn,cells)) is None:
            route = self.coordinator.diagnostic_route(role)
        return route.cost.get(route.nearest(adjacent_cells(self.turn, cells)), 10_000)

    def interact(self, role: Unit, target: Pos, command: dict, footprint=None) -> bool:
        cells = footprint or [target]
        if self.plan.near(role, cells):
            handled = self.plan.add(role.unit_id, command)
            if handled and role.kind == 'worker':
                self.coordinator.assign(role,command['action']+':'+command.get('name',''),target,role.pos)
            return handled
        if role.kind == 'worker':
            return self.coordinator.move_to(role, adjacent_cells(self.turn, cells),
                command['action']+':'+command.get('name',''), target)
        return self.travel(role, cells, command['action']+':'+command.get('name',''))

    def run(self) -> None:
        self.imp_defense.catch_available()
        # Resolve the pioneer first, so workers never claim its next step or control cell.
        available = sorted(self.turn.controllable(), key=lambda r: (r.kind != PIONEER, r.kind != IMP,
                           r.unit_id != self.gap_guard.worker_id,
                           r.unit_id != self.first_defense.worker_id,
                           -self.coordinator.job(r).get('stalled',0), r.unit_id != self.guard.worker_id, r.unit_id))
        self.opening_stage()
        for role in available:
            if role.unit_id in self.plan.used:
                continue
            if time.monotonic() >= self.deadline:
                break
            if role.kind == IMP:
                if (not self.raid_scouts.opening_imp(role) and not self.gap_guard.imp(role)
                        and not self.raid_scouts.imp(role)):
                    self.imp.decide(role)
                continue
            maximum = 200 if role.kind == PIONEER else 220
            if role.health <= maximum // 2 and "Medicine" in role.backpack:
                self.plan.add(role.unit_id, {"action": "use", "name": "Medicine"})
                continue
            if role.kind == PIONEER:
                if (self.turn.day==1 and not self.turn.phase_task
                        and (finished_count(self.memory)>=len(TASK_SEQUENCE) or not self.settings.enable_tasks)):
                    # The shopping worker handles the raid; the pioneer returns
                    # immediately after the three actual attempts settle.
                    if self.imp_defense.defend(role):
                        continue
                    if not self.sealed_home.pioneer_yield(role):
                        self.operate_weapons(role) if not self.turn.is_day else self.move_to_control(role)
                    continue
                if self.pioneer_should_defend(role):
                    self.operate_weapons(role)
                    continue
                if self.clear_build_cell(role):
                    continue
                if (self.turn.day==1 and self.settings.enable_tasks
                        and not self.boss_raid.tasks_finished()):
                    # Attempt Task2 -> Task1 -> Task2 before shopping. Day-one
                    # task admission never reserves a shopping/return budget.
                    if not self.task(role):
                        self.move_to_control(role)
                    continue
                # Preserve the opening budget; tasks can earn money without spending it.
                if self.opening_stage() in ("complete", "unconfigured"):
                    if self.consume(role, allow_travel=False) or self.treasure(role):
                        continue
                if self.turn.is_day and (self.task(role) or self.sell(role)):
                    continue
                if self.sealed_home.pioneer_yield(role):
                    continue
                self.move_to_control(role)
            else:
                self.run_worker(role)
        robots = self.raider.formation.ordered_robots()
        for index,robot in enumerate(robots):
            if time.monotonic() >= self.deadline:
                for skipped in robots[index:]:
                    self.raider.diag.set(skipped,reason='skip_deadline_before_robot_loop')
                break
            if robot.robot_id not in self.plan.used:
                self.raider.decide(robot)
            else:
                self.raider.diag.set(robot,reason='skip_already_acted')
        for role in self.turn.workers():
            if self.coordinator.job(role).get('round') != self.turn.round_no:
                command = self.plan.commands.get(str(role.unit_id),{})
                points = command.get('targetPos',[])
                self.coordinator.assign(role,command.get('action','wait')+':'+command.get('name',''),
                    Pos.load(points[0]) if points else None,role.pos)

    def run_worker(self, role: Unit) -> None:
        """One economic schedule; night adds safety and assigned guard duty."""
        if self.operating_home.worker(role):
            return
        if self.imp_defense.catch_near(role):
            return
        if self.boss_raid.worker(role):
            return
        if self.imp_defense.defend(role):
            return
        if self.sealed_home.evacuate(role):
            return
        if self.sealed_home.wait_for_operator(role):
            return
        if self.raid_scouts.worker(role):
            return
        if self.day_gate.worker(role):
            return
        if self.gap_guard.worker(role):
            return
        if self.first_defense.worker(role):
            return
        if self.coordinator.hold_for_yield(role):
            return
        if self.guard.full_time and not self.turn.is_day:
            self.guard.on_duty(role)
            return
        if self.guard.is_guard(role) and not self.turn.is_day:
            self.guard.on_duty(role)
            return
        if self.evade_worker(role):
            return
        if self.clear_build_cell(role):
            return
        if self.turn.is_day and self.opening_worker(role):
            return
        if self.turn.is_day and self.guard.daytime(role):
            return
        self.worker(role)

    def control_position(self, role: Unit) -> Pos | None:
        weapons = self.turn.weapons()
        if not weapons:
            return self.layout.operator_pos
        route = self.route(role)
        cells = adjacent_cells(self.turn, [w.pos for w in weapons])
        cells -= set(self.settings.build_cells(self.turn, "wall"))
        cells -= set(self.layout.tower_sites)
        reachable = [p for p in cells if p in route.cost]
        if not reachable:
            return None
        return min(reachable, key=lambda p: (
            -sum(distance(p, w.pos) <= 1 for w in weapons),
            p != self.layout.operator_pos, route.cost[p], p))

    def pioneer_should_defend(self, role: Unit) -> bool:
        if (self.turn.day==1 and self.settings.enable_tasks
                and (self.turn.phase_task or
                     finished_count(self.memory)<len(TASK_SEQUENCE))):
            # Complete the three first-day attempts even after night arrives.
            # Once they finish the normal night weapon schedule resumes.
            return False
        if not self.turn.weapons():
            return False
        target = self.control_position(role)
        cost = self.route(role).cost.get(target, 10_000)
        return not self.turn.is_day or self.turn.daylight_left <= cost + self.settings.return_margin

    def move_to_control(self, role: Unit) -> bool:
        target = self.control_position(role)
        step = self.route(role).step([target]) if target is not None else None
        return step is not None and self.plan.add(role.unit_id, move_command(step))

    def operate_weapons(self, role: Unit) -> bool:
        if not self.turn.is_day:
            health = {r.robot_id: r.health for r in self.turn.hostile_robots()}
            choices = []
            for tower in self.turn.weapons():
                if tower.cooldown != 0 or distance(role.pos, tower.pos) > 1:
                    continue
                predicted = dict(health)
                targets = choose_targets(self.turn, tower, predicted, self.deadline)
                if targets:
                    value = sum(health[rid] - remaining for rid, remaining in predicted.items())
                    choices.append((value, -tower.unit_id, tower, targets))
            if choices:
                _, _, tower, targets = max(choices, key=lambda entry: entry[:2])
                return self.plan.add(tower.unit_id, attack_command(role.unit_id, targets))
            # With separated towers, seek an accessible ready weapon with a target.
            ready = []
            for tower in self.turn.weapons():
                if tower.cooldown == 0 and choose_targets(self.turn, tower, dict(health), self.deadline):
                    ready.append(tower.pos)
            if ready and self.travel(role, ready):
                return True
        return self.move_to_control(role)

    def missing_walls(self) -> list[Pos]:
        standing = {w.pos for w in self.turn.walls()}
        return [p for p in self.settings.build_cells(self.turn, "wall") if p not in standing]

    def construction_walls(self) -> list[Pos]:
        return self.missing_walls()

    def stone_targets(self) -> dict[int, int]:
        return self.stone_planner.targets()

    def opening_stage(self) -> str:
        if self.memory.opening_complete:
            return "complete"
        if not self.settings.build_cells(self.turn, "rocket"):
            return "unconfigured"
        if len(self.turn.weapons()) < 3:
            return "towers"
        if not self.missing_walls():
            self.memory.opening_complete = True
            return "complete"
        quota = self.stone_targets()
        if any(w.backpack.count("stone") < quota[w.unit_id] for w in self.turn.workers()):
            return "stockpile"
        return "walls"

    def clear_build_cell(self, role: Unit) -> bool:
        # Crossing an empty blueprint cell is legal. Only yield when someone
        # can actually build here; blanket clearance caused repeated retreats.
        walls = set(self.construction_walls())
        sites = self.movement_reserved(role) & (walls | set(self.layout.tower_sites))
        builders = [w for w in self.turn.workers() if 'stone' in w.backpack]
        if walls == {role.pos} and any(distance(w.pos, role.pos)<=1 for w in builders):
            sites.add(role.pos)
        if role.kind != PIONEER and self.layout.operator_pos is not None:
            sites.add(self.layout.operator_pos)
        if role.pos not in sites:
            return False
        blocked = self.turn.blocked(role) | self.movement_reserved(role)
        for target in sorted(role.pos.neighbours(), key=lambda p: (self.danger.get(p, 0) if role.kind == "worker" else 0, p)):
            if role.kind == "worker" and self.danger.get(target, 0) > self.danger.get(role.pos, 0):
                continue
            if self.turn.land(target) and target not in blocked:
                if self.plan.add(role.unit_id, move_command(target)):
                    if role.kind == 'worker':
                        self.coordinator.assign(role, 'clear_site', role.pos, target, moving=True)
                    return True
        return False

    def opening_worker(self, role: Unit) -> bool:
        stage = self.opening_stage()
        if stage in ("complete", "unconfigured"):
            return False
        if stage == "towers":
            if not self.build_weapon(role):
                # A teammate may own the remaining build position or this
                # turn's gold. Start gathering material instead of idling.
                if self.plan.gold < 25 and self.plan.tower_count < 3 and self.sell(role):
                    return True
                if not self.mine(role, need_stone=True):
                    self.mine(role)
            return True
        quota = self.stone_targets().get(role.unit_id, 0)
        if self.stone_planner.can_build_now(role) and self.build_wall(role,local_only=True):
            return True
        if role.backpack.count("stone") < quota:
            if role.backpack_full:
                self.sell(role, keep_stone=True)
            else:
                if not self.mine(role, need_stone=True):
                    self.mine(role)
            return True
        # A worker with its material share can build while its teammate mines.
        # If all remaining stone is already in the other bag, keep mining income.
        if "stone" in role.backpack and self.build_wall(role):
            return True
        if self.wall_schedule.enabled and self.wall_schedule.assigned_missing(role,ignore_enemy_occupied=True):
            # A deferred construction post is not permission to leave for
            # unrelated income mining before the personal wall segment ends.
            self.coordinator.assign(role,'build_wait',None,role.pos)
            self.plan.used.add(role.unit_id)
            return True
        if role.backpack_full:
            self.sell(role, keep_stone=True)
        else:
            self.mine(role)
        return True

    def night_worker(self, role: Unit) -> None:
        """Compatibility entry; no separate night-only mining policy."""
        self.run_worker(role)

    def evade_worker(self, role: Unit) -> bool:
        """Stop economic work in a threat zone; flee if a non-worsening step exists."""
        current = self.danger.get(role.pos, 0)
        if not current:
            return False
        route = self.route(role)
        safe = {p for p in route.cost if not self.danger.get(p, 0)}
        step = route.step(safe)
        if step is not None and self.danger.get(step, 0) <= current:
            self.plan.add(role.unit_id, move_command(step))
            return True
        neighbours = [p for p in role.pos.neighbours() if route.cost.get(p) == 1
                      and self.danger.get(p, 0) < current]
        if neighbours:
            target = min(neighbours, key=lambda p: (self.danger.get(p, 0), p))
            self.plan.add(role.unit_id, move_command(target))
        return True

    def build_wall(self, role: Unit, local_only: bool = False) -> bool:
        if not self.turn.is_day or role.backpack.count('stone') <= self.day_gate.reserve_stone(role):
            return False
        if self.sealed_home.enabled and role.pos not in self.sealed_home.outside:
            return False
        walls = [p for p in self.construction_walls() if p not in self.turn.blocked(role)
                 and p not in self.plan.reserved and p not in self.goals and p != role.pos
                 and not self.coordinator.target_owned(role, p, 'build:wall')]
        for target in self.wall_schedule.targets(role,walls,local_only=local_only):
            if distance(role.pos,target)>1 and any(
                    w.unit_id!=role.unit_id and w.unit_id not in self.plan.used
                    and 'stone' in w.backpack and distance(w.pos,target)==1
                    and w.pos in self.sealed_home.outside
                    and not self.boss_raid.worker_mission_active(w) and not self.raid_scouts.is_worker(w)
                    and (not self.wall_schedule.enabled or len(walls)==1
                         or target in self.wall_schedule.state.get('arcs',{}).get(w.unit_id,()))
                    for w in self.turn.workers()):
                # A courier must not claim the local builder's immediate wall.
                self.coordinator.assign(role,'construction_share',None,role.pos)
                continue
            # Do not spend the last daylight rounds walking towards illegal night work.
            cost = self.wall_schedule.cost(role,target) if self.wall_schedule.enabled else self.cost(role,[target])
            if cost + 1 > self.turn.daylight_left:
                continue
            if not self.wall_keeps_exit(role,target):
                continue
            if self.wall_schedule.enabled:
                posts=self.wall_schedule.posts(role,target)
                if role.pos in posts:
                    handled=self.plan.add(role.unit_id,build_command(target,'wall'))
                    if handled:
                        self.coordinator.assign(role,'build:wall',target,role.pos)
                else:
                    handled=self.coordinator.move_to(role,posts,'build:wall',target)
            else:
                handled=self.interact(role,target,build_command(target,'wall'))
            if handled:
                self.goals.add(target)
                return True
        return False

    def consume(self, role: Unit, allow_travel: bool = True, allowed: set[Pos] | None = None) -> bool:
        maximum = 200 if role.kind == PIONEER else 220
        if role.health <= maximum // 2 and "Medicine" in role.backpack:
            return self.plan.add(role.unit_id, {"action": "use", "name": "Medicine"})
        if not self.turn.is_day:
            for name in ("Bomb", "DizzyWeapon"):
                if name not in role.backpack:
                    continue
                robots = [r for r in self.turn.hostile_robots() if r.health > 0 and (name == "Bomb" or r.abnormal_state != "dizzy")]
                candidates = {p for r in robots for p in (r.pos,) + r.pos.neighbours() if self.turn.in_bounds(p)}
                if candidates:
                    target = max(sorted(candidates), key=lambda p: sum(min(r.health, 100) if name == "Bomb" else 1 for r in robots if distance(r.pos, p) <= 1))
                    hit_count = sum(distance(r.pos, target) <= 1 for r in robots)
                    if hit_count >= 2:
                        return self.plan.add(role.unit_id, {"action": "use", "name": name, "targetPos": [target.dump()]})
        for name in sorted(set(role.backpack) & SUMMON_ITEMS):
            if name == BOSS_ORDER and self.settings.enable_boss_raid:
                continue  # Reserved for the task-complete day-one buyer workflow.
            if self.plan.summon_used < 10:
                spawn = rear_spawn_position(self.turn, self.settings, self.plan.summon_positions)
                if spawn is not None:
                    return self.plan.add(role.unit_id, {"action": "use", "name": name, "targetPos": [spawn.dump()]})
        # Purchase and use share one observed-state stage, regardless of bag order.
        candidates = self.upgrade_candidates()
        if candidates and candidates[0].kind == "wall":
            front = min(self.wall_depth(b) for b in candidates)
            candidates = [b for b in candidates if self.wall_depth(b) == front]
        candidates = [b for b in candidates if self.upgrade_name(b) in role.backpack]
        choices = [(self.upgrade_name(b), b) for b in sorted(candidates, key=lambda b: (
            b.kind != "rocket" if b.kind in TOWER_TYPES else False,
            b.health / self.building_max_health(b), self.cost(role, self.turn.footprint(b)), b.unit_id))]
        # An upgrade also heals the wall; only consider a carried fixer afterwards.
        if "WallFixer" in role.backpack and not self.guard.is_guard(role):
            repairs = [w for w in self.operating_home.retained_walls() if w.health < self.building_max_health(w)]
            choices.extend(("WallFixer", w) for w in sorted(repairs, key=lambda w: (
                self.wall_depth(w), w.health / self.building_max_health(w), self.cost(role, [w.pos]), w.unit_id)))
        for name, building in choices:
            if building.unit_id in self.plan.upgrade_targets | self.maintenance_claims:
                continue
            cells = self.turn.footprint(building)
            if not allow_travel and not self.plan.near(role, cells):
                continue
            if allowed is not None:
                if role.pos not in allowed:
                    continue
                if not self.plan.near(role, cells):
                    if self.coordinator.move_to(role, adjacent_cells(self.turn, cells),
                                                'use:'+name, tuple(cells), allowed=allowed):
                        self.maintenance_claims.add(building.unit_id)
                        return True
                    continue
            if self.interact(role, building.pos, {"action": "use", "name": name, "targetPos": [building.pos.dump()]}, cells):
                self.maintenance_claims.add(building.unit_id)
                return True
        return False

    def worker(self, role: Unit) -> None:
        """Upgrade, trade and collect in the same order on either side of dusk."""
        if self.rebuild_wall(role):
            return
        if self.plan.near_zone(role, "weaponShop") and self.buy_upgrade(role):
            return
        if self.consume(role) or self.build_weapon(role):
            return
        if self.sell(role, keep_stone=bool(self.missing_walls())) or self.buy_upgrade(role):
            return
        quota = self.stone_targets().get(role.unit_id, 0) if self.missing_walls() else 0
        gathering = self.mine(role, need_stone=role.backpack.count('stone') < quota)
        if not gathering and role.backpack.count('stone') < quota:
            gathering = self.mine(role)
        if not gathering and not self.turn.is_day:
            # Economic work is unreachable: take a safe route to shelter or wait.
            self.coordinator.move_to(role, self.guard.inner_cells(), 'shelter')

    def rebuild_wall(self, role: Unit) -> bool:
        """Repair a breach before economy; only build from actual observed stone."""
        if not self.turn.is_day or not self.missing_walls():
            return False
        if "stone" in role.backpack and self.build_wall(role):
            return True
        quota = self.stone_targets().get(role.unit_id, 0)
        if role.backpack.count("stone") < quota:
            if role.backpack_full:
                return self.sell(role, keep_stone=True)
            return self.mine(role, need_stone=True)
        return False

    @staticmethod
    def building_max_health(building: Unit) -> int:
        return 1500 * building.level if building.kind == "station" else 500 + 500 * building.level

    def wall_depth(self, building: Unit) -> int:
        """Smallest depth faces the enemy: rightmost for left bases, vice versa."""
        return building.pos.x if self.settings.mirrored_layout(self.turn) else -building.pos.x

    @staticmethod
    def upgrade_name(building: Unit) -> str:
        prefix = "Wall" if building.kind == "wall" else "Station" if building.kind == "station" else "Weapon"
        return f"{prefix}UpgradeVoucher{building.level}"

    def upgrade_candidates(self) -> list[Unit]:
        """First unfinished observed tier; never advance on a submitted use alone."""
        return upgrade_policy.upgrade_candidates(self)

    def upgrades_complete(self) -> bool:
        return upgrade_policy.upgrades_complete(self)

    def wall_keeps_exit(self, role: Unit, target: Pos) -> bool:
        if self.sealed_home.enabled:
            return self.sealed_home.safe_wall(target)
        if self.day_gate.enabled and target == self.day_gate.pos:
            return self.day_gate.can_seal(role)
        # Do not close a reachable route to a vendor/task point with this wall.
        if distance(role.pos, target) > 1:
            return True
        landmarks = [p for p, k in self.turn.zones.items() if k == "vendor" or k.startswith(self.turn.team_type + "TaskPoint")]
        goals = adjacent_cells(self.turn, landmarks)
        for actor in self.turn.controllable():
            reserved = set(self.plan.reserved)
            command = self.plan.commands.get(str(actor.unit_id),{})
            if command.get('action') == 'move':
                # This actor's own reserved destination is its exit, not an
                # obstacle. Other actors' destinations remain reserved.
                reserved.discard(Pos.load(command['targetPos'][0]))
            before = Routes(self.turn, actor, reserved)
            after = Routes(self.turn, actor, reserved | {target})
            if before.nearest(goals) is not None and after.nearest(goals) is None:
                return False
            if (actor.kind == PIONEER and self.layout.operator_pos in before.cost
                    and self.layout.operator_pos not in after.cost):
                return False
        return True

    def build_weapon(self, role: Unit) -> bool:
        if not self.turn.is_day or self.plan.tower_count >= 3 or self.plan.gold < 25:
            return False
        sites = [p for p in self.layout.tower_sites if p in self.settings.build_cells(self.turn, "rocket")
                 if p not in self.turn.blocked(role) and p not in self.plan.reserved and p not in self.goals and p != role.pos]
        desired = Counter(self.settings.loadout)
        desired.subtract(t.kind for t in self.turn.weapons())
        desired.subtract(c["name"] for c in self.plan.commands.values() if c["action"] == "build" and c["name"] in TOWER_TYPES)
        kind = next((k for k in self.settings.loadout if desired[k] > 0), self.settings.loadout[0])
        for target in sorted(sites, key=lambda p: (self.cost(role, [p]), p)):
            if self.interact(role, target, build_command(target, kind)):
                self.goals.add(target)
                return True
        return False

    def sell(self, role: Unit, keep_stone: bool = False) -> bool:
        minerals = Counter(i for i in role.backpack if i in MINERALS and i in self.turn.vendor_prices
                           and (i != "stone" or not keep_stone))
        gate = getattr(self, 'day_gate', None)
        if not keep_stone and gate is not None:
            minerals['stone'] = max(0, minerals['stone'] - gate.reserve_stone(role))
            if not minerals['stone']:
                minerals.pop('stone', None)
        if not minerals:
            return False
        near = self.plan.near_zone(role, "vendor")
        if not near and not role.backpack_full and sum(minerals.values()) < self.settings.sell_batch:
            return False
        name = max(minerals, key=lambda n: (minerals[n] * self.turn.vendor_prices[n], n))
        vendors = [p for p, k in self.turn.zones.items() if k == "vendor"]
        if near:
            return self.plan.add(role.unit_id, {"action": "sell", "name": name, "num": minerals[name]})
        return self.travel(role, vendors, 'sell')

    def buy_upgrade(self, role: Unit) -> bool:
        if role.backpack_full:
            return False
        shops = [p for p, k in self.turn.zones.items() if k == "weaponShop"]
        reserve = max(0, 3 - self.plan.tower_count) * 25 if self.settings.build_cells(self.turn, "rocket") else 0
        reserve += self.guard.budget_reserve()
        reserve += self.first_defense.reserve_gold()
        reserve += self.boss_raid.budget_reserve()
        planned = Counter(i for r in self.turn.controllable() for i in r.backpack)
        for command in self.plan.commands.values():
            if command["action"] == "buy":
                planned[command["name"]] += command.get("num", 1)
            elif command["action"] == "use":
                planned[command["name"]] -= 1
        needs = upgrade_policy.purchase_needs(self)
        if not needs or not shops:
            return False
        needed = [(name, count) for name, count in needs if count > planned[name]]
        if not needed:
            return False
        name, demand = needed[0]
        if name.startswith('WeaponUpgradeVoucher') and not self.boss_raid.weapon_upgrades_ready():
            return False
        if name not in self.turn.shop_prices:
            return False
        price = self.turn.shop_prices[name]
        missing = max(0, demand - planned[name])
        count = min(missing, role.capacity - len(role.backpack),
                    missing if price == 0 else max(0, self.plan.gold - reserve) // price)
        if count <= 0:
            return False
        if name in self.purchase_claims or self.coordinator.purchase_owned(role, name):
            return False
        if self.plan.near_zone(role, "weaponShop"):
            handled = self.plan.add(role.unit_id, {"action": "buy", "name": name, "num": count})
            if handled:
                self.coordinator.assign(role, 'buy_upgrade', tuple(shops), role.pos)
        else:
            handled = self.travel(role, shops, 'buy_upgrade')
        if handled:
            self.purchase_claims.add(name)
            self.coordinator.job(role)['purchase_item'] = name
        return handled

    def mine(self, role: Unit, need_stone: bool = False, return_cells: set[Pos] | None = None) -> bool:
        if need_stone and self.turn.day == 1:
            return self.stone_planner.mine(role,return_cells=return_cells)
        if role.backpack_full:
            return False
        options = []
        for pos, kind in self.turn.zones.items():
            if kind not in MINERALS or (need_stone and kind != "stone"):
                continue
            if (kind=='stone' and self.turn.day == 1 and self.turn.is_day and self.missing_walls()
                    and not self.stone_planner.needs_material(role)):
                continue  # Construction material is already funded by real bags.
            if self.memory.failed_mines.get(f"{pos.x},{pos.y}", 0) > self.turn.round_no:
                continue
            if any(c["name"] == kind and c["startDay"] <= self.turn.day <= c["endDay"] for c in self.memory.mine_closures):
                continue
            route = self.route(role)
            goals = adjacent_cells(self.turn, [pos])
            if route.nearest(goals) is None:
                route = self.coordinator.diagnostic_route(role)
            if self.danger:
                goals = {p for p in goals if not self.danger.get(p, 0) and route.exposure.get(p) == 0}
            if return_cells is not None and not (self.turn.day==1 and self.turn.is_day):
                goals = {p for p in goals if p in route.cost and return_cells
                         and route.cost[p] + 1 + min(distance(p, home) for home in return_cells)
                         + self.settings.return_margin < self.turn.daylight_left}
            cost = route.cost.get(route.nearest(goals), 10_000)
            if cost >= 10_000:
                continue
            value = 1 if need_stone else self.turn.vendor_prices.get(kind, 0)
            if value <= 0:
                continue
            job = self.coordinator.job(role)
            options.append((job.get('kind', '').startswith('collect:') and job.get('target') == pos,
                            not self.coordinator.target_owned(role,pos),
                            value / (cost + 2), -cost, pos, goals))
        for _, _, _, _, pos, goals in sorted(options, key=lambda entry: entry[:5], reverse=True):
            if role.pos in goals and self.plan.add(role.unit_id, collect_command(pos)):
                self.coordinator.assign(role,'collect:'+self.turn.zones[pos],pos,role.pos)
                return True
            if self.coordinator.move_to(role,goals,'collect:'+self.turn.zones[pos],pos):
                return True
        return False

    def task(self, role: Unit) -> bool:
        if not self.settings.enable_tasks or self.turn.phase_task:
            return False
        agent = self.memory.task_agent if self.memory else None
        cooling_point = (self.memory.last_task_point if agent and
                         self.turn.round_no < agent.self_evolve_abandon_tick else None)
        first_day = self.turn.day==1
        if first_day:
            self.memory.task_schedule.update(itinerary_closed=False,budget_policy='task_first_no_return_reserve')
            attempts = task_attempts(self.memory)
            pending = next(((key,job) for key,job in attempts if not job['finished']),None)
            if pending:
                key,job = pending
                selected = next((t for t in self.turn.tasks if (t.pos.x,t.pos.y)==job['point']),None)
                timeout = selected.timeout if selected and selected.timeout>0 else 15
                if self.turn.round_no-key[1] > timeout:
                    finish_attempt(self.memory,key,self.turn.round_no,reason='accepted_phase_timeout')
                else:
                    self.memory.task_schedule.update(status='awaiting_task_phase',attempt=key)
                    self.plan.used.add(role.unit_id)
                    return True
            step = finished_count(self.memory)
            if step>=len(TASK_SEQUENCE):
                self.memory.task_schedule.update(status='three_attempts_finished',step=step)
                return False
            expected = TASK_SEQUENCE[step]
            tasks = [t for t in self.turn.tasks if task_number(t.kind)==expected]
            self.memory.task_schedule.update(round=self.turn.round_no,step=step+1,expected_point=expected,
                                             status='selecting_task')
        else:
            tasks = [t for t in self.turn.tasks if t.valid and t.cooldown==0
                     and (self.turn.day,t.pos.x,t.pos.y) not in self.memory.task_points_attempted
                     and (t.pos.x,t.pos.y)!=cooling_point]
        tasks.sort(key=lambda t: (self.cost(role, self.turn.task_cells(t)), -t.gold - t.score, t.pos))
        failures = []
        for task in tasks:
            cells = self.turn.task_cells(task)
            route = self.route(role)
            goal = route.nearest(adjacent_cells(self.turn,cells))
            if goal is None:
                failures.append('route_blocked')
                continue
            travel = route.cost[goal]
            duration = task.timeout if task.timeout > 0 else 15
            wait = max(0,task.cooldown)
            if (task.pos.x,task.pos.y)==cooling_point:
                wait = max(wait,agent.self_evolve_abandon_tick-self.turn.round_no)
            if first_day:
                self.memory.task_schedule.update(travel_rounds=travel,cooldown=wait,timeout_rounds=duration,
                    return_rounds=0,tail_rounds=0,required_rounds=max(travel,wait),
                    daylight_left=self.turn.daylight_left,point=task.pos)
            else:
                # Later-day admission is unchanged. Only the first day gives
                # up the home/defence budget at the user's request.
                control = self.control_position(role)
                if control is None:
                    continue
                moved = replace(role,pos=goal)
                simulated = replace(self.turn,ours=tuple(moved if u.unit_id==role.unit_id else u for u in self.turn.ours))
                back = Routes(simulated,moved,self.movement_reserved(role)).cost.get(control)
                if back is None or max(travel,wait)+duration+back+self.settings.return_margin>self.turn.daylight_left:
                    continue
            if self.plan.near(role, cells):
                if not task.valid or wait:
                    if first_day:
                        self.memory.task_schedule.update(status='waiting_cooldown' if wait else 'point_unavailable',
                                                         cooldown=wait,point=task.pos)
                        self.plan.used.add(role.unit_id)
                        return True
                    continue
                accepted = self.plan.add(role.unit_id, {"action": "acceptTask"})
                if accepted and agent:
                    agent.accept(task)
                    if first_day:
                        self.memory.task_schedule.update(status='accepting_task',point=task.pos)
                return accepted
            if self.travel(role, cells):
                return True
            failures.append('route_blocked')
        if first_day:
            self.memory.task_schedule['status'] = 'route_blocked' if failures else 'missing_task_point'
            self.plan.used.add(role.unit_id)
            return True
        return False

    def treasure(self, role: Unit) -> bool:
        if self.upgrades_complete():
            return False  # All remaining spending belongs to repair kits.
        clue = self.memory.treasure
        if not clue or self.memory.treasure_done:
            return False
        if self.turn.round_no > clue["endRound"]:
            self.memory.treasure = None
            return False
        target = Pos.load(clue["targetPos"])
        missing = Counter(clue["items"]) - Counter(role.backpack)
        travel = self.cost(role, [target])
        if missing:
            shops = [p for p, k in self.turn.zones.items() if k == "weaponShop"]
            travel = self.cost(role, shops) + min((distance(p, target) for p in shops), default=10_000) + len(missing)
        if self.turn.round_no + travel > clue["endRound"]:
            return False
        if clue["startRound"] - self.turn.round_no > travel + self.settings.return_margin:
            return False
        if missing:
            shops = [p for p, k in self.turn.zones.items() if k == "weaponShop"]
            required = sum(self.turn.shop_prices.get(name, 10**9) * count for name, count in missing.items())
            if required > self.plan.gold or len(role.backpack) + sum(missing.values()) > role.capacity:
                return False
            name, count = next(iter(missing.items()))
            if self.plan.near_zone(role, "weaponShop"):
                return self.plan.add(role.unit_id, {"action": "buy", "name": name, "num": count})
            return self.travel(role, shops)
        if distance(role.pos, target) <= 1:
            if self.turn.round_no >= clue["startRound"]:
                return self.plan.add(role.unit_id, {"action": "summonTreasure", "targetPos": [target.dump()], "item": clue["items"]})
            self.plan.used.add(role.unit_id)
            return True
        return self.travel(role, [target])


def decide(payload: dict) -> dict:
    """Legacy demo entry: one stateless tactical turn, returning only the command map."""
    from app.config import Settings
    from app.service.memory import GameMemory
    turn = Turn.load(payload)
    plan = ActionPlan(turn, Settings())
    memory = GameMemory()
    memory.observe(turn)
    strategy = Strategy(turn, plan, memory)
    if turn.phase_task:
        plan.used.update(role.unit_id for role in turn.alive((PIONEER,)) if not strategy.pioneer_should_defend(role))
    strategy.run()
    return plan.commands
