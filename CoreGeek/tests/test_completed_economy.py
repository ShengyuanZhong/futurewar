"""Completed defenses must fund repair kits by continuing daytime work."""
import unittest

from agent.protocol import Pos
from app.service.memory import GameMemory
from tests.test_focused_upgrades import finished
from tests.test_u_layout import point
from tests.test_worker_safety import strategy


class CompletedEconomyTests(unittest.TestCase):
    def mining_map(self, mirrored=False):
        raw = finished(261, mirrored)
        raw['teamOur']['goldNum'] = 0
        raw['vendorShopList'] = [{'name':'stone','price':3}, {'name':'iron','price':3}]
        raw['mapInfo']['zones'].append({'neutralType':'iron', 'pos':point(3,5,mirrored).dump()})
        raw['teamOur']['roles'][2]['pos'] = point(4,9,mirrored).dump()
        raw['teamOur']['roles'][3]['pos'] = point(4,5,mirrored).dump()
        return raw

    def test_both_stocked_workers_keep_mining_during_day(self):
        for mirrored in (False, True):
            raw = self.mining_map(mirrored)
            s, plan = strategy(raw); s.run()
            for uid in ('501','504'):
                self.assertEqual(plan.commands[uid]['action'], 'collect')
            self.assertEqual(plan.rejections, [])

    def test_selling_funds_new_kits_after_upgrades(self):
        raw = finished(261)
        raw['teamOur']['goldNum'] = 0
        raw['teamOur']['roles'][2].update(pos={'x':3,'y':7}, backpack=['WallFixer']*5+['iron']*12)
        raw['vendorShopList'] = [{'name':'iron','price':5}]
        raw['weaponShopList'][-1]['price'] = 15
        memory = GameMemory(opening_complete=True)
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501'], {'action':'sell','name':'iron','num':12})
        memory.record(s.turn, plan)
        raw['roundNo'] += 1
        raw['teamOur']['roles'][2]['backpack'] = ['WallFixer']*5
        raw['teamOur']['goldNum'] = 60
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(plan.commands['501']['action'], 'buy')
        self.assertEqual(plan.commands['501']['name'], 'WallFixer')
        self.assertGreater(plan.commands['501']['num'], 1)

    def test_bulk_kit_purchase_keeps_a_batch_of_mining_space(self):
        raw = finished(261)
        raw['teamOur']['goldNum'] = 10000
        raw['teamOur']['roles'][2].update(pos={'x':3,'y':7}, backpack=[])
        raw['teamOur']['roles'][3]['backpack'] = []
        s, plan = strategy(raw); s.run()
        command = plan.commands['501']
        self.assertEqual(command['action'], 'buy')
        self.assertEqual(command['name'], 'WallFixer')
        self.assertEqual(command['num'], 100-s.settings.sell_batch)

    def test_both_workers_return_before_night_and_work_again_next_day(self):
        for mirrored in (False, True):
            raw = self.mining_map(mirrored)
            memory = GameMemory(opening_complete=True)
            for number in range(325, 339):
                raw['roundNo'] = number
                s, plan = strategy(raw, memory); s.run()
                for uid in ('501','504'):
                    command = plan.commands.get(uid, {})
                    self.assertNotIn(command.get('action'), ('collect','sell','buy'))
                    if number >= 331:
                        self.assertIn(next(w for w in s.turn.workers() if str(w.unit_id)==uid).pos,
                                      s.guard.inner_cells())
                    if command.get('action') == 'move':
                        next(r for r in raw['teamOur']['roles'] if str(r['id'])==uid)['pos'] = command['targetPos'][0]
                self.assertEqual(plan.rejections, [])
                memory.record(s.turn, plan)
            actions = set()
            for number in range(391, 406):
                raw['roundNo'] = number
                s, plan = strategy(raw, memory); s.run()
                for uid in ('501','504'):
                    command = plan.commands.get(uid, {})
                    if command.get('action') == 'collect':
                        actions.add(uid)
                    if command.get('action') == 'move':
                        next(r for r in raw['teamOur']['roles'] if str(r['id'])==uid)['pos'] = command['targetPos'][0]
                memory.record(s.turn, plan)
            self.assertEqual(actions, {'501','504'})


if __name__ == '__main__':
    unittest.main()
