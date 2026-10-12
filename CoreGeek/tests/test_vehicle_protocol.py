"""First-day car protocol: actual driving state and both sub-step collisions."""
import unittest

from agent.actions import ActionPlan
from agent.grid import Routes
from agent.protocol import Pos, Turn, move_command
from agent.vehicle import move_targets
from tests.fixtures import layout_settings, request, robot, unit


class VehicleProtocolTests(unittest.TestCase):
    def turn(self, driving=False, round_no=1, team_type='challenger'):
        raw = request(round_no)
        raw['teamOur']['type'] = team_type
        raw['teamOur']['roles'] = [unit(501, 'worker', 5, 5, isDriving=driving),
                                   unit(504, 'worker', 10, 5)]
        raw['mapInfo']['zones'] = []
        return raw

    def plan(self, raw):
        return ActionPlan(Turn.load(raw), layout_settings())

    def test_is_driving_comes_only_from_explicit_boolean_observation(self):
        for value, expected in ((True, True), (False, False), (None, False), ('true', False), (1, False)):
            raw = self.turn()
            raw['teamOur']['roles'][0]['isDriving'] = value
            self.assertEqual(Turn.load(raw).workers()[0].is_driving, expected)
        raw = self.turn()
        raw['teamOur']['roles'][0].pop('isDriving')
        self.assertFalse(Turn.load(raw).workers()[0].is_driving)

    def test_own_car_is_enterable_in_both_team_orientations_but_enemy_car_is_blocked(self):
        for own, enemy in (('challenger', 'defender'), ('defender', 'challenger')):
            raw = self.turn(team_type=own)
            raw['mapInfo']['zones'] = [
                {'neutralType': own + 'Vehicle', 'pos': Pos(6, 5).dump()},
                {'neutralType': enemy + 'Vehicle', 'pos': Pos(5, 6).dump()},
            ]
            turn = Turn.load(raw)
            role = turn.workers()[0]
            self.assertEqual(turn.vehicle_cells(), {Pos(6, 5)})
            self.assertEqual(turn.vehicle_cells(False), {Pos(5, 6)})
            self.assertFalse(turn.land(Pos(6, 5)))
            self.assertTrue(turn.walkable(Pos(6, 5)))
            self.assertNotIn(Pos(6, 5), turn.blocked(role))
            self.assertIn(Pos(5, 6), turn.blocked(role))
            self.assertTrue(self.plan(raw).add(501, move_command(Pos(6, 5))))
            self.assertFalse(self.plan(raw).add(501, move_command(Pos(5, 6))))

    def test_car_owned_by_a_stationary_driver_cannot_be_boarded(self):
        raw = self.turn()
        raw['mapInfo']['zones'] = [{'neutralType': 'challengerVehicle', 'pos': Pos(6, 5).dump()}]
        raw['teamOur']['roles'][1].update(pos=Pos(6, 5).dump(), isDriving=True)
        self.assertFalse(self.plan(raw).add(501, move_command(Pos(6, 5))))

    def test_two_coordinates_require_existing_daytime_driving_state(self):
        targets = (Pos(6, 6), Pos(7, 7))
        for driving, round_no, allowed in ((True, 1, True), (False, 1, False), (True, 71, False)):
            plan = self.plan(self.turn(driving, round_no))
            self.assertEqual(plan.add(501, move_command(targets)), allowed, plan.rejections)
        plan = self.plan(self.turn(True))
        self.assertTrue(plan.add(501, move_command(Pos(6, 6))))

    def test_each_driving_substep_must_be_one_eight_way_neighbour(self):
        for targets in ((Pos(7, 5), Pos(8, 5)), (Pos(6, 5), Pos(8, 5)),
                        (Pos(6, 5), Pos(6, 5)), (Pos(6, 5), Pos(7, 5), Pos(8, 5))):
            self.assertFalse(self.plan(self.turn(True)).add(501, move_command(targets)))

    def test_intermediate_and_final_cells_both_reject_occupants(self):
        for occupied in (Pos(6, 5), Pos(7, 5)):
            raw = self.turn(True)
            raw['teamEnemy']['roles'] = [unit(990, 'wall', occupied.x, occupied.y)]
            plan = self.plan(raw)
            self.assertFalse(plan.add(501, move_command((Pos(6, 5), Pos(7, 5)))))
            self.assertEqual(plan.reserved, set())
            self.assertEqual(plan.commands, {})

    def test_two_driving_cells_are_reserved_and_neither_can_be_claimed(self):
        for claim in (Pos(6, 5), Pos(7, 5)):
            raw = self.turn(True)
            raw['teamOur']['roles'][1]['pos'] = Pos(claim.x, 4).dump()
            plan = self.plan(raw)
            self.assertTrue(plan.add(501, move_command((Pos(6, 5), Pos(7, 5)))))
            self.assertEqual(plan.reserved, {Pos(6, 5), Pos(7, 5)})
            self.assertFalse(plan.add(504, move_command(claim)))

    def test_an_existing_reservation_rejects_both_substeps_atomically(self):
        for reserved in (Pos(6, 5), Pos(7, 5)):
            plan = self.plan(self.turn(True))
            plan.reserved.add(reserved)
            self.assertFalse(plan.add(501, move_command((Pos(6, 5), Pos(7, 5)))))
            self.assertEqual(plan.reserved, {reserved})
            self.assertNotIn(501, plan.used)

    def test_cannot_build_on_either_teams_vehicle(self):
        for team_type in ('challenger', 'defender'):
            raw = request()
            raw['teamOur']['roles'][1]['backpack'] = ['stone']
            raw['mapInfo']['zones'].append({'neutralType': team_type + 'Vehicle', 'pos': Pos(8, 22).dump()})
            plan = self.plan(raw)
            self.assertFalse(plan.add(501, {'action': 'build', 'name': 'wall', 'targetPos': [Pos(8, 22).dump()]}))
            self.assertEqual(plan.commands, {})

    def test_robot_remains_one_step_even_if_its_raw_payload_claims_driving(self):
        raw = self.turn(True, 71)
        owned = robot(990, 20, 20, roleType='bossRobot', health=2000, isDriving=True)
        raw['robot']['roles'] = [owned]
        raw['teamOur']['summonRobotList'] = [owned]
        plan = self.plan(raw)
        self.assertFalse(plan.add(990, move_command((Pos(21, 20), Pos(22, 20)))))
        self.assertTrue(plan.add(990, move_command(Pos(21, 20))))

    def test_path_helper_takes_real_safe_steps_and_never_teleports(self):
        raw = self.turn(True)
        raw['teamEnemy']['roles'] = [unit(990, 'wall', 6, 5)]
        turn = Turn.load(raw)
        role = turn.workers()[0]
        route = Routes(turn, role, {Pos(6, 4)})
        points = move_targets(turn, role, route, [Pos(8, 5)])
        self.assertEqual(len(points), 2)
        self.assertNotIn(Pos(6, 5), points)
        self.assertNotIn(Pos(6, 4), points)
        plan = ActionPlan(turn, layout_settings())
        self.assertTrue(plan.add(role.unit_id, move_command(points)), plan.rejections)
        self.assertEqual(route.path([role.pos]), ())
        self.assertEqual(route.path([Pos(6, 5)]), ())

    def test_path_helper_preserves_risk_search_and_single_step_dismount(self):
        raw = self.turn(True)
        turn = Turn.load(raw)
        role = turn.workers()[0]
        route = Routes(turn, role, danger={Pos(6, 5): 100})
        points = move_targets(turn, role, route, [Pos(8, 5)])
        self.assertEqual(points, route.path([Pos(8, 5)], limit=2))
        self.assertNotIn(Pos(6, 5), points)
        self.assertEqual(move_targets(turn, role, route, [Pos(6, 6)]), (Pos(6, 6),))

    def test_friendly_car_path_is_one_step_until_boarding_is_confirmed(self):
        raw = self.turn()
        raw['mapInfo']['zones'] = [{'neutralType': 'challengerVehicle', 'pos': Pos(6, 5).dump()}]
        turn = Turn.load(raw)
        role = turn.workers()[0]
        route = Routes(turn, role)
        self.assertEqual(move_targets(turn, role, route, turn.vehicle_cells()), (Pos(6, 5),))
        self.assertEqual(len(move_targets(turn, role, route, [Pos(8, 5)])), 1)

    def test_driver_can_collect_without_dismount_command(self):
        raw = self.turn(True)
        raw['mapInfo']['zones'] = [{'neutralType': 'iron', 'pos': Pos(6, 5).dump()}]
        plan = self.plan(raw)
        self.assertTrue(plan.add(501, {'action': 'collect', 'targetPos': [Pos(6, 5).dump()]}), plan.rejections)


if __name__ == '__main__':
    unittest.main()
