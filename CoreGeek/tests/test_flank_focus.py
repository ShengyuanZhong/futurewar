"""First-day flank paths, one-side deployment, and observed group targets."""
import copy
import unittest
from dataclasses import replace

from agent.protocol import IMP, Pos, Turn, distance
from agent.summoning import spawn_side, summon_cell_legal, enemy_base_position
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, robot, unit
from tests.test_worker_safety import strategy
from tests.test_worker_boss_buyer import worker_raid_scene, load_strategy
from tests.test_raid_efficiency import decide
from tests.test_layout_survey import reveal


IMP_ID, FIRST, SECOND = 505, 30005, 30006


def scout_scene(right=False):
    raw=request()
    home,enemy=(Pos(30,10),Pos(9,22)) if right else (Pos(9,22),Pos(30,10))
    raw['mapInfo']['zones']=[]
    raw['teamOur'].update(playerTasks=[],goldNum=0)
    raw['teamOur']['roles']=[unit(503,'station',home.x,home.y),
        unit(IMP_ID,IMP,home.x+(-1 if right else 1),home.y,health=500)]
    truth=[unit(990,'station',enemy.x,enemy.y)]
    truth += [unit(991+i,'rocket',enemy.x-1,y,health=1000)
              for i,y in enumerate((enemy.y-1,enemy.y,enemy.y+1))]
    reveal(raw,truth)
    return raw,truth


def group_scene(two=True):
    raw=request(71)
    raw['mapInfo']['zones']=[]
    raw['teamOur'].update(playerTasks=[],goldNum=0)
    raw['teamOur']['roles']=[unit(503,'station',2,5),unit(501,'worker',9,19)]
    raw['teamEnemy']['roles']=[unit(990,'station',14,20),
        unit(991,'rocket',13,20,health=1000),unit(993,'rocket',13,18,health=1000),
        unit(994,'railgun',14,18,health=1000),
        unit(41000,'worker',13,21,health=1),unit(41001,'pioneer',12,19,health=200)]
    raw['teamOur']['summonRobotList']=[robot(FIRST,10,21,800,roleType='bossRobot')]
    if two:
        raw['teamOur']['summonRobotList'].append(robot(SECOND,10,17,800,roleType='bossRobot'))
    raw['robot']['roles']=copy.deepcopy(raw['teamOur']['summonRobotList'])
    return raw


class ScoutFlankTests(unittest.TestCase):
    def settings(self):
        return Settings(enable_tasks=False,enable_news=False,enable_boss_raid=False,
                        enable_first_night_defense=False)

    def test_both_home_positions_use_a_stable_flank_and_complete_real_survey(self):
        for right in (False,True):
            with self.subTest(right=right):
                raw,truth=scout_scene(right)
                memory=GameMemory()
                side=None
                phases=set()
                path=[]
                for number in range(1,71):
                    raw['roundNo']=number
                    reveal(raw,truth)
                    s,plan=strategy(raw,memory,self.settings())
                    if memory.raid_scouts.get('opening_scout_complete'):
                        break
                    imp=s.turn.imps()[0]
                    self.assertTrue(s.raid_scouts.opening_imp(imp))
                    job=memory.raid_scouts['imp_flanks'][IMP_ID]
                    side=side or job['side']
                    self.assertEqual(job['side'],side)
                    phases.add(job['phase'])
                    command=plan.commands.get(str(IMP_ID))
                    self.assertIsNotNone(command)
                    point=Pos.load(command['targetPos'][0])
                    self.assertEqual(distance(point,imp.pos),1)
                    self.assertNotIn(point,s.turn.blocked(imp))
                    path.append(point)
                    if job['phase']=='crossing':
                        self.assertLessEqual(abs(point.y-job['crossing'].y),1)
                    next(u for u in raw['teamOur']['roles'] if u['id']==IMP_ID)['pos']=point.dump()
                    memory.record(s.turn,plan)
                    raw['lastRoundRoleActionResults']={str(IMP_ID):True}
                self.assertTrue(memory.raid_scouts.get('opening_scout_complete'))
                self.assertTrue({'outbound','crossing'}<=phases)
                self.assertEqual(len(memory.enemy_weapon_sites),3)
                self.assertGreater(len(path),25)
                self.assertLess(number,70)

    def test_visible_catcher_remains_excluded_on_the_flank(self):
        raw,truth=scout_scene()
        truth.append(unit(900,'worker',10,25))
        reveal(raw,truth)
        s,plan=strategy(raw,GameMemory(),self.settings())
        imp=s.turn.imps()[0]
        s.raid_scouts.opening_imp(imp)
        point=Pos.load(plan.commands[str(IMP_ID)]['targetPos'][0])
        self.assertGreater(distance(point,Pos(10,25)),2)
        self.assertEqual(plan.rejections,[])

    def test_nearby_scout_is_not_sent_back_to_a_remote_flank(self):
        raw,truth=scout_scene()
        next(u for u in raw['teamOur']['roles'] if u['id']==IMP_ID)['pos']=Pos(26,12).dump()
        reveal(raw,truth)
        s,plan=strategy(raw,GameMemory(),self.settings())
        s.raid_scouts.opening_imp(s.turn.imps()[0])
        self.assertNotIn(IMP_ID,s.memory.raid_scouts.get('imp_flanks',{}))
        self.assertEqual(plan.rejections,[])

    def test_zero_coupon_quota_keeps_the_flank_between_frames(self):
        raw,truth=scout_scene()
        memory=GameMemory(boss_raid={'order_decision_round':1,'target_count':0})
        s,plan=strategy(raw,memory,self.settings())
        s.raid_scouts.opening_imp(s.turn.imps()[0])
        original=copy.deepcopy(memory.raid_scouts['imp_flanks'][IMP_ID])
        next(u for u in raw['teamOur']['roles'] if u['id']==IMP_ID)['pos']=plan.commands[str(IMP_ID)]['targetPos'][0]
        raw['roundNo']=2
        reveal(raw,truth)
        s,plan=strategy(raw,memory,self.settings())
        s.raid_scouts.opening_imp(s.turn.imps()[0])
        job=memory.raid_scouts['imp_flanks'][IMP_ID]
        self.assertEqual(job['side'],original['side'])
        self.assertEqual(job['entry'],original['entry'])
        self.assertEqual(job['crossing'],original['crossing'])

    def test_new_obstacle_ends_an_unreachable_leg_without_restarting_it(self):
        raw,truth=scout_scene()
        memory=GameMemory()
        s,plan=strategy(raw,memory,self.settings())
        s.raid_scouts.opening_imp(s.turn.imps()[0])
        job=copy.deepcopy(memory.raid_scouts['imp_flanks'][IMP_ID])
        next(u for u in raw['teamOur']['roles'] if u['id']==IMP_ID)['pos']=plan.commands[str(IMP_ID)]['targetPos'][0]
        raw['mapInfo']['zones']=[dict(neutralType='stone',pos=job['entry'].dump())]
        for number in (2,3):
            raw['roundNo']=number
            reveal(raw,truth)
            s,plan=strategy(raw,memory,self.settings())
            s.raid_scouts.opening_imp(s.turn.imps()[0])
            current=memory.raid_scouts['imp_flanks'][IMP_ID]
            self.assertTrue(current['complete'])
            self.assertEqual(current['phase'],'fallback')
            command=plan.commands.get(str(IMP_ID),{})
            if command:
                point=Pos.load(command['targetPos'][0])
                self.assertNotIn(point,s.turn.blocked(s.turn.imps()[0]))
                next(u for u in raw['teamOur']['roles'] if u['id']==IMP_ID)['pos']=point.dump()
            self.assertEqual(plan.rejections,[])


class UnifiedSpawnTests(unittest.TestCase):
    def test_three_spawns_share_one_side_in_both_mirrors(self):
        for right in (False,True):
            raw,memory,settings=worker_raid_scene(lower_right=right,successes=3)
            s,plan=load_strategy(raw,memory,settings)
            positions=s.boss_raid.spawn_positions(3,scouted=True)
            self.assertEqual(len(set(positions)),3)
            base=enemy_base_position(s.turn)
            self.assertEqual(len({spawn_side(p,base) for p in positions}),1)
            self.assertTrue(all(summon_cell_legal(s.turn,settings,p) for p in positions))
            self.assertTrue(all(distance(p,positions[0])<=2 for p in positions))

    def test_subsequent_uses_and_failed_slots_do_not_switch_side(self):
        raw,memory,settings=worker_raid_scene(successes=3)
        s,plan=load_strategy(raw,memory,settings)
        first=s.boss_raid.spawn_positions(3,scouted=True)[0]
        side=memory.boss_raid['group_spawn']['side']
        memory.boss_raid['spawns']=[first]
        raw['roundNo']+=1
        s,plan=load_strategy(raw,memory,settings)
        rest=s.boss_raid.spawn_positions(2,scouted=True)
        self.assertEqual(len(rest),2)
        self.assertNotIn(first,rest)
        self.assertTrue(all(spawn_side(p,enemy_base_position(s.turn))==side for p in rest))
        memory.boss_raid['failed_positions']={rest[0]}
        raw['roundNo']+=1
        s,plan=load_strategy(raw,memory,settings)
        revised=s.boss_raid.spawn_positions(2,scouted=True)
        self.assertNotIn(rest[0],revised)
        self.assertTrue(all(spawn_side(p,enemy_base_position(s.turn))==side for p in revised))


class GroupFocusTests(unittest.TestCase):
    def assert_legal(self,s,plan):
        self.assertEqual(plan.rejections,[])
        occupied=s.turn.occupied_cells()
        destinations=set()
        for r in s.turn.summon_robots:
            cmd=plan.commands.get(str(r.robot_id),{})
            if cmd.get('action')=='attack':
                self.assertTrue(s.raider.clear_shot(r,Pos.load(cmd['targetPos'][0])))
            elif cmd.get('action')=='move':
                point=Pos.load(cmd['targetPos'][0])
                self.assertNotIn(point,occupied|destinations)
                self.assertEqual(distance(point,r.pos),1)
                destinations.add(point)

    def test_group_prefers_a_common_victim_over_a_one_hp_split_target(self):
        raw=group_scene()
        s,plan=decide(raw)
        for uid in (FIRST,SECOND):
            self.assertEqual(plan.commands[str(uid)],dict(action='attack',targetPos=[Pos(12,19).dump()]))
        self.assertEqual(s.memory.boss_raid['group_focus']['target_id'],41001)
        self.assert_legal(s,plan)

    def test_single_boss_keeps_the_existing_low_health_target_priority(self):
        s,plan=decide(group_scene(two=False))
        self.assertEqual(plan.commands[str(FIRST)]['targetPos'],[Pos(13,21).dump()])
        self.assert_legal(s,plan)

    def test_focus_remains_alive_after_healing_and_does_not_predict_death(self):
        raw=group_scene()
        memory=GameMemory(opening_complete=True)
        for hp in (40,220,80):
            next(u for u in raw['teamEnemy']['roles'] if u['id']==41001)['health']=hp
            s,plan=decide(raw,memory)
            self.assertTrue(all(plan.commands[str(uid)].get('targetPos')==[Pos(12,19).dump()]
                                for uid in (FIRST,SECOND)))
            memory.record(s.turn,plan)
            raw['roundNo']+=1
            raw['lastRoundRoleActionResults']={str(FIRST):True,str(SECOND):True}
            self.assert_legal(s,plan)

    def test_dead_or_hidden_shared_victim_is_not_reused_from_memory(self):
        for hidden in (False,True):
            raw=group_scene()
            memory=GameMemory(opening_complete=True)
            s,plan=decide(raw,memory)
            memory.record(s.turn,plan)
            raw['roundNo']+=1
            if hidden:
                raw['teamEnemy']['roles']=[u for u in raw['teamEnemy']['roles'] if u['id']!=41001]
            else:
                next(u for u in raw['teamEnemy']['roles'] if u['id']==41001)['health']=0
            s,plan=decide(raw,memory)
            self.assertNotEqual(memory.boss_raid['group_focus']['target_id'],41001)
            self.assertTrue(all(cmd.get('targetPos')!=[Pos(12,19).dump()]
                                for cmd in plan.commands.values() if cmd['action']=='attack'))
            self.assert_legal(s,plan)

    def test_failed_shot_repositions_instead_of_repeating_the_bad_ray(self):
        raw=group_scene()
        memory=GameMemory(opening_complete=True)
        s,plan=decide(raw,memory)
        memory.record(s.turn,plan)
        raw.update(roundNo=72,lastRoundRoleActionResults={str(FIRST):False,str(SECOND):True})
        s,plan=decide(raw,memory)
        self.assertNotEqual(plan.commands.get(str(FIRST)),dict(action='attack',targetPos=[Pos(12,19).dump()]))
        self.assert_legal(s,plan)

    def test_failed_shot_at_old_person_does_not_penalize_a_new_id_on_the_same_cell(self):
        raw=group_scene()
        memory=GameMemory(opening_complete=True)
        s,plan=decide(raw,memory)
        memory.record(s.turn,plan)
        raw.update(roundNo=72,lastRoundRoleActionResults={str(FIRST):False,str(SECOND):False})
        target=next(u for u in raw['teamEnemy']['roles'] if u['id']==41001)
        target['id']=41002
        s,plan=decide(raw,memory)
        self.assertTrue(all(plan.commands[str(uid)]==dict(action='attack',targetPos=[Pos(12,19).dump()])
                            for uid in (FIRST,SECOND)))
        self.assertEqual(memory.boss_raid['group_focus']['target_id'],41002)
        self.assert_legal(s,plan)

    def test_closed_base_without_guns_uses_one_wall_and_waits_for_real_death(self):
        raw=group_scene()
        raw['teamEnemy']['roles']=[u for u in raw['teamEnemy']['roles'] if u['roleType']=='station']
        raw['teamOur']['summonRobotList'][0]['pos']=Pos(10,20).dump()
        raw['teamOur']['summonRobotList'][1]['pos']=Pos(10,19).dump()
        raw['robot']['roles']=copy.deepcopy(raw['teamOur']['summonRobotList'])
        ring={Pos(x,y) for x in range(12,18) for y in range(17,23)
              if x in (12,17) or y in (17,22)}
        raw['teamEnemy']['roles'] += [unit(2000+i,'wall',p.x,p.y,health=40)
                                     for i,p in enumerate(sorted(ring))]
        memory=GameMemory(opening_complete=True)
        s,plan=decide(raw,memory)
        targets={tuple((p['x'],p['y'])) for cmd in plan.commands.values()
                 if cmd['action']=='attack' for p in cmd['targetPos']}
        self.assertEqual(len(targets),1)
        self.assertEqual(len(plan.commands),2)
        self.assertEqual(memory.boss_raid['group_focus']['kind'],'obstruction')
        self.assert_legal(s,plan)
        # One 40-damage shot could kill it; the second BOSS must still use the
        # actual frame, not switch to a different wall on predicted zero HP.
        self.assertTrue(all(cmd['action']=='attack' for cmd in plan.commands.values()))


if __name__=='__main__':
    unittest.main()
