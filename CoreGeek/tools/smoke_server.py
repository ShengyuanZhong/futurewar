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
    parser.add_argument('--robot-log-output', type=Path, help='Save structured robot diagnostics as JSONL')
    args = parser.parse_args()
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
            if args.robot_id is not None:
                command = result['roleCommandMap'][str(args.robot_id)]
                assert command['action'] in ('move', 'attack') and 'controllerId' not in command
            report = {"status": response.status, "elapsed_ms": round(elapsed, 3),
                      "actions": len(result["roleCommandMap"]), "entry": "python CoreGeek/main3.py <port>",
                      "request": 'unmodified request.txt' if args.request.resolve() == (ROOT.parent/'request.txt').resolve() else args.request.name,
                      'request_sha256': hashlib.sha256(body).hexdigest(), "bind_verified_from_startup_log": False,
                      "bash_executed": False}
            if args.robot_id is not None:
                report['controlled_robot_command'] = result['roleCommandMap'][str(args.robot_id)]
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
            report["task_debug_logged"] = all(
                marker in stderr for marker in (
                    b"[TASK-DEBUG R", b"phaseTask :", b"llmResp   :",
                    b"lastCmdResult   :", b"prompt    :", b"executeCmd:",
                )
            )
            assert report["task_debug_logged"], "Task trace is missing from server stderr"
            robot_logs = []
            for line in stderr.decode('utf-8',errors='replace').splitlines():
                for marker in ('robot_observation', 'robot_diagnostic'):
                    if marker+' {' in line:
                        robot_logs.append({'log_type':marker,'data':json.loads(line.split(marker+' ',1)[1])})
            report['robot_diagnostic_count'] = sum(row['log_type']=='robot_diagnostic' for row in robot_logs)
            if args.robot_id is not None:
                assert any(row['log_type']=='robot_diagnostic' and row['data']['robot']['id']==args.robot_id
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
