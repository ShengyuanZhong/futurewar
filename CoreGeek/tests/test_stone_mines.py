"""First-day finite stone stocks and stable independent mining appointments."""
import unittest
from agent.protocol import Pos, Turn
from tests.test_stone_planner import scene


A,B,C=Pos(4,8),Pos(14,8),Pos(1,8)


class StoneMineTests(unittest.TestCase):
    def test_two_ten_stone_mines_split_seventeen_stone_demand(self):
        _,s,plan,planner=scene(mines=[('stone',A),('stone',B)],remaining={A:10,B:10})
        for worker in s.turn.workers():
            self.assertTrue(planner.mine(worker))
        self.assertEqual(set(planner.state['assignments'].values()),{A,B})
        self.assertFalse(planner.state['shared_fallback'])
        self.assertEqual(sum(planner.targets().values()),17)
        self.assertFalse(plan.rejections)

    def test_fresh_assignment_prefers_stocks_that_cover_each_share(self):
        _,s,_,planner=scene(mines=[('stone',A),('stone',B),('stone',C)],remaining={A:2,B:10,C:10})
        self.assertEqual(set(planner.assignments().values()),{B,C})
        self.assertEqual(s.turn.mine_remaining[A],2)

    def test_shrinking_stock_and_new_near_mine_do_not_reverse_a_valid_trip(self):
        _,s,_,planner=scene(mines=[('stone',A),('stone',B)],remaining={A:10,B:10})
        before=planner.assignments()
        self.assertEqual(before,{501:A,504:B})
        _,next_s,_,next_planner=scene(number=13,memory=s.memory,
            mines=[('stone',A),('stone',B),('stone',C)],remaining={A:2,B:9,C:10})
        self.assertEqual(next_planner.assignments(),before)
        self.assertEqual(next_s.turn.mine_remaining[A],2)

    def test_actual_mine_disappearance_releases_only_its_owner(self):
        _,s,_,planner=scene(mines=[('stone',A),('stone',B)],remaining={A:10,B:10})
        self.assertEqual(planner.assignments(),{501:A,504:B})
        _,_,_,next_planner=scene(number=13,memory=s.memory,
            mines=[('stone',B),('stone',C)],remaining={B:8,C:10})
        self.assertEqual(next_planner.assignments(),{501:C,504:B})

    def test_failed_mine_is_not_reserved_for_another_worker(self):
        _,s,_,planner=scene(mines=[('stone',A),('stone',B)],remaining={A:10,B:10})
        planner.assignments()
        s.memory.failed_mines['4,8']=16
        _,_,_,next_planner=scene(number=13,memory=s.memory,
            mines=[('stone',A),('stone',B),('stone',C)],remaining={A:10,B:8,C:10})
        self.assertEqual(next_planner.assignments(),{501:C,504:B})

    def test_only_one_mine_keeps_workers_working_at_distinct_posts(self):
        _,s,plan,planner=scene(remaining={A:10})
        for worker in s.turn.workers():
            self.assertTrue(planner.mine(worker))
        self.assertTrue(planner.state['shared_fallback'])
        self.assertEqual(planner.state['assignments'],{501:A,504:A})
        self.assertNotEqual(s.coordinator.job(s.turn.workers()[0])['goal'],
                            s.coordinator.job(s.turn.workers()[1])['goal'])
        self.assertFalse(plan.rejections)

    def test_actual_filled_quota_releases_mine_without_another_collect(self):
        _,s,plan,planner=scene(first={'backpack':['stone']*9},
            mines=[('stone',A),('stone',B)],remaining={A:7,B:10})
        self.assertEqual(set(planner.assignments()),{504})
        self.assertFalse(planner.mine(s.turn.workers()[0]))
        self.assertNotIn('501',plan.commands)

    def test_submitted_collect_does_not_reduce_observed_remaining(self):
        raw,s,_,planner=scene(remaining={A:10})
        self.assertTrue(planner.mine(s.turn.workers()[0]))
        self.assertEqual(s.turn.mine_remaining[A],10)
        self.assertEqual(Turn.load(raw).mine_remaining[A],10)

    def test_missing_remaining_is_explicitly_unknown_in_diagnostics(self):
        _,_,_,planner=scene()
        self.assertIsNone(planner.diagnostic()['remaining'][A])
        self.assertEqual(planner.diagnostic()['unknown_remaining_fallback'],10)

    def test_non_integer_remaining_is_rejected_by_protocol(self):
        with self.assertRaises(ValueError):
            scene(remaining={A:'10'})


if __name__=='__main__':
    unittest.main()
