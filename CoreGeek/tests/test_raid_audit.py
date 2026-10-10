"""Hand-built positive/negative BOSS audits, without production decisions."""
import unittest

from agent.protocol import Pos
from tests.fixtures import request, robot, unit
from tools.validate import (independent_contract, independent_crew_opportunity,
                            independent_planning_clear, independent_wall_blocks)


BOSS = '30005'


def observation(crews, base=(12,10)):
    raw = request(71)
    raw['teamOur']['playerTasks'] = []
    raw['teamOur']['roles'] = [unit(503,'station',2,30)]
    raw['teamOur']['summonRobotList'] = [robot(int(BOSS),10,10,health=800,roleType='bossRobot')]
    raw['robot']['roles'] = list(raw['teamOur']['summonRobotList'])
    raw['teamEnemy']['roles'] = [unit(990,'station',*base)] + crews
    raw['mapInfo']['zones'] = []
    return raw


def response(action, target, uid=BOSS):
    return {'roleCommandMap':{uid:{'action':action,'targetPos':[Pos(*target).dump()]}},
            'prompt':'','executeCmd':''}


def opportunity(raw, budget=4):
    crews = [u for u in raw['teamEnemy']['roles'] if u['roleType'] in ('worker','pioneer') and u['health'] > 0]
    return independent_crew_opportunity(raw,raw['teamOur']['summonRobotList'][0],crews,budget)


class RaidIndependentAuditTests(unittest.TestCase):
    def test_direct_cannon_crew_forbids_forged_base_attack(self):
        raw = observation([unit(991,'rocket',12,13),unit(992,'worker',12,12,health=40)])
        with self.assertRaisesRegex(AssertionError,'lowest-current-HP'):
            independent_contract(raw,response('attack',(12,10)))
        independent_contract(raw,response('attack',(12,12)))

    def test_current_lowest_hp_direct_crew_is_still_required(self):
        raw = observation([unit(991,'rocket',12,13),unit(992,'worker',12,12,health=80),
                           unit(993,'pioneer',11,12,health=40)])
        with self.assertRaisesRegex(AssertionError,'lowest-current-HP'):
            independent_contract(raw,response('attack',(12,12)))
        independent_contract(raw,response('attack',(11,12)))

    def test_short_route_forbids_forged_base_attack(self):
        raw = observation([unit(991,'rocket',15,14),unit(992,'worker',15,13,health=40)])
        self.assertEqual(opportunity(raw)['walks'][992],2)
        with self.assertRaisesRegex(AssertionError,'access exceeds its budget'):
            independent_contract(raw,response('attack',(12,10)))

    def test_inaccessible_crew_allows_exposed_base_attack(self):
        raw = observation([unit(991,'rocket',20,20),unit(992,'worker',20,21,health=40)])
        raw['mapInfo']['zones'] = [{'neutralType':'vendor','pos':p.dump()} for p in Pos(10,10).neighbours()]
        self.assertIsNone(opportunity(raw)['walks'][992])
        independent_contract(raw,response('attack',(12,10)))

    def test_seven_step_crew_detour_allows_base_in_four_step_budget(self):
        raw = observation([unit(991,'rocket',20,21),unit(992,'worker',20,20,health=40)])
        self.assertEqual(opportunity(raw)['walks'][992],7)
        independent_contract(raw,response('attack',(12,10)))
        with self.assertRaisesRegex(AssertionError,'access exceeds its budget'):
            independent_contract(raw,response('attack',(12,10)),controller_budget=7)

    def test_building_blocked_shot_has_one_step_detour_not_a_direct_target(self):
        raw = observation([unit(991,'rocket',11,11),unit(992,'worker',12,12,health=40)],base=(8,9))
        available = opportunity(raw)
        self.assertEqual(available['direct'],[])
        self.assertEqual(available['walks'][992],1)
        # (9,11) reaches a line above the blocking cannon in one legal step.
        independent_contract(raw,response('move',(9,11)))
        with self.assertRaisesRegex(AssertionError,'access exceeds its budget'):
            independent_contract(raw,response('attack',(9,9)))

    def test_forged_shot_through_cannon_interior_is_rejected(self):
        raw = observation([unit(991,'rocket',11,11),unit(992,'worker',12,12,health=40)],base=(8,9))
        with self.assertRaisesRegex(AssertionError,'building interiors'):
            independent_contract(raw,response('attack',(12,12)))

    def test_building_corner_contact_remains_clear_but_wall_corner_blocks(self):
        raw = observation([unit(991,'rocket',11,12),unit(992,'worker',12,12,health=40)],base=(8,9))
        self.assertTrue(independent_planning_clear(raw,Pos(10,10),Pos(12,12)))
        self.assertTrue(independent_wall_blocks(Pos(10,10),Pos(12,12),Pos(11,12)))
        independent_contract(raw,response('attack',(12,12)))

    def test_other_station_footprint_cells_block_a_planned_line(self):
        raw = observation([unit(991,'rocket',13,11),unit(992,'worker',13,10,health=40)],base=(11,11))
        # The anchor (11,11) is off this horizontal line, but (11,10) is occupied.
        self.assertFalse(independent_planning_clear(raw,Pos(10,10),Pos(13,10)))
        self.assertTrue(independent_planning_clear(raw,Pos(10,10),Pos(11,10)))
        self.assertFalse(independent_planning_clear(raw,Pos(10,10),Pos(12,10)))

    def test_one_hit_wall_opening_forbids_base_fallback(self):
        raw = self.screened_crew(40)
        self.assertIsNone(opportunity(raw)['walks'][992])
        self.assertTrue(opportunity(raw)['cheap_walls'])
        with self.assertRaisesRegex(AssertionError,'access exceeds its budget'):
            independent_contract(raw,response('attack',(9,9)))
        independent_contract(raw,response('attack',(13,10)))

    def test_twenty_hit_wall_screen_allows_base_fallback(self):
        raw = self.screened_crew(800)
        self.assertEqual(opportunity(raw)['cheap_walls'],set())
        independent_contract(raw,response('attack',(9,9)))

    def test_six_step_route_can_still_have_a_three_round_wall_opening(self):
        raw = observation([unit(991,'rocket',16,11),unit(992,'worker',16,10,health=40)],base=(8,9))
        for uid,p in enumerate(Pos(16,10).neighbours(),1000):
            if p not in (Pos(16,11),Pos(16,9)):
                raw['teamEnemy']['roles'].append(unit(uid,'wall',p.x,p.y,health=40))
        available = opportunity(raw)
        self.assertEqual(available['walks'][992],6)
        self.assertTrue(available['cheap_walls'])
        with self.assertRaisesRegex(AssertionError,'access exceeds its budget'):
            independent_contract(raw,response('attack',(9,9)))
        independent_contract(raw,response('move',(11,10)))

    def test_two_owned_robots_cannot_move_into_the_same_cell(self):
        raw = observation([unit(991,'rocket',20,21),unit(992,'worker',20,20)],base=(8,9))
        second = robot(30006,10,11,health=800,roleType='bossRobot')
        raw['teamOur']['summonRobotList'].append(second)
        raw['robot']['roles'].append(second)
        out = response('move',(9,10))
        out['roleCommandMap'].update(response('move',(9,10),'30006')['roleCommandMap'])
        with self.assertRaises(AssertionError):
            independent_contract(raw,out)

    def test_robot_move_still_requires_one_target_night_and_no_stun(self):
        raw = observation([],base=(8,9))
        for variant in ('day','dizzy','two_targets','controller_id'):
            with self.subTest(variant=variant):
                trial = observation([],base=(8,9))
                out = response('move',(9,10))
                if variant == 'day':
                    trial['roundNo'] = 70
                elif variant == 'dizzy':
                    trial['teamOur']['summonRobotList'][0]['abnormalState'] = 'dizzy'
                elif variant == 'two_targets':
                    out['roleCommandMap'][BOSS]['targetPos'].append(Pos(9,11).dump())
                else:
                    out['roleCommandMap'][BOSS]['controllerId'] = BOSS
                with self.assertRaises(AssertionError):
                    independent_contract(trial,out)
        independent_contract(raw,response('move',(9,10)))

    @staticmethod
    def screened_crew(hp):
        raw = observation([unit(991,'rocket',14,11),unit(992,'worker',14,10,health=40)],base=(8,9))
        for uid,p in enumerate(Pos(14,10).neighbours(),1000):
            if p != Pos(14,11):
                raw['teamEnemy']['roles'].append(unit(uid,'wall',p.x,p.y,health=hp))
        return raw


if __name__ == '__main__':
    unittest.main()
