import unittest
from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.combat import choose_targets, damage_for, pair_weapons
from agent.protocol import Pos, Turn
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import request, unit, robot, layout_settings


class CombatStrategyTests(unittest.TestCase):
    def execute(self, raw, settings=None, memory=None):
        turn = Turn.load(raw)
        plan = ActionPlan(turn, settings or layout_settings())
        Strategy(turn, plan, memory or GameMemory()).run()
        self.assertEqual(plan.rejections, [])
        return plan

    def test_railgun_energy_and_gatling_nearest_robot(self):
        raw = request(71)
        raw["teamOur"]["roles"] = [unit(1, "railgun", 5, 5, level=2)]
        raw["robot"]["roles"] = [robot(2, 7, 5, health=5), robot(3, 9, 5, health=40)]
        turn = Turn.load(raw)
        health = {2: 5, 3: 40}
        self.assertEqual(damage_for(turn, turn.weapons()[0], Pos(9, 5), health), {2: 5, 3: 15})
        raw["teamOur"]["roles"][0]["roleType"] = "gatling"
        turn = Turn.load(raw)
        self.assertEqual(damage_for(turn, turn.weapons()[0], Pos(9, 5), health), {2: 5})

    def test_rocket_center_splash_and_repeated_centers(self):
        raw = request(71)
        raw["teamOur"]["roles"] = [unit(1, "rocket", 5, 5, level=3)]
        raw["robot"]["roles"] = [robot(2, 20, 20, health=500), robot(3, 21, 21), robot(4, 22, 22)]
        turn = Turn.load(raw)
        health = {r.robot_id: r.health for r in turn.robots}
        self.assertEqual(damage_for(turn, turn.weapons()[0], Pos(20, 20), health), {2: 20, 3: 10})
        raw["robot"]["roles"] = [robot(2, 20, 20, health=500)]
        turn = Turn.load(raw)
        health = {2: 500}
        self.assertEqual(choose_targets(turn, turn.weapons()[0], health), [Pos(20, 20)] * 3)
        self.assertEqual(health[2], 440)

    def test_all_projectiles_stay_in_gatling_cone(self):
        raw = request(71)
        raw["teamOur"]["roles"] = [unit(1, "gatling", 5, 5, level=3)]
        raw["robot"]["roles"] = [robot(10, 8, 5), robot(11, 2, 5), robot(12, 5, 8)]
        turn = Turn.load(raw)
        targets = choose_targets(turn, turn.weapons()[0], {r.robot_id: r.health for r in turn.robots})
        self.assertEqual(len(targets), 3)
        for a in targets:
            for b in targets:
                self.assertGreaterEqual((a.x-5)*(b.x-5)+(a.y-5)*(b.y-5), 0)

    def test_weapon_pairing_uses_positions_not_id_order(self):
        raw = request(71)
        raw["teamOur"]["roles"] = [unit(1, "worker", 20, 20), unit(2, "pioneer", 3, 3),
                                    unit(10, "rocket", 4, 3), unit(11, "gatling", 21, 20)]
        turn = Turn.load(raw)
        self.assertEqual({r.unit_id: t.unit_id for r, t in pair_weapons(turn, turn.controllable())}, {1: 11, 2: 10})

    def test_night_attacks_keyed_by_weapon_and_respects_cooldown(self):
        raw = request(71)
        raw["teamOur"]["roles"][2]["pos"] = {"x": 8, "y": 24}
        raw["teamOur"]["roles"].append(unit(601, "rocket", 9, 24, level=2))
        raw["robot"]["roles"] = [robot(900, 8, 26, health=500)]
        plan = self.execute(raw)
        self.assertEqual(plan.commands["601"]["controllerId"], "502")
        self.assertEqual(len(plan.commands["601"]["targetPos"]), 2)
        self.assertNotIn("502", plan.commands)
        raw["teamOur"]["roles"][-1]["cooldown"] = 3
        self.assertNotIn("601", self.execute(raw).commands)

    def test_pioneer_returns_at_dusk_while_worker_continues_building(self):
        raw = request(70)
        raw["teamOur"]["roles"].append(unit(601, "rocket", 9, 24))
        commands = self.execute(raw).commands
        self.assertEqual(commands["502"]["action"], "move")
        self.assertEqual(commands["504"]["action"], "build")

    def test_initial_construction_budget_is_shared(self):
        raw = request()
        raw["teamOur"]["goldNum"] = 25
        plan = self.execute(raw)
        builds = [c for c in plan.commands.values() if c["action"] == "build" and c["name"] != "wall"]
        self.assertEqual(len(builds), 1)
        self.assertEqual(plan.gold, 0)

    def test_current_vendor_prices_determine_sale(self):
        raw = request()
        raw["teamOur"]["roles"][1]["backpack"] = ["stone", "copper"]
        raw["vendorShopList"] = [{"name": "stone", "price": 100}, {"name": "copper", "price": 1}]
        plan = self.execute(raw, Settings(enable_news=False, allow_base_surroundings=False))
        self.assertEqual(plan.commands["501"], {"action": "sell", "name": "stone", "num": 1})

    def test_upgrades_are_purchased_then_used_on_observed_inventory(self):
        # Use a weapon voucher; base upgrades are disabled by the current strategy.
        raw = request(131)
        raw["teamOur"]["goldNum"] = 100
        raw["teamOur"]["roles"] = [unit(503, "station", 10, 24), unit(504, "worker", 12, 23), unit(601, "rocket", 11, 22)]
        plan = self.execute(raw, Settings(enable_news=False, allow_base_surroundings=False))
        self.assertEqual(plan.commands["504"]["action"], "buy")
        raw["teamOur"]["roles"][1]["backpack"] = ["WeaponUpgradeVoucher1"]
        self.assertEqual(self.execute(raw, Settings(enable_news=False, allow_base_surroundings=False)).commands["504"], {"action": "use", "name": "WeaponUpgradeVoucher1", "targetPos": [{"x": 11, "y": 22}]})

    def test_second_task_cell_and_dusk_task_admission(self):
        raw = request()
        raw["teamOur"]["playerTasks"][0]["isValid"] = False
        raw["teamOur"]["roles"][2]["pos"] = {"x": 15, "y": 17}
        self.assertEqual(self.execute(raw).commands["502"], {"action": "acceptTask"})
        raw["roundNo"] = 69
        self.assertNotEqual(self.execute(raw).commands.get("502", {}).get("action"), "acceptTask")

    def test_treasure_waits_then_sacrifices_exact_list(self):
        raw = request(5)
        raw["teamOur"]["roles"][2]["backpack"] = ["StarSand", "Medicine"]
        memory = GameMemory(opening_complete=True, treasure={"targetPos": {"x": 15, "y": 13}, "items": ["StarSand"], "startRound": 6, "endRound": 9})
        self.assertNotIn("502", self.execute(raw, memory=memory).commands)
        raw["roundNo"] = 6
        cmd = self.execute(raw, memory=memory).commands["502"]
        self.assertEqual(cmd["action"], "summonTreasure")
        self.assertEqual(cmd["item"], ["StarSand"])

    def test_no_discretionary_commands_for_dead_roles(self):
        raw = request()
        for role in raw["teamOur"]["roles"]:
            role["health"] = 0
        self.assertEqual(self.execute(raw).commands, {})

    def test_night_treasure_window_available_when_no_weapons_need_defence(self):
        raw = request(71)
        raw["teamOur"]["roles"][2]["backpack"] = ["StarSand"]
        memory = GameMemory(opening_complete=True, treasure={"targetPos": {"x": 15, "y": 13}, "items": ["StarSand"], "startRound": 71, "endRound": 72})
        self.assertEqual(self.execute(raw, memory=memory).commands["502"]["action"], "summonTreasure")

    def test_dusk_pioneer_does_not_deliver_remote_upgrade_instead_of_defending(self):
        raw = request(70)
        raw["teamOur"]["roles"][2]["backpack"] = ["StationUpgradeVoucher1"]
        raw["teamOur"]["roles"].append(unit(601, "rocket", 9, 24))
        self.assertEqual(self.execute(raw).commands["502"]["action"], "move")
