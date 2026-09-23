"""Start the real CLI as an owned subprocess and POST the unmodified sample."""
import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "reports" / "http-smoke.json")
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen([sys.executable, str(ROOT / "main3.py"), str(port)],
                               cwd=ROOT.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
        body = (ROOT.parent / "request.txt").read_bytes()
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
            report = {"status": response.status, "elapsed_ms": round(elapsed, 3),
                      "actions": len(result["roleCommandMap"]), "entry": "python CoreGeek/main3.py <port>",
                      "request": "unmodified request.txt", "bind_verified_from_startup_log": False,
                      "bash_executed": False}
        finally:
            conn.close()
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=3)
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
            output = args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report))
        elif stderr:
            sys.stderr.buffer.write(stderr)


if __name__ == "__main__":
    main()
