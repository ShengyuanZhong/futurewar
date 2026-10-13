"""All seventeen walls consume ordinary material; no recurring seal reserve."""
import unittest
from dataclasses import replace

from agent.protocol import Pos
from tests.test_worker_boss_buyer import actor, worker_raid_scene, load_strategy


class GateMaterialsTests(unittest.TestCase):
    def test_former_gate_owner_can_spend_last_stone_on_nearby_ordinary_wall(self):
        raw,memory,settings = worker_raid_scene(round_no=20,finished=0)
        settings = replace(settings,enable_boss_raid=False)
        missing = Pos(11,24)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType']=='wall' and u['pos']==missing.dump())]
        actor(raw,501).update(pos=Pos(12,24).dump(),backpack=['stone'])
        actor(raw,504).update(pos=Pos(12,26).dump(),backpack=[])
        s,plan = load_strategy(raw,memory,settings)
        owner,scout = (next(w for w in s.turn.workers() if w.unit_id==uid) for uid in (501,504))
        self.assertIsNone(s.day_gate.worker_id)
        self.assertEqual(s.day_gate.reserve_stone(owner),0)
        self.assertEqual(s.stone_targets(),{501:1,504:0})
        self.assertTrue(s.build_wall(owner,local_only=True))
        self.assertEqual(plan.commands['501'],dict(action='build',name='wall',targetPos=[missing.dump()]))
        self.assertNotIn('504',plan.commands)
        self.assertEqual(plan.rejections,[])

    def test_seventeen_missing_walls_need_exactly_seventeen_real_stones(self):
        raw,memory,settings = worker_raid_scene(round_no=1,finished=0)
        settings = replace(settings,enable_boss_raid=False)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['roleType']!='wall']
        actor(raw,501)['backpack'] = []
        actor(raw,504)['backpack'] = []
        memory.opening_complete = False
        s,_ = load_strategy(raw,memory,settings)
        targets = s.stone_targets()
        self.assertEqual(len(s.construction_walls()),17)
        self.assertEqual(sum(targets.values()),17)
        self.assertEqual(targets,{w.unit_id:s.wall_schedule.remaining(w) for w in s.turn.workers()})

    def test_no_gate_owner_is_needed_to_keep_buyer_and_scout_distinct(self):
        raw,memory,settings = worker_raid_scene(round_no=20,finished=0)
        s,_ = load_strategy(raw,memory,settings)
        self.assertIsNone(s.day_gate.worker_id)
        self.assertIsNone(s.day_gate.pos)
        self.assertEqual(s.boss_raid.buyer_id,501)
        self.assertEqual(s.raid_scouts.state.get('worker_id'),504)
        self.assertNotEqual(s.raid_scouts.state.get('worker_id'),501)


if __name__=='__main__':
    unittest.main()
