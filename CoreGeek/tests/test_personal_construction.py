"""Observed personal completion releases first-day workers independently."""
import unittest
from dataclasses import replace

from agent.actions import ActionPlan
from agent.boss_raid import BOSS_ORDER
from agent.brain import Strategy
from agent.protocol import Pos, Turn, build_command
from tests.fixtures import unit
from tests.test_wall_schedule import scene


def started_scene():
    raw, memory, settings = scene()
    settings = replace(settings, enable_tasks=True, enable_boss_raid=True)
    raw['weaponShopList'] = [dict(name=BOSS_ORDER, price=120)]
    memory.boss_raid['history_known'] = True
    make_strategy(raw, memory, settings)
    return raw, memory, settings


def make_strategy(raw, memory, settings):
    turn = Turn.load(raw)
    plan = ActionPlan(turn, settings)
    s = Strategy(turn, plan, memory)
    s.raid_scouts.refresh_dispatch()
    return s


def add_walls(raw, positions):
    for index, p in enumerate(positions, len(raw['teamOur']['roles'])):
        raw['teamOur']['roles'].append(unit(8000+index,'wall',p.x,p.y,health=1000))


class PersonalConstructionTests(unittest.TestCase):
    def test_buyer_leaves_after_own_observed_arc_while_peer_still_builds(self):
        raw, memory, settings = started_scene()
        buyer_id = memory.boss_raid['buyer_id']
        add_walls(raw, memory.sealed_home['wall_schedule']['arcs'][buyer_id])
        raw['roundNo'] += 1
        s = make_strategy(raw, memory, settings)
        buyer = next(w for w in s.turn.workers() if w.unit_id==buyer_id)
        self.assertFalse(s.boss_raid.dispatch_ready())
        self.assertTrue(s.wall_schedule.construction_ready(buyer))
        self.assertTrue(s.boss_raid.worker(buyer))
        self.assertEqual(s.plan.commands[str(buyer_id)]['action'],'move')
        self.assertEqual(s.boss_raid.state['departure_reason'],'personal_walls_ready')
        self.assertIn(buyer_id,s.wall_schedule.state['released'])
        peer = next(w for w in s.turn.workers() if w.unit_id!=buyer_id)
        self.assertFalse(s.wall_schedule.construction_ready(peer))
        self.assertTrue(s.wall_schedule.targets(peer,s.construction_walls()))

    def test_scout_leaves_after_own_arc_and_does_not_borrow_peers_walls(self):
        raw, memory, settings = started_scene()
        scout_id = next(uid for uid in memory.sealed_home['wall_schedule']['arcs']
                        if uid != memory.boss_raid['buyer_id'])
        add_walls(raw,memory.sealed_home['wall_schedule']['arcs'][scout_id])
        raw['roundNo'] += 1
        s = make_strategy(raw,memory,settings)
        scout = next(w for w in s.turn.workers() if w.unit_id==scout_id)
        self.assertFalse(s.raid_scouts.walls_ready())
        self.assertEqual(s.raid_scouts.state['worker_id'],scout_id)
        self.assertTrue(s.raid_scouts.worker(scout))
        self.assertEqual(s.plan.commands[str(scout_id)]['action'],'move')
        self.assertEqual(s.coordinator.job(scout)['kind'],'raid_scout')
        self.assertEqual(s.wall_schedule.targets(scout,s.construction_walls()),[])
        self.assertEqual(s.wall_schedule.remaining(scout),0)

    def test_submitted_last_personal_wall_does_not_count_as_completed(self):
        raw,memory,settings = started_scene()
        buyer_id = memory.boss_raid['buyer_id']
        arc = memory.sealed_home['wall_schedule']['arcs'][buyer_id]
        last = arc[-1]
        add_walls(raw,arc[:-1])
        worker = next(u for u in raw['teamOur']['roles'] if u['id']==buyer_id)
        initial = make_strategy(raw,memory,settings)
        worker['pos'] = min(initial.wall_schedule.posts(initial.boss_raid.buyer_role(),last)).dump()
        raw['roundNo'] += 1
        s = make_strategy(raw,memory,settings)
        buyer = s.boss_raid.buyer_role()
        self.assertTrue(s.plan.add(buyer_id,build_command(last,'wall')))
        self.assertFalse(s.wall_schedule.construction_ready(buyer))
        self.assertFalse(s.boss_raid.worker_mission_active(buyer))
        self.assertEqual(s.wall_schedule.assigned_missing(buyer),{last})

    def test_current_hostile_occupied_personal_gap_is_deferred(self):
        raw,memory,settings = started_scene()
        buyer_id = memory.boss_raid['buyer_id']
        arc = memory.sealed_home['wall_schedule']['arcs'][buyer_id]
        gap = arc[-1]
        add_walls(raw,arc[:-1])
        raw['teamEnemy']['roles'].append(unit(9901,'worker',gap.x,gap.y))
        raw['roundNo'] += 1
        s = make_strategy(raw,memory,settings)
        buyer = s.boss_raid.buyer_role()
        self.assertEqual(s.wall_schedule.assigned_missing(buyer),{gap})
        self.assertTrue(s.wall_schedule.construction_ready(buyer))
        self.assertTrue(s.boss_raid.worker(buyer))
        self.assertIn(gap,s.gap_guard.gaps)

    def test_historical_empty_gap_still_requires_actual_build(self):
        raw,memory,settings = started_scene()
        buyer_id = memory.boss_raid['buyer_id']
        arc = memory.sealed_home['wall_schedule']['arcs'][buyer_id]
        gap = arc[-1]
        add_walls(raw,arc[:-1])
        memory.wall_gap_defense = dict(worker_id=buyer_id,gaps={gap:dict(first_seen=1,last_seen=1)})
        raw['roundNo'] += 1
        s = make_strategy(raw,memory,settings)
        self.assertFalse(s.wall_schedule.construction_ready(s.boss_raid.buyer_role()))

    def test_dead_peer_walls_are_inherited_before_own_completion_dispatch(self):
        raw,memory,settings = started_scene()
        buyer_id = memory.boss_raid['buyer_id']
        own = set(memory.sealed_home['wall_schedule']['arcs'][buyer_id])
        add_walls(raw,own)
        next(u for u in raw['teamOur']['roles'] if u['roleType']=='worker'
             and u['id']!=buyer_id)['health'] = 0
        raw['roundNo'] += 1
        s = make_strategy(raw,memory,settings)
        buyer = s.boss_raid.buyer_role()
        self.assertTrue(s.wall_schedule.assigned_missing(buyer))
        self.assertFalse(s.wall_schedule.construction_ready(buyer))
        self.assertEqual(set(s.wall_schedule.targets(buyer,s.construction_walls())),
                         set(s.construction_walls()))

    def test_deadline_departure_releases_unfinished_arc_to_peer(self):
        raw,memory,settings = started_scene()
        raw['roundNo'] = 64
        s = make_strategy(raw,memory,settings)
        buyer = s.boss_raid.buyer_role()
        self.assertFalse(s.wall_schedule.construction_ready(buyer))
        self.assertTrue(s.boss_raid.worker(buyer))
        self.assertEqual(s.boss_raid.state['departure_reason'],'shop_deadline')
        peer = next(w for w in s.turn.workers() if w.unit_id!=buyer.unit_id)
        self.assertEqual(s.wall_schedule.assigned_missing(peer),set(s.construction_walls()))
        self.assertFalse(s.wall_schedule.construction_ready(peer))

    def test_sole_surviving_scout_resumes_abandoned_construction(self):
        raw,memory,settings = started_scene()
        scout_id = next(uid for uid in memory.sealed_home['wall_schedule']['arcs']
                        if uid != memory.boss_raid['buyer_id'])
        add_walls(raw,memory.sealed_home['wall_schedule']['arcs'][scout_id])
        raw['roundNo'] += 1
        s = make_strategy(raw,memory,settings)
        self.assertIsNotNone(s.raid_scouts.state.get('personal_dispatch_round'))
        raw['roundNo'] += 1
        next(u for u in raw['teamOur']['roles'] if u['id']==memory.boss_raid['buyer_id'])['health'] = 0
        s = make_strategy(raw,memory,settings)
        scout = next(w for w in s.turn.workers() if w.unit_id==scout_id)
        self.assertTrue(s.raid_scouts.state['paused_for_construction'])
        self.assertFalse(s.raid_scouts.is_worker(scout))
        self.assertNotIn(scout_id,s.wall_schedule.state['released'])
        self.assertEqual([w.unit_id for w in s.wall_schedule.active_builders()],[scout_id])
        self.assertEqual(s.wall_schedule.assigned_missing(scout),set(s.construction_walls()))
        self.assertEqual(set(s.wall_schedule.targets(scout,s.construction_walls())),
                         set(s.construction_walls()))
        self.assertEqual(s.stone_targets()[scout_id],len(s.construction_walls()))
        self.assertFalse(s.raid_scouts.dispatch_granted(scout))


if __name__ == '__main__':
    unittest.main()
