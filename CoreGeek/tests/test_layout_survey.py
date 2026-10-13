"""Real worker sight gates BOSS deployment and observed layouts shape placement.

These synthetic maps apply range-four friendly sight to private ground truth.
Summoned robots never reveal an enemy gun or character for the tests.
"""
import copy
import unittest

from agent.protocol import CONTROLLABLE_TYPES, TOWER_TYPES, Pos, Turn, Unit, distance, station_footprint
from agent.robot_combat import blocking_wall, clear_attack, planning_building_blocker
from agent.summoning import (enemy_layout_ready, enemy_weapon_cells, layout_operator_positions,
                            scouted_spawn_position, summon_cell_legal)
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import Session, TurnService
from tests.fixtures import robot, unit
from tests.test_maintenance import fortified
from tests.test_summon_control import ORDER, finished_tasks
from tests.test_worker_safety import strategy


SCOUT, HOME, PIONEER = 504, 501, 502
BASE = Pos(17, 17)


def actor(raw, uid):
    return next(u for u in raw['teamOur']['roles'] if u['id'] == uid)


def enemy_blueprint(pattern='corner_gap', base=BASE, mirror_x=False, mirror_y=False):
    """Four supplied drawings expressed relative to a two-by-two base.

    The closed corner pictures both need a wall breach. The second drawing
    has a lower-right opening; the fourth has three vertical guns and a gap
    occupied by the operator. Reflection includes the full base footprint.
    """
    guns = ((1, 1), (2, 1), (2, -1))
    operator = (2, 0)
    gaps = {(3, -1)} if pattern == 'corner_gap' else set()
    if pattern == 'vertical_gap':
        guns, operator, gaps = ((2, 1), (2, 0), (2, -1)), (3, 0), {(3, 0)}
    walls = {(x, y) for x in range(-2, 4) for y in (-3, 2)}
    walls |= {(x, y) for x in (-2, 3) for y in range(-2, 2)}
    result = [unit(990, 'station', base.x, base.y)]
    result += [unit(991 + i, kind, base.x + dx, base.y + dy, health=1000)
               for i, ((dx, dy), kind) in enumerate(zip(guns, TOWER_TYPES))]
    result += [unit(994, 'worker', base.x + operator[0], base.y + operator[1], health=500)]
    result += [unit(1100 + i, 'wall', base.x + dx, base.y + dy, health=1000)
               for i, (dx, dy) in enumerate(sorted(walls - gaps))]
    for item in result:
        x, y = item['pos']['x'], item['pos']['y']
        if mirror_x:
            item['pos']['x'] = 39 - x if item['roleType'] == 'station' else 40 - x
        if mirror_y:
            item['pos']['y'] = 32 - y if item['roleType'] == 'station' else 31 - y
    return result


def reveal(raw, truth):
    """Return only actual ordinary friendly sight plus global base/wall."""
    turn = Turn.load(raw)
    origins = [u.pos for u in turn.ours if u.health > 0
               and u.kind in CONTROLLABLE_TYPES + TOWER_TYPES + ('station', 'wall')]
    raw['teamEnemy']['roles'] = [copy.deepcopy(u) for u in truth
        if u['roleType'] in ('station', 'wall')
        or any(distance(p, Pos.load(u['pos'])) <= 4 for p in origins)]
    return raw


def survey_request(number=20, pattern='corner_gap', near=False):
    raw = fortified(number)
    raw['teamOur']['summonRobotList'] = []
    raw['weaponShopList'].append({'name': ORDER, 'price': 120})
    raw['teamOur']['goldNum'] = 240
    actor(raw, PIONEER)['pos'] = Pos(3, 6).dump()
    actor(raw, HOME).update(pos=Pos(3, 7).dump(), backpack=['stone']+['WallFixer'] * 5)
    actor(raw, SCOUT)['pos'] = (Pos(21, 17) if near else Pos(3, 6)).dump()
    truth = enemy_blueprint(pattern)
    reveal(raw, truth)
    return raw, truth


class LayoutSurveyTests(unittest.TestCase):
    def test_wall_completion_releases_scout_before_weapon_upgrades_and_repair_stock(self):
        raw, _ = survey_request()
        actor(raw, HOME)['backpack'] = []
        s, plan = strategy(raw, GameMemory(opening_complete=True), Settings(enable_news=False))
        self.assertFalse(s.first_defense.weapon_ready())
        self.assertFalse(s.first_defense.planned_inventory()["WallFixer"])
        self.assertTrue(s.raid_scouts.walls_ready())
        self.assertEqual(s.raid_scouts.state['worker_id'], SCOUT)
        s.run()
        self.assertEqual(s.memory.worker_tasks[SCOUT]['kind'], 'raid_scout')
        self.assertEqual(plan.commands[str(SCOUT)]['action'], 'move')

    def test_last_wall_command_is_not_actual_construction_completion(self):
        raw, _ = survey_request()
        actor(raw,HOME).update(pos=Pos(3,7).dump(),backpack=['stone']+['WallFixer']*5)
        memory = finished_tasks(1)
        initial, _ = strategy(raw, memory, Settings(enable_news=False))
        missing = Pos(9, 6)
        self.assertIn(missing, initial.wall_schedule.state['arcs'][SCOUT])
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles']
            if not (u['roleType'] == 'wall' and u['pos'] == missing.dump())]
        actor(raw, SCOUT).update(pos=Pos(10, 6).dump(), backpack=['stone'])
        memory.raid_scouts.pop('construction_verified_round',None)
        memory.raid_scouts.pop('personal_dispatch_round',None)
        memory.raid_scouts.pop('worker_id',None)
        memory.sealed_home['wall_schedule'].pop('released',None)
        s, plan = strategy(raw, memory, Settings(enable_news=False)); s.run()
        self.assertFalse(s.raid_scouts.walls_ready())
        self.assertNotIn('worker_id', memory.raid_scouts)
        self.assertTrue(any(c['action'] == 'build' and c['targetPos'] == [missing.dump()]
                            for c in plan.commands.values()))
        raw['roundNo'] += 1
        raw['teamOur']['roles'].append(unit(790, 'wall', missing.x, missing.y, health=1000))
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        self.assertEqual(s.raid_scouts.state['worker_id'], SCOUT)

    def test_global_enemy_walls_and_base_do_not_complete_layout(self):
        raw, _ = survey_request()
        s, _ = strategy(raw, finished_tasks(2), Settings(enable_news=False))
        self.assertEqual(s.raid_scouts.state['surveyed_count'], 0)
        self.assertEqual(s.raid_scouts.known_weapons(), ())
        self.assertFalse(s.raid_scouts.summon_ready())
        self.assertFalse(s.raid_scouts.state['layout_ready'])

    def test_global_boss_at_enemy_base_is_not_a_scout(self):
        raw, truth = survey_request(71)
        boss = robot(30005, BASE.x + 4, BASE.y, roleType='bossRobot', health=800)
        raw['teamOur']['summonRobotList'] = [boss]
        raw['robot']['roles'] = [copy.deepcopy(boss)]
        reveal(raw, truth)
        memory = finished_tasks(2)
        memory.boss_raid = {'status': 'deployed', 'spawn': Pos.load(boss['pos']), 'summon_round': 70}
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        self.assertEqual(s.raid_scouts.state['surveyed_count'], 0)
        self.assertEqual(s.raid_scouts.known_weapons(), ())
        self.assertFalse(s.raid_scouts.summon_ready())

    def test_three_actual_guns_complete_layout_without_assuming_other_sites_empty(self):
        raw, _ = survey_request(near=True)
        s, _ = strategy(raw, finished_tasks(2), Settings(enable_news=False))
        self.assertEqual(len(s.raid_scouts.known_weapons()), 3)
        self.assertTrue(s.raid_scouts.state['layout_ready'])
        self.assertTrue(s.raid_scouts.summon_ready())
        self.assertIn(Pos(BASE.x+2, BASE.y), s.raid_scouts.operator_cells())

    def test_two_actual_guns_require_all_twelve_weapon_cells_surveyed(self):
        raw, truth = survey_request(near=True)
        truth = [u for u in truth if u['id'] != 993]
        reveal(raw, truth)
        memory = finished_tasks(2)
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        cells = enemy_weapon_cells(s.turn)
        self.assertEqual(len(cells), 12)
        self.assertEqual(len(s.raid_scouts.known_weapons()), 2)
        self.assertFalse(s.raid_scouts.state['layout_ready'])
        raw['roundNo'] += 1
        actor(raw, SCOUT)['pos'] = Pos(14, 17).dump()
        reveal(raw, truth)
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        self.assertEqual(set(s.raid_scouts.state['surveyed']) & cells, set(cells))
        self.assertTrue(s.raid_scouts.state['layout_ready'])

    def test_historical_operator_coverage_does_not_replace_current_sight(self):
        raw, truth = survey_request(near=True)
        memory = finished_tasks(2)
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        self.assertTrue(s.raid_scouts.summon_ready())
        raw['roundNo'] += 1
        actor(raw, SCOUT)['pos'] = Pos(3, 6).dump()
        reveal(raw, truth)
        s, _ = strategy(raw, memory, Settings(enable_news=False))
        self.assertTrue(s.raid_scouts.state['layout_ready'])
        self.assertFalse(s.raid_scouts.summon_ready())
        self.assertTrue(s.raid_scouts.state['uncovered_operators'])

    def test_dead_scout_preserves_held_orders_instead_of_blind_use(self):
        raw, truth = survey_request(near=True)
        actor(raw, HOME)['backpack'] += [ORDER, ORDER]
        memory = finished_tasks(2)
        strategy(raw, memory, Settings(enable_news=False))
        raw['roundNo'] += 1
        actor(raw, SCOUT)['health'] = 0
        reveal(raw, truth)
        s, plan = strategy(raw, memory, Settings(enable_news=False)); s.run()
        self.assertFalse(s.raid_scouts.summon_ready())
        self.assertEqual(s.raid_scouts.state['readiness_reason'], 'no_live_scout')
        self.assertFalse(any(c.get('action') == 'use' and c.get('name') == ORDER
                             for c in plan.commands.values()))
        self.assertNotEqual(s.raid_scouts.state.get('worker_id'), HOME)

    def test_buy_before_survey_then_confirmed_inventory_waits_without_money_lock(self):
        raw, truth = survey_request()
        service = TurnService(Settings(enable_news=False))
        key = (raw['teamOur']['teamId'], raw['teamOur']['type'])
        service.sessions[key] = Session(memory=finished_tasks(2))
        response = service.decide(copy.deepcopy(raw))
        self.assertEqual(response['roleCommandMap'][str(HOME)],
                         {'action': 'buy', 'name': ORDER, 'num': 2})
        raw.update(roundNo=21, lastRoundRoleActionResults={str(HOME): True})
        actor(raw, HOME)['backpack'] += [ORDER, ORDER]
        raw['teamOur']['goldNum'] = 100
        reveal(raw, truth)
        response = service.decide(copy.deepcopy(raw))
        memory = service.sessions[key].memory
        s, _ = strategy(copy.deepcopy(raw), copy.deepcopy(memory), Settings(enable_news=False))
        self.assertTrue(s.boss_raid.weapon_upgrades_ready())
        self.assertEqual(s.boss_raid.budget_reserve(), 0)
        self.assertEqual(memory.boss_raid['status'], 'waiting_for_scout')
        self.assertEqual(memory.boss_raid['acquired_count'], 2)
        self.assertFalse(any(c.get('action') == 'use' and c.get('name') == ORDER
                             for c in response['roleCommandMap'].values()))

    def test_worker_scans_actual_layout_then_holds_with_home_worker_remaining(self):
        raw, truth = survey_request()
        memory = finished_tasks(2)
        ready_at = None
        for number in range(20, 65):
            raw['roundNo'] = number
            reveal(raw, truth)
            s, plan = strategy(raw, memory, Settings(enable_news=False))
            scout = next(w for w in s.turn.workers() if w.unit_id == SCOUT)
            self.assertEqual(s.raid_scouts.state['worker_id'], SCOUT)
            s.raid_scouts.worker(scout)
            if s.raid_scouts.summon_ready() and s.raid_scouts.state['posts'][SCOUT]['status'] == 'holding':
                ready_at = number
                self.assertNotIn(str(SCOUT), plan.commands)
                break
            command = plan.commands[str(SCOUT)]
            self.assertEqual(command['action'], 'move')
            target = Pos.load(command['targetPos'][0])
            self.assertEqual(distance(scout.pos, target), 1)
            self.assertNotIn(target, s.turn.occupied_cells())
            actor(raw, SCOUT)['pos'] = target.dump()
            memory.record(s.turn, plan)
        self.assertIsNotNone(ready_at)
        self.assertEqual(memory.raid_scouts['home_worker_id'], HOME)
        self.assertEqual(actor(raw, HOME)['pos'], Pos(3, 7).dump())

    def test_live_crew_and_common_control_cells_are_both_covered(self):
        raw, truth = survey_request(near=True)
        truth.append(unit(995, 'pioneer', BASE.x + 1, BASE.y + 1, health=200))
        # Put the extra role on a free one-gun position, never on a gun itself.
        truth[-1]['pos'] = Pos(BASE.x, BASE.y + 1).dump()
        reveal(raw, truth)
        s, _ = strategy(raw, finished_tasks(2), Settings(enable_news=False))
        cells = s.raid_scouts.operator_cells()
        self.assertIn(Pos(BASE.x + 2, BASE.y), cells)
        self.assertIn(Pos(BASE.x, BASE.y + 1), cells)
        self.assertTrue(s.raid_scouts.summon_ready())
        self.assertFalse(s.raid_scouts.state['uncovered_operators'])

    def test_four_drawings_and_both_mirrors_have_legal_layout_based_distinct_spawns(self):
        for pattern in ('corner_closed', 'corner_gap', 'corner_closed_low', 'vertical_gap'):
            for mirror_x in (False, True):
                for mirror_y in (False, True):
                    with self.subTest(pattern=pattern, x=mirror_x, y=mirror_y):
                        raw, _ = survey_request()
                        raw['teamEnemy']['roles'] = enemy_blueprint(pattern, mirror_x=mirror_x, mirror_y=mirror_y)
                        turn, settings = Turn.load(raw), Settings()
                        self.assertTrue(enemy_layout_ready(turn))
                        control = Pos.load(next(u for u in raw['teamEnemy']['roles'] if u['id'] == 994)['pos'])
                        self.assertIn(control, layout_operator_positions(turn))
                        first = scouted_spawn_position(turn, settings)
                        second = scouted_spawn_position(turn, settings, pending={first})
                        self.assertIsNotNone(first); self.assertIsNotNone(second)
                        self.assertNotEqual(first, second)
                        for pos in (first, second):
                            self.assertTrue(summon_cell_legal(turn, settings, pos))
                            self.assertNotIn(pos, turn.occupied_cells())
                        if pattern in ('corner_gap', 'vertical_gap'):
                            self.assertLessEqual(distance(first, control), 3)
                            self.assertIsNone(blocking_wall(turn, first, control))
                            if pattern == 'corner_gap':
                                self.assertEqual(abs(first.x - control.x), abs(first.y - control.y))
                        else:
                            # Closed ring can be breached; no imaginary corner gap.
                            self.assertIsNotNone(blocking_wall(turn, first, control))

    def test_inferred_control_positions_are_never_robot_attack_targets(self):
        raw, truth = survey_request(71, near=True)
        truth = [u for u in truth if u['id'] != 994]
        reveal(raw, truth)
        turn = Turn.load(raw)
        control = Pos(BASE.x + 2, BASE.y)
        spawn = scouted_spawn_position(turn, Settings())
        boss = robot(30005, spawn.x, spawn.y, roleType='bossRobot', health=800)
        raw['teamOur']['summonRobotList'] = [boss]; raw['robot']['roles'] = [copy.deepcopy(boss)]
        s, plan = strategy(raw, finished_tasks(2), Settings(enable_news=False))
        self.assertIn(control, layout_operator_positions(s.turn))
        self.assertFalse(clear_attack(s.turn, s.turn.summon_robots[0], control))
        s.raider.decide(s.turn.summon_robots[0])
        command = plan.commands.get('30005', {})
        if command.get('action') == 'attack':
            self.assertNotEqual(command['targetPos'], [control.dump()])
            self.assertIn(command['targetPos'][0], [u['pos'] for u in raw['teamEnemy']['roles']
                          if u['roleType'] in ('wall', 'station')] + [p.dump() for p in station_footprint(BASE)])

    def test_scout_keeps_sight_without_standing_on_planned_diagonal_fire_line(self):
        raw, truth = survey_request(near=True)
        first, second = Pos(BASE.x + 4, BASE.y - 2), Pos(BASE.x + 5, BASE.y - 3)
        blocking_post = Pos(BASE.x + 3, BASE.y - 1)
        actor(raw, SCOUT)['pos'] = blocking_post.dump()
        reveal(raw, truth)
        memory = finished_tasks(2)
        memory.boss_raid = {'status': 'deployed', 'deployed_count': 2, 'acquired_count': 2,
            'deployment_ledger_confirmed': True, 'spawns': [first, second], 'summon_round': 19}
        memory.raid_scouts = {'worker_id': SCOUT, 'home_worker_id': HOME,
            'posts': {SCOUT: {'goal': blocking_post}}}
        crew = Pos(BASE.x + 2, BASE.y)
        for number in range(20, 28):
            raw['roundNo'] = number
            reveal(raw, truth)
            s, plan = strategy(raw, memory, Settings(enable_news=False))
            worker = next(w for w in s.turn.workers() if w.unit_id == SCOUT)
            s.raid_scouts.worker(worker)
            if s.raid_scouts.state['posts'][SCOUT]['status'] == 'holding':
                break
            command = plan.commands[str(SCOUT)]
            self.assertEqual(command['action'], 'move')
            actor(raw, SCOUT)['pos'] = command['targetPos'][0]
            memory.record(s.turn, plan)
        else:
            self.fail('scout did not settle at an observation post')
        self.assertTrue(s.raid_scouts.summon_ready())
        for spawn in (first, second):
            self.assertIsNone(blocking_wall(s.turn, spawn, crew))
            blocker = planning_building_blocker(s.turn, spawn, crew, memory.enemy_structures.values())
            self.assertIsNone(blocker, 'scout obstructs a planned 45-degree BOSS shot')

    def test_unscouted_coupons_expire_the_window_without_blind_use_or_new_buy(self):
        raw, _ = survey_request(69)
        actor(raw,HOME)['backpack'] += [ORDER,ORDER]
        memory = finished_tasks(2)
        s,plan = strategy(raw,memory,Settings(enable_news=False)); s.run()
        self.assertFalse(memory.boss_raid.get('summon_window_closed',False))
        self.assertEqual(memory.boss_raid['status'],'waiting_for_scout')
        self.assertTrue(s.boss_raid.weapon_upgrades_ready())
        self.assertEqual(s.boss_raid.budget_reserve(),0)
        self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))
        raw['roundNo'] = 70
        s,plan = strategy(raw,memory,Settings(enable_news=False)); s.run()
        self.assertTrue(memory.boss_raid['summon_window_closed'])
        self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))
        self.assertEqual(actor(raw,HOME)['backpack'].count(ORDER),2)
        raw['roundNo'] = 71
        s,plan = strategy(raw,memory,Settings(enable_news=False)); s.run()
        self.assertFalse(s.raid_scouts.active)
        self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))

    def test_remembered_hidden_cannon_blocks_both_actual_and_relaxed_scout_routes(self):
        raw,_ = survey_request(20)
        actor(raw,SCOUT)['pos'] = Pos(12,18).dump()
        hidden = Unit.load(unit(1700,'rocket',17,18,health=1000))
        memory = finished_tasks(2)
        memory.enemy_structures[hidden.unit_id] = hidden
        memory.raid_scouts.update(worker_id=SCOUT,home_worker_id=HOME)
        s,plan = strategy(raw,memory,Settings(enable_news=False))
        scout = next(w for w in s.turn.workers() if w.unit_id==SCOUT)
        self.assertFalse(s.raid_scouts.seen(hidden.pos))
        self.assertIn(hidden.unit_id,memory.enemy_structures)
        self.assertNotIn(hidden.pos,s.raid_scouts.scout_route(scout).cost)
        self.assertNotIn(hidden.pos,s.route(scout).cost)
        # Forcing an impossible goal must not take the diagnostic fallback
        # through a known but currently invisible cannon.
        self.assertFalse(s.coordinator.move_to(scout,{hidden.pos},'raid_scout',BASE,allow_risk=True))
        self.assertNotIn(str(SCOUT),plan.commands)

    def test_last_daytime_second_use_has_no_return_budget_and_keeps_scout_sight(self):
        raw,truth = survey_request(70,near=True)
        actor(raw,HOME)['backpack'] += [ORDER]
        memory = finished_tasks(2)
        memory.boss_raid.update(status='deployed',deployed_count=1,acquired_count=2,
            deployment_ledger_confirmed=True,spawns=[Pos(21,15)],scouted_spawns=[Pos(21,15)])
        memory.raid_scouts.update(worker_id=SCOUT,home_worker_id=HOME)
        s,plan = strategy(raw,memory,Settings(enable_news=False)); s.run()
        command = plan.commands[str(HOME)]
        self.assertEqual(command['action'],'use')
        self.assertEqual(command['name'],ORDER)
        self.assertFalse(memory.boss_raid.get('summon_window_closed',False))
        memory.record(s.turn,plan)
        raw['roundNo'] = 71
        raw['lastRoundRoleActionResults'] = {str(HOME):True}
        actor(raw,HOME)['backpack'] = ['stone']+['WallFixer']*5
        boss = robot(30005,21,15,health=800,roleType='bossRobot')
        raw['teamOur']['summonRobotList'] = [boss]; raw['robot']['roles'] = [boss]
        reveal(raw,truth)
        s,plan = strategy(raw,memory,Settings(enable_news=False)); s.run()
        self.assertTrue(s.raid_scouts.active)
        self.assertEqual(s.memory.worker_tasks[SCOUT]['kind'],'raid_scout')
        self.assertFalse(any(c.get('name')==ORDER for c in plan.commands.values()))


if __name__ == '__main__':
    unittest.main()
