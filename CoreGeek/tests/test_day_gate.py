"""Temporary entrance keeps the user's sealed night drawing usable by workers."""
import copy
import unittest

from agent.protocol import Pos, Turn
from agent.grid import Routes
from app.service.turn_service import TurnService
from app.config import Settings
from tests.test_maintenance import fortified, setup
from tests.test_u_layout import point, WALLS, LANE


def gate_request(round_no=150, mirrored=False, closed=False, final=False):
    raw = fortified(round_no, mirrored=mirrored, weapon_level=3 if final else 1,
                    wall_level=2 if final else 1)
    if final:
        for wall in raw['teamOur']['roles']:
            if wall['roleType'] == 'wall' and wall['pos']['x'] == point(9, 7, mirrored).x:
                wall.update(level=3, health=2000)
    if not closed:
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                  if not (u['roleType'] == 'wall' and u['pos'] == point(5, 9, mirrored).dump())]
    return raw


class DayGateTests(unittest.TestCase):
    def test_closed_drawing_has_no_outside_to_inside_path(self):
        for mirrored in (False, True):
            raw = gate_request(mirrored=mirrored, closed=True)
            turn = Turn.load(raw)
            worker = turn.workers()[0]
            lane = {point(x, y, mirrored) for x, y in LANE}
            self.assertIsNone(Routes(turn, worker).nearest(lane))

    def test_open_gate_reconnects_shop_mine_and_each_repair_post(self):
        for mirrored in (False, True):
            raw = gate_request(mirrored=mirrored)
            s, plan = setup(raw)
            worker = s.turn.workers()[0]
            reached = set(s.route(worker).cost)
            self.assertTrue(s.guard.inner_cells() <= reached)
            self.assertIsNotNone(s.route(worker).nearest({point(3, 7, mirrored)}))
            for wall in s.turn.walls():
                self.assertTrue(any(distance == 1 for distance in
                                    [max(abs(wall.pos.x-p.x), abs(wall.pos.y-p.y))
                                     for p in s.guard.inner_cells()]))
            self.assertNotIn(s.day_gate.pos, s.movement_reserved(worker))
            self.assertEqual(plan.rejections, [])

    def test_construction_ready_requires_seal_stone_and_keeps_physical_closed_false(self):
        raw = gate_request(round_no=40)
        s, _ = setup(raw)
        self.assertFalse(s.day_gate.day_ready())
        raw['teamOur']['roles'][2]['backpack'] = ['stone']
        s, _ = setup(raw)
        self.assertTrue(s.day_gate.day_ready())
        self.assertTrue(s.first_defense.construction_ready())
        self.assertFalse(s.first_defense.closed())
        # An unrelated missing front wall cannot be dismissed as the gate.
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                                  if not (u['roleType'] == 'wall' and u['pos'] == {'x': 9, 'y': 7})]
        s, _ = setup(raw)
        self.assertFalse(s.day_gate.day_ready())

    def test_owner_collects_one_seal_stone_before_optional_supplies(self):
        raw = gate_request()
        raw['teamOur']['roles'][2]['pos'] = {'x': 4, 'y': 9}
        s, plan = setup(raw)
        s.run_worker(s.turn.workers()[0])
        self.assertEqual(plan.commands['501'], {'action': 'collect',
                                               'targetPos': [{'x': 3, 'y': 9}]})

    def test_sell_retains_only_one_stone_for_gate_owner(self):
        raw = gate_request()
        raw['teamOur']['roles'][2].update(pos={'x': 3, 'y': 7}, backpack=['stone']*4)
        s, plan = setup(raw)
        self.assertTrue(s.sell(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501']['num'], 3)
        raw['teamOur']['roles'][2]['backpack'] = ['stone']
        s, plan = setup(raw)
        self.assertFalse(s.sell(s.turn.workers()[0]))

    def test_owner_seals_from_inside_and_move_is_separate_action(self):
        for mirrored in (False, True):
            raw = gate_request(round_no=68, mirrored=mirrored)
            raw['teamOur']['roles'][2].update(pos=point(6, 8, mirrored).dump(), backpack=['stone'])
            s, plan = setup(raw)
            worker = s.turn.workers()[0]
            self.assertTrue(s.day_gate.can_seal(worker))
            s.run_worker(worker)
            self.assertEqual(plan.commands[str(worker.unit_id)],
                             {'action': 'build', 'name': 'wall',
                              'targetPos': [point(5, 9, mirrored).dump()]})
            self.assertEqual(plan.rejections, [])
            raw['teamOur']['roles'][2]['pos'] = point(4, 8, mirrored).dump()
            s, plan = setup(raw)
            s.run_worker(s.turn.workers()[0])
            self.assertEqual(plan.commands['501']['action'], 'move')
            self.assertFalse(any(c['action'] == 'build' for c in plan.commands.values()))

    def test_dual_guards_wait_until_both_inside_before_sealing(self):
        raw = gate_request(round_no=328, final=True)
        raw['teamOur']['roles'][2].update(pos={'x': 6, 'y': 8}, backpack=['stone', 'WallFixer'])
        raw['teamOur']['roles'][3].update(pos={'x': 3, 'y': 7}, backpack=['WallFixer'])
        s, plan = setup(raw)
        self.assertTrue(s.guard.full_time)
        self.assertFalse(s.day_gate.can_seal(s.turn.workers()[0]))
        s.run_worker(s.turn.workers()[0])
        self.assertEqual(plan.commands['501']['action'], 'move')
        s.run_worker(s.turn.workers()[1])
        if '504' in plan.commands:
            self.assertEqual(plan.commands['504']['action'], 'move')
        self.assertFalse(any(c['action'] == 'build' for c in plan.commands.values()))

    def test_next_morning_reopens_gate_without_changing_other_wall_sites(self):
        raw = gate_request(round_no=131, closed=True)
        raw['teamOur']['roles'][2]['pos'] = {'x': 6, 'y': 8}
        s, plan = setup(raw)
        s.run_worker(s.turn.workers()[0])
        self.assertEqual(plan.commands['501'], {'action': 'remove', 'targetPos': [{'x': 5, 'y': 9}]})
        self.assertEqual(len(s.settings.build_cells(s.turn, 'wall')), 17)

    def test_night_never_opens_gate_and_complete_template_matches_blueprint(self):
        raw = gate_request(round_no=201, closed=True)
        raw['teamOur']['roles'][2].update(pos={'x': 6, 'y': 8}, backpack=['stone'])
        s, plan = setup(raw)
        self.assertFalse(s.day_gate.worker(s.turn.workers()[0]))
        self.assertEqual({(w.pos.x, w.pos.y) for w in s.turn.walls()}, WALLS)
        self.assertFalse(any(c['action'] == 'remove' for c in plan.commands.values()))

    def test_two_workers_pass_entry_and_restore_seventeen_walls_before_night(self):
        for mirrored in (False, True):
            raw = gate_request(round_no=319, mirrored=mirrored, final=True)
            raw['teamOur']['roles'][2].update(pos=point(6, 8, mirrored).dump(),
                                            backpack=['stone', 'WallFixer', 'WallUpgradeVoucher1'])
            raw['teamOur']['roles'][3].update(pos=point(3, 7, mirrored).dump(), backpack=['WallFixer'])
            service = TurnService(Settings(enable_boss_raid=False))
            sealed_round = None
            for number in range(319, 332):
                raw['roundNo'] = number
                before = Turn.load(raw)
                reply = service.decide(copy.deepcopy(raw))
                roles = {str(u['id']): u for u in raw['teamOur']['roles']}
                moved_to = set()
                for uid, command in reply['roleCommandMap'].items():
                    actor = roles[uid]
                    if actor['roleType'] != 'worker':
                        continue
                    if command['action'] == 'move':
                        target = Pos.load(command['targetPos'][0])
                        self.assertNotIn(target, before.occupied_cells())
                        self.assertNotIn(target, moved_to)
                        moved_to.add(target)
                        actor['pos'] = target.dump()
                    elif command['action'] == 'build':
                        self.assertLessEqual(number, 330)
                        self.assertEqual(command['targetPos'][0], point(5, 9, mirrored).dump())
                        actor['backpack'].remove('stone')
                        p = Pos.load(command['targetPos'][0])
                        from tests.fixtures import unit
                        raw['teamOur']['roles'].append(unit(2000, 'wall', p.x, p.y, health=1000))
                        sealed_round = number
                    elif command['action'] == 'use':
                        self.assertEqual(command['name'], 'WallUpgradeVoucher1')
                        actor['backpack'].remove(command['name'])
                        gate = next(u for u in raw['teamOur']['roles'] if u['id'] == 2000)
                        gate.update(level=2, health=1500)
                if sealed_round is not None and next(u for u in raw['teamOur']['roles'] if u['id'] == 2000)['level'] == 2:
                    break
            self.assertIsNotNone(sealed_round, 'both workers must enter and seal rather than wait forever')
            turn = Turn.load(raw)
            self.assertEqual({w.pos for w in turn.walls()}, {point(x,y,mirrored) for x,y in WALLS})
            gate = next(w for w in turn.walls() if w.pos == point(5,9,mirrored))
            self.assertEqual((gate.level, gate.health), (2, 1500))

    def test_coupon_preparation_waits_for_all_other_upgrades_and_de_duplicates(self):
        raw = gate_request(final=True)
        raw['teamOur']['roles'][2].update(pos={'x': 3, 'y': 7}, backpack=['stone'])
        s, plan = setup(raw)
        s.run_worker(s.turn.workers()[0])
        self.assertEqual(plan.commands['501'], {'action': 'buy', 'name': 'WallUpgradeVoucher1', 'num': 1})
        raw['teamOur']['roles'][2]['backpack'].append('WallUpgradeVoucher1')
        s, plan = setup(raw)
        self.assertFalse(s.day_gate.prepare_coupon(s.turn.workers()[0]))
        raw['teamOur']['roles'][2]['backpack'].remove('WallUpgradeVoucher1')
        next(w for w in raw['teamOur']['roles'] if w['roleType'] == 'rocket')['level'] = 2
        s, plan = setup(raw)
        self.assertFalse(s.day_gate.prepare_coupon(s.turn.workers()[0]))

    def test_coupon_does_not_ignore_gold_capacity_or_return_window(self):
        for gold, bag, round_no in ((19,['stone'],150), (20,['stone']+['WallFixer']*99,150),
                                    (1000,['stone'],200)):
            raw = gate_request(round_no=round_no, final=True)
            raw['teamOur']['goldNum'] = gold
            raw['teamOur']['roles'][2].update(pos={'x': 3, 'y': 7}, backpack=bag)
            s, plan = setup(raw)
            self.assertFalse(s.day_gate.prepare_coupon(s.turn.workers()[0]))
            self.assertEqual(plan.commands, {})

    def test_opponent_on_gate_keeps_existing_body_relay_and_releases_it_next_day(self):
        from agent.actions import ActionPlan
        from agent.brain import Strategy
        from tests.fixtures import unit
        raw = gate_request(round_no=40)
        raw['teamOur']['roles'][2].update(pos={'x':4,'y':8}, backpack=['stone'])
        raw['teamEnemy']['roles'] = [unit(901, 'worker', 5, 9)]
        s, plan = setup(raw)
        self.assertIn(Pos(5,9), s.gap_guard.gaps)
        self.assertTrue(s.day_gate.day_ready(s.gap_guard.gaps))
        self.assertFalse(s.day_gate.worker(s.turn.workers()[0]))
        memory = s.memory
        raw.update(roundNo=71)
        raw['teamEnemy']['roles'] = []
        turn = Turn.load(raw)
        plan = ActionPlan(turn, Settings(enable_boss_raid=False))
        s = Strategy(turn, plan, memory)
        self.assertTrue(s.gap_guard.worker(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501'], {'action':'move','targetPos':[{'x':5,'y':9}]})
        raw.update(roundNo=131)
        raw['teamOur']['roles'][2]['pos'] = {'x':5,'y':9}
        turn = Turn.load(raw)
        s = Strategy(turn, ActionPlan(turn, Settings(enable_boss_raid=False)), memory)
        self.assertFalse(s.gap_guard.gaps)
        self.assertEqual(len(s.settings.build_cells(s.turn, 'wall')), 17)

