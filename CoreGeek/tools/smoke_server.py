"""Start the real CLI and POST an unmodified official or supplied fixture."""
import argparse
import http.client
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "reports" / "http-smoke.json")
    parser.add_argument('--request', type=Path, default=ROOT.parent / 'request.txt')
    parser.add_argument('--robot-id', type=int, help='Assert this controlled robot receives move/attack')
    parser.add_argument('--robot-ids', type=int, nargs='+', help='Assert multiple owned robots receive native commands')
    parser.add_argument('--boss-buy-num', type=int, choices=(1,2), help='Assert the BOSS order batch purchase quantity')
    parser.add_argument('--robot-log-output', type=Path, help='Save structured robot diagnostics as JSONL')
    parser.add_argument('--scout-ids', type=int, nargs='+', help='Assert these observers receive separate move commands')
    parser.add_argument('--repair-id', type=int, help='Assert this worker uses WallFixer at the supplied critical wall')
    args = parser.parse_args()
    robot_ids = list(dict.fromkeys(([args.robot_id] if args.robot_id is not None else []) + (args.robot_ids or [])))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    capture = tempfile.TemporaryFile()
    process = subprocess.Popen([sys.executable, str(ROOT / "main3.py"), str(port)],
                               cwd=ROOT.parent, stdout=subprocess.PIPE, stderr=capture,
                               creationflags=flags)
    report = {}
    try:
        deadline = time.monotonic() + 5
        while True:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                conn.request("GET", "/health")
                response = conn.getresponse()
                data = json.loads(response.read())
                if response.status == 200 and data["status"] == "ok":
                    break
            except (OSError, http.client.HTTPException):
                if time.monotonic() >= deadline or process.poll() is not None:
                    raise RuntimeError("CLI did not become healthy")
                time.sleep(.05)
            finally:
                conn.close()
        body = args.request.read_bytes()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            started = time.perf_counter()
            conn.request("POST", "/", body, {"Content-Type": "application/json"})
            response = conn.getresponse()
            result = json.loads(response.read())
            elapsed = (time.perf_counter() - started) * 1000
            assert response.status == 200
            assert set(result) == {"roleCommandMap", "prompt", "executeCmd"}
            assert isinstance(result["roleCommandMap"], dict)
            for uid in robot_ids:
                command = result['roleCommandMap'][str(uid)]
                assert command['action'] in ('move', 'attack') and 'controllerId' not in command
            if args.boss_buy_num is not None:
                buys = [(uid,c) for uid,c in result['roleCommandMap'].items()
                        if c['action']=='buy' and c.get('name')=='BossRobotSummonOrder']
                assert len(buys)==1 and buys[0][1].get('num',1)==args.boss_buy_num
            if args.scout_ids:
                commands = [result['roleCommandMap'][str(uid)] for uid in args.scout_ids]
                assert all(c['action']=='move' for c in commands)
                assert len({tuple(c['targetPos'][0].values()) for c in commands}) == len(commands)
            if args.repair_id is not None:
                repair = result['roleCommandMap'][str(args.repair_id)]
                assert repair['action']=='use' and repair.get('name')=='WallFixer'
            report = {"status": response.status, "elapsed_ms": round(elapsed, 3),
                      "actions": len(result["roleCommandMap"]), "entry": "python CoreGeek/main3.py <port>",
                      "request": 'unmodified request.txt' if args.request.resolve() == (ROOT.parent/'request.txt').resolve() else args.request.name,
                      'request_sha256': hashlib.sha256(body).hexdigest(), "bind_verified_from_startup_log": False,
                      "bash_executed": False}
            if args.robot_id is not None:
                report['controlled_robot_command'] = result['roleCommandMap'][str(args.robot_id)]
            if args.robot_ids:
                report['controlled_robot_commands'] = {str(uid):result['roleCommandMap'][str(uid)] for uid in robot_ids}
            if args.boss_buy_num is not None:
                report['boss_purchase_actor'],report['boss_purchase_command'] = buys[0]
            if args.scout_ids:
                report['scout_commands'] = {str(uid):result['roleCommandMap'][str(uid)] for uid in args.scout_ids}
            if args.repair_id is not None:
                report['repair_command'] = repair
                report['repair_worker'] = args.repair_id
        finally:
            conn.close()
    finally:
        process.terminate()
        stdout, _ = process.communicate(timeout=3)
        capture.seek(0)
        stderr = capture.read()
        capture.close()
        if report:
            report["bind_verified_from_startup_log"] = f"0.0.0.0:{port}".encode() in stderr
            report["construction_warning"] = b"D01" in stderr
            report["base_surroundings_enabled"] = b"construction_mode=base_surroundings" in stderr
            report['raid_scout_logged'] = b' | raid_scout round=' in stderr
            if args.scout_ids:
                assert report['raid_scout_logged'], 'Scout trace is missing from server stderr'
            report["task_debug_logged"] = all(
                marker in stderr for marker in (
                    b"[TASK-DEBUG R", b"phaseTask :", b"llmResp   :",
                    b"lastCmdResult   :", b"prompt    :", b"executeCmd:",
                )
            )
            assert report["task_debug_logged"], "Task trace is missing from server stderr"
            robot_logs = []
            for line in stderr.decode('utf-8',errors='replace').splitlines():
                for marker in ('robot_observation', 'robot_diagnostic', 'defense_diagnostic'):
                    if marker+' {' in line:
                        robot_logs.append({'log_type':marker,'data':json.loads(line.split(marker+' ',1)[1])})
            report['robot_diagnostic_count'] = sum(row['log_type']=='robot_diagnostic' for row in robot_logs)
            report['defense_diagnostic_count'] = sum(row['log_type']=='defense_diagnostic' for row in robot_logs)
            if args.repair_id is not None:
                assert report['defense_diagnostic_count']==1, 'First-night defense diagnostic is missing'
            for uid in robot_ids:
                assert any(row['log_type']=='robot_diagnostic' and row['data']['robot']['id']==uid
                           for row in robot_logs), 'Robot diagnostic is missing from server stderr'
            if args.robot_log_output is not None:
                args.robot_log_output.parent.mkdir(parents=True,exist_ok=True)
                args.robot_log_output.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in robot_logs),encoding='utf-8')
            output = args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report))
        elif stderr:
            sys.stderr.buffer.write(stderr)


if __name__ == "__main__":
    main()
