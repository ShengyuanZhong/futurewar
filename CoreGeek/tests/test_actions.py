import unittest
from agent.actions import ActionPlan
from agent.protocol import Turn, Pos, attack_command, build_command, move_command
from app.config import Settings
from tests.fixtures import request, unit, layout_settings


class ActionTests(unittest.TestCase):
    def plan(self, raw=None):
        return ActionPlan(Turn.load(raw or request()), layout_settings())

    def test_all_twelve_actions_have_valid_examples(self):
        cases = [
            (501, {"action": "move", "targetPos": [{"x": 8, "y": 24}]}),
            (601, {"action": "attack", "controllerId": "501", "targetPos": [{"x": 8, "y": 25}]}),
            (501, {"action": "sell", "name": "copper", "num": 2}),
            (504, {"action": "buy", "name": "Medicine", "num": 2}),
            (504, {"action": "build", "name": "rocket", "targetPos": [{"x": 12, "y": 24}]}),
            (501, {"action": "remove", "targetPos": [{"x": 8, "y": 22}]}),
            (502, {"action": "acceptTask"}),
            (502, {"action": "submitAnswer", "taskAnswer": "answer"}),
            (502, {"action": "summonTreasure", "targetPos": [{"x": 15, "y": 13}], "item": ["StarSand"]}),
            (501, {"action": "use", "name": "Medicine"}),
            (501, {"action": "drop", "name": "copper"}),
            (501, {"action": "collect", "targetPos": [{"x": 7, "y": 22}]}),
        ]
        for actor, cmd in cases:
            with self.subTest(action=cmd["action"]):
                raw = request(71 if cmd["action"] == "attack" else 1)
                raw["teamOur"]["roles"][1]["backpack"] = ["copper", "copper", "Medicine"]
                raw["teamOur"]["roles"][2]["backpack"] = ["StarSand"]
                raw["teamOur"]["roles"] += [unit(601, "gatling", 9, 24), unit(602, "wall", 8, 22)]
                if cmd["action"] == "submitAnswer":
                    raw["phaseTask"] = "active task"
                plan = self.plan(raw)
                self.assertTrue(plan.add(actor, cmd), plan.rejections)

    def test_shared_gold_and_three_weapon_limit(self):
        raw = request()
        raw["teamOur"]["goldNum"] = 25
        plan = self.plan(raw)
        self.assertTrue(plan.add(501, build_command(Pos(9, 24), "rocket")))
        self.assertFalse(plan.add(504, build_command(Pos(12, 24), "railgun")))
        self.assertEqual(plan.gold, 0)
        raw["teamOur"]["goldNum"] = 100
        raw["teamOur"]["roles"] += [unit(601+i, k, 20+i, 25) for i, k in enumerate(("gatling", "railgun", "rocket"))]
        self.assertFalse(self.plan(raw).add(501, build_command(Pos(9, 24), "rocket")))

    def test_replacement_does_not_add_fourth_weapon(self):
        raw = request()
        raw["teamOur"]["roles"] += [unit(601, "gatling", 9, 24), unit(602, "rocket", 10, 25), unit(603, "railgun", 12, 24)]
        plan = self.plan(raw)
        self.assertTrue(plan.add(501, build_command(Pos(9, 24), "rocket")))
        self.assertEqual(plan.tower_count, 3)

    def test_strict_mode_rejects_unverified_or_wrong_zone_building(self):
        turn = Turn.load(request())
        self.assertFalse(ActionPlan(turn, Settings(allow_base_surroundings=False)).add(501, build_command(Pos(9, 24), "rocket")))
        self.assertFalse(self.plan().add(501, build_command(Pos(8, 24), "rocket")))
        self.assertFalse(self.plan().add(501, build_command(Pos(9, 24), "wall")))

    def test_no_double_action_or_controller_reuse(self):
        raw = request(71)
        raw["teamOur"]["roles"] += [unit(601, "gatling", 9, 24), unit(602, "gatling", 9, 23)]
        plan = self.plan(raw)
        self.assertTrue(plan.add(601, attack_command(501, Pos(8, 25))))
        self.assertFalse(plan.add(501, move_command(Pos(8, 24))))
        self.assertFalse(plan.add(602, attack_command(501, Pos(8, 25))))

    def test_simultaneous_destination_swap_and_build_conflict(self):
        raw = request()
        raw["teamOur"]["roles"][3]["pos"] = {"x": 9, "y": 23}
        plan = self.plan(raw)
        self.assertFalse(plan.add(501, move_command(Pos(9, 23))))
        self.assertTrue(plan.add(501, move_command(Pos(9, 24))))
        self.assertFalse(plan.add(504, move_command(Pos(9, 24))))
        self.assertFalse(plan.add(504, build_command(Pos(9, 24), "rocket")))

    def test_attacks_require_night_cooldown_range_and_projectile_count(self):
        for round_no, cooldown, level, targets, allowed in (
                (70, 0, 1, [Pos(8, 25)], False), (71, 1, 1, [Pos(8, 25)], False),
                (71, 0, 2, [Pos(8, 25)], False), (71, 0, 2, [Pos(8, 25), Pos(8, 25)], True),
                (71, 0, 1, [Pos(30, 25)], False)):
            raw = request(round_no)
            raw["teamOur"]["roles"].append(unit(601, "rocket", 9, 24, cooldown=cooldown, level=level))
            plan = self.plan(raw)
            self.assertEqual(plan.add(601, attack_command(501, targets)), allowed)

    def test_gatling_ninety_degree_pairwise_cone(self):
        raw = request(71)
        raw["teamOur"]["roles"].append(unit(601, "gatling", 9, 24, level=2))
        self.assertTrue(self.plan(raw).add(601, attack_command(501, [Pos(10, 24), Pos(9, 25)])))
        self.assertFalse(self.plan(raw).add(601, attack_command(501, [Pos(10, 24), Pos(8, 24)])))

    def test_capacity_worker_restriction_and_no_credit_from_sale(self):
        raw = request()
        raw["teamOur"]["roles"][1]["backpack"] = ["stone"] * 100
        raw["teamOur"]["goldNum"] = 0
        plan = self.plan(raw)
        self.assertFalse(plan.add(501, {"action": "collect", "targetPos": [{"x": 7, "y": 22}]}))
        self.assertFalse(plan.add(502, {"action": "collect", "targetPos": [{"x": 7, "y": 22}]}))
        self.assertTrue(plan.add(501, {"action": "sell", "name": "stone", "num": 100}))
        self.assertFalse(plan.add(504, {"action": "buy", "name": "Medicine"}))

    def test_shop_prices_and_invalid_quantities(self):
        raw = request()
        raw["weaponShopList"] = [{"name": "Medicine", "price": 76}]
        self.assertFalse(self.plan(raw).add(504, {"action": "buy", "name": "Medicine"}))
        for n in (0, -1, True, "1", 1.5):
            self.assertFalse(self.plan().add(504, {"action": "buy", "name": "Medicine", "num": n}))

    def test_upgrade_level_and_base_footprint_reach(self):
        raw = request()
        raw["teamOur"]["roles"][3]["backpack"] = ["StationUpgradeVoucher1", "StationUpgradeVoucher2"]
        plan = self.plan(raw)
        self.assertFalse(plan.add(504, {"action": "use", "name": "StationUpgradeVoucher2", "targetPos": [{"x": 10, "y": 24}]}))
        self.assertTrue(plan.add(504, {"action": "use", "name": "StationUpgradeVoucher1", "targetPos": [{"x": 10, "y": 24}]}))

    def test_summon_daily_limit_and_required_area_target(self):
        raw = request()
        raw["teamOur"]["roles"][1]["backpack"] = ["SmallRobotSummonOrder", "Bomb"]
        plan = self.plan(raw)
        plan.summon_used = 10
        self.assertFalse(plan.add(501, {"action": "use", "name": "SmallRobotSummonOrder"}))
        self.assertFalse(plan.add(501, {"action": "use", "name": "Bomb"}))
        self.assertTrue(plan.add(501, {"action": "use", "name": "Bomb", "targetPos": [{"x": 40, "y": 0}]}))

    def test_treasure_multiplicity_and_role(self):
        raw = request()
        raw["teamOur"]["roles"][2]["backpack"] = ["StarSand"]
        plan = self.plan(raw)
        self.assertFalse(plan.add(502, {"action": "summonTreasure", "targetPos": [{"x": 14, "y": 13}], "item": ["StarSand", "StarSand"]}))
        self.assertFalse(plan.add(501, {"action": "acceptTask"}))

    def test_invalid_protocol_shapes(self):
        for command in ({"action": "teleport"}, {"action": "move"}, {"action": "move", "targetPos": {"x": 8, "y": 24}},
                        {"action": "move", "targetPos": [{"x": 8, "y": 24}], "extra": 1}):
            self.assertFalse(self.plan().add(501, command))
