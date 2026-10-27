"""Start the SwitchFleet operator application."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="switchfleet-ui", description="SwitchFleet: управление устройствами через Ansible")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data-dir", type=Path, help="Каталог инвентаря, зашифрованных учётных данных и заданий")
    args = parser.parse_args(argv)
    if args.data_dir:
        os.environ["SWITCHFLEET_DATA_DIR"] = str(args.data_dir.expanduser().resolve())
    import uvicorn

    uvicorn.run("app.fleet.api:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
