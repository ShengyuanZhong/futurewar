"""Bounded observation/decision traces; never used as tactical inputs."""
from .protocol import Pos, distance
from .robot_combat import enemy_at


LIMIT = 16
EVENT_LIMIT = 12


def plain(value):
    if isinstance(value, Pos):
        return value.dump()
    if isinstance(value, dict):
        return {str(key):plain(item) for key,item in value.items()}
    if isinstance(value, (tuple,list,set)):
        return [plain(item) for item in value]
    return value


def entity(unit):
    return {'id':unit.unit_id,'type':unit.kind,'pos':unit.pos.dump(),'hp':unit.health}


class RaidDiagnostics:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.enabled = strategy.settings.enable_robot_diagnostics
        self.records = {}
        self.old_jobs = {uid:dict(job) for uid,job in self.memory.robot_raids.items()} if self.enabled else {}
        self.old_motion = dict(self.memory.robot_motion) if self.enabled else {}
        if self.enabled:
            for robot in self.turn.summon_robots:
                previous = self.old_motion.get(robot.robot_id,{})
                consecutive = previous.get('round') == self.turn.round_no-1
                command = self.memory.last_commands.get(str(robot.robot_id)) if self.memory.last_round == self.turn.round_no-1 else None
                command_matched = command is not None
                result = self.turn.action_results.get(str(robot.robot_id))
                legality = ('unmatched' if not command_matched else
                            'legal' if result is True else 'illegal' if result is False else 'missing')
                history = (previous.get('positions',[]) if consecutive else []) + [robot.pos]
                history = history[-4:]
                motion = 'unmatched'
                if consecutive and command and command.get('action') == 'move':
                    planned = Pos.load(command['targetPos'][0])
                    motion = 'arrived_at_step' if robot.pos == planned else 'unchanged' if robot.pos == previous['pos'] else 'different_position'
                elif consecutive:
                    motion = 'position_changed' if robot.pos != previous['pos'] else 'unchanged'
                attack = previous.get('attack_target') if consecutive and command and command.get('action') == 'attack' else None
                current = next((u for u in self.turn.enemies if attack and u.unit_id == attack['id']),None)
                hp_state = ('not_applicable' if not attack else 'not_visible_or_absent' if current is None else
                            'observed_dead' if current.health <= 0 else 'decreased' if current.health < attack['hp'] else
                            'increased' if current.health > attack['hp'] else 'unchanged')
                self.records[robot.robot_id] = dict(round=self.turn.round_no, team_id=self.turn.team_id,
                    team_type=self.turn.team_type,robot=dict(entity(robot),state=robot.abnormal_state,owned=True,
                        target_team=robot.target_team,attack_power=robot.attack_power,attack_range=robot.range_of_attack()),
                    policy={'enabled':strategy.settings.enable_boss_raid,'day':self.turn.day,'is_day':self.turn.is_day},
                    previous={'round':previous.get('round',self.memory.last_round if command_matched else None),
                        'consecutive':consecutive,'command_matched':command_matched,'command':command,
                        'raw_action_result':result,'legality':legality,'position':previous.get('pos'),
                        'robot_hp_before':previous.get('hp') if consecutive else None,
                        'robot_observed_hp_delta':robot.health-previous['hp'] if consecutive and 'hp' in previous else None,
                        'displacement':distance(previous['pos'],robot.pos) if consecutive else None,
                        'movement':motion,'positions':history,
                        'oscillating':len(history)==4 and history[0]==history[2] and history[1]==history[3] and history[0]!=history[1],
                        'attack_target':attack,'target_hp_now':current.health if current else None,
                        'observed_hp_delta':current.health-attack['hp'] if current and attack else None,
                        'target_observation':hp_state},
                    previous_job={'round':self.old_jobs.get(robot.robot_id,{}).get('round'),
                                  'stage':self.old_jobs.get(robot.robot_id,{}).get('stage'),
                                  'goal':self.old_jobs.get(robot.robot_id,{}).get('goal'),
                                  'controller_id':self.old_jobs.get(robot.robot_id,{}).get('controller_id')},
                    called=False,reason='not_called',events=[],events_omitted=0)

    def set(self, robot, **fields):
        if self.enabled:
            self.records[robot.robot_id].update(fields)

    def event(self, robot, kind, **fields):
        if not self.enabled:
            return
        record = self.records[robot.robot_id]
        if kind == 'candidate':
            candidates = record.setdefault('candidates',[])
            if len(candidates) < LIMIT:
                candidates.append(fields)
            else:
                record['candidates_omitted'] = record.get('candidates_omitted',0)+1
        if len(record['events']) < EVENT_LIMIT:
            record['events'].append(dict(kind=kind,**fields))
        else:
            record['events_omitted'] += 1

    def finish(self):
        if not self.enabled:
            return None,[]
        alive = {r.robot_id for r in self.turn.summon_robots if r.health > 0}
        removed = [{'id':uid,'last_round':old.get('round'),
                    'reason':'expected_dawn_clear' if self.turn.is_day and (self.turn.round_no-1)%130==0
                    else 'removed_from_owned_alive_list'} for uid,old in self.old_motion.items() if uid not in alive]
        summary = dict(round=self.turn.round_no,team_id=self.turn.team_id,team_type=self.turn.team_type,
            owned_ids=[r.robot_id for r in self.turn.summon_robots][:LIMIT],
            owned_count=len(self.turn.summon_robots),
            global_boss_ids=[r.robot_id for r in self.turn.robots if r.kind=='bossRobot' and r.health>0][:LIMIT],
            removed=removed[:LIMIT],summon_status=self.memory.boss_raid.get('status'),
            requested_spawn=self.memory.boss_raid.get('spawn'),summon_round=self.memory.boss_raid.get('summon_round'))
        boss_count = sum(r.kind=='bossRobot' and r.health>0 for r in self.turn.robots)
        summary.update(global_boss_count=boss_count,global_boss_omitted=max(0,boss_count-LIMIT),
                       owned_omitted=max(0,len(self.turn.summon_robots)-LIMIT),
                       removed_count=len(removed),removed_omitted=max(0,len(removed)-LIMIT))
        motion = {}
        for robot in self.turn.summon_robots:
            record = self.records[robot.robot_id]
            command = self.plan.commands.get(str(robot.robot_id))
            record['final_command'] = command
            record['rejections'] = [r for r in self.plan.rejections if r.startswith(str(robot.robot_id)+':')][:8]
            if record['reason']=='not_called':
                record['reason']='not_reached_robot_loop'
            if robot.health <= 0:
                continue
            target = enemy_at(self.turn,Pos.load(command['targetPos'][0])) if command and command.get('action')=='attack' else None
            motion[robot.robot_id] = dict(round=self.turn.round_no,pos=robot.pos,hp=robot.health,
                positions=record['previous']['positions'],command=command,
                attack_target=entity(target) if target else None)
        self.memory.robot_motion = motion
        useful = self.records or removed or self.memory.boss_raid or summary['global_boss_ids']
        return plain(summary) if useful else None,[plain(record) for record in self.records.values()]
