"""First-day reconnaissance owns the IMP before any home-gap standby duty.

Enemy base/wall observations are global; hidden guns and mobile crews below
are exposed only through ordinary range-four sight in these synthetic maps.
"""
import copy
import unittest

from agent.protocol import Pos, distance, station_footprint
from agent.summoning import enemy_weapon_cells
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import robot, unit
from tests.test_gap_defense import GAP, occupied, role
from tests.test_layout_survey import BASE, HOME, SCOUT, actor, reveal, survey_request
from tests.test_summon_control import ORDER, finished_tasks
from tests.test_worker_safety import strategy


IMP_ID = 505
ENEMY_BASE = Pos(33, 25)


def opening_request(number=1):
    raw = occupied(number)
    role(raw, IMP_ID)['pos'] = Pos(10, 10).dump()
    raw['teamEnemy']['roles'].append(unit(990, 'station', ENEMY_BASE.x, ENEMY_BASE.y))
    return raw


def scout_settings(**changes):
    return Settings(enable_news=False, enable_tasks=False,
                    enable_first_night_defense=False, **changes)


class ImpOpeningScoutTests(unittest.TestCase):
    def assert_opening_probe(self, raw, memory, settings):
        initial = Pos.load(role(raw, IMP_ID)['pos'])
        s, plan = strategy(raw, memory, settings)
        s.run()
        command = plan.commands[str(IMP_ID)]
        self.assertEqual(command['action'], 'move')
        step = Pos.load(command['targetPos'][0])
        self.assertEqual(distance(initial, step), 1)
        self.assertLess(distance(step, ENEMY_BASE), distance(initial, ENEMY_BASE))
        post = memory.raid_scouts['posts'][IMP_ID]
        self.assertEqual(post['mode'], 'survey')
        self.assertGreater(sum(distance(post['goal'], p) <= 4
                               for p in enemy_weapon_cells(s.turn)), 0)
        self.assertFalse(memory.raid_scouts.get('opening_scout_complete', False))
        self.assertEqual(plan.rejections, [])
        return s, plan

    def test_round_one_hostile_wall_occupant_does_not_keep_imp_on_home_standby(self):
        raw = opening_request()
        memory = GameMemory(opening_complete=True)
        s, _ = self.assert_opening_probe(raw, memory, scout_settings())
        self.assertIn(GAP, s.gap_guard.gaps)
        self.assertEqual(s.gap_guard.imp_id, IMP_ID)

    def test_opening_probe_still_runs_when_boss_purchases_are_disabled(self):
        self.assert_opening_probe(opening_request(), GameMemory(opening_complete=True),
                                  scout_settings(enable_boss_raid=False))

    def test_zero_successful_tasks_does_not_cancel_initial_reconnaissance(self):
        memory = GameMemory(opening_complete=True,
                            boss_raid={'order_decision_round': 1, 'target_count': 0})
        self.assert_opening_probe(opening_request(), memory, scout_settings())

    def test_zero_purchase_quota_keeps_the_real_imp_survey_trip_between_rounds(self):
        raw=opening_request()
        memory=GameMemory(opening_complete=True,
                          boss_raid={'order_decision_round':1,'target_count':0})
        s,plan=self.assert_opening_probe(raw,memory,scout_settings())
        goal=memory.raid_scouts['posts'][IMP_ID]['goal']
        raw.update(roundNo=2,lastRoundRoleActionResults={str(IMP_ID):True})
        role(raw,IMP_ID)['pos']=plan.commands[str(IMP_ID)]['targetPos'][0]
        s,plan=self.assert_opening_probe(raw,memory,scout_settings())
        self.assertEqual(memory.raid_scouts['posts'][IMP_ID]['goal'],goal)

    def test_three_really_observed_guns_complete_opening_survey_and_record_sites(self):
        raw, truth = survey_request(near=True)
        memory = finished_tasks()
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        actual = {Pos.load(u['pos']): u['roleType'] for u in truth
                  if u['roleType'] in ('rocket', 'gatling', 'railgun')}
        self.assertEqual(memory.enemy_weapon_sites, actual)
        self.assertTrue(memory.raid_scouts['opening_scout_complete'])
        self.assertTrue(s.raid_scouts.spawn_ready())

    def test_fewer_guns_complete_only_after_both_real_sight_passes_cover_weapon_ring(self):
        raw, truth = survey_request(near=True)
        truth = [u for u in truth if u['id'] != 993]
        reveal(raw, truth)
        memory = finished_tasks()
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        self.assertFalse(memory.raid_scouts.get('opening_scout_complete', False))
        self.assertFalse(s.raid_scouts.spawn_ready())
        raw['roundNo'] += 1
        actor(raw, SCOUT)['pos'] = Pos(14, 17).dump()
        reveal(raw, truth)
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        self.assertEqual(memory.raid_scouts['surveyed'] & enemy_weapon_cells(s.turn),
                         set(enemy_weapon_cells(s.turn)))
        self.assertTrue(memory.raid_scouts['opening_scout_complete'])
        self.assertTrue(s.raid_scouts.spawn_ready())

    def test_completed_initial_survey_releases_imp_for_actual_night_gap_takeover(self):
        raw = opening_request(71)
        raw['teamEnemy']['roles'] = [u for u in raw['teamEnemy']['roles']
                                    if u['roleType'] == 'station']
        role(raw, HOME)['health'] = 0
        memory = GameMemory(opening_complete=True,
            raid_scouts={'opening_scout_complete': True},
            wall_gap_defense={'gaps': {GAP: {'first_seen': 1}},
                              'worker_id': HOME, 'imp_id': IMP_ID})
        s, plan = strategy(raw, memory, scout_settings())
        s.run()
        self.assertTrue(memory.raid_scouts['opening_scout_complete'])
        self.assertTrue(s.gap_guard.backup_needed())
        self.assertEqual(memory.wall_gap_defense['imp_status'], 'holding_gap')
        command = plan.commands[str(IMP_ID)]
        self.assertEqual(command['action'], 'move')
        self.assertLess(distance(Pos.load(command['targetPos'][0]), GAP), distance(Pos(10, 10), GAP))

    def test_known_layout_allows_use_after_scout_leaves_without_claiming_live_sight(self):
        raw, truth = survey_request(near=True)
        memory = finished_tasks()
        strategy(raw, memory, Settings(enable_news=False))
        sites = dict(memory.enemy_weapon_sites)
        raw['roundNo'] += 1
        actor(raw, SCOUT)['pos'] = Pos(3, 6).dump()
        actor(raw, HOME)['backpack'].append(ORDER)
        reveal(raw, truth)
        s, plan = strategy(raw, memory, Settings(enable_news=False))
        self.assertEqual(memory.enemy_weapon_sites, sites)
        self.assertTrue(s.raid_scouts.spawn_ready())
        self.assertFalse(s.raid_scouts.summon_ready())
        self.assertTrue(memory.raid_scouts['uncovered_operators'])
        s.run()
        self.assertEqual(plan.commands[str(HOME)]['action'], 'use')
        self.assertEqual(plan.commands[str(HOME)]['name'], ORDER)
        self.assertEqual(plan.rejections, [])

    def test_cached_guns_and_last_seen_worker_never_become_hidden_robot_targets(self):
        raw, truth = survey_request(near=True)
        memory = finished_tasks()
        strategy(raw, memory, Settings(enable_news=False))
        hidden = {Pos.load(u['pos']) for u in truth
                  if u['roleType'] in ('worker', 'pioneer', 'rocket', 'gatling', 'railgun')}
        raw['roundNo'] = 71
        actor(raw, SCOUT)['pos'] = Pos(3, 6).dump()
        boss = robot(30005, BASE.x + 4, BASE.y - 2, roleType='bossRobot', health=800)
        raw['teamOur']['summonRobotList'] = [boss]
        raw['robot']['roles'] = [copy.deepcopy(boss)]
        reveal(raw, truth)
        s, plan = strategy(raw, memory, Settings(enable_news=False))
        self.assertTrue(s.raid_scouts.spawn_ready())
        self.assertFalse(s.raid_scouts.summon_ready())
        s.raider.decide(s.turn.summon_robots[0])
        command = plan.commands.get('30005', {})
        self.assertIn(command.get('action'), ('move', 'attack'))
        if command.get('action') == 'attack':
            target = Pos.load(command['targetPos'][0])
            self.assertNotIn(target, hidden)
            visible = {p for u in s.turn.enemies for p in s.turn.footprint(u)}
            self.assertIn(target, visible | set(station_footprint(BASE)))
        self.assertEqual(plan.rejections, [])


if __name__ == '__main__':
    unittest.main()
