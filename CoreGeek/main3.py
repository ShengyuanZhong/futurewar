#!/usr/bin/env python3
import logging
import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="CoreGeek Future War HTTP agent")
    parser.add_argument("port", type=int)
    parser.add_argument("--config", help="local configuration JSON path")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be in 1..65535")
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "src"))

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s | %(message)s",
    )

    from app.config import Settings
    from app.server import serve
    serve(args.port, Settings.load(args.config))


if __name__ == "__main__":
    main()
