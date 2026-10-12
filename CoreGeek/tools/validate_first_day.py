"""Run only the first-day regressions requested for the current iteration."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'src')]

MODULES = (
    'tests.test_opening_log_regressions',
    'tests.test_pioneer_log_regressions',
    'tests.test_scout_bug_regression',
    'tests.test_three_tasks',
    'tests.test_first_day_order',
    'tests.test_opening_defense',
    'tests.test_scout_survival',
)
EXCLUDED = {
    'tests.test_first_day_order.FirstDayOrderTests.test_second_day_and_disabled_boss_do_not_lock_weapon_upgrades',
    'tests.test_scout_survival.ScoutSurvivalTests.test_second_day_original_imp_destroy_policy_is_not_given_catch_avoidance',
}
EXTRA = (
    'tests.test_layout_survey.LayoutSurveyTests.test_last_wall_command_is_not_actual_construction_completion',
    'tests.test_gap_defense.GapDefenseTests.test_standby_imp_does_not_cross_gap_while_the_worker_is_alive',
    'tests.test_day_gate.DayGateTests.test_owner_collects_one_seal_stone_before_optional_supplies',
    'tests.test_day_gate.DayGateTests.test_owner_seals_from_inside_and_move_is_separate_action',
    'tests.test_day_gate.DayGateTests.test_dual_guards_wait_until_both_inside_before_sealing',
    'tests.test_day_gate.DayGateTests.test_night_never_opens_gate_and_complete_template_matches_blueprint',
    'tests.test_day_gate.DayGateTests.test_two_workers_pass_entry_and_restore_seventeen_walls_before_night',
)


def cases(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    selected = [case for name in MODULES+EXTRA
                for case in cases(unittest.defaultTestLoader.loadTestsFromName(name))
                if case.id() not in EXCLUDED]
    identities = [case.id() for case in selected]
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
    paths = [p for p in ROOT.rglob('*.py')
             if not any(part in ('build','dist','.venv') for part in p.parts)]
    paths.append(ROOT/'pyproject.toml')
    rules = list((ROOT.parent/'32_docs').glob('*'))+[ROOT.parent/'DEVELOPMENT_RULES.md']
    log_hashes = {name:hashlib.sha256((ROOT.parent/'temp'/name).read_bytes()).hexdigest()
                  for name in ('bug_log1.log','bug_log2.log')
                  if (ROOT.parent/'temp'/name).is_file()}
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
        scope='First day only (rounds 1-130); local regression inputs, not official match replay',
        tests=dict(run=result.testsRun,failures=len(result.failures),errors=len(result.errors)),
        selected_tests=identities,excluded_non_first_day=sorted(EXCLUDED),
        failures=[dict(test=case.id(),trace=trace) for case,trace in result.failures+result.errors],
        source_hashes={p.relative_to(ROOT.parent).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(paths)},
        rule_hashes={p.relative_to(ROOT.parent).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in rules if p.is_file()},reference_log_hashes=log_hashes,
        unverified=['official full input/initial pioneer position missing from bug logs',
                    'official LLM/verdicts, moving enemy capture decisions and spawn displacement',
                    'no new official match; no multi-day simulation in this iteration'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['tests']))
    raise SystemExit(not result.wasSuccessful())


if __name__=='__main__':
    main()
