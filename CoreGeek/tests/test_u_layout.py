"""User drawing regression: base (6,7), rear rockets, twelve U-shaped walls."""
import copy
import unittest

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.construction import select_defense_layout
from agent.grid import Routes
from agent.protocol import Pos, Turn, distance, station_footprint
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import TurnService
from tests.fixtures import request, robot, unit


WALLS = {(6, 9), (7, 9), (8, 9), (9, 9), (9, 8), (9, 7),
         (9, 6), (9, 5), (9, 4), (8, 4), (7, 4), (6, 4)}
ROCKETS = {(5, 8), (5, 7), (5, 6)}
LANE = {(6, 8), (7, 8), (8, 8), (8, 7), (8, 6), (8, 5), (7, 5), (6, 5)}


def point(x, y, mirrored=False):
    return Pos(40 - x if mirrored else x, y)


def drawing_request(mirrored=False, team="challenger", built=False, round_no=1):
    raw = request(round_no)
    raw["teamOur"].update(type=team, playerTasks=[])
    raw["mapInfo"]["zones"] = []
    raw["teamOur"]["roles"] = [unit(503, "station", 33 if mirrored else 6, 7)]
    for uid, kind, x, y in ((502, "pioneer", 4, 7), (501, "worker", 4, 9), (504, "worker", 4, 5)):
        p = point(x, y, mirrored)
        raw["teamOur"]["roles"].append(unit(uid, kind, p.x, p.y))
    if built:
        raw["teamOur"]["goldNum"] = 0
        for uid, (x, y) in enumerate(sorted(ROCKETS), 601):
            p = point(x, y, mirrored)
            raw["teamOur"]["roles"].append(unit(uid, "rocket", p.x, p.y))
    return raw


class ULayoutTests(unittest.TestCase):
    def test_both_sides_finish_exact_template_in_rocket_stone_wall_order(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                raw = drawing_request(mirrored)
                for x, y in ((3, 9), (3, 5)):
                    raw["mapInfo"]["zones"].append({"neutralType": "stone", "pos": point(x, y, mirrored).dump()})
                service = TurnService()
                trace = []
                for number in range(1, 71):
                    raw["roundNo"] = number
                    before = Turn.load(raw)
                    response = service.decide(copy.deepcopy(raw))
                    if service.sessions[(before.team_id, before.team_type)].memory.opening_complete:
                        break
                    roles = {str(u["id"]): u for u in raw["teamOur"]["roles"]}
                    destinations = set()
                    for uid, command in response["roleCommandMap"].items():
                        action = command["action"]
                        self.assertIn(action, ("move", "build", "collect"))
                        target = Pos.load(command["targetPos"][0])
                        actor = roles[uid]
                        self.assertEqual(distance(Pos.load(actor["pos"]), target), 1)
                        if action in ("move", "build"):
                            self.assertNotIn(target, before.occupied_cells())
                            self.assertNotIn(target, destinations)
                            destinations.add(target)
                        if action == "move":
                            actor["pos"] = target.dump()
                        elif action == "collect":
                            self.assertEqual(len(before.weapons()), 3)
                            self.assertEqual(before.zones[target], "stone")
                            actor["backpack"].append("stone")
                            trace.append((number, "stone"))
                        else:
                            name = command["name"]
                            trace.append((number, name))
                            if name == "rocket":
                                raw["teamOur"]["goldNum"] -= 25
                            else:
                                self.assertEqual(name, "wall")
                                self.assertEqual(len(before.weapons()), 3)
                                actor["backpack"].remove("stone")
                            raw["teamOur"]["roles"].append(unit(1000 + len(trace), name, target.x, target.y))
                else:
                    self.fail(f"opening incomplete at dusk: {trace}")
                final = Turn.load(raw)
                self.assertEqual({w.pos for w in final.walls()}, {point(x, y, mirrored) for x, y in WALLS})
                self.assertEqual({w.pos for w in final.weapons()}, {point(x, y, mirrored) for x, y in ROCKETS})
                self.assertEqual(final.gold, 0)
                self.assertEqual(sum(kind == "stone" for _, kind in trace), 12)
                self.assertLess(max(n for n, kind in trace if kind == "rocket"), min(n for n, kind in trace if kind == "stone"))
                self.assertLess(max(n for n, kind in trace if kind == "stone"), min(n for n, kind in trace if kind == "wall"))

    def test_exact_drawing_and_horizontal_mirror_independent_of_team(self):
        for mirrored in (False, True):
            for team in ("challenger", "defender"):
                with self.subTest(mirrored=mirrored, team=team):
                    turn = Turn.load(drawing_request(mirrored, team))
                    settings = Settings()
                    walls = {point(x, y, mirrored) for x, y in WALLS}
                    rockets = {point(x, y, mirrored) for x, y in ROCKETS}
                    self.assertEqual(set(settings.build_cells(turn, "wall")), walls)
                    self.assertEqual(set(settings.build_cells(turn, "rocket")), rockets)
                    layout = select_defense_layout(turn, settings)
                    self.assertEqual(set(layout.tower_sites), rockets)
                    self.assertEqual(layout.operator_pos, point(4, 7, mirrored))
                    self.assertTrue(layout.shared_control)
                    self.assertTrue(all(distance(layout.operator_pos, p) == 1 for p in rockets))
                    self.assertFalse((walls | rockets) & set(station_footprint(turn.station().pos)))

    def test_completed_walls_leave_connected_inner_repair_lane(self):
        for mirrored in (False, True):
            raw = drawing_request(mirrored, built=True)
            for uid, (x, y) in enumerate(sorted(WALLS), 701):
                p = point(x, y, mirrored)
                raw["teamOur"]["roles"].append(unit(uid, "wall", p.x, p.y))
            turn = Turn.load(raw)
            lane = {point(x, y, mirrored) for x, y in LANE}
            reachable = Routes(turn, turn.workers()[0]).cost
            self.assertTrue(lane <= set(reachable))
            for wall in turn.walls():
                self.assertTrue(any(distance(wall.pos, p) == 1 for p in lane))
            self.assertTrue(all(min(distance(p, b) for b in station_footprint(turn.station().pos)) == 1
                                for p in lane))

    def test_planned_positions_stay_fixed_during_partial_construction_and_role_movement(self):
        for mirrored in (False, True):
            raw = drawing_request(mirrored)
            expected = select_defense_layout(Turn.load(raw), Settings())
            p = point(5, 8, mirrored)
            raw["teamOur"]["roles"].append(unit(601, "rocket", p.x, p.y))
            raw["teamOur"]["roles"][1]["pos"] = point(15, 15, mirrored).dump()
            self.assertEqual(select_defense_layout(Turn.load(raw), Settings(), expected), expected)

    def test_drawing_rotation_keeps_pioneer_at_p_and_workers_mining(self):
        for mirrored in (False, True):
            memory = GameMemory()
            fired = []
            for index, cooldowns in enumerate(((0, 0, 0), (3, 0, 0), (2, 3, 0), (1, 2, 3), (0, 1, 2))):
                raw = drawing_request(mirrored, built=True, round_no=71 + index)
                for x, y in ((3, 9), (3, 5)):
                    raw["mapInfo"]["zones"].append({"neutralType": "stone", "pos": point(x, y, mirrored).dump()})
                enemy = point(11, 7, mirrored)
                raw["robot"]["roles"] = [robot(900, enemy.x, enemy.y, health=500)]
                for tower, cooldown in zip(raw["teamOur"]["roles"][-3:], cooldowns):
                    tower["cooldown"] = cooldown
                turn = Turn.load(copy.deepcopy(raw))
                plan = ActionPlan(turn, Settings())
                Strategy(turn, plan, memory).run()
                self.assertEqual(plan.rejections, [])
                shots = [(key, cmd) for key, cmd in plan.commands.items() if cmd["action"] == "attack"]
                self.assertLessEqual(len(shots), 1)
                self.assertNotIn("502", plan.commands)
                self.assertEqual([plan.commands[str(uid)]["action"] for uid in (501, 504)], ["collect", "collect"])
                fired.append(int(shots[0][0]) if shots else None)
                self.assertTrue(all(cmd["controllerId"] == "502" for _, cmd in shots))
            self.assertEqual(fired, [601, 602, 603, None, 601])
