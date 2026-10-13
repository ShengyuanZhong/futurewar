"""First-night policy for three confirmed rocket sites and their shared post.

All enemy people below are current observation entries. Remembered weapons
describe immutable layout knowledge and never invent a live cannon operator.
The checks exercise issued commands, not official damage settlement.
"""
import copy
import unittest
from dataclasses import replace

from agent.protocol import Pos, Turn, distance
from app.service.memory import GameMemory
from tests.fixtures import unit
from tests.test_boss_formation import (BASE, FRONT, REAR, GAP, OPERATOR,
    formation_arena, reflected, reflected_cell)
from tests.test_raid_efficiency import decide


HERO = 41000


def settle(raw, plan):
    """Settle only accepted moves into actually empty, unique observed cells."""
    for boss in raw['teamOur']['summonRobotList']:
        command = plan.commands.get(str(boss['id']), {})
        if command.get('action') == 'move':
            boss['pos'] = copy.deepcopy(command['targetPos'][0])
    raw['robot']['roles'] = copy.deepcopy(raw['teamOur']['summonRobotList'])
    raw['roundNo'] += 1
    raw['lastRoundRoleActionResults'] = {uid: True for uid in plan.commands}


class RocketControlPolicyTests(unittest.TestCase):
    def assert_base_attack(self, strategy, plan, uid=FRONT):
        command = plan.commands[str(uid)]
        self.assertEqual(command['action'], 'attack')
        base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
        self.assertIn(Pos.load(command['targetPos'][0]), strategy.turn.footprint(base))
        self.assertEqual(plan.rejections, [])

    def assert_legal_moves(self, strategy, plan):
        destinations = set()
        occupied = strategy.turn.occupied_cells()
        for boss in strategy.turn.summon_robots:
            command = plan.commands.get(str(boss.robot_id), {})
            if command.get('action') != 'move':
                continue
            target = Pos.load(command['targetPos'][0])
            self.assertEqual(distance(boss.pos, target), 1)
            self.assertNotIn(target, occupied)
            self.assertNotIn(target, destinations)
            destinations.add(target)
        self.assertEqual(plan.rejections, [])

    def test_observed_three_rockets_have_only_the_actual_shared_control_cell(self):
        strategy, _ = decide(formation_arena(front=OPERATOR, rear=None))
        self.assertEqual(set(strategy.raider.rocket_control_posts()), {OPERATOR})

    def test_live_controllable_enemy_on_the_shared_post_preempts_base(self):
        for kind in ('worker', 'pioneer', 'imp'):
            with self.subTest(kind=kind):
                raw = formation_arena(front=GAP, rear=None)
                raw['teamEnemy']['roles'].append(unit(HERO, kind, OPERATOR.x, OPERATOR.y,
                                                      health=500))
                strategy, plan = decide(raw)
                self.assertEqual(plan.commands[str(FRONT)],
                                 {'action': 'attack', 'targetPos': [OPERATOR.dump()]})
                self.assertEqual(strategy.memory.robot_raids[FRONT]['controller_id'], HERO)
                self.assertEqual(plan.rejections, [])

    def test_a_lower_health_person_near_only_two_rockets_is_ignored(self):
        raw = formation_arena(front=OPERATOR, rear=None)
        raw['teamEnemy']['roles'].append(unit(HERO, 'worker', GAP.x, GAP.y, health=1))
        strategy, plan = decide(raw)
        self.assert_base_attack(strategy, plan)
        self.assertNotEqual(strategy.memory.robot_raids[FRONT].get('controller_id'), HERO)

    def test_shared_operator_preempts_direct_low_health_partial_operator(self):
        raw = formation_arena(front=GAP, rear=None)
        # Open this actual ring cell for a distinct, directly hittable person.
        # It controls the upper gun but cannot control the two lower guns.
        partial = Pos(12, 20)
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles']
            if not (u['roleType'] == 'wall' and Pos.load(u['pos']) == partial)]
        raw['teamEnemy']['roles'] += [unit(HERO, 'pioneer', OPERATOR.x, OPERATOR.y, health=500),
                                     unit(HERO+1, 'worker', partial.x, partial.y, health=1)]
        strategy, plan = decide(raw)
        self.assertTrue(strategy.raider.clear_shot(strategy.turn.summon_robots[0], partial))
        self.assertEqual(plan.commands[str(FRONT)],
                         {'action': 'attack', 'targetPos': [OPERATOR.dump()]})
        self.assertEqual(strategy.memory.robot_raids[FRONT]['controller_id'], HERO)

    def test_base_neighbour_outside_shared_control_post_is_not_a_target(self):
        raw = formation_arena(front=OPERATOR, rear=None)
        raw['teamEnemy']['roles'].append(unit(HERO, 'worker', 16, 19, health=1))
        strategy, plan = decide(raw)
        self.assert_base_attack(strategy, plan)

    def test_live_person_leaving_the_shared_post_is_not_chased_next_frame(self):
        raw = formation_arena(front=GAP, rear=None)
        raw['teamEnemy']['roles'].append(unit(HERO, 'worker', OPERATOR.x, OPERATOR.y, health=100))
        memory = GameMemory(opening_complete=True)
        strategy, plan = decide(raw, memory)
        self.assertEqual(plan.commands[str(FRONT)]['targetPos'], [OPERATOR.dump()])
        settle(raw, plan)
        next(u for u in raw['teamEnemy']['roles'] if u['id'] == HERO)['pos'] = Pos(13, 21).dump()
        strategy, plan = decide(raw, memory)
        self.assert_legal_moves(strategy, plan)
        self.assertNotEqual(plan.commands[str(FRONT)],
                            {'action': 'attack', 'targetPos': [Pos(13, 21).dump()]})
        self.assertNotEqual(memory.robot_raids[FRONT].get('controller_id'), HERO)
        self.assertEqual(memory.robot_raids[FRONT].get('pursuit_kind'), 'base')
        settle(raw, plan)
        strategy, plan = decide(raw, memory)
        self.assert_base_attack(strategy, plan)

    def test_observed_dead_shared_operator_does_not_delay_occupation(self):
        raw = formation_arena(front=GAP, rear=None)
        raw['teamEnemy']['roles'].append(unit(HERO, 'worker', OPERATOR.x, OPERATOR.y, health=0))
        strategy, plan = decide(raw)
        self.assertEqual(plan.commands[str(FRONT)],
                         {'action': 'move', 'targetPos': [OPERATOR.dump()]})
        self.assert_legal_moves(strategy, plan)

    def test_single_boss_claims_shared_post_then_keeps_attacking_base(self):
        raw = formation_arena(rear=None)
        memory = GameMemory(opening_complete=True)
        reached = False
        for _ in range(5):
            strategy, plan = decide(raw, memory)
            self.assert_legal_moves(strategy, plan)
            boss = strategy.turn.summon_robots[0]
            if boss.pos == OPERATOR:
                reached = True
                self.assert_base_attack(strategy, plan)
            elif plan.commands[str(FRONT)].get('action') == 'move':
                post = Pos.load(plan.commands[str(FRONT)]['targetPos'][0])
                base = next(u for u in strategy.turn.enemies if u.unit_id == BASE)
                self.assertTrue(any(strategy.raider.clear_shot(replace(boss, pos=post), p)
                                    for p in strategy.turn.footprint(base)))
            settle(raw, plan)
        self.assertTrue(reached, 'even one BOSS should deny the shared firing position')

    def test_single_boss_uses_actual_shared_post_in_all_reflections(self):
        for horizontal, vertical in ((False, False), (True, False),
                                     (False, True), (True, True)):
            with self.subTest(horizontal=horizontal, vertical=vertical):
                raw = reflected(formation_arena(rear=None), horizontal, vertical)
                memory = GameMemory(opening_complete=True)
                post = reflected_cell(OPERATOR, horizontal, vertical)
                found = False
                for _ in range(5):
                    strategy, plan = decide(raw, memory)
                    self.assertEqual(set(strategy.raider.rocket_control_posts()), {post})
                    self.assert_legal_moves(strategy, plan)
                    found |= strategy.turn.summon_robots[0].pos == post
                    settle(raw, plan)
                self.assertTrue(found)

    def test_multiple_bosses_cannot_share_destination_or_swap_actual_positions(self):
        raw = formation_arena(front=GAP, rear=Pos(11, 19))
        strategy, plan = decide(raw)
        self.assert_legal_moves(strategy, plan)
        self.assertEqual(plan.commands[str(FRONT)],
                         {'action': 'move', 'targetPos': [OPERATOR.dump()]})
        for boss in strategy.turn.summon_robots:
            if boss.robot_id != FRONT and plan.commands.get(str(boss.robot_id), {}).get('action') == 'move':
                self.assertNotEqual(plan.commands[str(boss.robot_id)]['targetPos'], [OPERATOR.dump()])
                self.assertNotEqual(plan.commands[str(boss.robot_id)]['targetPos'], [GAP.dump()])

    def test_third_rocket_without_common_control_cell_does_not_enable_partial_operator(self):
        raw = formation_arena(front=OPERATOR, rear=None)
        third = next(u for u in raw['teamEnemy']['roles'] if u['id'] == 994)
        third['pos'] = Pos(16, 18).dump()
        raw['teamEnemy']['roles'].append(unit(HERO, 'worker', GAP.x, GAP.y, health=1))
        strategy, plan = decide(raw)
        self.assertEqual(set(strategy.raider.rocket_control_posts()), set())
        self.assert_base_attack(strategy, plan)

    def test_mixed_weapons_keep_existing_partial_operator_priority(self):
        for kind in ('gatling', 'railgun'):
            with self.subTest(kind=kind):
                # No BOSS occupies the best control post, so the new group
                # base lock must not suppress ordinary mixed-layout targeting.
                raw = formation_arena(front=Pos(11, 19), rear=None)
                next(u for u in raw['teamEnemy']['roles'] if u['id'] == 994)['roleType'] = kind
                raw['teamEnemy']['roles'].append(unit(HERO, 'worker', GAP.x, GAP.y, health=1))
                strategy, plan = decide(raw)
                self.assertIsNone(strategy.raider.rocket_control_posts())
                self.assertFalse(strategy.raider.group_base_ready())
                self.assertEqual(plan.commands[str(FRONT)],
                                 {'action': 'attack', 'targetPos': [GAP.dump()]})

    def test_two_known_rockets_keep_existing_partial_operator_priority(self):
        raw = formation_arena(front=Pos(11, 19), rear=None)
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['id'] != 994]
        raw['teamEnemy']['roles'].append(unit(HERO, 'worker', GAP.x, GAP.y, health=1))
        strategy, plan = decide(raw)
        self.assertIsNone(strategy.raider.rocket_control_posts())
        self.assertFalse(strategy.raider.group_base_ready())
        self.assertEqual(plan.commands[str(FRONT)],
                         {'action': 'attack', 'targetPos': [GAP.dump()]})

    def test_confirmed_weapon_sites_keep_mode_without_fabricating_a_hidden_person(self):
        raw = formation_arena(front=OPERATOR, rear=None)
        memory = GameMemory(opening_complete=True)
        observed = Turn.load(raw)
        memory.enemy_structures.update((u.unit_id, u) for u in observed.enemies)
        memory.enemy_weapon_sites.update((u.pos, u.kind) for u in observed.enemies if u.kind == 'rocket')
        memory.robot_raids[FRONT] = dict(round=raw['roundNo']-1, stage='controller',
            pursuit_kind='controller', controller_id=HERO, controller_pos=OPERATOR,
            controller_health=40, action='attack', target=OPERATOR, position=GAP)
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles'] if u['roleType'] != 'rocket']
        raw['teamOur']['roles'][1]['pos'] = Pos(2, 6).dump()
        strategy, plan = decide(raw, memory)
        self.assertFalse(strategy.raider.seen_cell(OPERATOR))
        self.assertEqual(set(strategy.raider.rocket_control_posts()), {OPERATOR})
        self.assert_base_attack(strategy, plan)
        self.assertNotEqual(memory.robot_raids[FRONT].get('controller_id'), HERO)

    def test_real_shared_post_occupant_is_never_treated_as_empty_space(self):
        raw = formation_arena(front=GAP, rear=None)
        raw['teamEnemy']['roles'].append(unit(HERO, 'imp', OPERATOR.x, OPERATOR.y))
        strategy, plan = decide(raw)
        self.assert_legal_moves(strategy, plan)
        command = plan.commands[str(FRONT)]
        if command.get('action') == 'move':
            self.assertNotEqual(command['targetPos'], [OPERATOR.dump()])

    def test_prior_allied_move_reservation_excludes_shared_control_post(self):
        raw = formation_arena(front=GAP, rear=None)
        strategy, plan = decide(raw)
        plan.commands.clear()
        plan.used.clear()
        plan.reserved.clear()
        plan.reserved.add(OPERATOR)
        strategy.raider.decide(strategy.turn.summon_robots[0])
        self.assert_legal_moves(strategy, plan)
        command = plan.commands[str(FRONT)]
        if command.get('action') == 'move':
            self.assertNotEqual(command['targetPos'], [OPERATOR.dump()])

    def test_current_mixed_rebuild_overrides_remembered_three_rocket_mode(self):
        raw = formation_arena(front=Pos(11, 19), rear=None)
        state = GameMemory(opening_complete=True)
        old_turn = Turn.load(raw)
        state.enemy_structures.update((u.unit_id, u) for u in old_turn.enemies)
        state.enemy_weapon_sites.update((u.pos, u.kind) for u in old_turn.enemies if u.kind == 'rocket')
        replacement = next(u for u in raw['teamEnemy']['roles'] if u['id'] == 994)
        replacement.update(id=999, roleType='gatling')
        raw['teamEnemy']['roles'].append(unit(HERO, 'worker', GAP.x, GAP.y, health=1))
        strategy, plan = decide(raw, state)
        self.assertIsNone(strategy.raider.rocket_control_posts())
        self.assertFalse(strategy.raider.group_base_ready())
        self.assertEqual(state.enemy_weapon_sites[Pos(14, 18)], 'gatling')
        self.assertEqual(plan.commands[str(FRONT)],
                         {'action': 'attack', 'targetPos': [GAP.dump()]})


if __name__ == '__main__':
    unittest.main()
