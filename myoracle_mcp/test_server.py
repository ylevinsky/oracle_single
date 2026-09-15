"""Regression tests for local-only myoracle MCP behavior."""

from __future__ import annotations

import ast
from pathlib import Path
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
        ):
            status, is_issue = server._daily_backup_status("FLEX")
        self.assertEqual(status["status"], "no_errors_found")
        self.assertFalse(is_issue)

    def test_daily_routine_posts_compact_slack_summary_when_requested(self):
        result = {
            "minimum_free_percent": 15.0,
            "target_count": 2,
            "ok_count": 1,
            "issue_count": 1,
            "failed_count": 0,
            "targets": [
                {"connection_name": "FLEX", "status": "ok"},
                {"connection_name": "HUN", "status": "issues"},
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
        request = urlopen.call_args.args[0]
        self.assertNotIn("safe-token", request.data.decode("utf-8"))
        self.assertIn("HUN", request.data.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
