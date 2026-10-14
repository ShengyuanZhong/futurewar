"""Restore the v1.1.2 repair lane after the first night, using observed walls."""
from .upgrade_policy import retained_walls


class OperatingHome:
    def __init__(self, strategy):
        self.s = strategy
        self.turn, self.plan, self.memory = strategy.turn, strategy.plan, strategy.memory
        self.state = self.memory.operating_home
        self.extra = [w for w in self.turn.walls()
                      if w.pos in self.s.settings.opening_only_wall_cells(self.turn)]
        self.enabled = self.turn.day > 1
        self.worker_id = None
        self.state.update(round=self.turn.round_no, enabled=self.enabled,
                          pending=sorted(w.pos for w in self.extra) if self.enabled else [])
        if not self.enabled:
            return
        if not self.extra:
            self.state.update(status='operating', worker_id=None)
            return
        self.state['status'] = 'restoring_lane'
        if not self.turn.is_day:
            return  # Never open a first-night wall while the wave is still active.
        choices = []
        for worker in self.turn.workers():
            cost = min(self.s.cost(worker, [w.pos]) for w in self.extra)
            if cost < 10_000:
                choices.append((worker.unit_id != self.state.get('worker_id'), cost, worker.unit_id))
        if choices:
            self.worker_id = min(choices)[2]
        self.state['worker_id'] = self.worker_id

    def worker(self, role):
        if not self.enabled or not self.turn.is_day or role.unit_id != self.worker_id:
            return False
        previous = self.state.get('target')
        walls = sorted(self.extra, key=lambda w: (w.pos != previous, self.s.cost(role, [w.pos]), w.pos))
        for wall in walls:
            if self.s.interact(role, wall.pos, dict(action='remove', targetPos=[wall.pos.dump()])):
                self.state.update(target=wall.pos, status='awaiting_wall_observation'
                                  if self.plan.commands[str(role.unit_id)]['action'] == 'remove'
                                  else 'approaching_closure')
                self.s.maintenance_claims.add(wall.unit_id)
                return True
        self.state['status'] = 'no_reachable_closure'
        return False

    def retained_walls(self):
        """Do not spend upgrade coupons or repair kits on opening-only closures."""
        return retained_walls(self.s)

    def diagnostic(self):
        return dict(self.state, target_walls=len(self.s.settings.build_cells(self.turn, 'wall')))
