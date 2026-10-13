"""Print one complete offline synthetic result for an explicitly selected receiver."""

import json
import sys

from .journey import run_offline_journey
from .core import AdministrativeBoundaryError


def main() -> int:
    try:
        result = run_offline_journey()
    except AdministrativeBoundaryError as error:
        print(f"Offline administrative journey held: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
