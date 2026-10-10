"""Legal construction rings, a real worker/imp relay and affordable BOSS orders."""
import copy
import unittest
from agent.actions import ActionPlan
from agent.protocol import Pos, Turn, build_command, distance, station_footprint
from app.config import Settings
from app.service.memory import GameMemory
from app.service.turn_service import Session, TurnService
from tests.fixtures import unit, robot
from tests.test_maintenance import fortified
from tests.test_u_layout import point
from tests.test_worker_safety import strategy
from tests.test_summon_control import ORDER, finished_tasks


GAP = Pos(9,7)


def role(raw,uid):
    return next(u for u in raw['teamOur']['roles'] if u['id']==uid)


def occupied(number=60,mirrored=False):
    raw = fortified(number,mirrored)
    gap = point(9,7,mirrored)
    raw['teamOur']['goldNum'] = 0
    raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['pos'] != gap.dump()]
    role(raw,501).update(pos=point(8,7,mirrored).dump(),backpack=['stone'])
    role(raw,504).update(pos=point(4,5,mirrored).dump(),backpack=['stone']*2)
    p = point(8,8,mirrored)
    raw['teamOur']['roles'].append(unit(505,'imp',p.x,p.y,health=500))
    raw['teamEnemy']['roles'] = [unit(901,'worker',gap.x,gap.y,health=500)]
    return raw


def apply_moves(test,raw,s,plan):
    destinations = set()
    for uid,command in plan.commands.items():
        if command['action'] != 'move':
            continue
        target = Pos.load(command['targetPos'][0])
        actor = role(raw,int(uid))
        test.assertEqual(distance(Pos.load(actor['pos']),target),1)
        test.assertNotIn(target,s.turn.occupied_cells())
        test.assertNotIn(target,destinations)
        destinations.add(target)
        actor['pos'] = target.dump()


class GapDefenseTests(unittest.TestCase):
    def test_default_blueprint_uses_only_the_two_actual_rings(self):
        for mirrored in (False,True):
            turn = Turn.load(fortified(30,mirrored))
            base = station_footprint(turn.station().pos)
            settings = Settings()
            for kind,ring,count in (('rocket',1,3),('wall',2,12)):
                cells = settings.build_cells(turn,kind)
                self.assertEqual(len(cells),count)
                self.assertTrue(all(min(distance(p,b) for b in base)==ring for p in cells))

    def test_inner_wall_outer_wall_and_wrong_ring_weapon_are_rejected(self):
        raw = occupied()
        role(raw,501)['pos'] = Pos(8,7).dump()
        turn = Turn.load(raw)
        for target,kind in ((Pos(8,8),'wall'),(Pos(10,7),'wall'),(Pos(9,7),'rocket')):
            plan = ActionPlan(turn,Settings())
            self.assertFalse(plan.add(501,build_command(target,kind)))
        self.assertFalse(hasattr(ActionPlan(turn,Settings()),'authorize_wall_detour'))
        self.assertFalse(hasattr(Settings(),'wall_detour_cells'))

    def test_verified_layout_cannot_authorize_wrong_ring_cells(self):
        raw = fortified(30)
        turn = Turn.load(raw)
        settings = Settings(layouts={'challenger':{'verified':True,'source':'test',
            'weapons':[{'x':3,'y':0},{'x':-1,'y':0}],
            'walls':[{'x':2,'y':0},{'x':3,'y':0}]}})
        self.assertEqual(settings.build_cells(turn,'rocket'),(Pos(5,7),))
        self.assertEqual(settings.build_cells(turn,'wall'),(Pos(9,7),))

    def test_detects_occupied_planned_wall_immediately_without_malice_timer(self):
        s,plan = strategy(occupied(),GameMemory(opening_complete=True))
        self.assertEqual(set(s.gap_guard.gaps),{GAP})
        self.assertEqual(s.gap_guard.worker_id,501)
        self.assertEqual(s.gap_guard.imp_id,505)
        self.assertEqual(s.construction_walls(),[GAP])
        self.assertFalse(hasattr(s.memory,'temporary_wall_sites'))

    def test_non_wall_unit_death_or_offsite_enemy_does_not_create_a_gap_incident(self):
        for kind,health,x,y in (('worker',0,9,7),('rocket',1000,9,7),('worker',500,10,7)):
            raw = occupied()
            raw['teamEnemy']['roles'] = [unit(901,kind,x,y,health=health)]
            s,_ = strategy(raw)
            self.assertFalse(s.gap_guard.gaps)

    def test_unoccupied_other_walls_are_built_before_waiting(self):
        raw = occupied(30)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['pos'] != Pos(9,6).dump()]
        role(raw,501)['pos'] = Pos(8,6).dump()
        s,plan = strategy(raw,GameMemory())
        self.assertFalse(s.gap_guard.worker(s.turn.workers()[0]))
        s.run()
        builds = [c for c in plan.commands.values() if c['action']=='build']
        self.assertIn(build_command(Pos(9,6),'wall'),builds)
        self.assertTrue(all(Pos.load(c['targetPos'][0]) in s.settings.build_cells(s.turn,c['name']) for c in builds))

    def test_two_workers_continue_distinct_remaining_wall_jobs(self):
        raw = occupied(25)
        for p in (Pos(9,8),Pos(9,6)):
            raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['pos'] != p.dump()]
        role(raw,501).update(pos=Pos(8,6).dump(),backpack=['stone']*3)
        role(raw,504).update(pos=Pos(8,5).dump(),backpack=['stone']*2)
        role(raw,505)['pos'] = Pos(6,8).dump()
        s,plan = strategy(raw,GameMemory())
        s.run()
        self.assertTrue(all(uid in plan.commands for uid in ('501','504')))
        self.assertNotEqual(plan.commands['501'].get('targetPos'),plan.commands['504'].get('targetPos'))
        self.assertFalse(any(c['action']=='remove' for c in plan.commands.values()))

    def test_dusk_waits_adjacent_and_never_builds_extra_walls(self):
        raw = occupied(70)
        s,plan = strategy(raw)
        s.run()
        self.assertIn(501,plan.used)
        self.assertEqual(s.coordinator.job(s.turn.workers()[0])['kind'],'gap_wait')
        self.assertNotIn('501',plan.commands)
        self.assertFalse(any(c['action'] in ('build','remove') for c in plan.commands.values()))

    def test_enemy_still_on_gap_prevents_illegal_movement_at_night(self):
        raw = occupied(71)
        s,plan = strategy(raw)
        s.run()
        self.assertNotEqual(plan.commands.get('501',{}).get('targetPos'),[GAP.dump()])
        self.assertEqual(plan.rejections,[])
        self.assertIn(501,plan.used)

    def test_worker_enters_vacated_gap_and_holds_both_mirrors(self):
        for mirrored in (False,True):
            raw = occupied(70,mirrored)
            memory = GameMemory(opening_complete=True)
            strategy(raw,memory)
            raw['roundNo'] = 71
            raw['teamEnemy']['roles'] = []
            s,plan = strategy(raw,memory)
            s.run()
            self.assertEqual(plan.commands['501'],{'action':'move','targetPos':[point(9,7,mirrored).dump()]})
            apply_moves(self,raw,s,plan)
            memory.record(s.turn,plan)
            raw['roundNo'] = 72
            s,plan = strategy(raw,memory);s.run()
            self.assertNotIn('501',plan.commands)
            self.assertIn(501,plan.used)
            self.assertEqual(s.coordinator.job(s.turn.workers()[0])['kind'],'gap_body')

    def test_body_guard_does_not_evade_even_with_robots_in_range(self):
        raw = occupied(70)
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw['roundNo'] = 71
        raw['teamEnemy']['roles'] = []
        role(raw,501)['pos'] = GAP.dump()
        raw['robot']['roles'] = [robot(902,10,7)]
        s,plan = strategy(raw,memory);s.run()
        self.assertGreater(s.danger.get(GAP,0),0)
        self.assertNotIn('501',plan.commands)
        self.assertIn(501,plan.used)

    def test_low_hp_alive_worker_does_not_trigger_early_imp_takeover(self):
        raw = occupied(70)
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw['roundNo'] = 71
        raw['teamEnemy']['roles'] = []
        role(raw,501).update(pos=GAP.dump(),health=1)
        s,plan = strategy(raw,memory);s.run()
        self.assertNotEqual(plan.commands.get('505',{}).get('targetPos'),[GAP.dump()])
        self.assertEqual(memory.wall_gap_defense['imp_status'],'standby')

    def test_standby_imp_does_not_cross_gap_while_the_worker_is_alive(self):
        raw = occupied(70)
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw.update(roundNo=71)
        raw['teamEnemy']['roles'] = []
        role(raw,505)['pos'] = Pos(10,7).dump()
        s,plan = strategy(raw,memory);s.run()
        imp = next(iter(s.turn.imps()))
        self.assertIn(GAP,s.movement_reserved(imp))
        self.assertNotEqual(plan.commands.get('505',{}).get('targetPos'),[GAP.dump()])
        self.assertEqual(plan.commands['501']['targetPos'],[GAP.dump()])

    def test_imp_takes_over_only_after_worker_is_observed_dead_or_absent(self):
        for death in ('dead','absent'):
            raw = occupied(70)
            memory = GameMemory(opening_complete=True)
            strategy(raw,memory)
            raw['roundNo'] = 72
            raw['teamEnemy']['roles'] = []
            if death=='dead':
                role(raw,501).update(pos=GAP.dump(),health=0)
            else:
                raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['id']!=501]
            s,plan = strategy(raw,memory);s.run()
            self.assertEqual(s.gap_guard.worker_id,501)
            self.assertEqual(plan.commands['505'],{'action':'move','targetPos':[GAP.dump()]})
            self.assertEqual(plan.rejections,[])
            self.assertNotEqual(s.gap_guard.worker_id,504)

    def test_imp_holds_gap_after_takeover_instead_of_destroying_or_scouting(self):
        raw = occupied(70)
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw['roundNo'] = 73
        raw['teamEnemy']['roles'] = []
        role(raw,501)['health'] = 0
        role(raw,505)['pos'] = GAP.dump()
        s,plan = strategy(raw,memory);s.run()
        self.assertIn(505,plan.used)
        self.assertNotIn('505',plan.commands)

    def test_imp_leaves_gap_in_daylight_so_worker_can_build_on_next_observation(self):
        raw = occupied(70)
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw['roundNo'] = 131
        raw['teamEnemy']['roles'] = []
        role(raw,505)['pos'] = GAP.dump()
        s,plan = strategy(raw,memory);s.run()
        self.assertEqual(plan.commands['505']['action'],'move')
        self.assertNotEqual(plan.commands.get('501',{}).get('action'),'build')
        apply_moves(self,raw,s,plan)
        memory.record(s.turn,plan)
        raw['roundNo'] = 132
        s,plan = strategy(raw,memory);s.run()
        self.assertEqual(plan.commands['501'],build_command(GAP,'wall'))

    def test_daytime_rebuild_from_far_away_precedes_supply(self):
        raw = occupied(60)
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw['roundNo'] = 61
        raw['teamEnemy']['roles'] = []
        role(raw,501)['pos'] = Pos(6,5).dump()
        s,plan = strategy(raw,memory);s.run()
        self.assertEqual(s.coordinator.job(next(w for w in s.turn.workers() if w.unit_id==501))['kind'],'gap_rebuild')
        self.assertEqual(plan.commands['501']['action'],'move')

    def test_actual_wall_restored_releases_roles_without_remove(self):
        raw = occupied()
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw['teamOur']['roles'].append(unit(777,'wall',9,7,health=1000))
        raw['teamEnemy']['roles'] = []
        s,plan = strategy(raw,memory);s.run()
        self.assertFalse(memory.wall_gap_defense)
        self.assertFalse(any(c['action']=='remove' for c in plan.commands.values()))

    def test_holding_worker_can_repair_adjacent_wall_without_abandoning_gap(self):
        raw = occupied(70)
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw['roundNo'] = 71
        raw['teamEnemy']['roles'] = []
        role(raw,501).update(pos=GAP.dump(),backpack=['stone','WallFixer'])
        next(u for u in raw['teamOur']['roles'] if u['pos']==Pos(9,6).dump())['health'] = 100
        s,plan = strategy(raw,memory);s.run()
        self.assertEqual(plan.commands['501'],{'action':'use','name':'WallFixer','targetPos':[Pos(9,6).dump()]})

    def test_guard_medicine_does_not_vacate_gap(self):
        raw = occupied(70)
        memory = GameMemory(opening_complete=True)
        strategy(raw,memory)
        raw['roundNo'] = 71
        raw['teamEnemy']['roles'] = []
        role(raw,501).update(pos=GAP.dump(),health=200,backpack=['Medicine'])
        s,plan = strategy(raw,memory);s.run()
        self.assertEqual(plan.commands['501'],{'action':'use','name':'Medicine'})

    def test_no_workers_can_use_surviving_imp_as_night_replacement(self):
        raw = occupied(71)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['roleType']!='worker']
        memory = GameMemory(wall_gap_defense={'gaps':{GAP:{}},'worker_id':501})
        raw['teamEnemy']['roles'] = []
        s,plan = strategy(raw,memory);s.run()
        self.assertEqual(plan.commands['505']['targetPos'],[GAP.dump()])

    def test_corner_imp_stays_near_the_only_worker_post_then_closes_up_and_takes_over(self):
        for mirrored in (False,True):
            raw = occupied(70,mirrored)
            center,corner = point(9,7,mirrored),point(9,9,mirrored)
            raw['teamOur']['roles'].append(unit(777,'wall',center.x,center.y,health=1000))
            raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['pos'] != corner.dump()]
            raw['teamEnemy']['roles'][0]['pos'] = corner.dump()
            role(raw,501)['pos'] = point(8,8,mirrored).dump()
            role(raw,505)['pos'] = point(6,5,mirrored).dump()
            memory = GameMemory(opening_complete=True)
            s,plan = strategy(raw,memory);s.run()
            self.assertEqual(plan.commands['505']['action'],'move')
            goal = memory.wall_gap_defense['posts'][505]
            self.assertLessEqual(distance(goal,corner),2)
            self.assertNotEqual(goal,point(8,8,mirrored))
            role(raw,505)['pos'] = goal.dump()
            raw.update(roundNo=71)
            raw['teamEnemy']['roles'] = []
            s,plan = strategy(raw,memory);s.run()
            self.assertEqual(plan.commands['501']['targetPos'],[corner.dump()])
            apply_moves(self,raw,s,plan);memory.record(s.turn,plan)
            raw['roundNo'] = 72
            s,plan = strategy(raw,memory);s.run()
            self.assertEqual(plan.commands['505']['targetPos'],[point(8,8,mirrored).dump()])
            apply_moves(self,raw,s,plan);memory.record(s.turn,plan)
            raw['roundNo'] = 73
            role(raw,501)['health'] = 0
            s,plan = strategy(raw,memory);s.run()
            self.assertEqual(plan.commands['505']['targetPos'],[corner.dump()])

    def test_corner_daytime_reserve_yields_builder_post_and_lane_until_wall_is_rebuilt(self):
        for mirrored in (False,True):
            raw = occupied(70,mirrored)
            center,corner = point(9,7,mirrored),point(9,9,mirrored)
            raw['teamOur']['roles'].append(unit(777,'wall',center.x,center.y,health=1000))
            raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['pos'] != corner.dump()]
            raw['teamEnemy']['roles'][0]['pos'] = corner.dump()
            memory = GameMemory(opening_complete=True)
            strategy(raw,memory)
            raw['teamEnemy']['roles'] = []
            role(raw,505)['pos'] = corner.dump()
            role(raw,501)['pos'] = point(6,5,mirrored).dump()
            for number in range(131,145):
                raw['roundNo'] = number
                s,plan = strategy(raw,memory);s.run()
                if plan.commands.get('501')==build_command(corner,'wall'):
                    break
                self.assertNotEqual(plan.commands.get('501',{}).get('action'),'collect')
                apply_moves(self,raw,s,plan);memory.record(s.turn,plan)
            else:
                self.fail('reserve imp prevented the corner wall rebuild')

    def test_lost_base_releases_gap_roles_without_a_none_target(self):
        raw = occupied(71)
        role(raw,503)['health'] = 0
        memory = GameMemory(wall_gap_defense={'gaps':{GAP:{}},'worker_id':501,'imp_id':505})
        s,plan = strategy(raw,memory);s.run()
        self.assertFalse(s.gap_guard.gaps)
        self.assertFalse(memory.wall_gap_defense)
        self.assertFalse(any(p is None for c in plan.commands.values() for p in c.get('targetPos',[])))


class BossPurchaseRegressionTests(unittest.TestCase):
    def setup_raid(self,gold=120,number=30):
        raw = occupied(number)
        role(raw,502)['pos'] = Pos(3,7).dump()
        raw['teamOur']['goldNum'] = gold
        raw['weaponShopList'].append({'name':ORDER,'price':120})
        raw['teamEnemy']['roles'].append(unit(990,'station',33,25))
        settings = Settings(enable_first_night_defense=True,enable_news=False)
        return raw,finished_tasks(),settings

    def test_affordable_order_is_bought_despite_blocked_wall_and_unfunded_guard(self):
        raw,memory,settings = self.setup_raid()
        s,plan = strategy(raw,memory,settings);s.run()
        self.assertFalse(s.first_defense.closed())
        self.assertGreater(s.first_defense.reserve_gold(),120)
        self.assertEqual(plan.commands['502'],{'action':'buy','name':ORDER,'num':1})
        self.assertEqual(plan.gold,0)

    def test_two_orders_remain_affordable_before_guard_stock(self):
        raw,memory,settings = self.setup_raid(240)
        s,plan = strategy(raw,memory,settings);s.run()
        self.assertEqual(plan.commands['502'],{'action':'buy','name':ORDER,'num':2})
        self.assertEqual(plan.gold,0)

    def test_single_affordability_with_known_history_does_not_require_two_task_attempts(self):
        raw,_,settings = self.setup_raid()
        memory = GameMemory(opening_complete=True,last_round=29,day=1)
        s,plan = strategy(raw,memory,settings);s.run()
        self.assertEqual(plan.commands['502'],{'action':'buy','name':ORDER,'num':1})

    def test_worker_supply_cannot_spend_reserved_order_while_pioneer_walks(self):
        raw,memory,settings = self.setup_raid()
        role(raw,502)['pos'] = Pos(4,7).dump()
        role(raw,501)['pos'] = Pos(3,7).dump()
        s,plan = strategy(raw,memory,settings);s.run()
        self.assertEqual(plan.commands['502']['action'],'move')
        self.assertFalse(any(c['action']=='buy' for c in plan.commands.values()))
        self.assertEqual(s.boss_raid.budget_reserve(),120)

    def test_carried_order_is_used_when_wall_gap_is_still_open(self):
        raw,memory,settings = self.setup_raid(0)
        role(raw,502)['backpack'] = [ORDER]
        s,plan = strategy(raw,memory,settings);s.run()
        self.assertEqual(plan.commands['502']['action'],'use')
        self.assertEqual(plan.commands['502']['name'],ORDER)
        self.assertFalse(s.first_defense.closed())

    def test_not_enough_gold_or_return_time_does_not_force_illegal_purchase(self):
        for gold,number in ((119,30),(120,69)):
            raw,memory,settings = self.setup_raid(gold,number)
            s,plan = strategy(raw,memory,settings);s.run()
            self.assertFalse(any(c['action']=='buy' and c.get('name')==ORDER for c in plan.commands.values()))
            self.assertEqual(plan.rejections,[])

    def test_active_task_is_not_interrupted_for_purchase(self):
        raw,memory,settings = self.setup_raid(240)
        raw['phaseTask'] = 'active synthetic task'
        s,plan = strategy(raw,memory,settings)
        self.assertFalse(s.boss_raid.pioneer(next(u for u in s.turn.controllable() if u.kind=='pioneer')))
        self.assertEqual(memory.boss_raid['decision']['reason'],'active_task')

    def test_guard_does_not_spend_boss_budget_during_an_active_task(self):
        raw,memory,settings = self.setup_raid(120)
        raw['phaseTask'] = 'active synthetic task'
        role(raw,502)['pos'] = Pos(4,7).dump()
        role(raw,501)['pos'] = Pos(3,7).dump()
        s,plan = strategy(raw,memory,settings)
        self.assertEqual(s.boss_raid.budget_reserve(),120)
        self.assertFalse(s.first_defense.supply(next(w for w in s.turn.workers() if w.unit_id==501)))
        self.assertFalse(any(c['action']=='buy' for c in plan.commands.values()))

    def test_gap_standby_imp_overrides_enemy_rear_scout_but_other_worker_supplies_sight(self):
        raw,memory,settings = self.setup_raid(0)
        role(raw,504)['pos'] = Pos(37,23).dump()
        s,plan = strategy(raw,memory,settings);s.run()
        self.assertEqual(s.gap_guard.imp_id,505)
        self.assertEqual(memory.raid_scouts.get('worker_id'),504)
        self.assertNotIn(505,memory.raid_scouts.get('posts',{}))

    def test_service_purchase_inventory_feedback_then_use_is_not_blocked_by_missing_wall(self):
        raw,memory,settings = self.setup_raid(120)
        service = TurnService(settings)
        key = (raw['teamOur']['teamId'],raw['teamOur']['type'])
        service.sessions[key] = Session(memory=memory)
        response = service.decide(copy.deepcopy(raw))
        self.assertEqual(response['roleCommandMap']['502'],{'action':'buy','name':ORDER,'num':1})
        raw.update(roundNo=31,lastRoundRoleActionResults={'502':True})
        raw['teamOur']['goldNum'] = 0
        role(raw,502)['backpack'] = [ORDER]
        response = service.decide(copy.deepcopy(raw))
        self.assertEqual(response['roleCommandMap']['502']['action'],'use')
        raw.update(roundNo=32,lastRoundRoleActionResults={'502':True})
        role(raw,502)['backpack'] = []
        service.decide(copy.deepcopy(raw))
        self.assertEqual(service.sessions[key].memory.boss_raid['deployed_count'],1)
        self.assertEqual(service.sessions[key].memory.summon_attempts,1)
