"""Confirmed gun sites guide first-day summons without inventing live targets."""
import copy
import unittest

from agent.protocol import Pos, Turn, station_footprint
from agent.robot_combat import clear_attack
from agent.summoning import (enemy_layout_weapons, layout_operator_positions,
                             layout_weapon_sites, scouted_spawn_candidates,
                             summon_cell_legal)
from tests.fixtures import robot, unit
from tests.test_worker_boss_buyer import (BUYER, ORDER, SCOUT, actor, advance,
                                         load_strategy, role, worker_raid_scene)


def withdraw_sight(raw):
    """Only globally visible buildings remain in the observed enemy list."""
    raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles']
                                if u['roleType'] in ('station', 'wall')]
    actor(raw, SCOUT)['pos'] = Pos(16, 12).dump()


class CachedLayoutSummonTests(unittest.TestCase):
    def test_cached_sites_preserve_operator_and_spawn_geometry_on_both_sides(self):
        for lower_right in (False, True):
            with self.subTest(lower_right=lower_right):
                raw, memory, settings = worker_raid_scene(lower_right=lower_right)
                observed = Turn.load(raw)
                sites = {u.pos for u in observed.enemies if u.kind == 'rocket'}
                before = scouted_spawn_candidates(observed, settings)
                operators = layout_operator_positions(observed)
                withdraw_sight(raw)
                blind = Turn.load(raw)
                self.assertEqual(enemy_layout_weapons(blind), ())
                self.assertEqual(layout_weapon_sites(blind, confirmed_sites=sites), tuple(sorted(sites)))
                self.assertEqual(layout_operator_positions(blind, confirmed_sites=sites), operators)
                self.assertEqual(scouted_spawn_candidates(blind, settings, confirmed_sites=sites), before)
                self.assertTrue(before)
                self.assertNotIn(before[0], sites)
                self.assertTrue(summon_cell_legal(blind, settings, before[0]))

    def test_site_cache_from_other_base_cannot_complete_unknown_layout(self):
        raw, _, settings = worker_raid_scene()
        withdraw_sight(raw)
        turn = Turn.load(raw)
        foreign = {Pos(7, 25), Pos(7, 24), Pos(7, 23)}
        self.assertEqual(layout_weapon_sites(turn, confirmed_sites=foreign), ())
        self.assertEqual(scouted_spawn_candidates(turn, settings, confirmed_sites=foreign), ())

    def test_cached_geometry_still_uses_current_global_walls(self):
        raw, _, settings = worker_raid_scene()
        sites = {u.pos for u in Turn.load(raw).enemies if u.kind == 'rocket'}
        base = next(u for u in Turn.load(raw).enemies if u.kind == 'station').pos
        raw['teamEnemy']['roles'] += [unit(1200, 'wall', base.x+3, base.y),
                                     unit(1201, 'wall', base.x+3, base.y+1)]
        observed = Turn.load(raw)
        ranked = scouted_spawn_candidates(observed, settings)
        # Keep friendly positions equal when comparing placement geometry;
        # a moving observer can itself change a proposed firing path.
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles']
                                    if u['roleType'] in ('station', 'wall')]
        turn = Turn.load(raw)
        self.assertEqual(scouted_spawn_candidates(turn, settings, confirmed_sites=sites), ranked)
        self.assertEqual(len([u for u in turn.enemies if u.kind=='wall']), 2)

    def test_pending_and_failed_spawn_cells_are_not_reused_without_sight(self):
        raw, _, settings = worker_raid_scene()
        sites = {u.pos for u in Turn.load(raw).enemies if u.kind == 'rocket'}
        withdraw_sight(raw)
        turn = Turn.load(raw)
        first = scouted_spawn_candidates(turn, settings, confirmed_sites=sites)[0]
        second = scouted_spawn_candidates(turn, settings, pending=(first,), confirmed_sites=sites)[0]
        self.assertNotEqual(first, second)
        ranked = scouted_spawn_candidates(turn, settings, pending=(first,), failed=(second,),
                                          confirmed_sites=sites)
        self.assertNotIn(first, ranked)
        self.assertNotIn(second, ranked)

    def test_known_layout_can_use_coupon_after_observers_lose_current_sight(self):
        raw, memory, settings = worker_raid_scene(successes=1)
        s, _ = load_strategy(raw, memory, settings)
        sites = set(memory.enemy_weapon_sites)
        self.assertEqual(len(sites), 3)
        withdraw_sight(raw)
        actor(raw)['backpack'].append(ORDER)
        raw['teamOur']['goldNum'] = 0
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(s.raid_scouts.summon_ready())
        self.assertTrue(s.raid_scouts.spawn_ready())
        self.assertTrue(s.boss_raid.worker(role(s)))
        command = plan.commands[str(BUYER)]
        self.assertEqual(command['action'], 'use')
        self.assertEqual(command['name'], ORDER)
        self.assertTrue(summon_cell_legal(s.turn, settings, Pos.load(command['targetPos'][0])))
        self.assertEqual(plan.rejections, [])
        self.assertEqual(set(memory.enemy_weapon_sites), sites)

    def test_unobserved_layout_still_waits_instead_of_using_template(self):
        raw, memory, settings = worker_raid_scene(successes=1)
        withdraw_sight(raw)
        actor(raw)['backpack'].append(ORDER)
        raw['teamOur']['goldNum'] = 0
        s, plan = load_strategy(raw, memory, settings)
        self.assertFalse(s.raid_scouts.spawn_ready())
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertNotIn(str(BUYER), plan.commands)
        self.assertEqual(memory.boss_raid['status'], 'waiting_for_scout')

    def test_known_layout_does_not_bypass_three_task_attempts(self):
        raw, memory, settings = worker_raid_scene(finished=2, successes=2)
        load_strategy(raw, memory, settings)
        withdraw_sight(raw)
        actor(raw)['backpack'].append(ORDER)
        s, plan = load_strategy(raw, memory, settings)
        self.assertTrue(s.raid_scouts.spawn_ready())
        self.assertTrue(s.boss_raid.worker(role(s)))
        self.assertFalse(any(c.get('action') == 'use' and c.get('name') == ORDER
                             for c in plan.commands.values()))
        self.assertIsNone(s.boss_raid.target_orders())

    def test_three_orders_use_distinct_cells_and_require_next_round_confirmation(self):
        raw, memory, settings = worker_raid_scene(successes=3)
        load_strategy(raw, memory, settings)
        withdraw_sight(raw)
        actor(raw)['backpack'] += [ORDER]*3
        raw['teamOur']['goldNum'] = 0
        spawns = []
        for count in range(3):
            s, plan = load_strategy(raw, memory, settings)
            self.assertTrue(s.boss_raid.worker(role(s)))
            command = plan.commands[str(BUYER)]
            self.assertEqual(command['action'], 'use')
            spawn = Pos.load(command['targetPos'][0])
            self.assertNotIn(spawn, spawns)
            self.assertTrue(summon_cell_legal(s.turn, settings, spawn))
            self.assertEqual(memory.boss_raid['deployed_count'], count)
            spawns.append(spawn)
            actor(raw)['backpack'].remove(ORDER)
            advance(raw, memory, s, plan)
        s, plan = load_strategy(raw, memory, settings)
        self.assertEqual(memory.boss_raid['deployed_count'], 3)
        self.assertEqual(memory.boss_raid['spawns'], spawns)
        self.assertFalse(s.boss_raid.worker(role(s)))
        self.assertEqual(plan.commands, {})

    def test_cached_sites_never_become_live_attack_targets(self):
        raw, memory, settings = worker_raid_scene(successes=1)
        load_strategy(raw, memory, settings)
        sites = set(memory.enemy_weapon_sites)
        withdraw_sight(raw)
        memory.enemy_structures.clear()  # Exercise the persistent site cache alone.
        raw['roundNo'] = 71
        base = next(u for u in Turn.load(raw).enemies if u.kind == 'station')
        born = robot(30005, base.pos.x+4, base.pos.y, health=800, roleType='bossRobot')
        raw['teamOur']['summonRobotList'] = [born]
        raw['robot']['roles'] = [copy.deepcopy(born)]
        s, plan = load_strategy(raw, memory, settings)
        boss = s.turn.summon_robots[0]
        for site in sites:
            self.assertFalse(clear_attack(s.turn, boss, site))
        self.assertEqual(enemy_layout_weapons(s.turn, memory.enemy_structures.values()), ())
        s.raider.decide(boss)
        command = plan.commands[str(boss.robot_id)]
        if command['action'] == 'attack':
            self.assertIn(Pos.load(command['targetPos'][0]), station_footprint(base.pos))
        self.assertEqual(set(memory.enemy_weapon_sites), sites)


if __name__ == '__main__':
    unittest.main()
