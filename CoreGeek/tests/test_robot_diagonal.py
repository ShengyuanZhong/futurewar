"""Range-three square and the exact-45-degree corner rule from the user."""
import unittest
from agent.actions import ActionPlan
from agent.protocol import Pos,Turn,distance
from agent.robot_combat import blocking_wall,clear_attack
from app.config import Settings
from tests.fixtures import request,unit,robot
from tests.test_worker_safety import strategy


def scene(start,end,walls=()):
    raw = request(71)
    raw['teamOur']['roles'] = [unit(503,'station',30,25)]
    raw['teamOur']['playerTasks'] = []
    raw['mapInfo']['zones'] = []
    raw['teamEnemy']['roles'] = [unit(900,'worker',end.x,end.y,health=500)]
    raw['teamEnemy']['roles'] += [unit(901+i,'wall',p.x,p.y,health=1000) for i,p in enumerate(walls)]
    born = robot(31035,start.x,start.y,health=800,roleType='bossRobot',targetTeam='defender')
    raw['teamOur']['summonRobotList'] = [born]
    raw['robot']['roles'] = [born]
    return raw


class RobotDiagonalTests(unittest.TestCase):
    def test_users_one_step_diagonal_ignores_both_side_walls(self):
        raw = scene(Pos(1,1),Pos(0,0),(Pos(0,1),Pos(1,0)))
        s,plan = strategy(raw)
        self.assertIsNone(blocking_wall(s.turn,Pos(1,1),Pos(0,0)))
        self.assertTrue(s.raider.clear_shot(s.turn.summon_robots[0],Pos(0,0)))
        self.assertTrue(plan.add(31035,{'action':'attack','targetPos':[Pos(0,0).dump()]}),plan.rejections)

    def test_all_four_diagonal_directions_and_lengths_one_to_three(self):
        for sx,sy in ((1,1),(1,-1),(-1,1),(-1,-1)):
            for length in (1,2,3):
                with self.subTest(sx=sx,sy=sy,length=length):
                    start = Pos(10,10)
                    end = Pos(10+sx*length,10+sy*length)
                    sides = tuple(p for i in range(length) for p in
                        (Pos(10+sx*i,10+sy*(i+1)),Pos(10+sx*(i+1),10+sy*i)))
                    turn = Turn.load(scene(start,end,sides))
                    self.assertTrue(clear_attack(turn,turn.summon_robots[0],end))

    def test_wall_actually_on_the_diagonal_still_blocks(self):
        for sx,sy in ((1,1),(1,-1),(-1,1),(-1,-1)):
            start,end = Pos(10,10),Pos(10+3*sx,10+3*sy)
            wall = Pos(10+sx,10+sy)
            turn = Turn.load(scene(start,end,(wall,)))
            self.assertEqual(blocking_wall(turn,start,end).pos,wall)
            self.assertFalse(clear_attack(turn,turn.summon_robots[0],end))

    def test_diagonal_blocker_is_nearest_collinear_wall(self):
        start,end = Pos(10,10),Pos(13,13)
        turn = Turn.load(scene(start,end,(Pos(12,12),Pos(11,12),Pos(11,11))))
        self.assertEqual(blocking_wall(turn,start,end).pos,Pos(11,11))

    def test_non_45_degree_corner_contact_keeps_previous_wall_rule(self):
        start,end = Pos(10,10),Pos(13,11)
        turn = Turn.load(scene(start,end,(Pos(11,11),)))
        self.assertIsNotNone(blocking_wall(turn,start,end))
        self.assertFalse(clear_attack(turn,turn.summon_robots[0],end))

    def test_entire_seven_by_seven_square_uses_chebyshev_range(self):
        start = Pos(10,10)
        accepted = 0
        for dx in range(-4,5):
            for dy in range(-4,5):
                if dx==dy==0:
                    continue
                end = Pos(start.x+dx,start.y+dy)
                turn = Turn.load(scene(start,end))
                legal = clear_attack(turn,turn.summon_robots[0],end)
                self.assertEqual(legal,max(abs(dx),abs(dy))<=3,(dx,dy))
                accepted += legal
        self.assertEqual(accepted,48)

    def test_move_and_attack_cannot_be_issued_to_the_same_robot_in_one_round(self):
        raw = scene(Pos(10,10),Pos(13,13))
        turn = Turn.load(raw)
        for first in ('move','attack'):
            plan = ActionPlan(turn,Settings())
            commands = {'move':{'action':'move','targetPos':[Pos(10,11).dump()]},
                        'attack':{'action':'attack','targetPos':[Pos(13,13).dump()]}}
            self.assertTrue(plan.add(31035,commands[first]))
            self.assertFalse(plan.add(31035,commands['attack' if first=='move' else 'move']))
            self.assertEqual(len(plan.commands),1)

    def test_raider_directly_attacks_crew_through_diagonal_corner(self):
        start,end = Pos(10,10),Pos(11,11)
        raw = scene(start,end,(Pos(10,11),Pos(11,10)))
        raw['teamEnemy']['roles'].append(unit(999,'rocket',12,11,health=1000))
        s,plan = strategy(raw)
        self.assertTrue(s.raider.decide(s.turn.summon_robots[0]))
        self.assertEqual(plan.commands['31035'],{'action':'attack','targetPos':[end.dump()]})
