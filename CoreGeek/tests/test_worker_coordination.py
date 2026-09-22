"""Independent worker goals, cooperative yielding, shelter and late-game stock."""
import unittest
from agent.protocol import Pos, Turn
from agent.worker_safety import robot_danger
from app.service.memory import GameMemory
from tests.fixtures import request, unit, robot
from tests.test_worker_safety import strategy
from tests.test_focused_upgrades import finished, set_wall
from tests.test_maintenance import fortified
from tests.test_u_layout import point
from app.config import Settings
import json
import tempfile
from pathlib import Path


class WorkerCoordinationTests(unittest.TestCase):
    def test_blocked_guard_entrance_does_not_trigger_distant_escape(self):
        raw=finished();raw['teamOur']['roles'][2]['pos']={'x':10,'y':7}
        raw['robot']['roles']=[robot(900,12,7)]
        raw['mapInfo']['zones'] += [{'neutralType':'stone','pos':{'x':6,'y':y}} for y in (8,5)]
        s,plan=strategy(raw);s.run()
        self.assertGreater(s.danger.get(Pos(10,7),0),0)
        self.assertNotIn('501',plan.commands)

    def test_no_yield_pocket_waits_without_illegal_swap(self):
        raw=request(20);raw['teamOur']['roles']=[unit(501,'worker',2,2),unit(504,'worker',3,2)]
        free={Pos(2,2),Pos(3,2),Pos(4,2)}
        raw['mapInfo']['zones']=[{'neutralType':'stone','pos':{'x':x,'y':y}}
                                for x in range(41) for y in range(32) if Pos(x,y) not in free]
        s,plan=strategy(raw)
        s.coordinator.move_to(s.turn.workers()[0],{Pos(4,2)},'delivery',Pos(4,2))
        self.assertEqual(plan.commands,{})
        self.assertEqual(plan.rejections,[])

    def test_corner_touch_is_not_cover_and_multiple_enemies_are_independent(self):
        from agent.worker_safety import wall_shelters
        self.assertFalse(wall_shelters(Pos(0,0),Pos(2,2),[Pos(1,0)]))
        self.assertTrue(wall_shelters(Pos(0,0),Pos(2,2),[Pos(1,1)]))
        raw=finished();raw['robot']['roles']=[robot(900,11,7),robot(901,8,8)]
        s,_=strategy(raw)
        self.assertGreater(s.danger.get(Pos(8,7),0),0)

    def test_night_breach_keeps_both_repairers_until_daytime_rebuilding(self):
        raw=finished();memory=GameMemory(opening_complete=True)
        s,_=strategy(raw,memory)
        self.assertTrue(s.guard.full_time)
        raw['roundNo']+=1;set_wall(raw,9,7,3,health=0)
        s,plan=strategy(raw,memory);s.run()
        self.assertTrue(all(s.guard.is_guard(w) for w in s.turn.workers()))
        self.assertFalse(any(c['action']=='collect' for c in plan.commands.values()))
        raw['roundNo']=391;s,_=strategy(raw,memory)
        self.assertFalse(s.guard.full_time)

    def test_actual_repair_usage_rolls_over_without_counting_failed_use(self):
        memory=GameMemory(day=3,last_round=389,last_commands={'501':{'action':'use','name':'WallFixer'}})
        raw=fortified(390);raw['lastRoundRoleActionResults']={'501':False}
        memory.observe(Turn.load(raw));self.assertEqual(memory.repair_usage_today,{})
        memory.last_round=390
        raw.update(roundNo=391,lastRoundRoleActionResults={'501':True})
        memory.observe(Turn.load(raw))
        self.assertEqual(memory.repair_usage_previous,{501:1})
        self.assertEqual(memory.repair_usage_today,{})

    def test_growth_configuration_can_be_disabled_and_rejects_invalid_values(self):
        for value in (-1,101,True,1.5):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'config.json';p.write_text(json.dumps({'repair_stock_per_day':value}))
                with self.assertRaises(ValueError):Settings.load(str(p))
        s,_=strategy(fortified(1171),settings=Settings(repair_stock_per_day=0))
        self.assertEqual(s.guard.stock_missing(),5)

    def test_worker_tasks_discard_dead_and_stale_owners(self):
        raw=finished();memory=GameMemory(opening_complete=True)
        memory.worker_tasks={501:{'round':330,'target':Pos(9,7)},504:{'round':1,'target':Pos(9,6)}}
        raw['teamOur']['roles'][2]['health']=0
        s,_=strategy(raw,memory)
        self.assertEqual(memory.worker_tasks,{})

    def test_swapped_repair_posts_converge_without_swap_or_destination_collision(self):
        raw=finished();raw['teamOur']['goldNum']=0
        raw['teamOur']['roles'][2]['pos']={'x':8,'y':6}
        raw['teamOur']['roles'][3]['pos']={'x':8,'y':7}
        memory=GameMemory(opening_complete=True)
        for n in range(331,351):
            raw['roundNo']=n;s,plan=strategy(raw,memory);s.run()
            destinations=[]
            for uid,cmd in plan.commands.items():
                if uid not in ('501','504') or cmd['action']!='move':continue
                target=Pos.load(cmd['targetPos'][0]);destinations.append(target)
                self.assertNotIn(target,s.turn.occupied_cells())
                self.assertIn(target,s.guard.inner_cells())
                next(r for r in raw['teamOur']['roles'] if str(r['id'])==uid)['pos']=target.dump()
            self.assertEqual(len(destinations),len(set(destinations)))
            self.assertEqual(plan.rejections,[])
            memory.record(s.turn,plan)
            if raw['teamOur']['roles'][2]['pos']=={'x':8,'y':7} and raw['teamOur']['roles'][3]['pos']=={'x':8,'y':6}:break
        else:self.fail('swapped posts failed to converge')

    def test_standing_wall_shelters_but_breach_and_inside_robot_do_not(self):
        for mirrored in (False, True):
            raw=finished(mirrored=mirrored)
            raw['robot']['roles']=[robot(900,point(11,7,mirrored).x,7)]
            s,_=strategy(raw)
            self.assertEqual(s.danger.get(point(8,7,mirrored),0),0)
            set_wall(raw,9,7,3,mirrored,health=0)
            s,_=strategy(raw)
            self.assertGreater(s.danger.get(point(8,7,mirrored),0),0)
            raw['robot']['roles']=[robot(900,point(8,8,mirrored).x,8)]
            s,_=strategy(raw)
            self.assertGreater(s.danger.get(point(8,7,mirrored),0),0)

    def test_guard_repairs_behind_wall_with_enemy_close(self):
        raw=finished();set_wall(raw,9,7,3,health=100)
        raw['robot']['roles']=[robot(900,11,7)]
        s,plan=strategy(raw);s.run()
        self.assertEqual(plan.commands['501']['name'],'WallFixer')
        for uid in (501,504):
            cmd=plan.commands.get(str(uid),{})
            if cmd.get('action')=='move':self.assertIn(Pos.load(cmd['targetPos'][0]),s.guard.inner_cells())

    def test_worker_has_separate_persistent_mining_target(self):
        raw=request(20)
        raw['teamOur']['roles']=[unit(501,'worker',8,10),unit(504,'worker',12,10)]
        raw['mapInfo']['zones']=[{'neutralType':'stone','pos':{'x':10,'y':12}},
                                {'neutralType':'stone','pos':{'x':10,'y':8}}]
        memory=GameMemory(opening_complete=True)
        s,plan=strategy(raw,memory)
        for worker in s.turn.workers():s.mine(worker)
        jobs=memory.worker_tasks
        self.assertEqual(set(jobs),{501,504})
        self.assertNotEqual(jobs[501]['target'],jobs[504]['target'])
        self.assertNotEqual(jobs[501]['goal'],jobs[504]['goal'])

    def test_yield_pocket_unblocks_corridor_without_swap(self):
        raw=request(20)
        raw['teamOur']['roles']=[unit(501,'worker',2,2),unit(504,'worker',3,2)]
        free={Pos(x,2) for x in range(1,7)}|{Pos(4,3)}
        raw['mapInfo']['zones']=[{'neutralType':'stone','pos':{'x':x,'y':y}}
                                for x in range(41) for y in range(32) if Pos(x,y) not in free]
        memory=GameMemory(opening_complete=True)
        visited=[]
        for number in range(20,28):
            raw['roundNo']=number;s,plan=strategy(raw,memory)
            mover=s.turn.workers()[0]
            if mover.pos==Pos(6,2):break
            s.coordinator.move_to(mover,{Pos(6,2)},'delivery',Pos(6,2))
            destinations=[]
            for uid,cmd in plan.commands.items():
                actor=next(r for r in raw['teamOur']['roles'] if str(r['id'])==uid)
                self.assertEqual(cmd['action'],'move')
                target=Pos.load(cmd['targetPos'][0]);destinations.append(target)
                self.assertNotIn(target,s.turn.occupied_cells())
                actor['pos']=target.dump()
            self.assertEqual(len(destinations),len(set(destinations)))
            self.assertEqual(plan.rejections,[])
            visited.append(dict(plan.commands));memory.record(s.turn,plan)
        else:self.fail('worker never passed the blocker')
        self.assertEqual(visited[0]['504']['targetPos'],[{'x':4,'y':3}])

    def test_stock_grows_by_day_and_previous_actual_usage(self):
        for day,expected in ((3,5),(4,8),(6,14),(10,26)):
            raw=fortified((day-1)*130+1)
            s,_=strategy(raw)
            self.assertEqual(s.guard.stock_missing(),expected)
        memory=GameMemory(opening_complete=True)
        memory.repair_usage_previous={501:17}
        s,_=strategy(fortified(391),memory)
        self.assertEqual(s.guard.stock_missing(),19)

    def test_two_guards_keep_upper_lower_posts(self):
        raw=finished();raw['teamOur']['goldNum']=0
        raw['teamOur']['roles'][2]['pos']={'x':6,'y':8}
        raw['teamOur']['roles'][3]['pos']={'x':6,'y':5}
        memory=GameMemory(opening_complete=True)
        for n in range(331,340):
            raw['roundNo']=n;s,plan=strategy(raw,memory);s.run()
            for uid,cmd in plan.commands.items():
                if uid not in ('501','504'):continue
                actor=next(r for r in raw['teamOur']['roles'] if str(r['id'])==uid)
                if cmd['action']=='move':
                    dest=Pos.load(cmd['targetPos'][0]);self.assertIn(dest,s.guard.inner_cells())
                    actor['pos']=dest.dump()
            memory.record(s.turn,plan)
        self.assertEqual(raw['teamOur']['roles'][2]['pos'],{'x':8,'y':7})
        self.assertEqual(raw['teamOur']['roles'][3]['pos'],{'x':8,'y':6})
