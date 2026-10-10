"""Only the first-night observing IMP avoids visible enemy catch neighbourhoods."""
import unittest

from agent.protocol import Pos, distance
from app.config import Settings
from tests.fixtures import unit
from tests.test_raid_scouts import IMP_ID, role, scout_memory, scout_request
from tests.test_worker_safety import strategy


SETTINGS = Settings(enable_first_night_defense=False)


class ScoutSurvivalTests(unittest.TestCase):
    def setup(self, raw, memory=None):
        return strategy(raw, memory or scout_memory(), SETTINGS)

    def test_imp_relocates_instead_of_holding_beside_each_enemy_role(self):
        for base, start, enemy in ((Pos(9,22), Pos(8,24), Pos(8,23)),
                                   (Pos(30,10), Pos(32,12), Pos(32,11))):
            for kind in ('worker', 'pioneer', 'imp'):
                with self.subTest(base=base, kind=kind):
                    raw = scout_request(35, enemy_base=base)
                    role(raw, IMP_ID)['pos'] = start.dump()
                    raw['teamEnemy']['roles'].append(unit(900, kind, enemy.x, enemy.y, health=500))
                    s, plan = self.setup(raw)
                    imp = next(iter(s.turn.imps()))
                    self.assertTrue(s.raid_scouts.imp(imp))
                    command = plan.commands[str(IMP_ID)]
                    self.assertEqual(command['action'], 'move')
                    destination = Pos.load(command['targetPos'][0])
                    self.assertEqual(distance(start, destination), 1)
                    self.assertGreater(distance(destination, enemy), 1)
                    self.assertNotIn(destination, s.turn.blocked(imp))

    def test_route_and_each_observed_step_avoid_the_catch_neighbours(self):
        raw = scout_request(35, enemy_base=Pos(9,22))
        role(raw, IMP_ID)['pos'] = {'x':4, 'y':21}
        catcher = Pos(6,23)
        raw['teamEnemy']['roles'].append(unit(900, 'worker', catcher.x, catcher.y, health=500))
        memory = scout_memory()
        arrived = False
        for number in range(35,56):
            raw['roundNo'] = number
            s, plan = self.setup(raw, memory)
            imp = next(iter(s.turn.imps()))
            route = s.raid_scouts.scout_route(imp)
            self.assertTrue(all(p not in route.cost for p in catcher.neighbours() if p != imp.pos))
            self.assertTrue(s.raid_scouts.imp(imp))
            command = plan.commands.get(str(IMP_ID))
            if command is None:
                self.assertEqual(memory.raid_scouts['posts'][IMP_ID]['status'], 'holding')
                self.assertGreaterEqual(distance(imp.pos, catcher), 3)
                arrived = True
                break
            self.assertEqual(command['action'], 'move')
            target = Pos.load(command['targetPos'][0])
            self.assertGreater(distance(target, catcher), 1)
            self.assertEqual(distance(imp.pos, target), 1)
            role(raw, IMP_ID)['pos'] = target.dump()
            raw['lastRoundRoleActionResults'] = {str(IMP_ID): True}
            memory.record(s.turn, plan)
        self.assertTrue(arrived)

    def test_a_previous_holding_goal_is_abandoned_when_a_catcher_approaches(self):
        raw = scout_request(35, enemy_base=Pos(9,22))
        start = Pos(8,24)
        role(raw, IMP_ID)['pos'] = start.dump()
        raw['teamEnemy']['roles'].append(unit(900, 'pioneer', 8,23, health=500))
        memory = scout_memory()
        memory.raid_scouts = {'posts':{IMP_ID:{'goal':start, 'status':'holding', 'round':34}}}
        s, plan = self.setup(raw, memory)
        s.raid_scouts.imp(next(iter(s.turn.imps())))
        self.assertNotEqual(memory.raid_scouts['posts'][IMP_ID]['goal'], start)
        self.assertEqual(plan.commands[str(IMP_ID)]['action'], 'move')

    def test_dead_enemy_does_not_force_a_safe_observer_to_move(self):
        raw = scout_request(35, enemy_base=Pos(9,22))
        role(raw, IMP_ID)['pos'] = {'x':8, 'y':24}
        raw['teamEnemy']['roles'].append(unit(900, 'worker', 8,23, health=0))
        s, plan = self.setup(raw)
        imp = next(iter(s.turn.imps()))
        self.assertTrue(s.raid_scouts.imp(imp))
        self.assertNotIn(str(IMP_ID), plan.commands)
        self.assertIn(IMP_ID, plan.used)
        self.assertEqual(s.memory.raid_scouts['posts'][IMP_ID]['status'], 'holding')

    def test_catch_safe_post_still_observes_a_real_rear_weapon_and_avoids_spawns(self):
        raw = scout_request(35, enemy_base=Pos(9,22))
        role(raw, IMP_ID)['pos'] = {'x':8, 'y':24}
        raw['teamEnemy']['roles'] += [unit(900, 'worker', 8,23, health=500),
                                     unit(901, 'rocket', 8,22, health=1000)]
        memory = scout_memory()
        spawns = {Pos(6,22), Pos(6,21)}
        memory.boss_raid.update(spawn=Pos(6,21), spawns=list(spawns))
        memory.pending_summon_positions = set(spawns)
        s, plan = self.setup(raw, memory)
        imp = next(iter(s.turn.imps()))
        post = s.raid_scouts.post(imp)
        self.assertNotIn(post, spawns)
        self.assertGreaterEqual(distance(post, Pos(8,23)), 3)
        self.assertLessEqual(distance(post, Pos(8,22)), 4)
        self.assertGreater(sum(distance(post,p)<=4 for p in s.raid_scouts.watch_cells()), 0)
        s.raid_scouts.imp(imp)
        self.assertNotIn(Pos.load(plan.commands[str(IMP_ID)]['targetPos'][0]), spawns)

    def test_an_available_safe_escape_is_not_replaced_by_mining_or_idle(self):
        raw = scout_request(35, enemy_base=Pos(9,22))
        start, escape = Pos(8,24), Pos(7,25)
        role(raw, IMP_ID)['pos'] = start.dump()
        raw['teamEnemy']['roles'].append(unit(900, 'worker', 8,23, health=500))
        raw['mapInfo']['zones'] += [{'neutralType':'stone', 'pos':p.dump()}
            for p in start.neighbours() if p != escape and p != Pos(8,23)]
        s, plan = self.setup(raw)
        s.raid_scouts.imp(next(iter(s.turn.imps())))
        self.assertEqual(plan.commands[str(IMP_ID)], {'action':'move', 'targetPos':[escape.dump()]})

    def test_second_day_original_imp_destroy_policy_is_not_given_catch_avoidance(self):
        raw = scout_request(131)
        role(raw, IMP_ID)['pos'] = {'x':33, 'y':12}
        raw['teamEnemy']['roles'].append(unit(900, 'worker', 32,12, health=500))
        raw['mapInfo']['zones'].append({'neutralType':'iron', 'pos':{'x':33,'y':11}})
        s, plan = self.setup(raw)
        self.assertFalse(s.raid_scouts.active)
        s.imp.decide(next(iter(s.turn.imps())))
        self.assertEqual(plan.commands[str(IMP_ID)],
                         {'action':'destroy', 'targetPos':[{'x':33,'y':11}]})


if __name__ == '__main__':
    unittest.main()
