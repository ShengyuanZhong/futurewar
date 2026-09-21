"""End-to-end opening with the user's base-surroundings assumption, no local file."""
import copy
import unittest
from agent.actions import ActionPlan
from agent.construction import select_defense_layout
from agent.protocol import Pos, Turn, build_command, distance, station_footprint
from app.config import Settings
from app.service.turn_service import TurnService
from tests.fixtures import request, unit, layout_settings


class DefaultOpeningTests(unittest.TestCase):
    def test_default_enables_building_without_verified_coordinates(self):
        turn = Turn.load(request())
        self.assertTrue(Settings().build_cells(turn, "rocket"))
        plan = ActionPlan(turn, Settings())
        self.assertTrue(plan.add(501, build_command(Pos(9, 24), "rocket")), plan.rejections)

    def test_default_opening_finishes_rockets_then_stone_then_walls_before_night(self):
        for team in ("challenger", "defender"):
            with self.subTest(team=team):
                raw = request()
                raw["teamOur"]["type"] = team
                service = TurnService()
                trace = []
                for number in range(1, 71):
                    raw["roundNo"] = number
                    before = Turn.load(raw)
                    response = service.decide(copy.deepcopy(raw))
                    if service.sessions[(before.team_id, team)].memory.opening_complete:
                        break
                    units = {str(r["id"]): r for r in raw["teamOur"]["roles"]}
                    for key, cmd in response["roleCommandMap"].items():
                        actor = units[key]
                        if actor["roleType"] != "worker":
                            if cmd["action"] == "move":
                                actor["pos"] = cmd["targetPos"][0]
                            continue
                        action = cmd["action"]
                        self.assertNotIn(action, ("sell", "buy"), "opening must precede normal economy")
                        if action == "move":
                            actor["pos"] = cmd["targetPos"][0]
                        elif action == "build":
                            name = cmd["name"]
                            point = Pos.load(cmd["targetPos"][0])
                            radius = min(distance(point, p) for p in station_footprint(before.station().pos))
                            self.assertEqual(radius, 1 if name == "rocket" else 2)
                            trace.append((number, name))
                            if name == "rocket":
                                self.assertEqual(actor["backpack"], [])
                                raw["teamOur"]["goldNum"] -= 25
                                self.assertGreaterEqual(raw["teamOur"]["goldNum"], 0)
                            else:
                                self.assertEqual(len(before.weapons()), 3)
                                self.assertTrue(all(w.kind == "rocket" for w in before.weapons()))
                                actor["backpack"].remove("stone")
                            raw["teamOur"]["roles"].append(unit(10000 + number*10 + int(key), name, point.x, point.y))
                        elif action == "collect":
                            self.assertEqual(len(before.weapons()), 3, "finish all three rockets before mining")
                            point = cmd["targetPos"][0]
                            name = next(z["neutralType"] for z in raw["mapInfo"]["zones"] if z["pos"] == point)
                            self.assertEqual(name, "stone")
                            trace.append((number, "collect"))
                            actor["backpack"].append(name)
                else:
                    self.fail(f"default opening failed to finish before night: {trace}")
                self.assertEqual([kind for _, kind in trace if kind != "collect"][:3], ["rocket"]*3)
                self.assertTrue(any(kind == "wall" for _, kind in trace))
                self.assertLess(max(n for n, kind in trace if kind == "rocket"), min(n for n, kind in trace if kind == "collect"))
                self.assertLess(min(n for n, kind in trace if kind == "collect"), min(n for n, kind in trace if kind == "wall"))
                self.assertEqual(raw["teamOur"]["goldNum"], 0)

    def test_base_surroundings_clip_to_map_and_avoid_neutral_cells(self):
        for x, y in ((0, 1), (39, 31), (10, 24)):
            raw = request()
            raw["teamOur"]["roles"] = [unit(503, "station", x, y)]
            turn = Turn.load(raw)
            settings = Settings()
            weapons, walls = set(settings.build_cells(turn, "rocket")), set(settings.build_cells(turn, "wall"))
            if x in (0, 39):
                # Fixed rear row lies outside the map; never invent replacement sites.
                self.assertEqual(weapons, set())
            else:
                self.assertEqual(len(weapons), 3)
            self.assertTrue(walls)
            self.assertFalse(weapons & walls)
            for p in weapons | walls:
                self.assertTrue(turn.in_bounds(p))
                self.assertTrue(turn.land(p))
                self.assertNotIn(p, station_footprint(turn.station().pos))

    def test_existing_unverified_empty_layout_uses_enabled_fallback(self):
        turn = Turn.load(request())
        old = {"challenger": {"verified": False, "source": "old empty template", "weapons": [], "walls": []}}
        self.assertEqual(Settings(layouts=old).build_cells(turn, "rocket"), Settings().build_cells(turn, "rocket"))
        self.assertEqual(Settings(layouts=old, allow_base_surroundings=False).build_cells(turn, "rocket"), ())

    def test_explicit_layout_takes_precedence_over_fallback(self):
        turn = Turn.load(request())
        self.assertEqual(set(layout_settings().build_cells(turn, "rocket")), {Pos(9, 24), Pos(10, 25), Pos(12, 24)})
        self.assertEqual(set(layout_settings().build_cells(turn, "wall")), {Pos(8, 22), Pos(13, 22)} - set(turn.zones))

    def test_default_layout_has_shared_control_space_and_wall_openings(self):
        turn = Turn.load(request())
        settings = Settings()
        layout = select_defense_layout(turn, settings)
        self.assertEqual(len(layout.tower_sites), 3)
        self.assertTrue(layout.shared_control)
        self.assertNotIn(layout.operator_pos, settings.build_cells(turn, "wall"))
        self.assertTrue(all(distance(layout.operator_pos, p) <= 1 for p in layout.tower_sites))
        self.assertEqual(layout.operator_pos, Pos(8, 24))
        self.assertIn(Pos(10, 26), settings.build_cells(turn, "wall"))
        self.assertIn(Pos(11, 21), settings.build_cells(turn, "wall"))
        self.assertNotIn(Pos(9, 26), settings.build_cells(turn, "wall"))
        self.assertNotIn(Pos(9, 21), settings.build_cells(turn, "wall"))
