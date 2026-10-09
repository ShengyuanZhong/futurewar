"""User screenshot (base 9,22), its translated/mirrored adjacent rear cells."""
import unittest

from agent.actions import ActionPlan
from agent.protocol import Pos, Turn
from agent.summoning import rear_spawn_position, summon_cell_legal
from app.config import Settings
from tests.fixtures import request, unit, robot


def arena(base=Pos(9, 22)):
    raw = request(30)
    ours = Pos(39-base.x, 32-base.y)
    raw['teamOur']['roles'] = [unit(503,'station',ours.x,ours.y),
                             unit(502,'pioneer',20,15,backpack=['BossRobotSummonOrder'])]
    raw['teamOur']['playerTasks'] = []
    raw['teamEnemy']['roles'] = [unit(990,'station',base.x,base.y)]
    raw['mapInfo']['zones'] = []
    raw['robot']['roles'] = []
    raw['teamOur']['summonRobotList'] = []
    return raw


class RearSpawnGeometryTests(unittest.TestCase):
    def test_screenshot_primary_points_are_legal_and_tried_in_order(self):
        turn = Turn.load(arena()); settings = Settings()
        self.assertTrue(summon_cell_legal(turn,settings,Pos(6,22)))
        self.assertTrue(summon_cell_legal(turn,settings,Pos(6,21)))
        self.assertEqual(rear_spawn_position(turn,settings),Pos(6,22))
        self.assertEqual(rear_spawn_position(turn,settings,failed={Pos(6,22)}),Pos(6,21))
        plan = ActionPlan(turn,settings)
        self.assertTrue(plan.add(502,{'action':'use','name':'BossRobotSummonOrder',
                                   'targetPos':[{'x':6,'y':22}]}),plan.rejections)

    def test_four_quadrants_follow_two_by_two_mirroring(self):
        for base, top, bottom in ((Pos(9,22),Pos(6,22),Pos(6,21)),
                                  (Pos(30,22),Pos(34,22),Pos(34,21)),
                                  (Pos(9,10),Pos(6,10),Pos(6,9)),
                                  (Pos(30,10),Pos(34,10),Pos(34,9))):
            turn = Turn.load(arena(base))
            self.assertEqual(rear_spawn_position(turn,Settings()),top)
            self.assertEqual(rear_spawn_position(turn,Settings(),failed={top}),bottom)

    def test_building_area_is_the_whole_six_by_six_not_just_planned_cells(self):
        turn = Turn.load(arena())
        for margin in (0,1,2):
            for x in range(7,13):
                for y in range(19,25):
                    self.assertFalse(summon_cell_legal(turn,Settings(summon_build_margin=margin),Pos(x,y)))
            self.assertTrue(summon_cell_legal(turn,Settings(summon_build_margin=margin),Pos(6,22)))

    def test_npc_failed_and_pending_primary_cells_fall_back_nearby(self):
        raw=arena(); raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':6,'y':22}}]
        turn=Turn.load(raw)
        self.assertEqual(rear_spawn_position(turn,Settings()),Pos(6,21))
        alternate=rear_spawn_position(turn,Settings(),pending={Pos(6,21)})
        self.assertIsNotNone(alternate)
        self.assertNotIn(alternate,{Pos(6,22),Pos(6,21)})
        self.assertLessEqual(max(abs(alternate.x-6),abs(alternate.y-22)),2)
        self.assertTrue(summon_cell_legal(turn,Settings(),alternate))

    def test_dynamic_primary_occupant_prefers_other_empty_point_but_stays_legal(self):
        raw=arena(); raw['teamEnemy']['roles'].append(unit(991,'worker',6,22))
        raw['robot']['roles']=[robot(900,6,22)]
        turn=Turn.load(raw)
        self.assertTrue(summon_cell_legal(turn,Settings(),Pos(6,22)))
        self.assertEqual(rear_spawn_position(turn,Settings()),Pos(6,21))

    def test_static_building_occupancy_and_larger_explicit_margin_are_respected(self):
        raw=arena(); raw['teamEnemy']['roles'].append(unit(991,'wall',6,22))
        turn=Turn.load(raw)
        self.assertFalse(summon_cell_legal(turn,Settings(),Pos(6,22)))
        self.assertEqual(rear_spawn_position(turn,Settings()),Pos(6,21))
        turn=Turn.load(arena())
        self.assertFalse(summon_cell_legal(turn,Settings(summon_build_margin=5),Pos(6,22)))


if __name__ == '__main__':
    unittest.main()
