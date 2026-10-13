"""Real bug-log gaps: an IMP's sight must not wait for a distant worker."""
import unittest

from agent.protocol import Pos, distance
from agent.summoning import enemy_weapon_cells, scouted_spawn_position
from app.config import Settings
from tests.fixtures import unit
from tests.test_raid_scouts import (GAP, IMP_ID, WORKER_ID, role,
                                    scout_memory, scout_request)
from tests.test_worker_safety import strategy


class ScoutBugRegressionTests(unittest.TestCase):
    def log2_scout_scene(self):
        # bug_log2 R28: the IMP had completed the real twelve-site survey;
        # R53: walls were ready, but the assigned worker was still travelling.
        raw, memory = scout_request(53, enemy_base=Pos(9,22)), scout_memory()
        role(raw, IMP_ID)['pos'] = Pos(6,23).dump()
        role(raw, WORKER_ID)['pos'] = Pos(28,8).dump()
        memory.raid_scouts['worker_id'] = WORKER_ID
        s, _ = strategy(raw, memory)
        memory.raid_scouts['surveyed'] = set(enemy_weapon_cells(s.turn))
        return raw, memory

    def test_log2_safe_imp_unlocks_summon_while_worker_travels(self):
        raw, memory = self.log2_scout_scene()
        s, _ = strategy(raw, memory)
        self.assertTrue(s.raid_scouts.walls_ready())
        self.assertFalse(memory.raid_scouts['worker_near'])
        self.assertTrue(memory.raid_scouts['imp_ready'])
        self.assertEqual(memory.raid_scouts['observer_ids'], [IMP_ID])
        self.assertTrue(s.raid_scouts.summon_ready())
        self.assertEqual(memory.raid_scouts['worker_id'], WORKER_ID)

    def test_imp_sight_does_not_release_a_worker_before_walls(self):
        raw, memory = self.log2_scout_scene()
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType']=='wall' and u['pos']==GAP.dump())]
        # This case starts before actual completion; the survey helper above
        # must not grant a historical construction approval to that scenario.
        memory.raid_scouts.pop('construction_verified_round',None)
        s, _ = strategy(raw, memory)
        self.assertTrue(memory.raid_scouts['imp_ready'])
        self.assertFalse(s.raid_scouts.summon_ready())
        worker = next(w for w in s.turn.workers() if w.unit_id==WORKER_ID)
        self.assertFalse(s.raid_scouts.is_worker(worker))

    def test_imp_close_to_a_catcher_cannot_unlock_summon(self):
        raw, memory = self.log2_scout_scene()
        raw['teamEnemy']['roles'].append(unit(1900,'worker',8,23))
        s, _ = strategy(raw, memory)
        self.assertFalse(memory.raid_scouts['imp_ready'])
        self.assertFalse(s.raid_scouts.summon_ready())
        imp = next(iter(s.turn.imps()))
        route = s.raid_scouts.scout_route(imp)
        self.assertTrue(all(distance(p,Pos(8,23))>=3 for p in route.cost if p!=imp.pos))
        s.raid_scouts.imp(imp)
        command = s.plan.commands.get(str(IMP_ID))
        if command:
            self.assertGreaterEqual(distance(Pos.load(command['targetPos'][0]),Pos(8,23)),3)

    def test_own_boss_is_never_an_observer(self):
        raw, memory = scout_request(71,enemy_base=Pos(30,10),boss=True),scout_memory()
        role(raw,IMP_ID)['pos'] = Pos(4,12).dump()
        role(raw,WORKER_ID)['pos'] = Pos(4,5).dump()
        s, _ = strategy(raw,memory)
        memory.raid_scouts['surveyed'] = set(enemy_weapon_cells(s.turn))
        s, _ = strategy(raw,memory)
        self.assertFalse(s.raid_scouts.summon_ready())
        self.assertFalse(memory.raid_scouts['imp_ready'])
        self.assertEqual(memory.raid_scouts['observer_ids'], [])

    def test_confirmed_weapon_sites_survive_death_without_live_ghost_guns(self):
        raw,memory = scout_request(enemy_base=Pos(9,22)),scout_memory()
        sites = (Pos(8,22),Pos(8,20),Pos(9,20))
        guns = [unit(1901+i,'rocket',p.x,p.y) for i,p in enumerate(sites)]
        raw['teamEnemy']['roles'] += guns
        s,_ = strategy(raw,memory)
        self.assertEqual(set(memory.enemy_weapon_sites),set(sites))
        self.assertTrue(memory.raid_scouts['layout_ready'])
        self.assertLess(memory.raid_scouts['surveyed_count'],12)
        raw['roundNo'] = 21
        for gun in guns:
            gun['health'] = 0
        s,_ = strategy(raw,memory)
        self.assertTrue(memory.raid_scouts['layout_ready'])
        self.assertEqual(set(memory.enemy_weapon_sites),set(sites))
        self.assertEqual(s.raid_scouts.known_weapons(),())
        self.assertFalse(any(u.kind=='rocket' for u in memory.enemy_structures.values()))
        self.assertFalse(s.raid_scouts.summon_ready())
        # Known sites unlock layout planning; dead guns never block the ray.
        self.assertIsNotNone(scouted_spawn_position(s.turn,Settings(),
            memory.enemy_structures.values(),confirmed_sites=memory.enemy_weapon_sites))
        # Rebuilding at a confirmed site updates its real type and id once seen.
        raw['roundNo'] = 22
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['health']>0]
        raw['teamEnemy']['roles'].append(unit(2000,'gatling',8,22))
        s,_ = strategy(raw,memory)
        self.assertEqual(memory.enemy_weapon_sites[Pos(8,22)],'gatling')
        self.assertEqual([u.unit_id for u in s.raid_scouts.known_weapons()],[2000])

    def test_live_hidden_weapons_remain_in_layout_memory(self):
        raw,memory = scout_request(enemy_base=Pos(9,22)),scout_memory()
        raw['teamEnemy']['roles'] += [unit(1901+i,'rocket',x,y)
            for i,(x,y) in enumerate(((8,22),(8,20),(9,20)))]
        strategy(raw,memory)
        raw['roundNo'] = 21
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['roleType']=='station']
        s,_ = strategy(raw,memory)
        self.assertEqual(len(s.raid_scouts.known_weapons()),3)
        self.assertEqual(len(memory.enemy_weapon_sites),3)
        self.assertTrue(memory.raid_scouts['layout_ready'])

    def test_catcher_approach_allows_strictly_improving_escape_then_full_buffer(self):
        raw,memory = scout_request(35,enemy_base=Pos(9,22)),scout_memory()
        start,catcher = Pos(8,24),Pos(8,23)
        role(raw,IMP_ID)['pos'] = start.dump()
        raw['teamEnemy']['roles'].append(unit(1900,'worker',catcher.x,catcher.y))
        memory.raid_scouts['posts'] = {IMP_ID:{'goal':start,'status':'holding','round':34}}
        for number in (35,36):
            raw['roundNo'] = number
            s,plan = strategy(raw,memory)
            imp = next(iter(s.turn.imps()))
            before = distance(imp.pos,catcher)
            s.raid_scouts.imp(imp)
            command = plan.commands[str(IMP_ID)]
            self.assertEqual(command['action'],'move')
            after = Pos.load(command['targetPos'][0])
            self.assertGreater(distance(after,catcher),before)
            self.assertGreater(distance(after,catcher),1)
            role(raw,IMP_ID)['pos'] = after.dump()
            memory.record(s.turn,plan)
        self.assertGreaterEqual(distance(after,catcher),3)
        raw['roundNo'] = 37
        s,_ = strategy(raw,memory)
        route = s.raid_scouts.scout_route(next(iter(s.turn.imps())))
        self.assertTrue(all(distance(p,catcher)>=3 for p in route.cost))

    def test_first_observation_beside_a_catcher_escapes_without_a_previous_goal(self):
        raw,memory = scout_request(35,enemy_base=Pos(9,22)),scout_memory()
        role(raw,IMP_ID)['pos'] = Pos(8,24).dump()
        raw['teamEnemy']['roles'].append(unit(1900,'worker',8,23))
        memory.raid_scouts.clear()
        s,plan = strategy(raw,memory)
        imp = next(iter(s.turn.imps()))
        goal = s.raid_scouts.post(imp)
        self.assertIsNotNone(goal)
        self.assertGreaterEqual(distance(goal,Pos(8,23)),3)
        s.raid_scouts.imp(imp)
        command = plan.commands[str(IMP_ID)]
        self.assertEqual(command['action'],'move')
        self.assertEqual(distance(Pos.load(command['targetPos'][0]),Pos(8,23)),2)


if __name__=='__main__':
    unittest.main()
