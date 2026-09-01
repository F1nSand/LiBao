from __future__ import annotations

import sys

from real_e2e import run_real_e2e


if __name__ == "__main__":
    raise SystemExit(run_real_e2e(sys.argv[1:]))
