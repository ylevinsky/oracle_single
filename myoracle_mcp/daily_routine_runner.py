"""Windows Task Scheduler entry point for the repository daily routine."""

from __future__ import annotations

from pathlib import Path

from server import daily_rutione_check


def main() -> int:
    result = daily_rutione_check()
    report = result.get("markdown_report") or {}
    report_path = report.get("path")
    if report_path and Path(report_path).is_file():
        print(Path(report_path).read_text(encoding="utf-8"))
    else:
        print(f"Markdown report unavailable: {report.get('error', 'report was not written')}")
    if result.get("slack_notification", {}).get("delivered"):
        print("Slack: Markdown report uploaded.")
    elif result.get("slack_notification"):
        print(f"Slack delivery failed: {result['slack_notification'].get('error', 'unknown error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
