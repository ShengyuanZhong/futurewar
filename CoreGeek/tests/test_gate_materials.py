"""Keep the daytime entrance's stone out of ordinary wall construction."""
import unittest

from agent.protocol import Pos
from app.config import Settings
from app.service.memory import GameMemory
from tests.test_three_tasks import three_task_request
from tests.test_layout_survey import actor
from tests.test_worker_safety import strategy


class GateMaterialsTests(unittest.TestCase):
    def test_owner_seal_stone_cannot_claim_the_nearby_builders_last_wall(self):
        raw,_ = three_task_request(20)
        missing = Pos(9,6)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType']=='wall' and u['pos'] in (Pos(5,9).dump(),missing.dump()))]
        actor(raw,501).update(pos=Pos(3,7).dump(),backpack=['stone'])
        actor(raw,504).update(pos=Pos(8,6).dump(),backpack=['stone'])
        s,plan = strategy(raw,GameMemory(opening_complete=True),Settings(enable_news=False))
        owner,scout = (next(w for w in s.turn.workers() if w.unit_id==uid) for uid in (501,504))
        self.assertEqual(s.day_gate.worker_id,owner.unit_id)
        self.assertEqual(s.stone_targets(),{501:1,504:1})
        self.assertFalse(s.build_wall(owner))
        self.assertNotIn('501',plan.commands)
        self.assertTrue(s.build_wall(scout))
        self.assertEqual(plan.commands['504'],dict(action='build',name='wall',targetPos=[missing.dump()]))

    def test_opening_stone_quota_includes_one_real_seal_stone(self):
        raw,_ = three_task_request()
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['roleType']!='wall']
        actor(raw,501)['backpack'] = []
        actor(raw,504)['backpack'] = []
        s,_ = strategy(raw,GameMemory(),Settings(enable_news=False))
        targets = s.stone_targets()
        self.assertEqual(len(s.construction_walls()),16)
        self.assertEqual(sum(targets.values()),17)
        self.assertEqual(targets,{501:9,504:8})

    def test_gate_owner_cannot_be_sent_away_as_scout_when_first_defense_is_disabled(self):
        raw,_ = three_task_request(20)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType']=='wall' and u['pos']==Pos(5,9).dump())]
        actor(raw,501).update(pos=Pos(18,10).dump(),backpack=['stone'])
        actor(raw,504).update(pos=Pos(3,6).dump(),backpack=['stone'])
        s,_ = strategy(raw,GameMemory(opening_complete=True),
                       Settings(enable_news=False,enable_first_night_defense=False))
        self.assertEqual(s.day_gate.worker_id,501)
        self.assertNotEqual(s.raid_scouts.state.get('worker_id'),501)


if __name__=='__main__':
    unittest.main()
