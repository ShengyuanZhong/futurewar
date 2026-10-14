"""Stable upper/lower scouting legs, with real catch avoidance on every step."""
from .protocol import Pos, distance, station_footprint


def flank_step(scouts, role, post):
    """Return an optional first-survey detour step; never invent a clear route."""
    turn = scouts.turn
    jobs = scouts.state.setdefault('imp_flanks', {})
    job = jobs.get(role.unit_id)
    if scouts.state.get('layout_ready'):
        if job:
            job.update(complete=True, reason='layout_confirmed')
        return None
    if job and job.get('base') != scouts.base:
        jobs.pop(role.unit_id)
        job = None
    if job and job.get('complete'):
        return None
    # A late observation already near the build ring must not send the scout
    # back across the map merely to recreate an opening trip.
    if job is None and min(distance(role.pos, p) for p in station_footprint(scouts.base)) <= 8:
        return None
    full = scouts.scout_route(role)
    if job is None:
        rows = (('south', max(1, min(role.pos.y, scouts.base.y-1)-5)),
                ('north', min(turn.height-2, max(role.pos.y, scouts.base.y)+5)))
        options = []
        blocked = turn.blocked(role) | scouts.s.movement_reserved(role)
        for side, y in rows:
            entry = full.nearest(Pos(x, y) for x in range(max(0, role.pos.x-1), min(turn.width, role.pos.x+2)))
            crossing = full.nearest(Pos(x, y) for x in range(max(0, post.x-1), min(turn.width, post.x+2)))
            if entry is None or crossing is None or entry in blocked or crossing in blocked:
                continue
            cost = full.cost[entry] + distance(entry, crossing) + distance(crossing, post)
            options.append(((cost, abs(y-role.pos.y), side), side, entry, crossing))
        if not options:
            return None
        _, side, entry, crossing = min(options, key=lambda row: row[0])
        job = dict(base=scouts.base, side=side, entry=entry, crossing=crossing,
                   phase='outbound', started=turn.round_no, complete=False)
        jobs[role.unit_id] = job
    if job['phase'] == 'outbound' and role.pos == job['entry']:
        job['phase'] = 'crossing'
    if job['phase'] == 'crossing' and role.pos == job['crossing']:
        job.update(phase='approach', reason='flank_reached')
    if job['phase'] == 'approach' and role.pos == post:
        job.update(complete=True, reason='lookout_reached')
        return None
    goal = job['entry'] if job['phase'] == 'outbound' else job['crossing'] if job['phase']=='crossing' else post
    if job['phase'] == 'outbound':
        allowed = {Pos(x, y) for x in range(max(0, job['entry'].x-2), min(turn.width, job['entry'].x+3))
                   for y in range(turn.height)}
    elif job['phase']=='crossing':
        allowed = {Pos(x, y) for x in range(turn.width)
                   for y in range(max(0, goal.y-1), min(turn.height, goal.y+2))}
    else:
        allowed = {Pos(x,y) for x in range(max(0,min(goal.x,job['crossing'].x)-1),
                                          min(turn.width,max(goal.x,job['crossing'].x)+2))
                   for y in range(turn.height)}
    route = scouts.scout_route(role, allowed=allowed)
    step = route.step({goal})
    job.update(round=turn.round_no, waypoint=goal,
               reason='flank_travelling' if step is not None else 'flank_blocked_use_safe_route')
    if step is None:
        job.update(complete=True, phase='fallback')
    # Catch avoidance is already part of scout_route, including emergency
    # outward steps at distance one/two. Never relax that for a planned flank.
    return step
