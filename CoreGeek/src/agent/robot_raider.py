"""First-night BOSS controllers: find cannon operators, then siege their base."""
import math
import time
from .grid import Routes
from .protocol import PIONEER, WORKER, TOWER_TYPES, Pos, distance, move_command
from .robot_combat import blocking_wall, clear_attack, enemy_at
from .raid_diagnostics import RaidDiagnostics, LIMIT, entity


class RobotRaider:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.diag = RaidDiagnostics(strategy)
        live = {r.robot_id for r in self.turn.summon_robots if r.health > 0}
        self.memory.robot_raids = {uid: job for uid, job in self.memory.robot_raids.items()
                                   if uid in live and not self.turn.is_day and self.turn.day == 1}

    def firing_key(self, target, post):
        victim = enemy_at(self.turn,target)
        return (victim.unit_id if victim else None,target,post)

    def firing_plan(self, robot, points, route):
        options = []
        counts = dict(examined=0,same_target=0,unreachable=0,failed_cache=0,wall_blocked=0,legal=0)
        old = self.memory.robot_raids.get(robot.robot_id, {})
        for target in points:
            for x in range(max(0, target.x-3), min(self.turn.width, target.x+4)):
                for y in range(max(0, target.y-3), min(self.turn.height, target.y+4)):
                    now = time.monotonic()
                    if now >= self.s.deadline:
                        self.diag.event(robot,'firing_sweep',targets=points,counts=counts,timed_out=True)
                        self.diag.set(robot,firing_timed_out=True)
                        return None
                    post = Pos(x, y)
                    counts['examined'] += 1
                    if post == target:
                        counts['same_target'] += 1
                        continue
                    if post not in route.cost:
                        counts['unreachable'] += 1
                        continue
                    if self.firing_key(target,post) in old.get('failed_firing', {}):
                        counts['failed_cache'] += 1
                        continue
                    if blocking_wall(self.turn, post, target) is not None:
                        counts['wall_blocked'] += 1
                        continue
                    counts['legal'] += 1
                    options.append((route.cost[post], post != old.get('goal'), post, target))
        best = min(options) if options else None
        self.diag.event(robot,'firing_sweep',targets=points,counts=counts,timed_out=False,
                        best={'cost':best[0],'post':best[2],'target':best[3]} if best else None)
        return best

    def issue(self, robot, action, target, goal, stage, **extra):
        command = ({'action': 'attack', 'targetPos': [target.dump()]} if action == 'attack'
                   else move_command(target))
        accepted = self.plan.add(robot.robot_id, command)
        self.diag.set(robot,stage=stage,attempted_command=command,goal=goal,
                      accepted=accepted,reason='command_rejected' if not accepted else
                      'direct_attack' if action=='attack' and stage!='breach' else
                      'breach_attack' if action=='attack' else 'breach_reposition' if stage=='breach' else 'reposition')
        if not accepted:
            return False
        old = self.memory.robot_raids.get(robot.robot_id, {})
        victim = enemy_at(self.turn,target) if action == 'attack' else None
        self.memory.robot_raids[robot.robot_id] = dict(old, round=self.turn.round_no, stage=stage,
            position=robot.pos, target=target, goal=goal, action=action,
            attack_target_id=victim.unit_id if victim else None, **extra)
        return True

    def pursue(self, robot, points, route, stage, **extra):
        self.diag.set(robot,intent=stage,target_points=points)
        failed = self.memory.robot_raids.get(robot.robot_id, {}).get('failed_firing', {})
        direct = []
        for p in points:
            audit = {} if self.diag.enabled else None
            clear = clear_attack(self.turn,robot,p,audit)
            cache = self.firing_key(p,robot.pos) in failed if clear else False
            self.diag.event(robot,'attack_check',target=p,check=audit,cache_hit=cache)
            if clear and not cache:
                direct.append(p)
        if direct:
            target = min(direct, key=lambda p: (distance(robot.pos, p), p))
            return self.issue(robot, 'attack', target, robot.pos, stage, **extra)
        firing = self.firing_plan(robot, points, route)
        if firing:
            _, _, post, target = firing
            step = route.step({post})
            if step is not None:
                return self.issue(robot, 'move', step, post, stage, **extra)
            self.diag.event(robot,'missing_step',goal=post,target=target)
        # A completely screened target may require breaking an observed enemy wall.
        walls = [u for u in self.turn.enemies if u.health > 0 and u.kind == 'wall']
        nearest = blocking_wall(self.turn, robot.pos, min(points, key=lambda p: distance(robot.pos, p)))
        options = []
        for wall in walls:
            now = time.monotonic()
            if now >= self.s.deadline:
                self.diag.set(robot,reason='deadline_during_breach',deadline_remaining_ms=(self.s.deadline-now)*1000)
                return False
            firing = self.firing_plan(robot, [wall.pos], route)
            if firing is not None:
                cost = firing[0] + math.ceil(wall.health / max(1, robot.attack_power))
                options.append((wall != nearest, min(distance(wall.pos, p) for p in points), cost,
                                wall.unit_id, wall, firing))
                self.diag.event(robot,'breach_candidate',wall=entity(wall),first_blocker=wall==nearest,
                                estimated_turns=cost,firing_cost=firing[0],post=firing[2])
        if not options:
            timed_out = self.diag.records.get(robot.robot_id,{}).get('firing_timed_out')
            self.diag.set(robot,reason='deadline_in_firing_search' if timed_out else 'no_reachable_firing_position_or_wall',
                          blocking_wall=entity(nearest) if nearest else None)
            return False
        _, _, _, _, wall, firing = min(options, key=lambda entry: entry[:4])
        self.diag.set(robot,breach_wall=entity(wall))
        if clear_attack(self.turn, robot, wall.pos) and self.firing_key(wall.pos,robot.pos) not in failed:
            return self.issue(robot, 'attack', wall.pos, robot.pos, 'breach', **extra)
        step = route.step({firing[2]})
        if step is None:
            self.diag.set(robot,reason='no_step_to_breach_post',goal=firing[2])
        return step is not None and self.issue(robot, 'move', step, firing[2], 'breach', **extra)

    def decide(self, robot):
        self.diag.set(robot,called=True)
        if (not self.s.settings.enable_boss_raid or self.turn.day != 1 or self.turn.is_day
                or robot.health <= 0 or robot.kind != 'bossRobot' or robot.abnormal_state == 'dizzy'):
            reason = ('disabled' if not self.s.settings.enable_boss_raid else 'after_day_one' if self.turn.day!=1 else
                      'daytime' if self.turn.is_day else 'dead' if robot.health<=0 else
                      'unsupported_robot_type' if robot.kind!='bossRobot' else 'stunned')
            self.diag.set(robot,reason='skip_'+reason)
            return False
        route = Routes(self.turn, robot, self.plan.reserved)
        if self.diag.enabled:
            neighbours = [p for p in robot.pos.neighbours() if self.turn.in_bounds(p)]
            occupants = {p:[] for p in neighbours}
            for unit in self.turn.ours + self.turn.enemies + self.turn.robots:
                if unit.health > 0:
                    for p in self.turn.footprint(unit):
                        if p in occupants:
                            occupants[p].append({'id':unit.unit_id,'type':unit.kind})
            self.diag.set(robot,route={'reachable_count':len(route.cost),
                'adjacent':[{'pos':p,'terrain':self.turn.zones.get(p,'land'),
                    'land':self.turn.land(p),'reachable':p in route.cost,
                    'reserved':p in self.plan.reserved,'occupants':occupants[p]} for p in neighbours]})
        old = self.memory.robot_raids.setdefault(robot.robot_id, {})
        failed = {key: until for key, until in old.get('failed_firing', {}).items() if until > self.turn.round_no}
        if (old.get('round') == self.turn.round_no-1 and old.get('action') == 'attack'
                and old.get('position') == robot.pos
                and self.turn.action_results.get(str(robot.robot_id)) is False):
            failed[old.get('attack_target_id'),old['target'],robot.pos] = self.turn.round_no+4
        old['failed_firing'] = failed
        self.diag.set(robot,failed_cache=[{'target_id':key[0],'target_pos':key[1],'post':key[2],'until_round':until}
                                         for key,until in list(failed.items())[:LIMIT]],
                      failed_cache_omitted=max(0,len(failed)-LIMIT))
        weapons = [u for u in self.turn.enemies if u.health > 0 and u.kind in TOWER_TYPES]
        crew = [u for u in self.turn.enemies if u.kind in (PIONEER, WORKER)
                and any(distance(u.pos,w.pos) <= 1 for w in weapons)]
        old['operator_snapshot'] = tuple((u.unit_id,u.health) for u in crew)
        operators = [u for u in crew if u.health > 0]
        visible = [u for u in self.turn.enemies if u.kind in (PIONEER,WORKER)]
        old_id = self.diag.old_jobs.get(robot.robot_id,{}).get('controller_id')
        old_target = next((u for u in self.turn.enemies if u.unit_id==old_id),None)
        old_state = ('not_applicable' if old_id is None else 'not_visible_or_absent' if old_target is None else
                     'observed_dead' if old_target.health<=0 else 'still_at_weapon' if old_target in operators else 'moved_away')
        self.diag.set(robot,weapons=[entity(w) for w in weapons[:LIMIT]],weapons_count=len(weapons),
            weapons_omitted=max(0,len(weapons)-LIMIT),old_controller_state=old_state,
            old_controller_now=entity(old_target) if old_target else None,
            visible_heroes=[dict(entity(u),near_weapon_ids=[w.unit_id for w in weapons if distance(u.pos,w.pos)<=1],
                                  eligible=u in operators) for u in visible[:LIMIT]],
            visible_heroes_count=len(visible),visible_heroes_omitted=max(0,len(visible)-LIMIT),
            operator_count=len(operators),candidates=[])
        if operators:
            choices = []
            for target in operators:
                now = time.monotonic()
                if now >= self.s.deadline:
                    self.diag.set(robot,reason='deadline_during_candidates',deadline_remaining_ms=(self.s.deadline-now)*1000)
                    return False
                audit = {} if self.diag.enabled else None
                direct = (clear_attack(self.turn,robot,target.pos,audit)
                          and self.firing_key(target.pos,robot.pos) not in failed)
                firing = self.firing_plan(robot,[target.pos],route) if not direct else None
                walk = 0 if direct else firing[0] if firing is not None else 10_000
                rank = (not direct, not direct and firing is None,
                        math.ceil(target.health / max(1,robot.attack_power)), target.health, walk,
                        -sum(distance(target.pos,w.pos) <= 1 for w in weapons),
                        target.unit_id != old.get('controller_id'), distance(robot.pos,target.pos),target.unit_id)
                choices.append((rank,target))
                self.diag.event(robot,'candidate',target=entity(target),check=audit,rank=rank,direct=direct,
                    cache_until=failed.get(self.firing_key(target.pos,robot.pos)),
                    firing={'cost':firing[0],'post':firing[2]} if firing else None)
            target = min(choices,key=lambda entry:entry[0])[1]
            self.diag.set(robot,selected=entity(target),selected_rank=min(choices,key=lambda entry:entry[0])[0],
                          target_changed=target.unit_id!=self.diag.old_jobs.get(robot.robot_id,{}).get('controller_id'))
            # This branch is a hard barrier: alive cannon crews forbid base attacks.
            return self.pursue(robot, [target.pos], route, 'controller', controller_id=target.unit_id,
                                controller_pos=target.pos, controller_health=target.health,
                                last_seen=self.turn.round_no)
        for key in ('controller_id','controller_pos','controller_health','last_seen','scouted'):
            old.pop(key,None)
        base = next((u for u in self.turn.enemies if u.health > 0 and u.kind == 'station'), None)
        self.diag.set(robot,selected=entity(base) if base else None,
                      reason='no_visible_operators_try_base' if base else 'no_visible_operator_or_live_base')
        return base is not None and self.pursue(robot, [base.pos], route, 'base')
