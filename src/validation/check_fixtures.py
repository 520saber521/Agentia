"""Minimal fixture self-check for protocol validation."""

import glob
import json
import os
import sys
from pathlib import Path


def main():
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "src"))

    from validation import validate_message

    fixtures_dir = repo_root / "fixtures" / "messages"
    failures = []
    for path in sorted(glob.glob(str(fixtures_dir / "*.json"))):
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        errors = validate_message(payload)
        if errors:
            failures.append((path, errors))

    if failures:
        for path, errors in failures:
            print(path)
            for error in errors:
                print(f"  - {error}")
        return 1

    print("all fixtures valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
