import unittest
from agent.protocol import CommandResult, Pos, Turn, distance, station_footprint
from agent.grid import Routes, next_step
from tests.fixtures import request, unit


class ProtocolTests(unittest.TestCase):
    def test_day_night_boundaries(self):
        for number, day, daylight in ((1, 1, True), (70, 1, True), (71, 1, False), (130, 1, False), (131, 2, True), (1300, 10, False)):
            with self.subTest(number=number):
                turn = Turn.load(request(number))
                self.assertEqual((turn.day, turn.is_day), (day, daylight))

    def test_base_top_left_and_distance(self):
        self.assertEqual(set(station_footprint(Pos(10, 24))), {Pos(10, 24), Pos(11, 24), Pos(10, 23), Pos(11, 23)})
        self.assertEqual(distance(Pos(0, 0), Pos(3, 2)), 3)

    def test_visible_enemies_dead_units_and_second_task_cell(self):
        raw = request()
        raw["teamEnemy"]["roles"] = [unit(990, "station", 30, 10), unit(991, "worker", 9, 23), unit(992, "wall", 8, 22, health=0)]
        turn = Turn.load(raw)
        blocked = turn.blocked(turn.workers()[0])
        for p in (Pos(30, 10), Pos(31, 9), Pos(9, 23), Pos(16, 17), Pos(17, 17)):
            self.assertIn(p, blocked)
        self.assertNotIn(Pos(8, 22), blocked)
        self.assertEqual(set(turn.task_cells(turn.tasks[1])), {Pos(16, 17), Pos(17, 17)})

    def test_diagonal_allowed_between_obstacles(self):
        raw = request()
        raw["teamOur"]["roles"] = [unit(1, "worker", 1, 1), unit(2, "wall", 1, 2), unit(3, "wall", 2, 1)]
        turn = Turn.load(raw)
        self.assertEqual(next_step(turn, turn.workers()[0], Pos(2, 2)), Pos(2, 2))
        self.assertIsNone(next_step(turn, turn.workers()[0], Pos(1, 1)))
        self.assertIsNone(next_step(turn, turn.workers()[0], Pos(1, 2)))

    def test_reserved_cell_is_avoided_by_path_search(self):
        raw = request()
        raw["teamOur"]["roles"] = [unit(1, "worker", 1, 1)]
        turn = Turn.load(raw)
        route = Routes(turn, turn.workers()[0], {Pos(2, 2)})
        self.assertNotEqual(route.step([Pos(3, 3)]), Pos(2, 2))
        self.assertEqual(route.cost[Pos(3, 3)], 3)

    def test_sandbox_result_semantics(self):
        cases = [("", "empty", None, False), ("[exitCode:0]\nok", "exited", 0, False),
                 ("[exitCode:7]\nfailed", "exited", 7, False), ("[exitCode:-9]\nkilled", "exited", -9, False),
                 ("[TIMEOUT]\npartial", "timeout", None, False),
                 ("[JUDGER_ERROR]\nreason", "judger_error", None, False),
                 ("[exitCode:0]\npartial\n[TRUNCATED]", "exited", 0, True)]
        for raw, status, code, truncated in cases:
            with self.subTest(raw=raw):
                result = CommandResult.load(raw)
                self.assertEqual((result.status, result.exit_code, result.truncated), (status, code, truncated))
                self.assertEqual(result.raw, raw)

    def test_official_dimensions_ids_and_round_types(self):
        for mutate in (lambda r: r.update(roundNo=True), lambda r: r.update(roundNo=0),
                       lambda r: r["mapInfo"].update(width=50),
                       lambda r: r["teamOur"]["roles"].append(r["teamOur"]["roles"][0])):
            raw = request()
            mutate(raw)
            with self.assertRaises(ValueError):
                Turn.load(raw)

    def test_conflicting_sample_range_cannot_expand_rule(self):
        raw = request()
        raw["teamOur"]["roles"] = [unit(1, "rocket", 1, 1, attackRange=2147483647), unit(2, "gatling", 2, 2, attackRange=4)]
        self.assertEqual([u.range_of_attack() for u in Turn.load(raw).weapons()], [10, 3])
