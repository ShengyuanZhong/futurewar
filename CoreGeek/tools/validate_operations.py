"""Validate the first-night transition and later v1.1.2 economic/repair policy."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from tools.validate_first_day import cases

MODULES = (
    'tests.test_operating_home',
    'tests.test_maintenance',
    'tests.test_focused_upgrades',
    'tests.test_worker_safety',
    'tests.test_worker_schedule',
)
EXTRA = (
    'tests.test_worker_efficiency.WorkerEfficiencyTests.test_only_one_worker_travels_for_the_same_upgrade_purchase',
    'tests.test_worker_efficiency.WorkerEfficiencyTests.test_valid_mining_trip_is_not_abandoned_when_peer_uses_same_mine',
    'tests.test_worker_efficiency.WorkerEfficiencyTests.test_mining_commitment_releases_an_unsafe_or_exhausted_mine',
    'tests.test_first_day_order.FirstDayOrderTests.test_second_day_and_disabled_boss_do_not_lock_weapon_upgrades',
    'tests.test_scout_survival.ScoutSurvivalTests.test_second_day_original_imp_destroy_policy_is_not_given_catch_avoidance',
    'tests.test_opening_defense.OpeningDefenseTests.test_second_day_active_task_retains_previous_night_defence_priority',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    selected = [case for name in MODULES + EXTRA
                for case in cases(unittest.defaultTestLoader.loadTestsFromName(name))]
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
    paths = [p for p in ROOT.rglob('*.py')
             if not any(part in ('build', 'dist', '.venv') for part in p.parts)] + [ROOT / 'pyproject.toml']
    rules = list((ROOT.parent / '32_docs').glob('*')) + [ROOT.parent / 'DEVELOPMENT_RULES.md']
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
        scope='Local day-one/day-two transition, later upgrades/economy/repair regressions; not official match replay',
        policy_reference=dict(version='v1.1.2', commit='6946877',
                              exceptions='Current first-day strategy, v2.0 protocol and hostile robot filtering retained'),
        tests=dict(run=result.testsRun, failures=len(result.failures), errors=len(result.errors)),
        selected_tests=[case.id() for case in selected],
        failures=[dict(test=case.id(), trace=trace) for case, trace in result.failures + result.errors],
        source_hashes={p.relative_to(ROOT.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(paths)},
        rule_hashes={p.relative_to(ROOT.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in rules if p.is_file()},
        unverified=['No new official match or complete adversarial ten-day simulation',
                    'Official moving enemy behavior, spawn displacement and mine respawns',
                    'Local transition fixtures initially supply the first-day built walls'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['tests']))
    raise SystemExit(not result.wasSuccessful())


if __name__ == '__main__':
    main()
