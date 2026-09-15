"""Regression tests for local-only myoracle MCP behavior."""

from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import server


class _Database:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, _query):
        return self

    def fetchone(self):
        return ("rag", True, "rag_documents", "rag_chunks")


class ServerTests(unittest.TestCase):
    def test_every_public_top_level_function_is_registered_as_a_tool(self):
        tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
        missing = []
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            registered = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
                for decorator in node.decorator_list
            )
            if not registered:
                missing.append(node.name)
        self.assertEqual(missing, [])

    def test_spreadsheet_metadata_omits_secret_columns(self):
        records, ignored = server._connection_metadata(
            [[["Host", "Username", "Password"], ["db.example", "SYS", "secret-value"]]]
        )
        self.assertEqual(records, [{"Host": "db.example", "Username": "SYS"}])
        self.assertEqual(ignored, ["Password"])

    def test_rag_health_check_uses_environment_url(self):
        database = _Database()
        with mock.patch.dict(server.os.environ, {"RAG_DATABASE_URL": "postgresql://safe-test"}, clear=False):
            with mock.patch.object(server.psycopg, "connect", return_value=database) as connect:
                result = server.inspect_local_rag_database()
        connect.assert_called_once_with("postgresql://safe-test")
        self.assertTrue(result["healthy"])

    def test_rag_health_check_requires_environment_url(self):
        with mock.patch.dict(server.os.environ, {}, clear=True), \
             mock.patch.object(server, "_read_windows_user_environment_variable", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "RAG_DATABASE_URL"):
                server.inspect_local_rag_database()

    def test_rag_health_check_falls_back_to_windows_user_environment(self):
        database = _Database()
        with mock.patch.dict(server.os.environ, {}, clear=True), \
             mock.patch.object(
                 server,
                 "_read_windows_user_environment_variable",
                 return_value="postgresql://safe-user-environment",
             ), \
             mock.patch.object(server.psycopg, "connect", return_value=database) as connect:
            result = server.inspect_local_rag_database()
        connect.assert_called_once_with("postgresql://safe-user-environment")
        self.assertTrue(result["healthy"])

    def test_resolve_slack_channel_returns_visible_channel_id(self):
        response = mock.MagicMock()
        response.read.return_value = b'{"ok": true, "channels": [{"id": "C0123456789", "name": "essence"}], "response_metadata": {"next_cursor": ""}}'
        with mock.patch.object(server, "_read_windows_credential", return_value="safe-token"), \
             mock.patch.object(server, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            result = server.resolve_slack_channel("#essence")
        self.assertEqual(result, {"channel_name": "essence", "channel_id": "C0123456789"})
        request = urlopen.call_args.args[0]
        self.assertNotIn("safe-token", request.full_url)

    def test_copy_schema_artifacts_are_excluded_from_daily_job_alerts(self):
        self.assertTrue(server._is_copy_schema_job({"owner": "COPY_SCHEMA"}))
        self.assertTrue(server._is_copy_schema_job({"job_action": "begin dbms_datapump.open(); end;"}))
        self.assertFalse(server._is_copy_schema_job({"owner": "TRANSFER_USER", "job_action": "begin sync(); end;"}))

    def test_daily_backup_status_summarizes_clean_backup(self):
        with mock.patch.object(
            server,
            "inspect_saved_backup_log_errors",
            return_value={"status": "no_errors_found", "files_considered": "up to 20", "match_count": 0},
        ), mock.patch.object(
            server,
            "run_ssh_command",
            return_value={"stdout": '"\\Oracle\\Daily_RMAN_Backup"'},
        ):
            status, is_issue = server._daily_backup_status("FLEX")
        self.assertEqual(status["status"], "no_errors_found")
        self.assertFalse(is_issue)
        self.assertEqual(status["scheduled_backup_tasks"], ['"\\Oracle\\Daily_RMAN_Backup"'])

    def test_rman_backup_alerts_checks_backup_set_incremental_level(self):
        cursor = mock.MagicMock()
        cursor.fetchone.side_effect = [None, (101,)]
        cursor.__iter__.return_value = [(201, "FAILED", "start", "end", "1G")]
        database = mock.MagicMock()
        database.cursor.return_value.__enter__.return_value = cursor
        database.__enter__.return_value = database
        with mock.patch.object(server, "_read_connection", return_value={}), \
             mock.patch.object(server, "_connect", return_value=database):
            alerts = server._rman_backup_alerts("FLEX")

        self.assertEqual(alerts, [
            {"type": "missing_full", "incremental_level": 0, "days": 14},
            {"type": "failed_backup", "session_key": 201, "status": "FAILED", "start_time": "start", "end_time": "end", "backup_size": "1G"},
        ])
        full_sql, full_binds = cursor.execute.call_args_list[0].args
        incremental_sql, incremental_binds = cursor.execute.call_args_list[1].args
        self.assertIn("v$backup_set_details", full_sql)
        self.assertIn("backup_set.incremental_level = :incremental_level", full_sql)
        failed_sql = cursor.execute.call_args_list[2].args[0]
        self.assertNotIn("input_type", full_sql.lower())
        self.assertNotIn("input_type", failed_sql.lower())
        self.assertEqual(full_binds, {"incremental_level": 0, "days": 14})
        self.assertEqual(incremental_binds, {"incremental_level": 1, "days": 3})

    def test_spain_refresh_mv_alerts_returns_at_most_five_recent_errors(self):
        recent_runs = [
            {"state": "ERROR", "started_at": f"start-{number}", "ended_at": f"end-{number}", "output": f"ORA-{number}"}
            for number in range(6)
        ]
        with mock.patch.object(
            server,
            "inspect_saved_sync_process_status",
            return_value={"recent_runs": recent_runs},
        ) as inspect:
            alerts = server._spain_refresh_mv_alerts()
        inspect.assert_called_once_with("es_db2_orclsp_sys", history_days=2)
        self.assertEqual(len(alerts), 5)
        self.assertEqual(alerts[0]["error"], "ORA-0")

    def test_spain_refresh_mv_alerts_reports_missing_execution(self):
        with mock.patch.object(
            server,
            "inspect_saved_sync_process_status",
            return_value={"recent_runs": []},
        ):
            alerts = server._spain_refresh_mv_alerts()
        self.assertEqual(
            alerts,
            [{"type": "refresh_mv_not_executed", "status": "failure", "hours": 48}],
        )

    def test_configure_daily_routine_schedule_creates_and_verifies_8am_task(self):
        completed = mock.MagicMock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(server.subprocess, "run", return_value=completed) as run:
            result = server.configure_daily_routine_schedule()
        self.assertEqual(result["schedule"], "daily 08:00")
        self.assertEqual(result["task_name"], r"\OracleMCP\DailyRoutine")
        create_command = run.call_args_list[0].args[0]
        self.assertEqual(create_command[0], "schtasks.exe")
        self.assertEqual(create_command[create_command.index("/st") + 1], "08:00")
        self.assertEqual(create_command[create_command.index("/sc") + 1], "daily")

    def test_daily_routine_default_recipient_uses_yaml_configuration(self):
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text('{"daily_routine":{"slack_user_id":"U0123456789"}}', encoding="utf-8")
            with mock.patch.object(server, "DAILY_ROUTINE_CONFIG_FILE", config_path):
                self.assertEqual(
                    server._default_daily_routine_slack_user_id(), "U0123456789"
                )

    def test_open_slack_direct_message_returns_bot_channel(self):
        response = mock.MagicMock()
        response.read.return_value = b'{"ok": true, "channel": {"id": "D0123456789"}}'
        with mock.patch.object(server, "_read_windows_credential", return_value="safe-token"), \
             mock.patch.object(server, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            channel_id = server._open_slack_direct_message("U0123456789")
        self.assertEqual(channel_id, "D0123456789")
        self.assertNotIn("safe-token", urlopen.call_args.args[0].data.decode("utf-8"))

    def test_daily_routine_default_recipient_allows_missing_configuration(self):
        with TemporaryDirectory() as directory, \
             mock.patch.object(server, "DAILY_ROUTINE_CONFIG_FILE", Path(directory) / "missing.yaml"):
            self.assertEqual(
                server._default_daily_routine_slack_user_id(), ""
            )

    def test_daily_routine_posts_compact_slack_summary_when_requested(self):
        result = {
            "minimum_free_percent": 15.0,
            "target_count": 2,
            "ok_count": 1,
            "issue_count": 1,
            "failed_count": 0,
            "targets": [
                {"connection_name": "FLEX", "status": "ok"},
                {
                    "connection_name": "HUN",
                    "status": "issues",
                    "space_issues": [{"tablespace_name": "USERS", "free_percent": 9.5, "issue": "free_percent_below_threshold"}],
                },
            ],
        }
        with mock.patch.object(server, "_read_windows_credential", return_value="safe-token"), \
             mock.patch.object(server, "urlopen") as urlopen:
            response = mock.MagicMock()
            response.read.return_value = b'{"ok": true, "ts": "123.456"}'
            urlopen.return_value.__enter__.return_value = response
            notification = server._send_daily_routine_slack_message("D03JEDPH5CH", result)

        self.assertTrue(notification["delivered"])
        self.assertEqual(notification["message_ts"], "123.456")
        self.assertEqual(notification["message_count"], 1)
        request = urlopen.call_args.args[0]
        self.assertNotIn("safe-token", request.data.decode("utf-8"))
        self.assertIn("Space: USERS 9.50% free", request.data.decode("utf-8"))
        self.assertNotIn("Refresh/job", request.data.decode("utf-8"))

    def test_daily_routine_notification_splits_long_reports(self):
        result = {
            "minimum_free_percent": 15.0,
            "target_count": 1,
            "ok_count": 0,
            "issue_count": 1,
            "failed_count": 0,
            "targets": [{
                "connection_name": "FLEX",
                "status": "issues",
                "backup": {"status": "errors_found", "match_count": 1},
                "job_issues": [],
                "space_issues": [
                    {"tablespace_name": f"TABLESPACE_{number:03d}", "free_percent": 9.5, "issue": "free_percent_below_threshold"}
                    for number in range(30)
                ],
            }],
        }
        messages = server._daily_routine_notification_messages(result)
        self.assertGreater(len(messages), 1)
        self.assertLessEqual(len(messages), 3)
        self.assertTrue(all(len(message) <= 830 for message in messages))


if __name__ == "__main__":
    unittest.main()
