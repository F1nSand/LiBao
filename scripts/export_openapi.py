from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the FastAPI OpenAPI snapshot.")
    parser.add_argument("--output", type=Path, default=ROOT / "contracts" / "openapi.json")
    args = parser.parse_args()

    sys.path.insert(0, str(BACKEND))
    from app.api.main import create_app

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
