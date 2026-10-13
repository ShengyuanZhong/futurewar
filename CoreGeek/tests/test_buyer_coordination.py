"""Day-one dispatch and scouting stay separate from a shop worker's return cost."""
import unittest

from agent.protocol import Pos, Turn, build_command
from app.config import Settings
from app.service.memory import GameMemory
from tests.test_raid_scouts import HOME_ID, WORKER_ID, role, scout_memory, scout_request
from tests.test_worker_safety import strategy


def dispatch_scene(round_no=69):
    raw = scout_request(round_no)
    # The dispatcher starts from the completed permanent drawing, rather than
    # the historical fixture's daytime doorway. Both workers are outside.
    from tests.fixtures import unit
    raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['roleType']!='wall']
    turn = Turn.load(raw)
    raw['teamOur']['roles'] += [unit(700+i,'wall',p.x,p.y,health=1000)
        for i,p in enumerate(Settings().build_cells(turn,'wall'))]
    role(raw, HOME_ID).update(pos=Pos(20, 15).dump(), backpack=['stone'])
    memory = scout_memory()
    memory.raid_scouts.update(worker_id=WORKER_ID, home_worker_id=HOME_ID)
    memory.boss_raid['buyer_id'] = HOME_ID
    return raw, memory


def buyer_gap_scene(departed=True):
    from tests.test_gap_defense import GAP, occupied
    raw = occupied(70)
    role(raw, HOME_ID)['pos'] = Pos(3, 7).dump()
    memory = GameMemory(opening_complete=True,
                        boss_raid={'buyer_id':HOME_ID, 'buyer_departed':departed},
                        wall_gap_defense={'worker_id':HOME_ID})
    strategy(raw, memory)
    raw['roundNo'] = 71
    raw['teamEnemy']['roles'] = []
    memory.worker_tasks[HOME_ID] = dict(round=70, kind='gap_body', target=GAP,
                                      goal=GAP, position=Pos(3, 7), moving=True)
    return raw, memory


class BuyerCoordinationTests(unittest.TestCase):
    def test_imp_covers_actual_gap_while_alive_dispatched_buyer_is_at_shop(self):
        from tests.test_gap_defense import GAP
        for departed in (False, True):
            with self.subTest(departed=departed):
                raw, memory = buyer_gap_scene(departed)
                s, plan = strategy(raw, memory)
                imp = next(iter(s.turn.imps()))
                self.assertEqual(s.gap_guard.backup_needed(), departed)
                self.assertEqual(s.gap_guard.enter_gap(imp), departed)
                self.assertTrue(s.gap_guard.imp(imp))
                target = plan.commands.get(str(imp.unit_id),{}).get('targetPos')
                if departed:
                    self.assertEqual(target, [GAP.dump()])
                else:
                    self.assertNotEqual(target, [GAP.dump()])
                self.assertEqual(plan.rejections, [])
        # A future worker goal may be ignored, a real same-frame move cannot.
        raw, memory = buyer_gap_scene()
        s, plan = strategy(raw, memory)
        imp = next(iter(s.turn.imps()))
        plan.reserved.add(GAP)
        self.assertTrue(s.gap_guard.imp(imp))
        self.assertNotEqual(plan.commands.get(str(imp.unit_id),{}).get('targetPos'), [GAP.dump()])

    def test_imp_yields_gap_when_buyer_is_actually_back_at_an_adjacent_cell(self):
        from tests.test_gap_defense import GAP
        raw, memory = buyer_gap_scene()
        raw['roundNo'] = 72
        role(raw, HOME_ID)['pos'] = Pos(8, 7).dump()
        role(raw, 505)['pos'] = GAP.dump()
        memory.worker_tasks[HOME_ID]['round'] = 71
        s, plan = strategy(raw, memory)
        imp = next(iter(s.turn.imps()))
        self.assertFalse(s.gap_guard.backup_needed())
        self.assertFalse(s.gap_guard.enter_gap(imp))
        self.assertTrue(s.gap_guard.imp(imp))
        command = plan.commands[str(imp.unit_id)]
        self.assertEqual(command['action'], 'move')
        self.assertNotEqual(command['targetPos'], [GAP.dump()])
        self.assertEqual(memory.wall_gap_defense['imp_status'], 'standby')
        self.assertEqual(plan.rejections, [])

    def test_far_buyer_does_not_revoke_completed_construction_or_current_scout(self):
        raw, memory = dispatch_scene()
        s, plan = strategy(raw, memory)
        self.assertTrue(s.day_gate.day_ready())
        self.assertTrue(s.day_gate.dispatch_ready())
        self.assertTrue(s.raid_scouts.walls_ready())
        scout = next(w for w in s.turn.workers() if w.unit_id == WORKER_ID)
        self.assertTrue(s.raid_scouts.is_worker(scout))
        self.assertTrue(s.raid_scouts.worker(scout))
        self.assertIsNone(s.day_gate.worker_id)
        self.assertIsNone(s.day_gate.pos)
        self.assertFalse(s.day_gate.enabled)
        self.assertEqual(plan.rejections, [])
        buyer = next(w for w in s.turn.workers() if w.unit_id == HOME_ID)
        # Explicit buyer exclusion also applies to stale role assignments,
        # independently of the doorway/home guard identities.
        s.day_gate.enabled = False
        s.gap_guard.worker_id = None
        s.raid_scouts.state['worker_id'] = HOME_ID
        self.assertFalse(s.raid_scouts.is_worker(buyer))
        self.assertFalse(s.raid_scouts.worker(buyer))
        s.raid_scouts.state['worker_id'] = WORKER_ID
        self.assertTrue(s.raid_scouts.is_worker(scout))

    def test_dispatch_requires_observed_wall_completion_but_no_seal_stone(self):
        raw, memory = dispatch_scene(40)
        role(raw, HOME_ID)['backpack'] = []
        s, _ = strategy(raw, memory)
        self.assertTrue(s.day_gate.dispatch_ready())
        self.assertEqual(len(s.turn.walls()),17)
        self.assertEqual(s.day_gate.reserve_stone(next(w for w in s.turn.workers()
                                                     if w.unit_id==HOME_ID)),0)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                 if not (u['roleType'] == 'wall' and u['pos'] == Pos(9, 7).dump())]
        role(raw, WORKER_ID).update(pos=Pos(8, 7).dump(), backpack=['stone'])
        s, plan = strategy(raw, memory)
        self.assertFalse(s.day_gate.dispatch_ready())
        self.assertTrue(plan.add(WORKER_ID, build_command(Pos(9, 7), 'wall')))
        self.assertFalse(s.day_gate.dispatch_ready())

    def test_observed_occupied_gap_can_be_ignored_but_not_an_unfinished_site(self):
        from tests.fixtures import unit
        raw, memory = dispatch_scene(40)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                 if not (u['roleType'] == 'wall' and u['pos'] == Pos(9, 7).dump())]
        s, _ = strategy(raw, memory)
        self.assertFalse(s.day_gate.dispatch_ready(s.gap_guard.gaps))
        raw['teamEnemy']['roles'].append(unit(901, 'worker', 9, 7, health=500))
        s, _ = strategy(raw, memory)
        self.assertIn(Pos(9, 7), s.gap_guard.gaps)
        self.assertTrue(s.day_gate.dispatch_ready(s.gap_guard.gaps))


if __name__ == '__main__':
    unittest.main()
