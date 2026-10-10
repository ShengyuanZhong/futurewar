"""First-day observed closure, protected supply and a bounded home repairer."""
import unittest
import json
import tempfile
from pathlib import Path

from agent.actions import ActionPlan
from agent.brain import Strategy
from agent.first_night_defense import FirstNightDefense, FIXER, VOUCHER
from agent.protocol import Pos, Turn
from app.config import Settings
from app.service.memory import GameMemory
from tests.fixtures import robot, unit
from tests.test_maintenance import fortified
from tests.test_u_layout import point


def setup(raw=None, memory=None, boss=False, **overrides):
    raw = fortified(30) if raw is None else raw
    settings = Settings(enable_first_night_defense=True,enable_boss_raid=boss,enable_news=False,**overrides)
    turn = Turn.load(raw)
    plan = ActionPlan(turn,settings)
    s = Strategy(turn,plan,memory or GameMemory(opening_complete=True))
    defense = getattr(s,'first_defense',None) or FirstNightDefense(s)
    s.first_defense = defense
    return s,plan,defense


def actor(raw, uid=501):
    return next(u for u in raw['teamOur']['roles'] if u['id'] == uid)


def ready(raw, position=(8,7), stock=5):
    actor(raw)['pos'] = Pos(*position).dump()
    actor(raw)['backpack'] = [FIXER]*stock
    next(u for u in raw['teamOur']['roles'] if u['id']==601)['level'] = 2
    for item in raw['weaponShopList']:
        if item['name']==FIXER:
            item['price'] = 15
    return raw


class FirstNightDefenseTests(unittest.TestCase):
    def test_constructor_does_not_require_boss_or_scout_objects(self):
        s,_,_ = setup()
        del s.boss_raid
        del s.raid_scouts
        defense = FirstNightDefense(s)
        self.assertTrue(defense.enabled)
        self.assertEqual(defense.worker_id,501)

    def test_home_identity_prefers_gap_then_scout_home_then_existing(self):
        for memory,expected in ((GameMemory(raid_scouts={'home_worker_id':504}),504),
                                (GameMemory(first_night_defense={'worker_id':504}),504)):
            _,_,defense = setup(memory=memory)
            self.assertEqual(defense.worker_id,expected)
        raw,memory = self.occupied_gap()
        s,_,defense = setup(raw,memory)
        self.assertEqual(defense.worker_id,s.gap_guard.worker_id)

    def test_only_living_worker_is_kept_home(self):
        raw = fortified(30)
        actor(raw,501)['health'] = 0
        _,_,defense = setup(raw,memory=GameMemory(first_night_defense={'worker_id':501}))
        self.assertEqual(defense.worker_id,504)

    def test_minimum_readiness_requires_observed_l2_and_real_guard_stock(self):
        raw = ready(fortified(30))
        _,_,defense = setup(raw)
        self.assertTrue(defense.prepared())
        actor(raw)['backpack'].pop()
        _,_,defense = setup(raw)
        self.assertFalse(defense.prepared())
        actor(raw)['backpack'].append(FIXER)
        next(u for u in raw['teamOur']['roles'] if u['id']==601)['level'] = 1
        actor(raw)['backpack'].append(VOUCHER)
        _,_,defense = setup(raw)
        self.assertFalse(defense.prepared())

    def test_stock_target_clamps_to_worker_capacity(self):
        raw = ready(fortified(30),stock=2)
        actor(raw)['backPackCapability'] = 2
        _,_,defense = setup(raw)
        self.assertEqual(defense.stock_target(),2)
        self.assertTrue(defense.prepared())

    def test_missing_wall_is_not_closed_by_a_submitted_build(self):
        raw = fortified(30)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['pos'] != Pos(9,7).dump()]
        actor(raw)['pos'] = Pos(8,7).dump()
        actor(raw)['backpack'] = ['stone']
        s,plan,defense = setup(raw)
        self.assertFalse(defense.closed())
        self.assertFalse(defense.worker(s.turn.workers()[0]))
        self.assertTrue(plan.add(501,{'action':'build','name':'wall','targetPos':[Pos(9,7).dump()]}))
        self.assertFalse(defense.closed())

    def test_occupied_gap_is_not_a_physical_closed_wall(self):
        raw,memory = self.occupied_gap()
        s,_,defense = setup(raw,memory)
        self.assertFalse(defense.closed())
        self.assertTrue(defense.construction_ready())
        self.assertTrue(defense.prepared())
        self.assertEqual(set(s.construction_walls()),{Pos(9,7)})

    def test_reserve_uses_observed_prices_and_does_not_buy_a_team_held_coupon_twice(self):
        raw = fortified(30)
        next(i for i in raw['weaponShopList'] if i['name']==FIXER)['price'] = 15
        _,_,defense = setup(raw)
        self.assertEqual(defense.reserve_gold(),175)
        actor(raw,504)['backpack'] = [VOUCHER]
        _,_,defense = setup(raw)
        self.assertEqual(defense.reserve_gold(),75)

    def test_plan_bought_kits_and_used_coupon_are_not_reserved_again(self):
        raw = fortified(30)
        next(i for i in raw['weaponShopList'] if i['name']==FIXER)['price'] = 15
        actor(raw)['pos'] = Pos(3,7).dump()
        actor(raw,504)['backpack'] = [VOUCHER]
        _,plan,defense = setup(raw)
        self.assertTrue(plan.add(501,{'action':'buy','name':FIXER,'num':5}))
        self.assertTrue(plan.add(504,{'action':'use','name':VOUCHER,'targetPos':[Pos(5,6).dump()]}))
        self.assertEqual(defense.reserve_gold(),0)
        self.assertFalse(defense.prepared())

    def test_supply_buys_five_kits_then_one_coupon_at_the_same_stop(self):
        raw = fortified(30)
        actor(raw)['pos'] = Pos(3,7).dump()
        next(i for i in raw['weaponShopList'] if i['name']==FIXER)['price'] = 15
        memory = GameMemory(opening_complete=True)
        s,plan,defense = setup(raw,memory)
        self.assertTrue(defense.worker(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501'],{'action':'buy','name':FIXER,'num':5})
        memory.record(s.turn,plan)
        raw['roundNo'] += 1
        actor(raw)['backpack'] = [FIXER]*5
        raw['teamOur']['goldNum'] -= 75
        raw['lastRoundRoleActionResults'] = {'501':True}
        s,plan,defense = setup(raw,memory)
        self.assertTrue(defense.worker(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501'],{'action':'buy','name':VOUCHER,'num':1})

    def test_owned_coupon_is_delivered_without_another_purchase(self):
        raw = fortified(30)
        actor(raw)['pos'] = Pos(4,5).dump()
        actor(raw)['backpack'] = [FIXER]*5+[VOUCHER]
        actor(raw,504)['pos'] = Pos(4,9).dump()
        s,plan,defense = setup(raw)
        self.assertTrue(defense.worker(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501'],{'action':'use','name':VOUCHER,'targetPos':[Pos(5,6).dump()]})

    def test_minimum_prepared_guard_continues_normal_l3_upgrade_purchase(self):
        raw = ready(fortified(30),position=(3,7))
        s,plan,defense = setup(raw)
        self.assertTrue(defense.worker(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501'],{'action':'buy','name':'WeaponUpgradeVoucher2','num':1})

    def test_first_night_repairs_below_thirty_percent_even_without_day_three_guard(self):
        for mirrored in (False,True):
            raw = fortified(71,mirrored=mirrored)
            actor(raw)['pos'] = point(8,7,mirrored).dump()
            actor(raw)['backpack'] = [FIXER]*5
            wall = next(u for u in raw['teamOur']['roles'] if u['pos']==point(9,7,mirrored).dump())
            wall['health'] = 100
            raw['robot']['roles'] = [robot(900,*tuple(point(11,7,mirrored).dump().values()))]
            s,plan,defense = setup(raw)
            self.assertIsNone(s.guard.worker_id)
            self.assertTrue(defense.worker(s.turn.workers()[0]))
            self.assertEqual(plan.commands['501'],{'action':'use','name':FIXER,
                                                  'targetPos':[point(9,7,mirrored).dump()]})

    def test_first_night_preserves_on_site_l3_upgrade(self):
        raw = ready(fortified(71),position=(6,5))
        actor(raw)['backpack'].append('WeaponUpgradeVoucher2')
        s,plan,defense = setup(raw)
        self.assertTrue(defense.worker(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501'],{'action':'use','name':'WeaponUpgradeVoucher2',
                                              'targetPos':[Pos(5,6).dump()]})
        self.assertIsNone(s.guard.worker_id)

    def test_night_breach_keeps_worker_inside_instead_of_mining_or_fleeing(self):
        raw = ready(fortified(71),position=(7,5))
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['pos'] != Pos(9,7).dump()]
        raw['mapInfo']['zones'].append({'neutralType':'iron','pos':Pos(20,6).dump()})
        raw['robot']['roles'] = [robot(900,10,7)]
        s,plan,defense = setup(raw)
        self.assertFalse(defense.closed())
        self.assertTrue(defense.worker(s.turn.workers()[0]))
        command = plan.commands.get('501')
        if command:
            self.assertEqual(command['action'],'move')
            self.assertIn(Pos.load(command['targetPos'][0]),s.guard.inner_cells())

    def test_dusk_from_a_distant_mine_returns_without_a_new_supply_or_collect_trip(self):
        raw = ready(fortified(70),position=(20,7))
        raw['mapInfo']['zones'].append({'neutralType':'iron','pos':Pos(20,6).dump()})
        s,plan,defense = setup(raw)
        self.assertTrue(defense.worker(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501']['action'],'move')
        self.assertLess(plan.commands['501']['targetPos'][0]['x'],20)

    def test_late_shop_round_trip_does_not_fit_and_guard_holds_home(self):
        raw = ready(fortified(61),stock=0)
        s,plan,defense = setup(raw)
        self.assertTrue(defense.worker(s.turn.workers()[0]))
        self.assertNotIn('501',plan.commands)
        self.assertIn(501,plan.used)

    def test_occupied_gap_guard_returns_to_a_legal_inner_waiting_post(self):
        raw,memory = self.occupied_gap(number=70)
        actor(raw)['pos'] = Pos(6,5).dump()
        s,plan,defense = setup(raw,memory)
        self.assertTrue(defense.return_home(s.turn.workers()[0]))
        self.assertEqual(plan.commands['501']['action'],'move')
        goal = memory.wall_gap_defense['posts'][501]
        self.assertIn(goal,s.gap_guard.posts())
        self.assertNotIn(goal,{w.pos for w in s.turn.walls()})

    def test_disabled_next_day_and_missing_workers_do_not_reserve_or_take_actions(self):
        for variant in ('disabled','day_two','no_workers'):
            raw = ready(fortified(131 if variant=='day_two' else 30))
            if variant=='no_workers':
                raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['roleType']!='worker']
            s,_,defense = setup(raw)
            if variant=='disabled':
                from dataclasses import replace
                s.settings = replace(s.settings,enable_first_night_defense=False)
                defense = FirstNightDefense(s)
            self.assertEqual(defense.reserve_gold(),0)
            self.assertFalse(defense.prepared())

    def test_diagnostic_has_actual_hp_and_occupied_gaps_without_temp_walls(self):
        raw,memory = self.occupied_gap()
        s,_,defense = setup(raw,memory)
        report = defense.diagnostic()
        self.assertEqual(report['station']['hp'],1500)
        self.assertTrue(all({'id','pos','hp','level'} <= set(w) for w in report['walls']))
        self.assertEqual(report['permanent_missing'],[Pos(9,7).dump()])
        self.assertEqual(report['occupied_gaps'],[Pos(9,7).dump()])
        self.assertFalse(report['closed'])
        self.assertNotIn('temporary_observed',report)

    def test_diagnostic_records_a_destroyed_base_instead_of_omitting_it(self):
        raw = ready(fortified(71))
        actor(raw,503)['health'] = 0
        _,_,defense = setup(raw)
        self.assertFalse(defense.enabled)
        self.assertEqual(defense.diagnostic()['station']['hp'],0)

    def test_many_ore_candidates_share_one_reverse_home_path_search(self):
        raw = ready(fortified(35))
        raw['mapInfo']['zones'] += [{'neutralType':'iron','pos':Pos(x,y).dump()}
                                   for x in (12,15,18,21,24,27,30) for y in (2,5,8,11,14)]
        s,_,defense = setup(raw)
        guard = s.turn.workers()[0]
        for position,kind in s.turn.zones.items():
            if kind in ('stone','iron'):
                defense.trip(guard,{p for p in position.neighbours() if s.turn.land(p)})
        self.assertEqual(len(defense.return_cost_cache),1)

    def test_new_settings_validate_types_and_stock_range(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            for value in (0,-1,101,True,'5'):
                path.write_text(json.dumps({'first_night_repair_stock':value}),encoding='utf-8')
                with self.subTest(stock=value),self.assertRaises(ValueError):
                    Settings.load(str(path))
            for value in (1,'true',None):
                path.write_text(json.dumps({'enable_first_night_defense':value}),encoding='utf-8')
                with self.subTest(enabled=value),self.assertRaises(ValueError):
                    Settings.load(str(path))
            path.write_text(json.dumps({'enable_first_night_defense':False,'first_night_repair_stock':100}),encoding='utf-8')
            configured = Settings.load(str(path))
            self.assertFalse(configured.enable_first_night_defense)
            self.assertEqual(configured.first_night_repair_stock,100)

    def test_strategy_scout_waits_for_defense_then_assigns_only_the_other_worker(self):
        raw = fortified(30)
        s,_,defense = setup(raw,boss=True)
        self.assertFalse(defense.prepared())
        self.assertIsNone(s.memory.raid_scouts.get('worker_id'))
        raw = ready(raw)
        s,_,defense = setup(raw,boss=True)
        self.assertTrue(defense.prepared())
        self.assertEqual(defense.worker_id,501)
        self.assertEqual(s.memory.raid_scouts.get('worker_id'),504)
        self.assertEqual(s.memory.raid_scouts.get('home_worker_id'),501)

    def test_strategy_boss_purchase_has_priority_over_defense_stock(self):
        tasks = {(1,3,9),(1,4,9)}
        for prepared,gold,expected_reserve,quantity in ((False,120,175,1),(False,240,175,2),(True,240,0,2)):
            with self.subTest(prepared=prepared):
                raw = fortified(30)
                actor(raw)['pos'] = Pos(8,7).dump()
                actor(raw,502)['pos'] = Pos(3,7).dump()
                next(i for i in raw['weaponShopList'] if i['name']==FIXER)['price'] = 15
                raw['weaponShopList'].append({'name':'BossRobotSummonOrder','price':120})
                raw['teamOur']['goldNum'] = gold
                if prepared:
                    ready(raw)
                memory = GameMemory(opening_complete=True,task_points_attempted=tasks,
                                    task_points_succeeded=tasks,first_night_defense={'worker_id':501})
                s,plan,defense = setup(raw,memory,boss=True)
                self.assertEqual(defense.reserve_gold(),expected_reserve)
                pioneer = next(u for u in s.turn.controllable() if u.kind=='pioneer')
                self.assertTrue(s.boss_raid.pioneer(pioneer))
                self.assertEqual(plan.commands['502'],{'action':'buy','name':'BossRobotSummonOrder','num':quantity})
                self.assertEqual(plan.gold,gold-120*quantity)

    @staticmethod
    def occupied_gap(number=30):
        raw = ready(fortified(number))
        gap = Pos(9,7)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['pos'] != gap.dump()]
        raw['teamEnemy']['roles'] = [unit(995,'worker',gap.x,gap.y,health=500)]
        actor(raw)['backpack'].append('stone')
        memory = GameMemory(opening_complete=True,first_night_defense={'worker_id':501})
        return raw,memory


if __name__ == '__main__':
    unittest.main()
