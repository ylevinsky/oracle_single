"""Windows Task Scheduler entry point for the repository daily routine."""

from __future__ import annotations

from server import daily_rutione_check


def main() -> int:
    daily_rutione_check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
