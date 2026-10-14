"""The tenth day spends all weapon fire on our diagonal half of the map.

These synthetic observations exercise decisions and the public HTTP adapter;
they do not simulate authoritative damage, visibility, or official matches.
"""
import http.client
import json
import threading
import unittest

from agent.combat import choose_targets
from agent.map_regions import base_side, diagonal_side
from agent.protocol import Pos, Turn
from app.config import Settings
from app.server import AgentServer
from app.service.turn_service import TurnService
from tests.fixtures import robot, unit
from tests.test_rocket_sectors import battlefield


def scene(round_no=1241, lower=False, level=3):
    raw = battlefield(lower)
    raw['roundNo'] = round_no
    raw['teamOur']['roles'][1]['level'] = level
    return raw


def targets(raw, expected=None):
    turn = Turn.load(raw)
    expected = expected if expected is not None else {
        r.robot_id: r.health for r in turn.hostile_robots()}
    return choose_targets(turn, turn.weapons()[0], expected)


def close_sector_scene(kind, level, lower=False, enemy_only=False):
    """Both halves have targets within even a level-one gatling's range."""
    raw = scene(lower=lower, level=level)
    reflect = (lambda x, y: (40-x, 31-y)) if lower else (lambda x, y: (x, y))
    x, y = reflect(20, 16)
    raw['teamOur']['roles'][1] = unit(601, kind, x, y, level=level)
    raw['robot']['roles'] = [
        robot(900, *reflect(19, 19), health=500, roleType='largeRobot'),
        robot(901, *reflect(22, 13), health=1, roleType='bossRobot')]
    if enemy_only:
        raw['robot']['roles'] = raw['robot']['roles'][1:]
    return raw


class FinalDayDefenseTests(unittest.TestCase):
    def test_day_nine_keeps_two_home_one_enemy_until_round_1170(self):
        for number in (1111, 1170):
            for lower in (False, True):
                with self.subTest(round_no=number, lower=lower):
                    raw = scene(number, lower)
                    own, enemy = [Pos.load(r['pos']) for r in raw['robot']['roles']]
                    self.assertEqual(Turn.load(raw).day, 9)
                    self.assertEqual(targets(raw), [own, own, enemy])

    def test_round_1171_starts_own_half_only_selection(self):
        for number in (1171, 1240, 1241, 1300):
            for lower in (False, True):
                with self.subTest(round_no=number, lower=lower):
                    raw = scene(number, lower)
                    own = Pos.load(raw['robot']['roles'][0]['pos'])
                    self.assertEqual(Turn.load(raw).day, 10)
                    self.assertEqual(targets(raw), [own]*3)

    def test_every_final_night_round_defends_our_half_in_both_positions(self):
        for lower in (False, True):
            for number in range(1241, 1301):
                with self.subTest(round_no=number, lower=lower):
                    raw = scene(number, lower)
                    own = Pos.load(raw['robot']['roles'][0]['pos'])
                    self.assertEqual(targets(raw), [own]*3)

    def test_all_weapon_types_levels_and_team_labels_only_target_our_half(self):
        for lower in (False, True):
            for team in ('challenger', 'defender'):
                for kind in ('rocket', 'gatling', 'railgun'):
                    for level in (1, 2, 3):
                        with self.subTest(lower=lower, team=team, kind=kind, level=level):
                            raw = close_sector_scene(kind, level, lower)
                            raw['teamOur']['type'] = team
                            own = Pos.load(raw['robot']['roles'][0]['pos'])
                            self.assertEqual(targets(raw), [own]*(1 if kind == 'railgun' else level))

    def test_enemy_only_has_no_final_day_salvo_for_any_weapon(self):
        for lower in (False, True):
            for kind in ('rocket', 'gatling', 'railgun'):
                for level in (1, 2, 3):
                    with self.subTest(lower=lower, kind=kind, level=level):
                        raw = close_sector_scene(kind, level, lower, enemy_only=True)
                        health = {901: 1}
                        self.assertEqual(targets(raw, health), [])
                        self.assertEqual(health, {901: 1})

    def test_enemy_splash_score_cannot_pull_fire_away_from_better_home_cluster(self):
        for lower in (False, True):
            with self.subTest(lower=lower):
                raw = scene(lower=lower)
                reflect = (lambda x, y: (40-x, 31-y)) if lower else (lambda x, y: (x, y))
                raw['robot']['roles'] = [
                    robot(900, *reflect(20, 16), health=500, roleType='largeRobot'),
                    robot(901, *reflect(16, 20), health=60, roleType='middleRobot'),
                    robot(902, *reflect(20, 15), health=1, roleType='bossRobot')]
                # The opposing one-HP boss neighbours the worse home centre.
                # Only our medium robot's 2/60 outranks our large one's 4/500.
                preferred = Pos(*reflect(16, 20))
                self.assertEqual(targets(raw), [preferred]*3)

    def test_dead_home_robot_does_not_unlock_enemy_only_fallback(self):
        raw = scene()
        raw['robot']['roles'][0]['health'] = 0
        self.assertEqual(targets(raw), [])

    def test_exact_map_diagonal_is_home_in_both_positions(self):
        for lower in (False, True):
            with self.subTest(lower=lower):
                raw = scene(lower=lower)
                raw['robot']['roles'] = [robot(900, 0, 0, health=1)]
                self.assertEqual(targets(raw), [Pos(0, 0)]*3)

    def test_missing_base_uses_enemy_base_or_weapon_position_to_identify_home(self):
        for enemy_base in (False, True):
            raw = scene()
            raw['teamOur']['roles'] = raw['teamOur']['roles'][1:]
            if enemy_base:
                raw['teamEnemy']['roles'] = [unit(800, 'station', 30, 7)]
            self.assertEqual(targets(raw), [Pos(12, 24)]*3)

    def test_turn_service_changes_only_attack_allocation_across_day_boundary(self):
        service = TurnService(Settings(enable_news=False, enable_tasks=False))
        for number in (1170, 1171, 1241, 1300):
            raw = scene(number)
            response = service.decide(raw)
            self.assertEqual(set(response), {'roleCommandMap', 'prompt', 'executeCmd'})
            attack = response['roleCommandMap'].get('601')
            if number == 1171:
                self.assertIsNone(attack, 'daytime must still obey the night-only firing rule')
                continue
            self.assertEqual(attack['controllerId'], '502')
            self.assertEqual(attack['action'], 'attack')
            wanted = [{'x':12, 'y':24}]*2 + [{'x':30, 'y':5}] if number == 1170 else [{'x':12, 'y':24}]*3
            self.assertEqual(attack['targetPos'], wanted)
            self.assertNotIn('502', response['roleCommandMap'])

    def test_final_day_turn_service_keeps_cooldown_and_empty_home_rules(self):
        for lower in (False, True):
            for cooldown, home_health in ((3, 500), (0, 0)):
                with self.subTest(lower=lower, cooldown=cooldown, home_health=home_health):
                    raw = scene(lower=lower)
                    raw['teamOur']['roles'][1]['cooldown'] = cooldown
                    raw['robot']['roles'][0]['health'] = home_health
                    response = TurnService(Settings(enable_news=False, enable_tasks=False)).decide(raw)
                    self.assertNotIn('601', response['roleCommandMap'])


class FinalDayHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = AgentServer(('127.0.0.1', 0), TurnService(
            Settings(enable_news=False, enable_tasks=False)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def call(self, raw):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=4)
        try:
            connection.request('POST', '/judger', json.dumps(raw).encode(),
                               {'Content-Type':'application/json'})
            response = connection.getresponse()
            data = response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(int(response.getheader('Content-Length')), len(data))
            return json.loads(data)
        finally:
            connection.close()

    def test_http_first_and_last_night_rounds_emit_only_occupied_home_centres(self):
        for lower in (False, True):
            for number in (1241, 1300):
                with self.subTest(lower=lower, round_no=number):
                    raw = scene(number, lower)
                    raw['teamOur']['teamId'] = f'final-http-{lower}-{number}'
                    response = self.call(raw)
                    self.assertEqual(set(response), {'roleCommandMap', 'prompt', 'executeCmd'})
                    attack = response['roleCommandMap']['601']
                    self.assertEqual(attack['action'], 'attack')
                    self.assertEqual(attack['controllerId'], '502')
                    own = raw['robot']['roles'][0]['pos']
                    self.assertEqual(attack['targetPos'], [own]*3)
                    turn = Turn.load(raw)
                    self.assertTrue(all(diagonal_side(Pos.load(p),41,32)*base_side(turn)>=0
                                        for p in attack['targetPos']))
                    self.assertNotIn('502', response['roleCommandMap'])

    def test_http_enemy_only_remains_silent_instead_of_fallback_attack(self):
        for lower in (False, True):
            raw = scene(lower=lower)
            raw['teamOur']['teamId'] = f'final-http-empty-{lower}'
            raw['robot']['roles'] = raw['robot']['roles'][1:]
            self.assertNotIn('601', self.call(raw)['roleCommandMap'])


if __name__ == '__main__':
    unittest.main()
