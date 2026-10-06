"""Windows Task Scheduler entry point for the repository daily routine."""

from __future__ import annotations

import json

from server import _daily_routine_notification_messages, daily_rutione_check


def main() -> int:
    result = daily_rutione_check()
    try:
        messages = _daily_routine_notification_messages(result)
    except Exception as exc:
        print(f"Local report formatting failed: {exc}")
    else:
        for message in messages:
            print(message)
            print()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
