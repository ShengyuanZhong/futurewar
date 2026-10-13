"""First-night static geometry; no private visibility or wave-AI assumptions."""
import unittest
from dataclasses import replace

from agent.protocol import Pos, Robot, Turn, Unit, distance, station_footprint
from agent.robot_combat import blocking_wall
from agent.summoning import (enemy_layout_weapons, layout_operator_positions,
                            summon_cell_legal)
from agent.wall_assault import plan_assault, protected_layout
from app.config import Settings
from tests.fixtures import request, unit


BASE = Pos(9, 22)
BOTTOM_GUNS = (Pos(8, 21), Pos(8, 20), Pos(10, 20))
TOP_GUNS = (Pos(8, 23), Pos(9, 23), Pos(8, 21))


def reflect(pos, horizontal=False, vertical=False):
    return Pos(40 - pos.x if horizontal else pos.x,
               31 - pos.y if vertical else pos.y)


def scene(guns=BOTTOM_GUNS, gaps=(), horizontal=False, vertical=False, kinds=None):
    raw = request(55)
    raw['mapInfo']['zones'] = []
    raw['teamOur']['playerTasks'] = []
    raw['teamOur']['roles'] = [unit(503, 'station', 30, 10)]
    footprint = station_footprint(BASE)
    walls = {Pos(x, y) for x in range(7, 13) for y in range(19, 25)
             if min(distance(Pos(x, y), cell) for cell in footprint) == 2}
    walls -= set(gaps)
    mirrored = [reflect(p, horizontal, vertical) for p in footprint]
    base = Pos(min(p.x for p in mirrored), max(p.y for p in mirrored))
    raw['teamEnemy']['roles'] = [unit(990, 'station', base.x, base.y)]
    raw['teamEnemy']['roles'] += [unit(1000 + i, 'wall', p.x, p.y, health=1000)
        for i, p in enumerate(sorted(reflect(p, horizontal, vertical) for p in walls))]
    raw['teamEnemy']['roles'] += [unit(991 + i, kind, p.x, p.y, health=1000)
        for i, (kind, p) in enumerate(zip(kinds or ('rocket',) * 3,
                            (reflect(p, horizontal, vertical) for p in guns)))]
    return Turn.load(raw)


class WallAssaultPlanTests(unittest.TestCase):
    def assert_legal_common_wall(self, turn, plan, count=3, pending=()):
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan['spawns']), count)
        self.assertEqual(len(set(plan['spawns'])), count)
        wall = next(u for u in turn.enemies if u.unit_id == plan['wall_id'])
        self.assertEqual(wall.pos, plan['wall_pos'])
        for origin in plan['spawns']:
            self.assertTrue(summon_cell_legal(turn, Settings(), origin, pending))
            self.assertLessEqual(distance(origin, wall.pos), 3)
            self.assertIsNone(blocking_wall(turn, origin, wall.pos))

    def test_first_picture_attacks_one_north_wall_from_three_straight_cells(self):
        turn = scene()
        self.assertEqual(layout_operator_positions(turn), (Pos(9, 20),))
        self.assertTrue(protected_layout(turn, Settings()))
        plan = plan_assault(turn, Settings(), 3)
        self.assertEqual(plan['side'], 'north')
        self.assertEqual(plan['wall_pos'], Pos(9, 24))
        self.assertEqual(plan['spawns'], [Pos(9, 25), Pos(9, 26), Pos(9, 27)])
        self.assert_legal_common_wall(turn, plan)

    def test_second_picture_uses_south_not_the_west_cannon_side(self):
        turn = scene(TOP_GUNS)
        self.assertEqual(layout_operator_positions(turn), (Pos(8, 22),))
        self.assertTrue(protected_layout(turn, Settings()))
        plan = plan_assault(turn, Settings(), 3)
        self.assertEqual(plan['side'], 'south')
        self.assertEqual(plan['wall_pos'], Pos(9, 19))
        self.assertEqual(plan['spawns'], [Pos(9, 18), Pos(9, 17), Pos(9, 16)])
        self.assert_legal_common_wall(turn, plan)

    def test_both_pictures_keep_common_wall_and_flank_in_every_mirror(self):
        for guns, wall, positions in (
                (BOTTOM_GUNS, Pos(9, 24), (Pos(9, 25), Pos(9, 26), Pos(9, 27))),
                (TOP_GUNS, Pos(9, 19), (Pos(9, 18), Pos(9, 17), Pos(9, 16)))):
            for horizontal, vertical in ((True, False), (False, True), (True, True)):
                with self.subTest(guns=guns, horizontal=horizontal, vertical=vertical):
                    turn = scene(guns, horizontal=horizontal, vertical=vertical)
                    self.assertTrue(protected_layout(turn, Settings()))
                    plan = plan_assault(turn, Settings(), 3)
                    self.assertEqual(plan['wall_pos'], reflect(wall, horizontal, vertical))
                    self.assertEqual(plan['spawns'], [reflect(p, horizontal, vertical) for p in positions])
                    self.assert_legal_common_wall(turn, plan)

    def test_45_degree_gap_with_two_side_walls_keeps_direct_operator_policy(self):
        turn = scene(gaps=(Pos(8, 19),))
        self.assertIn(Pos(7, 19), {u.pos for u in turn.enemies if u.kind == 'wall'})
        self.assertIn(Pos(9, 19), {u.pos for u in turn.enemies if u.kind == 'wall'})
        self.assertIsNone(blocking_wall(turn, Pos(7, 18), Pos(9, 20)))
        self.assertFalse(protected_layout(turn, Settings()))

    def test_open_far_door_allows_a_wall_free_walk_to_an_interior_firing_cell(self):
        guns = (Pos(8, 23), Pos(9, 23), Pos(10, 23))
        closed = scene(guns)
        self.assertEqual(layout_operator_positions(closed), (Pos(8, 22),))
        self.assertTrue(protected_layout(closed, Settings()))
        opened = scene(guns, gaps=(Pos(11, 24),))
        # Exterior firing line still hits the north wall. The open east end
        # permits this concrete route around the base to a clear inner shot.
        self.assertIsNotNone(blocking_wall(opened, Pos(11, 25), Pos(8, 22)))
        route = [Pos(11, 25), Pos(11, 24), Pos(11, 23), Pos(11, 22),
                 Pos(11, 21), Pos(11, 20), Pos(10, 20), Pos(9, 20),
                 Pos(8, 20), Pos(8, 21)]
        self.assertTrue(summon_cell_legal(opened, Settings(), route[0]))
        self.assertTrue(all(distance(a, b) == 1 for a, b in zip(route, route[1:])))
        self.assertTrue(set(route).isdisjoint(opened.occupied_cells()))
        self.assertIsNone(blocking_wall(opened, route[-1], Pos(8, 22)))
        self.assertFalse(protected_layout(opened, Settings()))
        occupied_door = replace(opened, enemies=opened.enemies +
                               (Unit(1500, Pos(11, 24), 'worker', 500),))
        self.assertFalse(protected_layout(occupied_door, Settings()))

    def test_no_actual_wall_never_counts_building_blockage_as_a_wall_shield(self):
        turn = scene()
        turn = replace(turn, enemies=tuple(u for u in turn.enemies if u.kind != 'wall'))
        self.assertFalse(protected_layout(turn, Settings()))
        self.assertIsNone(plan_assault(turn, Settings(), 3))

    def test_best_posts_protected_is_not_cancelled_by_an_exposed_partial_crew(self):
        turn = scene(gaps=(Pos(7, 22),), kinds=('rocket', 'railgun', 'gatling'))
        turn = replace(turn, enemies=turn.enemies + (Unit(1500, Pos(8, 22), 'worker', 500),))
        self.assertIsNone(blocking_wall(turn, Pos(6, 22), Pos(8, 22)))
        self.assertTrue(protected_layout(turn, Settings()))

    def test_live_shielded_mixed_cannon_crew_can_trigger_with_exposed_best_post(self):
        turn = scene(gaps=(Pos(8, 19),), kinds=('rocket', 'railgun', 'gatling'))
        self.assertFalse(protected_layout(turn, Settings()))
        turn = replace(turn, enemies=turn.enemies + (Unit(1500, Pos(8, 22), 'worker', 500),))
        self.assertTrue(protected_layout(turn, Settings()))

    def test_three_rockets_ignore_shielded_partial_control_people(self):
        turn = scene(gaps=(Pos(8, 19),))
        turn = replace(turn, enemies=turn.enemies + (Unit(1500, Pos(8, 22), 'worker', 500),))
        self.assertFalse(protected_layout(turn, Settings()))

    def test_cached_three_rocket_types_keep_partial_people_out_of_the_policy(self):
        turn = scene(gaps=(Pos(8, 19),))
        types = {g.pos: g.kind for g in enemy_layout_weapons(turn)}
        hidden = replace(turn, enemies=tuple(u for u in turn.enemies if u.kind != 'rocket')
                         + (Unit(1500, Pos(8, 22), 'worker', 500),))
        self.assertFalse(protected_layout(hidden, Settings(), confirmed_sites=types))
        # Bare positions establish geometry but do not identify weapon types.
        self.assertTrue(protected_layout(hidden, Settings(), confirmed_sites=tuple(types)))

    def test_hidden_confirmed_sites_plan_geometry_without_creating_enemy_units(self):
        turn = scene()
        known = enemy_layout_weapons(turn)
        hidden = replace(turn, enemies=tuple(u for u in turn.enemies if u.kind != 'rocket'))
        self.assertTrue(protected_layout(hidden, Settings(), confirmed_sites=[u.pos for u in known]))
        remembered = plan_assault(hidden, Settings(), 3, remembered=known)
        sites_only = plan_assault(hidden, Settings(), 3, confirmed_sites=[u.pos for u in known])
        self.assertEqual(remembered, sites_only)
        self.assertEqual(sites_only['spawns'], [Pos(9, 25), Pos(9, 26), Pos(9, 27)])
        self.assertEqual(len(hidden.enemies), len(turn.enemies) - 3)

    def test_later_ticket_keeps_same_wall_and_excludes_pending_and_failed(self):
        turn = scene()
        first = plan_assault(turn, Settings(), 1)
        next_two = plan_assault(turn, Settings(), 2, pending=first['spawns'],
                               preferred_wall=first['wall_pos'])
        self.assertEqual(first['wall_id'], next_two['wall_id'])
        self.assertEqual(next_two['spawns'], [Pos(9, 26), Pos(9, 27)])
        self.assert_legal_common_wall(turn, next_two, count=2, pending=first['spawns'])
        retry = plan_assault(turn, Settings(), 1, pending=first['spawns'],
                            failed=(Pos(9, 26),), preferred_wall=first['wall_id'])
        self.assertNotIn(retry['spawns'][0], first['spawns'] + [Pos(9, 26)])
        self.assertEqual(retry['wall_id'], first['wall_id'])

    def test_neutral_dynamic_and_robot_occupants_do_not_displace_planned_spawns(self):
        turn = scene()
        turn = replace(turn, zones={Pos(9, 25): 'weaponShop'},
                       ours=turn.ours + (Unit(501, Pos(9, 26), 'worker', 500),),
                       robots=(Robot(30000, Pos(9, 27), 40),))
        plan = plan_assault(turn, Settings(), 3)
        self.assert_legal_common_wall(turn, plan)
        self.assertTrue(set(plan['spawns']).isdisjoint({Pos(9, 25), Pos(9, 26), Pos(9, 27)}))

    def test_preferred_missing_wall_does_not_silently_split_the_team_breach(self):
        turn = scene()
        self.assertIsNone(plan_assault(turn, Settings(), 1, preferred_wall=Pos(9, 19 - 1)))
        self.assertIsNone(plan_assault(turn, Settings(), 0))

    def test_seen_wave_risk_changes_spawn_ranking_without_an_ai_prediction(self):
        turn = scene()
        turn = replace(turn, robots=(Robot(30000, Pos(9, 26), 40),))
        plan = plan_assault(turn, Settings(), 3)
        self.assert_legal_common_wall(turn, plan)
        self.assertTrue(all(distance(p, Pos(9, 26)) > 3 or
                            blocking_wall(turn, Pos(9, 26), p) is not None
                            for p in plan['spawns']))

    def test_enlarged_margin_remains_legal_and_may_reject_a_shared_breach(self):
        turn = scene()
        self.assertIsNone(plan_assault(turn, Settings(summon_build_margin=5), 3))


if __name__ == '__main__':
    unittest.main()
