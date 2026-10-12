"""Real task attempts, including a repeated first point, without coordinate dedup."""

TASK_SEQUENCE = (1, 2, 1)
FIRST_DAY_LIMIT = len(TASK_SEQUENCE)


def task_number(kind):
    return 2 if str(kind).endswith('2') else 1


def task_attempts(memory, day=1):
    return [(key, job) for key, job in sorted(memory.task_attempts.items()) if key[0] == day]


def record_attempt(memory, day, accepted_round, point, kind='', origin='accepted'):
    key = (day, accepted_round, *point)
    memory.task_attempts.setdefault(key, dict(kind=kind, point=tuple(point),
        origin=origin, finished=False, succeeded=False))
    memory.task_active_attempt = key
    memory.task_points_attempted.add((day,*point))
    return key


def finish_attempt(memory, key, round_no, succeeded=False, reason='ended'):
    job = memory.task_attempts.get(key)
    if job is None:
        return
    if not job['finished']:
        job.update(finished=True, finished_round=round_no, reason=reason)
    job['succeeded'] = job['succeeded'] or succeeded
    memory.task_points_finished.add((key[0],*job['point']))
    if job['succeeded']:
        memory.task_points_succeeded.add((key[0],*job['point']))


def finished_count(memory, day=1):
    return sum(job['finished'] for _,job in task_attempts(memory,day)[:FIRST_DAY_LIMIT])


def success_count(memory, day=1):
    return sum(job['succeeded'] for _,job in task_attempts(memory,day)[:FIRST_DAY_LIMIT])
