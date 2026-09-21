"""Replay one official JSON request or newline-delimited observations offline."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from app.config import Settings
from app.service.turn_service import TurnService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config")
    args = parser.parse_args()
    text = args.input.read_text(encoding="utf-8-sig")
    try:
        decoded = json.loads(text)
        payloads = decoded if isinstance(decoded, list) else [decoded]
    except json.JSONDecodeError:
        payloads = [json.loads(line) for line in text.splitlines() if line.strip()]
    service = TurnService(Settings.load(args.config))
    responses = [service.decide(payload) for payload in payloads]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(responses[0] if len(responses) == 1 else responses,
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"replayed {len(responses)} observation(s) -> {args.output}")


if __name__ == "__main__":
    main()
