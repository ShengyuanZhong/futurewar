"""First-night shared sight comes from heroes, with a worker kept at home."""
import copy
import unittest

from agent.protocol import Pos, Turn, distance
from app.config import Settings
from app.service.turn_service import Session, TurnService
from tests.fixtures import robot, unit
from tests.test_maintenance import fortified
from tests.test_site_blockade import GAP
from tests.test_summon_control import finished_tasks
from tests.test_worker_safety import strategy


IMP_ID, WORKER_ID, HOME_ID, BOSS_ID = 505, 504, 501, 30005


def role(raw, uid):
    return next(u for u in raw['teamOur']['roles'] if u['id'] == uid)


def scout_request(number=20, enemy_base=Pos(30, 10), boss=False):
    raw = fortified(number)
    raw['teamOur']['roles'].append(unit(IMP_ID, 'imp', 4, 12, health=500))
    role(raw, WORKER_ID)['pos'] = {'x': 32, 'y': 7}
    raw['teamEnemy']['roles'] = [unit(990, 'station', enemy_base.x, enemy_base.y)]
    raw['teamOur']['summonRobotList'] = []
    if boss:
        born = robot(BOSS_ID, 34, 10, health=800, roleType='bossRobot')
        raw['teamOur']['summonRobotList'] = [born]
        raw['robot']['roles'] = [born]
    return raw


def scout_memory():
    memory = finished_tasks()
    memory.boss_raid = {'status': 'deployed', 'spawn': Pos(34, 10), 'summon_round': 10}
    return memory


def ready_roles(raw):
    s, _ = strategy(raw, scout_memory())
    for uid in (IMP_ID, WORKER_ID):
        actor = next(u for u in s.turn.controllable() if u.unit_id == uid)
        role(raw, uid)['pos'] = s.raid_scouts.post(actor).dump()


class RaidScoutTests(unittest.TestCase):
    def test_daytime_breach_returns_assigned_observer_to_construction(self):
        raw, memory = scout_request(), scout_memory()
        strategy(raw, memory)
        self.assertEqual(memory.raid_scouts['worker_id'], WORKER_ID)
        raw['roundNo'] = 21
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType'] == 'wall' and u['pos'] == GAP.dump())]
        role(raw, WORKER_ID).update(pos={'x':8,'y':7}, backpack=['stone'])
        s, plan = strategy(raw, memory)
        worker = next(w for w in s.turn.workers() if w.unit_id == WORKER_ID)
        self.assertFalse(s.raid_scouts.is_worker(worker))
        s.run()
        self.assertEqual(plan.commands[str(WORKER_ID)],
            {'action':'build','name':'wall','targetPos':[GAP.dump()]})
        self.assertEqual(memory.raid_scouts['worker_id'], WORKER_ID)

    def test_actual_wall_completion_and_three_weapons_gate_worker_departure(self):
        for missing in ('wall', 'weapon', 'none'):
            with self.subTest(missing=missing):
                raw = scout_request()
                if missing == 'wall':
                    raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
                        if not (u['roleType'] == 'wall' and u['pos'] == GAP.dump())]
                elif missing == 'weapon':
                    weapon = next(u for u in raw['teamOur']['roles'] if u['roleType'] == 'rocket')
                    raw['teamOur']['roles'].remove(weapon)
                memory = scout_memory()
                s, _ = strategy(raw, memory)
                self.assertTrue(s.raid_scouts.active)
                self.assertEqual(s.raid_scouts.walls_ready(), missing == 'none')
                self.assertEqual(memory.raid_scouts.get('worker_id') is not None, missing == 'none')
                self.assertTrue(s.raid_scouts.imp(next(iter(s.turn.imps()))))

    def test_unbuilt_temporary_wall_and_empty_wall_configuration_are_not_ready(self):
        raw = scout_request()
        s, _ = strategy(raw, scout_memory())
        self.assertTrue(s.raid_scouts.walls_ready())
        s.site_guard.temporary_needed.add(Pos(10, 7))
        self.assertFalse(s.raid_scouts.walls_ready())
        s, _ = strategy(raw, scout_memory(), Settings(allow_base_surroundings=False))
        self.assertFalse(s.raid_scouts.walls_ready())

    def test_submitted_last_wall_does_not_release_worker_before_next_observation(self):
        raw = scout_request(35)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType'] == 'wall' and u['pos'] == GAP.dump())]
        role(raw, WORKER_ID).update(pos={'x': 8, 'y': 7}, backpack=['stone'])
        memory = scout_memory()
        s, plan = strategy(raw, memory); s.run()
        self.assertNotIn('worker_id', memory.raid_scouts)
        self.assertTrue(any(c.get('action') == 'build' and c.get('name') == 'wall'
                            and c.get('targetPos') == [GAP.dump()] for c in plan.commands.values()))
        raw['roundNo'] = 36
        raw['teamOur']['roles'].append(unit(2001, 'wall', GAP.x, GAP.y))
        s, _ = strategy(raw, memory)
        self.assertTrue(s.raid_scouts.walls_ready())
        self.assertIsNotNone(memory.raid_scouts.get('worker_id'))

    def test_left_and_right_posts_cover_weapon_neighbourhood_and_avoid_spawn(self):
        for base, imp_post, worker_post in ((Pos(9, 22), Pos(5, 24), Pos(5, 20)),
                                           (Pos(30, 10), Pos(35, 12), Pos(35, 8))):
            with self.subTest(base=base):
                raw = scout_request(enemy_base=base)
                memory = scout_memory(); memory.boss_raid['spawn'] = Pos(base.x-3 if base.x<20 else base.x+4, base.y)
                s, _ = strategy(raw, memory)
                imp = next(iter(s.turn.imps()))
                worker = next(w for w in s.turn.workers() if w.unit_id == WORKER_ID)
                self.assertEqual(s.raid_scouts.preferred(imp), imp_post)
                self.assertEqual(s.raid_scouts.preferred(worker), worker_post)
                posts = (s.raid_scouts.post(imp), s.raid_scouts.post(worker))
                self.assertTrue(all(any(distance(post, p) <= 4 for post in posts)
                                    for p in s.raid_scouts.watch_cells()))
                for post in posts:
                    self.assertNotEqual(post, memory.boss_raid['spawn'])
                self.assertEqual([u.kind for u in s.turn.enemies], ['station'])

    def test_worker_and_home_id_remain_stable_when_relative_distances_change(self):
        raw, memory = scout_request(), scout_memory()
        s, _ = strategy(raw, memory)
        self.assertEqual(memory.raid_scouts['worker_id'], WORKER_ID)
        self.assertEqual(memory.raid_scouts['home_worker_id'], HOME_ID)
        raw['roundNo'] = 21
        role(raw, HOME_ID)['pos'] = {'x': 35, 'y': 9}
        role(raw, WORKER_ID)['pos'] = {'x': 4, 'y': 5}
        s, _ = strategy(raw, memory)
        self.assertEqual(memory.raid_scouts['worker_id'], WORKER_ID)
        self.assertEqual(memory.raid_scouts['home_worker_id'], HOME_ID)
        self.assertFalse(s.raid_scouts.is_worker(next(w for w in s.turn.workers() if w.unit_id == HOME_ID)))

    def test_home_worker_keeps_site_blockade_priority(self):
        raw, memory = scout_request(), scout_memory()
        strategy(raw, memory)
        raw['roundNo'] = 71
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType'] == 'wall' and u['pos'] == GAP.dump())]
        role(raw, HOME_ID).update(pos={'x': 8, 'y': 7}, backpack=['stone'])
        ready_roles(raw)
        raw['teamEnemy']['roles'].append(unit(901, 'worker', GAP.x, GAP.y, health=500))
        memory.wall_blockades[GAP] = {'enemy_id': 901, 'confirmed_round': 65}
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(memory.blockade_worker_id, HOME_ID)
        self.assertEqual(s.coordinator.job(next(w for w in s.turn.workers() if w.unit_id == HOME_ID))['kind'],
                         'blockade_watch')
        self.assertIn(HOME_ID, plan.used)
        self.assertEqual(memory.raid_scouts['worker_id'], WORKER_ID)
        self.assertEqual(memory.worker_tasks[WORKER_ID]['kind'], 'raid_scout')

    def test_observers_have_separate_goals_and_legal_distinct_steps(self):
        raw, memory = scout_request(), scout_memory()
        role(raw, IMP_ID)['pos'] = {'x': 33, 'y': 11}
        role(raw, WORKER_ID)['pos'] = {'x': 33, 'y': 9}
        s, plan = strategy(raw, memory); s.run()
        posts = memory.raid_scouts['posts']
        self.assertNotEqual(posts[IMP_ID]['goal'], posts[WORKER_ID]['goal'])
        moves = [Pos.load(plan.commands[str(uid)]['targetPos'][0]) for uid in (IMP_ID, WORKER_ID)]
        self.assertNotEqual(moves[0], moves[1])
        for uid, target in zip((IMP_ID, WORKER_ID), moves):
            actor = next(u for u in s.turn.controllable() if u.unit_id == uid)
            self.assertEqual(distance(actor.pos, target), 1)
            self.assertNotIn(target, s.turn.blocked(actor))
            self.assertNotEqual(target, memory.boss_raid['spawn'])

    def test_reached_posts_hold_without_mining_destroying_or_redundant_moving(self):
        raw, memory = scout_request(), scout_memory()
        ready_roles(raw)
        worker_pos, imp_pos = Pos.load(role(raw, WORKER_ID)['pos']), Pos.load(role(raw, IMP_ID)['pos'])
        raw['mapInfo']['zones'] += [{'neutralType': 'iron', 'pos': Pos(worker_pos.x, worker_pos.y-1).dump()},
                                   {'neutralType': 'stone', 'pos': Pos(imp_pos.x, imp_pos.y+1).dump()}]
        s, plan = strategy(raw, memory); s.run()
        for uid in (IMP_ID, WORKER_ID):
            self.assertIn(uid, plan.used)
            self.assertNotIn(str(uid), plan.commands)
            self.assertEqual(memory.raid_scouts['posts'][uid]['status'], 'holding')
        self.assertEqual(memory.worker_tasks[WORKER_ID]['kind'], 'raid_scout')

    def test_night_keeps_view_region_even_when_robots_threaten_preferred_post(self):
        raw, memory = scout_request(70), scout_memory()
        ready_roles(raw)
        s, plan = strategy(raw, memory); s.run()
        raw['roundNo'] = 71
        raw['robot']['roles'] = [robot(900, 35, 9)]
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(memory.raid_scouts['worker_id'], WORKER_ID)
        self.assertEqual(memory.worker_tasks[WORKER_ID]['kind'], 'raid_scout')
        goals = [memory.raid_scouts['posts'][uid]['goal'] for uid in (IMP_ID, WORKER_ID)]
        for goal in goals:
            self.assertGreater(goal.x, 31)
        self.assertTrue(all(any(distance(goal, p) <= 4 for goal in goals)
                            for p in s.raid_scouts.watch_cells()))
        self.assertNotIn(plan.commands.get(str(WORKER_ID), {}).get('action'), ('collect', 'sell', 'buy'))

    def test_second_day_restores_worker_mining_and_imp_destruction(self):
        raw, memory = scout_request(70), scout_memory()
        ready_roles(raw)
        s, plan = strategy(raw, memory); s.run()
        raw['roundNo'] = 131
        raw['teamOur']['goldNum'] = 0
        worker_pos, imp_pos = Pos.load(role(raw, WORKER_ID)['pos']), Pos.load(role(raw, IMP_ID)['pos'])
        raw['mapInfo']['zones'] += [{'neutralType': 'iron', 'pos': Pos(worker_pos.x, worker_pos.y-1).dump()},
                                   {'neutralType': 'stone', 'pos': Pos(imp_pos.x, imp_pos.y-1).dump()}]
        s, plan = strategy(raw, memory); s.run()
        self.assertFalse(s.raid_scouts.active)
        self.assertEqual(memory.raid_scouts, {})
        self.assertEqual(plan.commands[str(IMP_ID)]['action'], 'destroy')
        self.assertEqual(plan.commands[str(WORKER_ID)]['action'], 'collect')
        self.assertNotEqual(memory.worker_tasks[WORKER_ID]['kind'], 'raid_scout')

    def test_dead_observer_never_reassigns_the_only_live_home_worker(self):
        raw, memory = scout_request(), scout_memory()
        strategy(raw, memory)
        raw['roundNo'] = 21
        role(raw, WORKER_ID)['health'] = 0
        s, plan = strategy(raw, memory); s.run()
        self.assertEqual(memory.raid_scouts['worker_id'], WORKER_ID)
        self.assertEqual(memory.raid_scouts['home_worker_id'], HOME_ID)
        self.assertFalse(s.raid_scouts.is_worker(next(iter(s.turn.workers()))))
        self.assertNotEqual(memory.worker_tasks[HOME_ID]['kind'], 'raid_scout')

    def test_unreachable_routes_and_late_eta_do_not_assign_a_worker(self):
        for mode in ('blocked', 'too_late'):
            with self.subTest(mode=mode):
                raw = scout_request(70 if mode == 'too_late' else 20)
                role(raw, HOME_ID)['pos'] = {'x': 0, 'y': 0}
                role(raw, WORKER_ID)['pos'] = {'x': 0, 'y': 3}
                if mode == 'blocked':
                    for centre in (Pos(0, 0), Pos(0, 3)):
                        raw['mapInfo']['zones'] += [{'neutralType': 'vendor', 'pos': p.dump()}
                            for p in centre.neighbours() if 0 <= p.x < 41 and 0 <= p.y < 32]
                s, _ = strategy(raw, scout_memory())
                self.assertTrue(s.raid_scouts.walls_ready())
                self.assertNotIn('worker_id', s.raid_scouts.state)
                self.assertEqual(s.raid_scouts.state['worker_status'], 'unreachable_or_too_late')

    def test_disabled_switch_clears_scout_state_and_resumes_imp_strategy(self):
        raw, memory = scout_request(), scout_memory()
        ready_roles(raw)
        s, plan = strategy(raw, memory); s.run()
        raw['roundNo'] = 21
        imp_pos = Pos.load(role(raw, IMP_ID)['pos'])
        raw['mapInfo']['zones'].append({'neutralType': 'stone', 'pos': Pos(imp_pos.x, imp_pos.y-1).dump()})
        s, plan = strategy(raw, memory, Settings(enable_boss_raid=False)); s.run()
        self.assertEqual(memory.raid_scouts, {})
        self.assertEqual(plan.commands[str(IMP_ID)]['action'], 'destroy')
        self.assertNotEqual(memory.worker_tasks[WORKER_ID]['kind'], 'raid_scout')

    def test_seen_boss_disappearing_releases_and_does_not_restart_next_frame(self):
        raw, memory = scout_request(70), scout_memory()
        ready_roles(raw)
        strategy(raw, memory)
        raw['roundNo'] = 71
        boss = robot(BOSS_ID, 34, 10, health=800, roleType='bossRobot')
        raw['teamOur']['summonRobotList'] = [boss]
        raw['robot']['roles'] = [boss]
        s, _ = strategy(raw, memory)
        self.assertTrue(s.raid_scouts.active)
        raw['teamOur']['summonRobotList'] = []; raw['robot']['roles'] = []
        for number in (72, 73):
            raw['roundNo'] = number
            s, _ = strategy(raw, memory)
            self.assertFalse(s.raid_scouts.active)
            self.assertTrue(memory.raid_scouts['finished'])
            self.assertNotIn('worker_id', memory.raid_scouts)

    def test_same_frame_service_cache_does_not_repeat_scout_progress(self):
        raw = scout_request()
        service = TurnService(Settings(enable_news=False))
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        service.sessions[key] = Session(memory=scout_memory())
        response = service.decide(copy.deepcopy(raw))
        before = copy.deepcopy(service.sessions[key].memory)
        repeated = service.decide(copy.deepcopy(raw))
        self.assertEqual(response, repeated)
        self.assertEqual(service.sessions[key].memory, before)

    def test_real_shared_hero_sight_reveals_operator_without_boss_sight(self):
        blind = scout_request(71, boss=True)
        role(blind, WORKER_ID)['pos'] = {'x': 4, 'y': 5}
        s, plan = strategy(blind, scout_memory())
        s.raider.decide(s.turn.summon_robots[0])
        self.assertEqual([u.kind for u in s.turn.enemies], ['station'])
        self.assertEqual(s.memory.robot_raids[BOSS_ID]['stage'], 'base')
        self.assertNotIn('controller_id', s.memory.robot_raids[BOSS_ID])
        raw, memory = scout_request(), scout_memory()
        role(raw, WORKER_ID)['pos'] = {'x': 4, 'y': 5}
        truth = [unit(991, 'gatling', 29, 11), unit(993, 'railgun', 29, 8),
                 unit(994, 'rocket', 31, 11), unit(992, 'worker', 28, 11, health=500),
                 unit(995, 'pioneer', 28, 8, health=200)]
        revealed = False
        attacked = False
        for number in range(20, 91):
            raw['roundNo'] = number
            # Ground truth is deliberately hidden unless an actual hero sees it.
            observers = [Pos.load(u['pos']) for u in raw['teamOur']['roles']
                         if u['health'] > 0 and u['roleType'] in ('worker', 'pioneer', 'imp')]
            visible = [copy.deepcopy(u) for u in truth
                       if any(distance(origin, Pos.load(u['pos'])) <= 4 for origin in observers)]
            raw['teamEnemy']['roles'] = [unit(990, 'station', 30, 10)] + visible
            if number == 20:
                self.assertEqual(visible, [])
            revealed = revealed or any(u['id'] == 992 for u in visible)
            if number == 71:
                boss = robot(BOSS_ID, 34, 10, health=800, roleType='bossRobot')
                raw['teamOur']['summonRobotList'] = [boss]; raw['robot']['roles'] = [boss]
            # Isolate shared-sight behaviour from the default four-step siege fallback.
            s, plan = strategy(raw, memory, Settings(boss_controller_max_walk=30))
            imp = next(iter(s.turn.imps()))
            s.raid_scouts.imp(imp)
            scout = next(w for w in s.turn.workers() if s.raid_scouts.is_worker(w))
            s.raid_scouts.worker(scout)
            if number >= 71:
                s.raider.decide(s.turn.summon_robots[0])
                self.assertEqual(memory.robot_raids[BOSS_ID]['stage'], 'controller')
                command = plan.commands[str(BOSS_ID)]
                if command['action'] == 'attack':
                    self.assertIn(memory.robot_raids[BOSS_ID]['controller_id'], (992, 995))
                    self.assertIn(command['targetPos'][0], [u['pos'] for u in visible
                                                          if u['roleType'] in ('worker', 'pioneer')])
                    attacked = True
                    break
            for uid in (IMP_ID, scout.unit_id) + ((BOSS_ID,) if number >= 71 else ()):
                command = plan.commands.get(str(uid))
                if command:
                    self.assertEqual(command['action'], 'move')
                    actor = raw['teamOur']['summonRobotList'][0] if uid == BOSS_ID else role(raw, uid)
                    origin = Pos.load(actor['pos'])
                    destination = Pos.load(command['targetPos'][0])
                    self.assertEqual(distance(origin, destination), 1)
                    actor['pos'] = destination.dump()
            memory.record(s.turn, plan)
        self.assertTrue(revealed)
        self.assertTrue(attacked)
        self.assertEqual(memory.raid_scouts['posts'][IMP_ID]['status'], 'holding')
        self.assertEqual(memory.raid_scouts['posts'][scout.unit_id]['status'], 'holding')


if __name__ == '__main__':
    unittest.main()
