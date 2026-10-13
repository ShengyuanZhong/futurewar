"""Advance one BOSS through a real opening without abandoning a base shot."""
from dataclasses import replace

from .grid import Routes
from .protocol import TOWER_TYPES, Pos, distance
from .summoning import layout_operator_positions


class BossFormation:
    def __init__(self, raider):
        self.raid = raider
        self.turn, self.plan, self.memory = raider.turn, raider.plan, raider.memory

    def base_distance(self, position, base):
        return min(distance(position,p) for p in self.turn.footprint(base))

    def ordered_robots(self):
        base = next((u for u in self.turn.enemies if u.kind=='station' and u.health>0),None)
        return sorted(self.turn.summon_robots,key=lambda r:
            (self.base_distance(r.pos,base) if base else 0,r.robot_id))

    def clear_base_cells(self, robot, base, position):
        moved = replace(robot,pos=position)
        failed = self.memory.robot_raids.get(robot.robot_id,{}).get('failed_firing',{})
        return [p for p in self.turn.footprint(base)
                if self.raid.clear_shot(moved,p) and self.raid.firing_key(p,position) not in failed]

    def advance(self, robot, base, route):
        """Move only the front BOSS; every proposed step retains a base shot.

        A gunner position must be covered by real ordinary sight before it is
        treated as an empty occupation goal. Other robots remain obstacles at
        their observed positions even when they have a move command this turn.
        """
        bosses = [r for r in self.turn.summon_robots if r.health>0
                  and r.kind=='bossRobot' and r.abnormal_state!='dizzy']
        if len(bosses)<2 or 130-(self.turn.round_no-1)%130<=1:
            return False
        front = min(bosses,key=lambda r:(self.base_distance(r.pos,base),r.robot_id))
        nearby = [r for r in bosses if r.robot_id!=front.robot_id
                  and self.base_distance(r.pos,base)<=6]
        if robot.robot_id!=front.robot_id or not nearby:
            return False
        current_distance = self.base_distance(robot.pos,base)
        guns = [u for u in self.memory.enemy_structures.values()
                if u.health>0 and u.kind in TOWER_TYPES]
        coverage = lambda p: sum(distance(p,u.pos)<=1 for u in guns)
        old = self.memory.robot_raids.get(robot.robot_id,{})
        options = []
        for post in layout_operator_positions(self.turn,self.memory.enemy_structures.values()):
            if (coverage(post)<2 or post not in route.cost or not self.raid.seen_cell(post)
                    or not self.clear_base_cells(robot,base,post)):
                continue
            # Already occupying an equally useful cannon control cell is the
            # goal, not a reason to circulate among tied candidate positions.
            if post==robot.pos:
                self.raid.diag.set(robot,formation=dict(front_id=front.robot_id,
                    action='holding_operator_post',post=post,control_count=coverage(post)))
                return False
            step = route.step({post})
            if (step is None or not self.raid.seen_cell(step) or not self.clear_base_cells(robot,base,step)
                    or self.base_distance(step,base)>current_distance
                    or (self.base_distance(step,base)==current_distance
                        and coverage(step)<=coverage(robot.pos))):
                continue
            options.append((-coverage(post),post!=old.get('formation_goal'),route.cost[post],
                            self.base_distance(post,base),post,step))
        if options:
            *_,post,step = min(options)
            mode = 'occupy_operator_post'
        else:
            # Even an unusual gun layout can permit an immediate step closer
            # to the base, freeing the approach for the following BOSS.
            steps = [p for p in robot.pos.neighbours() if route.cost.get(p)==1
                     and self.base_distance(p,base)<current_distance
                     and self.raid.seen_cell(p)
                     and self.clear_base_cells(robot,base,p)]
            if not steps:
                return False
            step = min(steps,key=lambda p:(-coverage(p),self.base_distance(p,base),p))
            post,mode = step,'advance_to_base'
        self.raid.diag.set(robot,formation=dict(front_id=front.robot_id,action=mode,
            post=post,next_step=step,current_base_distance=current_distance,
            next_base_distance=self.base_distance(step,base),control_count=coverage(post),
            next_direct_base_cells=self.clear_base_cells(robot,base,step)))
        return self.raid.issue(robot,'move',step,post,'base',formation_goal=post,
                               formation_action=mode,pursuit_rounds=0)

    def occupy_rocket_post(self, robot, base, route, posts):
        """Claim an available shared three-rocket post, including a single BOSS.

        Known sites are geometry, not live hero targets. Current occupancy and
        reservations remain authoritative; never move into a teammate's old
        cell just because it also received a move this frame.
        """
        if robot.pos in posts:
            self.raid.diag.set(robot,formation=dict(action='holding_rocket_control_post',post=robot.pos))
            return False
        remaining=130-(self.turn.round_no-1)%130
        if remaining<=1:
            return False
        direct=bool(self.clear_base_cells(robot,base,robot.pos))
        occupied=self.turn.occupied_cells() | self.plan.reserved
        old=self.memory.robot_raids.get(robot.robot_id,{})
        options=[]
        for post in posts:
            if (post in occupied or post not in route.cost
                    or route.cost[post]+1>remaining or not self.clear_base_cells(robot,base,post)):
                continue
            step=route.step({post})
            if step is None or (direct and not self.clear_base_cells(robot,base,step)):
                continue
            options.append((post!=old.get('formation_goal'),route.cost[post],post,step))
        if not options:
            return False
        _,_,post,step=min(options)
        self.raid.diag.set(robot,formation=dict(action='occupy_rocket_control_post',post=post,next_step=step,
            control_count=3,next_direct_base_cells=self.clear_base_cells(robot,base,step)))
        return self.raid.issue(robot,'move',step,post,'base',formation_goal=post,
                               formation_action='occupy_rocket_control_post',pursuit_rounds=0)

    def wait_for_lane(self, robot, base):
        """Wait briefly for an actually commanded teammate to clear the lane.

        Ignoring its old cell and destination is diagnostic only. Never issue
        a move or attack from this projected occupancy map.
        """
        old = self.memory.robot_raids.get(robot.robot_id,{})
        consecutive = old.get('round')==self.turn.round_no-1 and old.get('action')=='wait'
        waits = old.get('formation_wait_rounds',0) if consecutive else 0
        if waits>=3:
            return False
        moving = [r for r in self.turn.summon_robots if r.robot_id!=robot.robot_id
                  and r.health>0 and r.kind=='bossRobot'
                  and self.plan.commands.get(str(r.robot_id),{}).get('action')=='move']
        if not moving:
            return False
        ids = {r.robot_id for r in moving}
        destinations = {Pos.load(self.plan.commands[str(uid)]['targetPos'][0]) for uid in ids}
        projected = replace(self.turn,robots=tuple(r for r in self.turn.robots if r.robot_id not in ids),
                            summon_robots=tuple(r for r in self.turn.summon_robots if r.robot_id not in ids))
        remembered = {p for u in self.memory.enemy_structures.values() for p in self.turn.footprint(u)}
        blocked = set(old.get('blocked_steps',{}))
        route = Routes(projected,robot,(self.plan.reserved-destinations) | remembered | blocked)
        firing = self.raid.firing_plan(robot,self.turn.footprint(base),route)
        if firing is None or route.cost[firing[2]]>3:
            return False
        self.plan.used.add(robot.robot_id)
        self.memory.robot_raids[robot.robot_id] = dict(old,round=self.turn.round_no,stage='base',
            pursuit_kind='base',action='wait',position=robot.pos,target=None,goal=firing[2],
            formation_wait_rounds=waits+1)
        self.raid.diag.set(robot,stage='base',reason='waiting_for_boss_lane',
            formation=dict(action='wait_for_observed_teammate_move',moving_ids=sorted(ids),
                post=firing[2],wait_rounds=waits+1),accepted=True)
        return True
