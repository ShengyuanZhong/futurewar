"""Direct/cheap cannon crews take priority; costly routes may attack the base."""
import unittest

from agent.protocol import Pos, TOWER_TYPES
from tests.fixtures import unit
from tests.test_boss_raid import update_robot
from tests.test_summon_control import finished_tasks, raid_request
from tests.test_worker_safety import strategy


BOSS_ID = 30005


def decide(raw, memory=None):
    """Exercise the independent robot policy through its normal action gate."""
    s, plan = strategy(raw, memory or finished_tasks())
    s.raider.decide(s.turn.summon_robots[0])
    return s, plan


class RaidPriorityTests(unittest.TestCase):
    def assert_attack(self, plan, x, y):
        self.assertEqual(plan.commands[str(BOSS_ID)],
                         {'action': 'attack', 'targetPos': [{'x': x, 'y': y}]})
        self.assertEqual(plan.rejections, [])

    def test_workers_and_pioneers_beside_each_weapon_override_base(self):
        for weapon in TOWER_TYPES:
            for role in ('worker', 'pioneer'):
                for target in Pos(35, 27).neighbours():
                    with self.subTest(weapon=weapon, role=role, target=target):
                        raw = raid_request(71, boss=True)
                        # Stand outside this neighbour, so the weapon is not
                        # between the BOSS and the role in the direct-shot case.
                        dx, dy = target.x-35, target.y-27
                        update_robot(raw, {'x':target.x+(1 if dx>0 else -1 if dx<0 else 0),
                                           'y':target.y+(1 if dy>0 else -1 if dy<0 else 0)})
                        raw['teamEnemy']['roles'] = [unit(990, 'station', 31, 23),
                            unit(991, weapon, 35, 27), unit(992, role, target.x, target.y)]
                        s, plan = decide(raw)
                        self.assert_attack(plan, target.x, target.y)
                        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'controller')

    def test_old_controller_leaves_weapon_and_new_worker_takes_priority(self):
        raw = raid_request(71, boss=True)
        memory = finished_tasks()
        s, plan = decide(raw, memory); memory.record(s.turn, plan)
        self.assert_attack(plan, 36, 25)
        raw['roundNo'] = 72
        raw['teamEnemy']['roles'][2]['pos'] = {'x': 36, 'y': 20}
        raw['teamEnemy']['roles'].append(unit(994, 'worker', 36, 25, health=40))
        s, plan = decide(raw, memory)
        self.assert_attack(plan, 36, 25)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['controller_id'], 994)

    def test_failed_shot_at_departed_pioneer_does_not_blacklist_new_worker(self):
        raw = raid_request(71, boss=True)
        memory = finished_tasks()
        s, plan = decide(raw, memory); memory.record(s.turn, plan)
        self.assert_attack(plan, 36, 25)
        raw['roundNo'] = 72
        raw['lastRoundRoleActionResults'] = {str(BOSS_ID): False}
        raw['teamEnemy']['roles'][2]['pos'] = {'x': 36, 'y': 20}
        raw['teamEnemy']['roles'].append(unit(994, 'worker', 36, 25, health=40))
        s, plan = decide(raw, memory)
        self.assert_attack(plan, 36, 25)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['controller_id'], 994)

    def test_departed_controller_is_released_when_base_is_attackable(self):
        raw = raid_request(71, boss=True)
        memory = finished_tasks()
        s, plan = decide(raw, memory); memory.record(s.turn, plan)
        raw['roundNo'] = 72
        raw['teamEnemy']['roles'][2]['pos'] = {'x': 36, 'y': 20}
        update_robot(raw, {'x': 36, 'y': 24})
        s, plan = decide(raw, memory)
        self.assert_attack(plan, 34, 24)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'base')

    def test_current_health_and_healing_keep_operator_alive(self):
        raw = raid_request(71, boss=True)
        memory = finished_tasks()
        for number, health in ((71, 40), (72, 200), (73, 160)):
            raw['roundNo'] = number
            raw['teamEnemy']['roles'][2]['health'] = health
            s, plan = decide(raw, memory)
            self.assert_attack(plan, 36, 25)
            self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'controller')
            memory.record(s.turn, plan)

    def test_dead_controller_does_not_unlock_base_while_worker_remains(self):
        raw = raid_request(71, boss=True)
        memory = finished_tasks()
        s, plan = decide(raw, memory); memory.record(s.turn, plan)
        raw['roundNo'] = 72
        raw['teamEnemy']['roles'][2]['health'] = 0
        raw['teamEnemy']['roles'].append(unit(994, 'worker', 36, 26, health=80))
        s, plan = decide(raw, memory)
        self.assert_attack(plan, 36, 26)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'controller')

    def test_healed_locked_pioneer_yields_to_a_direct_worker_with_forty_hp(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'][2]['health'] = 40
        memory = finished_tasks()
        s, plan = decide(raw, memory); memory.record(s.turn, plan)
        self.assert_attack(plan, 36, 25)
        raw['roundNo'] = 72
        raw['teamEnemy']['roles'][2]['health'] = 500
        raw['teamEnemy']['roles'].append(unit(994, 'worker', 36, 26, health=40))
        s, plan = decide(raw, memory)
        self.assert_attack(plan, 36, 26)
        self.assertEqual(memory.robot_raids[BOSS_ID]['controller_id'], 994)
        self.assertEqual(set(memory.robot_raids[BOSS_ID]['operator_snapshot']),
                         {(992, 500), (994, 40)})

    def test_base_waits_until_all_current_cannon_crew_are_confirmed_dead(self):
        raw = raid_request(71, boss=True)
        update_robot(raw, {'x': 36, 'y': 25})
        raw['teamEnemy']['roles'] = [unit(990, 'station', 33, 25),
            unit(991, 'rocket', 35, 27), unit(992, 'pioneer', 36, 27, health=40),
            unit(994, 'worker', 36, 28, health=80)]
        memory = finished_tasks()
        for number, pioneer_hp, worker_hp, target, stage in (
                (71, 40, 80, Pos(36, 27), 'controller'),
                (72, 0, 40, Pos(36, 28), 'controller'),
                (73, 0, 0, Pos(34, 24), 'base')):
            raw['roundNo'] = number
            raw['teamEnemy']['roles'][2]['health'] = pioneer_hp
            raw['teamEnemy']['roles'][3]['health'] = worker_hp
            s, plan = decide(raw, memory)
            self.assert_attack(plan, target.x, target.y)
            self.assertEqual(memory.robot_raids[BOSS_ID]['stage'], stage)
            self.assertEqual(set(memory.robot_raids[BOSS_ID]['operator_snapshot']),
                             {(992, pioneer_hp), (994, worker_hp)})
            memory.record(s.turn, plan)
        self.assertNotIn('controller_id', memory.robot_raids[BOSS_ID])

    def test_operator_returning_during_base_attack_preempts_base(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'][2]['health'] = 0
        update_robot(raw, {'x': 36, 'y': 24})
        memory = finished_tasks()
        s, plan = decide(raw, memory)
        self.assert_attack(plan, 34, 24)
        memory.record(s.turn, plan)
        raw['roundNo'] = 72
        raw['teamEnemy']['roles'][2].update(health=200, pos={'x': 36, 'y': 26})
        s, plan = decide(raw, memory)
        self.assert_attack(plan, 36, 26)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'controller')

    def test_imp_beside_weapon_is_not_a_cannon_crew_target(self):
        raw = raid_request(71, boss=True)
        update_robot(raw, {'x': 36, 'y': 24})
        raw['teamEnemy']['roles'][2] = unit(992, 'imp', 36, 26, health=40)
        s, plan = decide(raw)
        self.assert_attack(plan, 34, 24)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'base')

    def test_pioneer_near_rear_but_away_from_weapons_is_not_pursued(self):
        raw = raid_request(71, boss=True)
        update_robot(raw, {'x': 36, 'y': 24})
        raw['teamEnemy']['roles'][2]['pos'] = {'x': 36, 'y': 21}
        s, plan = decide(raw)
        self.assert_attack(plan, 34, 24)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'base')

    def test_direct_worker_preempts_previously_locked_screened_pioneer(self):
        raw = raid_request(71, boss=True)
        memory = finished_tasks()
        s, plan = decide(raw, memory); memory.record(s.turn, plan)
        raw['roundNo'] = 72
        for uid, pos in enumerate(Pos(36, 25).neighbours(), 1001):
            raw['teamEnemy']['roles'].append(unit(uid, 'wall', pos.x, pos.y, health=40))
        raw['teamEnemy']['roles'] += [unit(1101, 'railgun', 38, 28),
                                     unit(1102, 'worker', 39, 28, health=40)]
        s, plan = decide(raw, memory)
        self.assert_attack(plan, 39, 28)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['controller_id'], 1102)

    def test_inaccessible_live_operator_falls_back_to_the_exposed_base_cell(self):
        raw = raid_request(71, boss=True)
        update_robot(raw, {'x': 36, 'y': 25})
        raw['teamEnemy']['roles'] = [unit(990, 'station', 33, 25),
            unit(991, 'rocket', 10, 10), unit(992, 'worker', 10, 11, health=40)]
        # NPC squares cannot be traversed or attacked. The robot is enclosed,
        # while the base remains within range and has no intervening wall.
        raw['mapInfo']['zones'] += [{'neutralType': 'vendor', 'pos': p.dump()}
                                   for p in Pos(36, 25).neighbours()]
        s, plan = decide(raw)
        self.assert_attack(plan, 34, 24)
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['fallback_reason'],'controller_unreachable')
        self.assertEqual(plan.rejections, [])
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['operator_snapshot'], ((992, 40),))

    def test_no_visible_operator_goes_directly_to_base_without_scout_stage(self):
        raw = raid_request(71, boss=True)
        raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:2]
        s, plan = decide(raw)
        self.assertEqual(plan.commands[str(BOSS_ID)]['action'], 'move')
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'base')
        self.assertEqual(plan.rejections, [])

    def test_hidden_old_operator_is_not_shot_or_scouted_at_stale_position(self):
        raw = raid_request(71, boss=True)
        memory = finished_tasks()
        s, plan = decide(raw, memory); memory.record(s.turn, plan)
        raw['roundNo'] = 72
        raw['teamEnemy']['roles'] = raw['teamEnemy']['roles'][:2]
        s, plan = decide(raw, memory)
        self.assertEqual(plan.commands[str(BOSS_ID)]['action'], 'move')
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'base')
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['operator_snapshot'], ())
        self.assertNotIn('controller_id', s.memory.robot_raids[BOSS_ID])
        self.assertEqual(plan.rejections, [])


if __name__ == '__main__':
    unittest.main()
