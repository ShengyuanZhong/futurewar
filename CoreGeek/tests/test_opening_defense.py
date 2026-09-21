"""Synthetic construction/rotation regressions; coordinates are not official geography."""
import copy
import unittest
from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.construction import select_defense_layout
from agent.protocol import Pos, Turn
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import TurnService
from tests.fixtures import request, unit, robot


def opening_settings():
    return Settings(layouts={"challenger": {
        "verified": True, "source": "synthetic regression only",
        "weapons": [{"x": -1, "y": 1}, {"x": 0, "y": 1}, {"x": 1, "y": 1}],
        "walls": [{"x": -2, "y": 0}, {"x": -2, "y": -1}, {"x": 3, "y": 0}, {"x": 3, "y": 1}],
    }}, enable_news=False)


def opening_request(round_no=1, towers=False):
    raw = request(round_no)
    raw["teamOur"]["roles"] = [unit(503, "station", 10, 24), unit(501, "worker", 8, 25),
                                    unit(502, "pioneer", 10, 26), unit(504, "worker", 12, 25)]
    raw["mapInfo"]["zones"] = [z for z in raw["mapInfo"]["zones"] if z["neutralType"] not in ("stone", "copper")]
    raw["mapInfo"]["zones"] += [{"neutralType": "stone", "pos": {"x": 7, "y": 25}},
                                      {"neutralType": "stone", "pos": {"x": 13, "y": 26}}]
    if towers:
        raw["teamOur"]["roles"] += [unit(601+i, "rocket", 9+i, 25) for i in range(3)]
        raw["teamOur"]["goldNum"] = 0
    return raw


class OpeningDefenseTests(unittest.TestCase):
    def decide(self, raw, memory=None):
        turn = Turn.load(raw)
        plan = ActionPlan(turn, opening_settings())
        Strategy(turn, plan, memory or GameMemory()).run()
        self.assertEqual(plan.rejections, [])
        return plan

    def test_default_loadout_is_three_rockets(self):
        self.assertEqual(Settings().loadout, ("rocket",) * 3)

    def test_initial_gold_builds_rockets_before_stone_or_trade(self):
        raw = opening_request()
        for r in raw["teamOur"]["roles"]:
            if r["roleType"] == "worker":
                r["backpack"] = ["stone"] * 12
        plan = self.decide(raw)
        worker_commands = [plan.commands[str(i)] for i in (501, 504)]
        self.assertEqual([c["action"] for c in worker_commands], ["build", "build"])
        self.assertEqual([c["name"] for c in worker_commands], ["rocket", "rocket"])
        self.assertEqual(plan.gold, 25)

    def test_stockpile_stone_before_wall_construction(self):
        raw = opening_request(towers=True)
        raw["teamOur"]["roles"][1]["backpack"] = ["stone"]
        raw["teamOur"]["roles"][3]["backpack"] = ["stone"]
        plan = self.decide(raw)
        self.assertEqual(plan.commands["501"]["action"], "collect")
        self.assertEqual(plan.commands["504"]["action"], "collect")

    def test_sufficient_stone_builds_walls_before_selling_or_upgrades(self):
        raw = opening_request(towers=True)
        raw["teamOur"]["goldNum"] = 200
        for r in raw["teamOur"]["roles"]:
            if r["roleType"] == "worker":
                r["backpack"] = ["stone"] * 12
        raw["teamOur"]["roles"][1]["pos"] = {"x": 7, "y": 24}
        raw["teamOur"]["roles"][3]["pos"] = {"x": 12, "y": 24}
        plan = self.decide(raw)
        self.assertEqual([plan.commands[str(i)]["action"] for i in (501, 504)], ["build", "build"])
        self.assertTrue(all(plan.commands[str(i)]["name"] == "wall" for i in (501, 504)))

    def test_workers_collect_at_night_while_pioneer_fires(self):
        raw = opening_request(71, towers=True)
        raw["robot"]["roles"] = [robot(900, 10, 31, health=500)]
        plan = self.decide(raw)
        attacks = [c for c in plan.commands.values() if c["action"] == "attack"]
        self.assertEqual(len(attacks), 1)
        self.assertEqual(attacks[0]["controllerId"], "502")
        self.assertEqual([plan.commands[str(i)]["action"] for i in (501, 504)], ["collect", "collect"])
        self.assertNotIn("502", plan.commands)

    def test_rotation_uses_observed_cooldown_with_one_blank_round(self):
        memory = GameMemory()
        schedules = [(0, 0, 0), (3, 0, 0), (2, 3, 0), (1, 2, 3), (0, 1, 2)]
        fired = []
        for index, cooldowns in enumerate(schedules):
            raw = opening_request(71+index, towers=True)
            raw["robot"]["roles"] = [robot(900, 10, 29, health=500)]
            for tower, cooldown in zip(raw["teamOur"]["roles"][-3:], cooldowns):
                tower["cooldown"] = cooldown
            plan = self.decide(raw, memory)
            attacks = [(k, c) for k, c in plan.commands.items() if c["action"] == "attack"]
            self.assertLessEqual(len(attacks), 1)
            fired.append(int(attacks[0][0]) if attacks else None)
            self.assertTrue(all(c["controllerId"] == "502" for _, c in attacks))
        self.assertEqual(fired, [601, 602, 603, None, 601])

    def test_ready_weapon_is_not_ignored_for_nearer_cooling_weapon(self):
        raw = opening_request(71, towers=True)
        raw["teamOur"]["roles"][-3]["cooldown"] = 3
        raw["teamOur"]["roles"][-2]["cooldown"] = 2
        raw["robot"]["roles"] = [robot(900, 10, 29, health=500)]
        plan = self.decide(raw)
        self.assertEqual(plan.commands["603"]["controllerId"], "502")

    def test_worker_does_not_return_to_tower_at_dusk(self):
        raw = opening_request(70, towers=True)
        plan = self.decide(raw)
        self.assertEqual(plan.commands["501"]["action"], "collect")
        self.assertEqual(plan.commands["504"]["action"], "collect")

    def test_pioneer_returns_to_common_control_cell(self):
        raw = opening_request(65, towers=True)
        raw["teamOur"]["roles"][2]["pos"] = {"x": 10, "y": 29}
        plan = self.decide(raw)
        self.assertEqual(plan.commands["502"], {"action": "move", "targetPos": [{"x": 9, "y": 28}]})

    def test_no_night_worker_attack_even_if_pioneer_dead(self):
        raw = opening_request(71, towers=True)
        raw["teamOur"]["roles"][2]["health"] = 0
        raw["robot"]["roles"] = [robot(900, 10, 31, health=500)]
        plan = self.decide(raw)
        self.assertFalse(any(c["action"] == "attack" for c in plan.commands.values()))
        self.assertEqual(plan.commands["501"]["action"], "collect")

    def test_active_task_yields_to_night_defence(self):
        raw = opening_request(66, towers=True)
        raw["phaseTask"] = "active task"
        service = TurnService(opening_settings())
        self.assertTrue(service.decide(raw)["prompt"])
        raw.update(roundNo=67, llmResp='{"executeCmd":"pwd"}')
        result = service.decide(raw)
        self.assertEqual(result["executeCmd"], "")
        self.assertEqual(result["prompt"], "")
        raw.update(roundNo=71, llmResp="")
        raw["robot"]["roles"] = [robot(900, 10, 29, health=500)]
        result = service.decide(raw)
        self.assertTrue(any(c.get("controllerId") == "502" for c in result["roleCommandMap"].values()))

    def test_multi_turn_opening_observed_builds_before_economy(self):
        raw = opening_request()
        service = TurnService(opening_settings())
        built, first_collect, first_wall = [], None, None
        opening_done = False
        # Minimal action feedback fixture: no combat, refresh, scoring or judger claims.
        for number in range(1, 45):
            raw["roundNo"] = number
            commands = service.decide(copy.deepcopy(raw))["roleCommandMap"]
            units = {str(r["id"]): r for r in raw["teamOur"]["roles"]}
            for key, cmd in commands.items():
                actor = units[key]
                action = cmd["action"]
                if action == "move":
                    actor["pos"] = cmd["targetPos"][0]
                elif action == "build":
                    name = cmd["name"]
                    p = cmd["targetPos"][0]
                    if name == "rocket":
                        raw["teamOur"]["goldNum"] -= 25
                        built.append(number)
                    else:
                        first_wall = first_wall or number
                        actor["backpack"].remove("stone")
                    raw["teamOur"]["roles"].append(unit(1000 + number*10 + int(key), name, p["x"], p["y"]))
                elif action == "collect":
                    self.assertEqual(len(built), 3)
                    first_collect = first_collect or number
                    p = cmd["targetPos"][0]
                    name = next(z["neutralType"] for z in raw["mapInfo"]["zones"] if z["pos"] == p)
                    actor["backpack"].append(name)
                elif action in ("sell", "buy"):
                    self.assertTrue(opening_done, "economy must wait for observed fortifications")
            walls = [r for r in raw["teamOur"]["roles"] if r["roleType"] == "wall"]
            if len(built) == 3 and len(walls) == 4:
                opening_done = True
                break
        self.assertTrue(opening_done)
        self.assertEqual(len(built), 3)
        self.assertLess(max(built), first_collect)
        self.assertLess(first_collect, first_wall)
        self.assertEqual(raw["teamOur"]["goldNum"], 0)

    def test_confirmed_opening_completion_resumes_economy(self):
        raw = opening_request(towers=True)
        raw["teamOur"]["roles"] += [unit(700+i, "wall", 10+p["x"], 24+p["y"])
                                    for i, p in enumerate(opening_settings().layouts["challenger"]["walls"])]
        raw["teamOur"]["roles"][1].update(pos={"x": 6, "y": 23}, backpack=["copper"]*12)
        memory = GameMemory()
        plan = self.decide(raw, memory)
        self.assertTrue(memory.opening_complete)
        self.assertEqual(plan.commands["501"], {"action": "sell", "name": "copper", "num": 12})

    def test_opening_protects_gold_from_pioneer_treasure_purchase(self):
        raw = opening_request()
        raw["teamOur"]["roles"][2]["pos"] = {"x": 14, "y": 23}
        memory = GameMemory(treasure={"targetPos": {"x": 14, "y": 24}, "items": ["StarSand"], "startRound": 1, "endRound": 10})
        plan = self.decide(raw, memory)
        self.assertFalse(any(c["action"] == "buy" for c in plan.commands.values()))
        self.assertEqual(plan.gold, 25)

    def test_night_defence_precedes_treasure_with_weapons(self):
        raw = opening_request(71, towers=True)
        raw["teamOur"]["roles"][2]["backpack"] = ["StarSand"]
        raw["robot"]["roles"] = [robot(900, 10, 29, health=500)]
        memory = GameMemory(opening_complete=True, treasure={"targetPos": {"x": 10, "y": 27}, "items": ["StarSand"], "startRound": 71, "endRound": 72})
        plan = self.decide(raw, memory)
        self.assertEqual(plan.commands["601"]["controllerId"], "502")
        self.assertFalse(any(c["action"] == "summonTreasure" for c in plan.commands.values()))

    def test_full_backpack_sells_nonstone_without_spending_wall_reserve(self):
        raw = opening_request(71, towers=True)
        raw["teamOur"]["roles"][1].update(pos={"x": 6, "y": 23}, backpack=["stone"]*2 + ["copper"]*98)
        plan = self.decide(raw)
        self.assertEqual(plan.commands["501"], {"action": "sell", "name": "copper", "num": 98})

    def test_worker_on_operator_cell_moves_away(self):
        raw = opening_request(71, towers=True)
        raw["teamOur"]["roles"][1]["pos"] = {"x": 10, "y": 26}
        raw["teamOur"]["roles"][2]["pos"] = {"x": 10, "y": 28}
        plan = self.decide(raw)
        self.assertEqual(plan.commands["501"]["action"], "move")
        self.assertNotEqual(plan.commands["501"]["targetPos"], [{"x": 10, "y": 26}])

    def test_temporary_block_does_not_freeze_incomplete_layout(self):
        raw = opening_request()
        raw["teamOur"]["roles"].append(unit(900, "wall", 11, 25))
        first = select_defense_layout(Turn.load(raw), opening_settings())
        self.assertEqual(len(first.tower_sites), 2)
        raw["teamOur"]["roles"].pop()
        second = select_defense_layout(Turn.load(raw), opening_settings(), first)
        self.assertEqual(len(second.tower_sites), 3)
        self.assertTrue(second.shared_control)

    def test_defender_layout_uses_its_own_confirmed_offsets(self):
        raw = opening_request(71, towers=True)
        raw["teamOur"]["type"] = "defender"
        config = opening_settings()
        config.layouts["defender"] = config.layouts.pop("challenger")
        raw["robot"]["roles"] = [robot(900, 10, 31, health=500, targetTeam="defender")]
        turn = Turn.load(raw)
        plan = ActionPlan(turn, config)
        Strategy(turn, plan, GameMemory()).run()
        self.assertEqual(plan.commands["601"]["controllerId"], "502")
        self.assertEqual(plan.commands["501"]["action"], "collect")
