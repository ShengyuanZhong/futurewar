"""Drawing-specific upgrade targets and two-worker maintenance end state."""
import unittest
import copy
from agent.protocol import Pos
from app.service.turn_service import TurnService
from tests.test_maintenance import fortified, setup
from tests.test_u_layout import point


def set_wall(raw, x, y, level, mirrored=False, health=None):
    wall = next(r for r in raw['teamOur']['roles'] if r['roleType'] == 'wall' and r['pos'] == point(x, y, mirrored).dump())
    wall.update(level=level, health=health if health is not None else 500 + 500 * level)
    return wall


def finished(round_no=331, mirrored=False):
    raw = fortified(round_no, mirrored=mirrored, weapon_level=3, wall_level=2)
    for y in range(4, 10): set_wall(raw, 9, y, 3, mirrored)
    for i, y in ((2, 7), (3, 6)):
        raw['teamOur']['roles'][i].update(pos=point(8, y, mirrored).dump(), backpack=['WallFixer'] * 5)
    return raw


class FocusedUpgradesTests(unittest.TestCase):
    def test_same_rocket_reaches_three_before_any_other_upgrade(self):
        raw = fortified()
        s, _ = setup(raw)
        pending = s.upgrade_candidates()
        self.assertEqual(len(pending), 1)
        target = next(r for r in raw['teamOur']['roles'] if r['id'] == pending[0].unit_id)
        target.update(level=2, health=1500)
        s, _ = setup(raw)
        self.assertEqual([r.unit_id for r in s.upgrade_candidates()], [target['id']])
        self.assertEqual(s.upgrade_name(s.upgrade_candidates()[0]), 'WeaponUpgradeVoucher2')

    def test_drawing_wall_stages_and_mirror(self):
        for mirrored in (False, True):
            raw = fortified(mirrored=mirrored)
            towers = [r for r in raw['teamOur']['roles'] if r['roleType']=='rocket']
            towers[0].update(level=3, health=2000)
            for level in (1,2):
                s,_=setup(raw)
                self.assertEqual({w.pos for w in s.upgrade_candidates()}, {point(9,y,mirrored) for y in (7,6)})
                self.assertTrue(all(w.level==level for w in s.upgrade_candidates()))
                for y in (7,6):set_wall(raw,9,y,level+1,mirrored)
            s,_=setup(raw)
            self.assertEqual([(w.unit_id,w.level) for w in s.upgrade_candidates()],[(towers[1]['id'],1)])
            towers[1].update(level=2,health=1500)
            for level in (1,2):
                s,_=setup(raw)
                self.assertEqual({w.pos for w in s.upgrade_candidates()}, {point(9,y,mirrored) for y in (9,8,5,4)})
                self.assertTrue(all(w.level==level for w in s.upgrade_candidates()))
                for y in (9,8,5,4):set_wall(raw,9,y,level+1,mirrored)
            for tower,level in ((towers[1],2),(towers[2],1),(towers[2],2)):
                s,_=setup(raw)
                self.assertEqual([(w.unit_id,w.level) for w in s.upgrade_candidates()],[(tower['id'],level)])
                tower.update(level=level+1,health=500+500*(level+1))
            s,_=setup(raw)
            cells={(x,y) for x in (6,7,8) for y in (4,9)}
            self.assertEqual({w.pos for w in s.upgrade_candidates()},{point(x,y,mirrored) for x,y in cells})
            for x,y in cells:set_wall(raw,x,y,2,mirrored)
            s,_=setup(raw)
            self.assertTrue(s.upgrades_complete())
            self.assertEqual(s.upgrade_candidates(),[])

    def test_rear_wall_stops_at_two_and_base_is_excluded(self):
        raw = finished(261)
        raw['teamOur']['roles'][0].update(level=1, health=1)
        raw['teamOur']['roles'][2]['backpack']=['StationUpgradeVoucher1','StationUpgradeVoucher2']
        s,plan=setup(raw)
        self.assertEqual(s.upgrade_candidates(), [])
        self.assertTrue(s.upgrades_complete())
        self.assertFalse(s.buy_upgrade(s.turn.workers()[0]))
        self.assertFalse(s.consume(s.turn.workers()[0]))
        self.assertEqual(plan.commands,{})

    def test_second_rocket_does_not_prebuy_level_three_before_front_walls(self):
        raw=fortified()
        next(r for r in raw['teamOur']['roles'] if r['roleType']=='rocket').update(level=3,health=2000)
        for y in (7,6):set_wall(raw,9,y,3)
        raw['teamOur']['roles'][2].update(pos={'x':3,'y':7},backpack=['WeaponUpgradeVoucher1'])
        s,plan=setup(raw)
        self.assertFalse(s.buy_upgrade(s.turn.workers()[0]))
        self.assertEqual(plan.commands,{})

    def test_focus_coupons_can_be_prepared_in_one_shop_visit(self):
        raw=fortified()
        raw['teamOur']['roles'][2].update(pos={'x':3,'y':7},backpack=['WeaponUpgradeVoucher1'])
        s, plan=setup(raw)
        s.worker(s.turn.workers()[0])
        self.assertEqual(plan.commands['501'], {'action':'buy','name':'WeaponUpgradeVoucher2','num':1})

    def test_both_workers_repair_distinct_walls_in_final_stage(self):
        for mirrored in (False,True):
            raw=finished(mirrored=mirrored)
            set_wall(raw,9,7,3,mirrored,100)
            set_wall(raw,9,6,3,mirrored,150)
            s,plan=setup(raw);s.run()
            repairs=[plan.commands.get(str(uid),{}) for uid in (501,504)]
            self.assertTrue(all(c.get('name')=='WallFixer' for c in repairs))
            self.assertNotEqual(repairs[0]['targetPos'],repairs[1]['targetPos'])
            self.assertEqual(plan.rejections,[])

    def test_final_workers_hold_inside_day_and_night_without_mining(self):
        for number in (201,261,331):
            raw=finished(number);raw['teamOur']['goldNum']=0
            s,plan=setup(raw);s.run()
            for uid in (501,504):
                cmd=plan.commands.get(str(uid),{})
                self.assertNotIn(cmd.get('action'),('collect','buy','sell'))
                if cmd.get('action')=='move': self.assertIn(Pos.load(cmd['targetPos'][0]),s.guard.inner_cells())

    def test_final_purchase_uses_budget_beyond_five_and_shares_stock(self):
        raw=finished(261);raw['teamOur']['goldNum']=200
        raw['teamOur']['roles'][2].update(pos={'x':3,'y':7},backpack=[])
        raw['teamOur']['roles'][3]['backpack']=[]
        s,plan=setup(raw);s.run()
        self.assertEqual(plan.commands['501'],{'action':'buy','name':'WallFixer','num':10})
        self.assertEqual(plan.gold,100)
        self.assertNotEqual(plan.commands.get('504',{}).get('action'),'buy')

    def test_final_night_never_leaves_for_kits(self):
        raw=finished();raw['teamOur']['goldNum']=500
        for i in (2,3):raw['teamOur']['roles'][i]['backpack']=[]
        s,plan=setup(raw);s.run()
        for uid in (501,504):
            cmd=plan.commands.get(str(uid),{})
            self.assertNotEqual(cmd.get('action'),'buy')
            if cmd.get('action')=='move':self.assertIn(Pos.load(cmd['targetPos'][0]),s.guard.inner_cells())

    def test_missing_wall_exits_completed_mode_for_rebuilding(self):
        raw=finished(261);set_wall(raw,9,7,3,health=0)
        s,_=setup(raw)
        self.assertFalse(s.upgrades_complete())

    def test_final_mode_does_not_purchase_treasure_items(self):
        raw=finished(261)
        raw['teamOur']['roles'][1]['pos']={'x':3,'y':7}
        raw['weaponShopList'].append({'name':'AcientTablet','price':1})
        s,plan=setup(raw)
        pioneer=s.turn.alive(('pioneer',))[0]
        s.memory.treasure={'targetPos':pioneer.pos.dump(),'items':['AcientTablet'],'startRound':261,'endRound':300}
        self.assertFalse(s.treasure(pioneer))
        self.assertEqual(plan.commands,{})

    def test_supplier_round_trips_spend_all_affordable_gold_with_one_guard_home(self):
        raw=finished(261);raw['teamOur']['goldNum']=200
        service=TurnService()
        purchases=[]
        for number in range(261,321):
            raw['roundNo']=number
            s,_=setup(raw)
            reply=service.decide(copy.deepcopy(raw))
            for uid,command in reply['roleCommandMap'].items():
                actor=next(r for r in raw['teamOur']['roles'] if str(r['id'])==uid)
                if actor['roleType']!='worker':continue
                if command['action']=='move':
                    actor['pos']=command['targetPos'][0]
                elif command['action']=='buy':
                    self.assertEqual(command['name'],'WallFixer')
                    raw['teamOur']['goldNum']-=command['num']*10
                    actor['backpack']+=['WallFixer']*command['num']
                    purchases.append(uid)
                else:self.fail(f'unexpected final-duty action: {command}')
            workers=[r for r in raw['teamOur']['roles'] if r['roleType']=='worker']
            self.assertGreaterEqual(sum(Pos.load(r['pos']) in s.guard.inner_cells() for r in workers),1)
            if raw['teamOur']['goldNum']==0 and all(Pos.load(w['pos']) in s.guard.inner_cells() for w in workers):break
        else:self.fail('suppliers failed to finish both round trips')
        self.assertEqual(purchases,['501','504'])
        self.assertEqual([w['backpack'].count('WallFixer') for w in workers],[15,15])

    def test_one_critical_wall_is_not_repaired_twice_and_threshold_is_strict(self):
        for health,expected in ((599,1),(600,0)):
            raw=finished();set_wall(raw,9,7,3,health=health)
            s,plan=setup(raw);s.run()
            self.assertEqual(sum(c.get('name')=='WallFixer' for c in plan.commands.values()),expected)
            self.assertEqual(plan.rejections,[])

    def test_final_restock_respects_capacity_price_and_dusk(self):
        for gold,price,bag,expected in ((100,10,['stone']*99,1),(0,0,['stone']*98,2),(5,10,[],0)):
            raw=finished(261);raw['teamOur']['goldNum']=gold
            raw['teamOur']['roles'][2].update(pos={'x':3,'y':7},backpack=bag)
            raw['teamOur']['roles'][3]['backpack']=['WallFixer']*100
            raw['weaponShopList'][-1]['price']=price
            s,plan=setup(raw);s.run()
            self.assertEqual(plan.commands.get('501',{}).get('num',0),expected)
        raw=finished(330);raw['teamOur']['roles'][2].update(pos={'x':3,'y':7},backpack=[])
        s,plan=setup(raw);s.run()
        self.assertNotEqual(plan.commands.get('501',{}).get('action'),'buy')

    def test_dead_supplier_reassigned_and_final_duty_starts_before_day_three(self):
        raw=finished(131)
        raw['teamOur']['roles'][2]['health']=0
        raw['teamOur']['roles'][3].update(pos={'x':3,'y':7},backpack=[])
        raw['teamOur']['goldNum']=100
        s,plan=setup(raw);s.memory.repair_supplier_id=501
        # Recreate using the dead supplier memory, as the next request does.
        from agent.brain import Strategy
        s=Strategy(s.turn,plan,s.memory);s.run()
        self.assertEqual(s.memory.repair_supplier_id,504)
        self.assertEqual(plan.commands['504'],{'action':'buy','name':'WallFixer','num':10})
