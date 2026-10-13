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
    'tests.test_imp_opening_scout',
    'tests.test_cached_layout_summon',
    'tests.test_layout_survey',
    'tests.test_vehicle_protocol',
    'tests.test_scout_vehicle',
    'tests.test_worker_boss_buyer',
    'tests.test_buyer_deadline',
    'tests.test_buyer_coordination',
    'tests.test_sealed_home',
    'tests.test_stone_planner',
    'tests.test_stone_mines',
    'tests.test_personal_construction',
    'tests.test_exterior_repair',
    'tests.test_day_gate',
    'tests.test_gate_materials',
    'tests.test_wall_schedule',
    'tests.test_boss_raid',
    'tests.test_boss_formation',
    'tests.test_robot_diagonal',
    'tests.test_raid_efficiency',
    'tests.test_raid_priorities',
    'tests.test_layout_raider',
    'tests.test_robot_diagnostics',
)
EXCLUDED = {
    'tests.test_first_day_order.FirstDayOrderTests.test_second_day_and_disabled_boss_do_not_lock_weapon_upgrades',
    'tests.test_scout_survival.ScoutSurvivalTests.test_second_day_original_imp_destroy_policy_is_not_given_catch_avoidance',
    'tests.test_opening_defense.OpeningDefenseTests.test_second_day_active_task_retains_previous_night_defence_priority',
    'tests.test_boss_raid.BossRaidTests.test_stun_death_new_day_and_deadline_stop_robot_orders',
    'tests.test_boss_raid.BossRaidTests.test_api_sequence_buys_once_summons_then_kills_controller_before_base',
    'tests.test_robot_diagnostics.RobotDiagnosticTests.test_ineligible_robots_still_get_explicit_skip_records',
}
EXTRA = (
    'tests.test_gap_defense.GapDefenseTests.test_standby_imp_does_not_cross_gap_while_the_worker_is_alive',
    'tests.test_gap_defense.GapDefenseTests.test_first_day_dusk_does_not_start_body_wait_or_build_extra_walls',
    'tests.test_first_night_defense.FirstNightDefenseTests.test_first_night_repairs_below_thirty_percent_even_without_day_three_guard',
    'tests.test_first_night_defense.FirstNightDefenseTests.test_supply_buys_five_kits_then_one_coupon_at_the_same_stop',
    'tests.test_first_night_defense.FirstNightDefenseTests.test_dusk_from_a_distant_mine_keeps_working_without_a_return_budget',
    'tests.test_first_night_defense.FirstNightDefenseTests.test_blocked_shop_does_not_turn_daytime_worker_into_a_waiting_guard',
    'tests.test_first_night_defense.FirstNightDefenseTests.test_first_day_ore_trips_do_not_search_a_return_path',
    'tests.test_first_night_defense.FirstNightDefenseTests.test_occupied_gap_guard_returns_to_a_legal_exterior_waiting_post',
    'tests.test_worker_efficiency.WorkerEfficiencyTests.test_build_target_keeps_its_identity_during_the_trip',
    'tests.test_worker_efficiency.WorkerEfficiencyTests.test_builders_keep_their_distinct_in_progress_wall_assignments',
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
                  for name in ('bug_log1.log','bug_log2.log','boss_attack_log.log','build_bug.log')
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
