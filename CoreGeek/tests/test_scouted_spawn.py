"""Scouted cannon patterns, complete walls, diagonal gaps and reflections."""
import unittest
from dataclasses import replace

from agent.protocol import Pos, Turn, Unit, Robot, distance, station_footprint
from agent.grid import Routes
from agent.robot_combat import blocking_wall, planning_building_blocker
from agent.summoning import (enemy_layout_ready, enemy_layout_weapons, enemy_weapon_cells,
                            layout_operator_positions, scouted_spawn_candidates,
                            scouted_spawn_position, summon_cell_legal)
from app.config import Settings
from tests.fixtures import request, unit


BASE = Pos(10, 15)
OPERATOR = Pos(12, 15)
GUNS = (Pos(11, 16), Pos(12, 16), Pos(12, 14))


def reflect(pos, horizontal=False, vertical=False):
    return Pos(40-pos.x if horizontal else pos.x, 31-pos.y if vertical else pos.y)


def scene(gap=None, vertical_guns=False, visible_operator=False, horizontal=False, vertical=False):
    raw = request(55)
    raw['mapInfo']['zones'] = []
    raw['teamOur']['playerTasks'] = []
    raw['teamOur']['roles'] = [unit(503, 'station', 29, 17)]
    guns = (Pos(12, 16), Pos(12, 15), Pos(12, 14)) if vertical_guns else GUNS
    operator = Pos(13, 15) if vertical_guns else OPERATOR
    footprint = station_footprint(BASE)
    wall_positions = {Pos(x, y) for x in range(8, 14) for y in range(12, 18)
                      if min(distance(Pos(x, y), cell) for cell in footprint) == 2}
    if gap:
        wall_positions.discard(gap)
    if vertical_guns:
        wall_positions.discard(operator)
    # Mirroring all four cells changes which cell is the station's top-left.
    mirrored = tuple(reflect(p, horizontal, vertical) for p in footprint)
    base = Pos(min(p.x for p in mirrored), max(p.y for p in mirrored))
    raw['teamEnemy']['roles'] = [unit(990, 'station', base.x, base.y)]
    raw['teamEnemy']['roles'] += [unit(991+i, kind, p.x, p.y, health=1000)
        for i, (kind, p) in enumerate(zip(('rocket', 'railgun', 'gatling'),
                                         (reflect(p, horizontal, vertical) for p in guns)))]
    raw['teamEnemy']['roles'] += [unit(1000+i, 'wall', p.x, p.y, health=1000)
        for i, p in enumerate(sorted(reflect(p, horizontal, vertical) for p in wall_positions))]
    if visible_operator:
        operator = reflect(operator, horizontal, vertical)
        raw['teamEnemy']['roles'].append(unit(1100, 'worker', operator.x, operator.y, health=500))
    return Turn.load(raw)


class ScoutedSpawnTests(unittest.TestCase):
    def test_third_boss_does_not_price_a_walk_through_two_stationary_spawns(self):
        turn,settings = scene(gap=Pos(13,14)),Settings()
        first = scouted_spawn_position(turn,settings)
        second = scouted_spawn_position(turn,settings,pending={first})
        third = scouted_spawn_position(turn,settings,pending={first,second})
        self.assertEqual(len({first,second,third}),3)
        self.assertTrue(summon_cell_legal(turn,settings,third,{first,second}))
        route = Routes(turn,Robot(39999,third,800,'bossRobot'),{first,second})
        shots = {p for p in route.cost if 0<distance(p,OPERATOR)<=3
                 and blocking_wall(turn,p,OPERATOR) is None
                 and planning_building_blocker(turn,p,OPERATOR) is None}
        goal = route.nearest(shots)
        self.assertIsNotNone(goal)
        self.assertEqual(route.cost[goal],1)
        self.assertNotIn(route.step({goal}),{first,second})

    def test_twelve_weapon_ring_cells_exclude_base_and_wall_ring(self):
        turn = scene()
        cells = enemy_weapon_cells(turn)
        self.assertEqual(len(cells), 12)
        self.assertTrue(set(GUNS) <= cells)
        self.assertTrue(all(min(distance(p, cell) for cell in station_footprint(BASE)) == 1
                            for p in cells))

    def test_actual_three_weapons_confirm_layout_without_fabricating_any_unit(self):
        turn = scene()
        self.assertTrue(enemy_layout_ready(turn))
        self.assertEqual(set(g.pos for g in enemy_layout_weapons(turn)), set(GUNS))
        self.assertEqual(layout_operator_positions(turn), (OPERATOR,))
        self.assertNotIn(OPERATOR, {u.pos for u in turn.enemies})

    def test_fewer_guns_wait_until_entire_ring_actually_surveyed(self):
        turn = scene()
        turn = replace(turn, enemies=tuple(u for u in turn.enemies if u.unit_id != 993))
        ring = enemy_weapon_cells(turn)
        self.assertFalse(enemy_layout_ready(turn))
        self.assertIsNone(scouted_spawn_position(turn, Settings()))
        self.assertFalse(enemy_layout_ready(turn, surveyed=ring-{next(iter(ring))}))
        self.assertTrue(enemy_layout_ready(turn, surveyed=ring))
        self.assertIsNotNone(scouted_spawn_position(turn, Settings(), surveyed=ring))

    def test_remembered_real_guns_plan_layout_when_current_guns_outside_sight(self):
        full = scene(gap=Pos(13, 14))
        known = enemy_layout_weapons(full)
        hidden = replace(full, enemies=tuple(u for u in full.enemies if u.kind not in
                                            ('rocket', 'railgun', 'gatling')))
        self.assertTrue(enemy_layout_ready(hidden, known))
        self.assertEqual(layout_operator_positions(hidden, known), (OPERATOR,))
        self.assertEqual(scouted_spawn_position(hidden, Settings(), known), Pos(14, 13))
        self.assertEqual(len(hidden.enemies), len(full.enemies)-3)

    def test_observed_dead_gun_overrides_live_static_memory(self):
        turn = scene()
        known = enemy_layout_weapons(turn)
        gone = replace(turn, enemies=tuple(replace(u, health=0) if u.unit_id == 993 else u
                                          for u in turn.enemies))
        self.assertEqual(len(enemy_layout_weapons(gone, known)), 2)
        self.assertFalse(enemy_layout_ready(gone, known))

    def test_new_gun_id_at_same_position_replaces_old_remembered_gun(self):
        turn = scene()
        known = enemy_layout_weapons(turn)
        replacement = replace(known[0], unit_id=9990, kind='gatling')
        turn = replace(turn, enemies=tuple(u for u in turn.enemies if u.unit_id != known[0].unit_id)
                       + (replacement,))
        merged = enemy_layout_weapons(turn, known)
        self.assertEqual(len(merged), 3)
        self.assertIn(replacement, merged)
        self.assertNotIn(known[0], merged)

    def test_closed_first_picture_chooses_right_side_shared_single_wall_breach(self):
        turn = scene(visible_operator=True)
        first = scouted_spawn_position(turn, Settings())
        second = scouted_spawn_position(turn, Settings(), pending=(first,))
        self.assertEqual(first, Pos(14, 15))
        self.assertEqual(second, Pos(15, 15))
        self.assertEqual(blocking_wall(turn, first, OPERATOR).pos, Pos(13, 15))
        self.assertEqual(blocking_wall(turn, second, OPERATOR).pos, Pos(13, 15))

    def test_diagonal_gap_pictures_choose_two_direct_45_degree_points(self):
        turn = scene(gap=Pos(13, 14), visible_operator=True)
        first = scouted_spawn_position(turn, Settings())
        second = scouted_spawn_position(turn, Settings(), pending=(first,))
        self.assertEqual((first, second), (Pos(14, 13), Pos(15, 12)))
        for pos in (first, second):
            self.assertLessEqual(distance(pos, OPERATOR), 3)
            self.assertIsNone(blocking_wall(turn, pos, OPERATOR))
            self.assertIsNone(planning_building_blocker(turn, pos, OPERATOR))
            self.assertTrue(summon_cell_legal(turn, Settings(), pos))

    def test_horizontal_and_vertical_reflections_keep_diagonal_gap_shots(self):
        for horizontal, vertical in ((True, False), (False, True), (True, True)):
            with self.subTest(horizontal=horizontal, vertical=vertical):
                turn = scene(gap=Pos(13, 14), visible_operator=True,
                             horizontal=horizontal, vertical=vertical)
                first = scouted_spawn_position(turn, Settings())
                second = scouted_spawn_position(turn, Settings(), pending=(first,))
                self.assertEqual(first, reflect(Pos(14, 13), horizontal, vertical))
                self.assertEqual(second, reflect(Pos(15, 12), horizontal, vertical))
                target = reflect(OPERATOR, horizontal, vertical)
                self.assertIsNone(blocking_wall(turn, first, target))
                self.assertIsNone(blocking_wall(turn, second, target))

    def test_vertical_three_gun_picture_detects_outer_ring_operator(self):
        turn = scene(vertical_guns=True, visible_operator=True)
        target = Pos(13, 15)
        self.assertEqual(layout_operator_positions(turn), (target,))
        first = scouted_spawn_position(turn, Settings())
        second = scouted_spawn_position(turn, Settings(), pending=(first,))
        self.assertEqual((first, second), (Pos(14, 15), Pos(14, 14)))
        self.assertIsNone(blocking_wall(turn, first, target))
        self.assertIsNone(blocking_wall(turn, second, target))

    def test_visible_crew_overrides_an_empty_maximum_control_hypothesis(self):
        turn = scene(gap=Pos(13, 14))
        # The real gunner chose an upper position controlling only two guns.
        crew = Unit(1100, Pos(12, 17), 'pioneer', 500)
        turn = replace(turn, enemies=tuple(u for u in turn.enemies if u.pos != crew.pos)+(crew,))
        self.assertEqual(layout_operator_positions(turn), (OPERATOR,))
        chosen = scouted_spawn_position(turn, Settings())
        self.assertIsNone(blocking_wall(turn, chosen, crew.pos))
        self.assertLessEqual(distance(chosen, crew.pos), 3)

    def test_pending_failed_npc_and_dynamic_occupants_never_force_duplicate_spawn(self):
        turn = scene(gap=Pos(13, 14), visible_operator=True)
        preferred = Pos(14, 13)
        turn = replace(turn, zones={preferred: 'weaponShop'})
        first = scouted_spawn_position(turn, Settings())
        second = scouted_spawn_position(turn, Settings(), pending=(first,), failed=(Pos(14, 12),))
        self.assertNotIn(first, (preferred,))
        self.assertNotIn(second, (preferred, first, Pos(14, 12)))
        self.assertTrue(summon_cell_legal(turn, Settings(), first))
        self.assertTrue(summon_cell_legal(turn, Settings(), second, (first,)))
        turn = scene(gap=Pos(13, 14), visible_operator=True)
        turn = replace(turn, ours=turn.ours+(Unit(501, preferred, 'worker', 500),))
        self.assertNotEqual(scouted_spawn_position(turn, Settings()), preferred)

    def test_all_ranked_points_are_legal_even_with_larger_construction_margin(self):
        turn = scene(gap=Pos(13, 14))
        settings = Settings(summon_build_margin=4)
        candidates = scouted_spawn_candidates(turn, settings)
        self.assertTrue(candidates)
        self.assertEqual(len(candidates), len(set(candidates)))
        self.assertTrue(all(summon_cell_legal(turn, settings, p) for p in candidates))

    def test_no_weapons_after_complete_real_survey_uses_base_without_inventing_crew(self):
        turn = scene()
        turn = replace(turn, enemies=tuple(u for u in turn.enemies
                                          if u.kind not in ('rocket', 'railgun', 'gatling')))
        self.assertEqual(layout_operator_positions(turn), ())
        self.assertEqual(enemy_layout_weapons(turn), ())
        self.assertIsNotNone(scouted_spawn_position(turn, Settings(), surveyed=enemy_weapon_cells(turn)))


if __name__ == '__main__':
    unittest.main()
