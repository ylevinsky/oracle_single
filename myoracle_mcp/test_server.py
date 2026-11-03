"""Regression tests for local-only myoracle MCP behavior."""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import philippines_refresh
import public_database_link
import clone_time
import saved_query
import schema_movement
import ephemeral_oracle
import table_timestamps
import readonly_user
import connection_migration
import local_postgres
import transfer_queue
import ph_remaining_copy
import hungary_targeted_copy
import site_force_refresh
import remote_copy
import exact_table_stats
import schema_datapump
import schema_sql_copy
import package_overloads
import scheduled_task_logon
import server


class _Database:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

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

    def test_missing_programdata_is_restored_for_windows_child_processes(self):
        with mock.patch.dict(server.os.environ, {}, clear=False):
            server.os.environ.pop("ProgramData", None)
            server._ensure_windows_programdata()
            if server.os.name == "nt":
                self.assertEqual(server.os.environ["ProgramData"], r"C:\ProgramData")
            else:
                self.assertNotIn("ProgramData", server.os.environ)

    def test_scp_upload_keeps_the_password_out_of_the_process_arguments(self):
        command = remote_copy.scp_command(
            "es-db2-sp.example", 22, "brillix", [Path("probe.bin")], "C:/Temp/probe"
        )
        self.assertNotIn("secret-value", command)
        self.assertEqual(command[-1], "brillix@es-db2-sp.example:C:/Temp/probe/")
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(remote_copy, "_askpass_program", return_value="askpass.exe"), \
             mock.patch.object(remote_copy.subprocess, "run", return_value=completed) as run:
            result = remote_copy.upload_with_scp(
                "es-db2-sp.example", 22, "brillix", "secret-value", [Path("probe.bin")], "C:/Temp/probe"
            )
        self.assertEqual(result["uploaded"], ["C:/Temp/probe/probe.bin"])
        self.assertNotIn("secret-value", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["env"]["SCP_UPLOAD_SECRET"], "secret-value")
        self.assertEqual(run.call_args.kwargs["env"]["ProgramData"], r"C:\ProgramData")

    def test_spreadsheet_metadata_omits_secret_columns(self):
        records, ignored = server._connection_metadata(
            [[["Host", "Username", "Password"], ["db.example", "SYS", "secret-value"]]]
        )
        self.assertEqual(records, [{"Host": "db.example", "Username": "SYS"}])
        self.assertEqual(ignored, ["Password"])

    def test_rag_health_check_uses_environment_url(self):
        database = _Database()
        with mock.patch.dict(server.os.environ, {"RAG_DATABASE_URL": "postgresql://safe-test"}, clear=False):
            with mock.patch.object(server.psycopg2, "connect", return_value=database) as connect:
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
             mock.patch.object(server.psycopg2, "connect", return_value=database) as connect:
            result = server.inspect_local_rag_database()
        connect.assert_called_once_with("postgresql://safe-user-environment")
        self.assertTrue(result["healthy"])

    def test_list_local_postgres_databases_uses_saved_postgresql_connection(self):
        document = {
            "connections": {
                "local_postgres_admin": {
                    "engine": "postgresql",
                    "host": "localhost",
                    "port": 5432,
                    "database": "postgres",
                    "username": "postgres",
                    "password": "secret-value",
                    "sslmode": "disable",
                }
            }
        }
        rows = [("airflow", "airflow", "UTF8", "10 MB", True)]

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, query):
                self.query = query

            def fetchall(self):
                return rows

        class _Database:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return _Cursor()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "connections.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch.object(server, "CONNECTIONS_FILE", path), \
                 mock.patch.object(local_postgres.psycopg2, "connect", return_value=_Database()) as connect:
                result = server.list_local_postgres_databases()
        connect.assert_called_once_with(
            host="localhost",
            port=5432,
            dbname="postgres",
            user="postgres",
            password="secret-value",
            sslmode="disable",
            connect_timeout=10,
        )
        self.assertEqual(result["databases"], [{
            "name": "airflow",
            "owner": "airflow",
            "encoding": "UTF8",
            "size": "10 MB",
            "allow_connections": True,
        }])
        self.assertNotIn("secret-value", str(result))

    def test_list_local_postgres_databases_rejects_oracle_connection(self):
        document = {
            "connections": {
                "RH": {"engine": "oracle", "host": "db.example", "port": 1521, "database": "rh", "username": "SYS", "password": "secret-value"}
            }
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "connections.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch.object(server, "CONNECTIONS_FILE", path):
                with self.assertRaisesRegex(ValueError, "not a PostgreSQL connection"):
                    server.list_local_postgres_databases("RH")

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

    def test_application_catalog_marks_missing_and_different_objects(self):
        source = {
            "tables": {
                "HC.UUT_RESULT": {"owner": "HC", "table_name": "UUT_RESULT", "num_rows": 10, "column_count": 2, "structure_hash": 1, "last_analyzed": "2026-09-01 00:00:00"},
                "HC.STEP_RESULT": {"owner": "HC", "table_name": "STEP_RESULT", "num_rows": 4, "column_count": 3, "structure_hash": 9, "last_analyzed": None},
            },
            "code": {
                "EREPORTS.RUN.PROCEDURE": {"owner": "EREPORTS", "name": "RUN", "type": "PROCEDURE", "line_count": 8, "source_hash": 100},
                "EREPORTS.OLD.PACKAGE": {"owner": "EREPORTS", "name": "OLD", "type": "PACKAGE", "line_count": 3, "source_hash": 4},
            },
        }
        target = {
            "tables": {
                "HC.UUT_RESULT": {"owner": "HC", "table_name": "UUT_RESULT", "num_rows": 9, "column_count": 2, "structure_hash": 1, "last_analyzed": "2026-09-02 00:00:00"},
                "HC.EXTRA": {"owner": "HC", "table_name": "EXTRA", "num_rows": 1, "column_count": 1, "structure_hash": 2, "last_analyzed": None},
            },
            "code": {
                "EREPORTS.RUN.PROCEDURE": {"owner": "EREPORTS", "name": "RUN", "type": "PROCEDURE", "line_count": 9, "source_hash": 101},
            },
        }
        result = schema_movement.compare_application_catalogs(source, target)
        by_table = {row["table_name"]: row["status"] for row in result["tables"]}
        by_code = {(row["name"], row["type"]): row["status"] for row in result["code"]}
        self.assertEqual(by_table["UUT_RESULT"], "same_structure")
        self.assertEqual(by_table["STEP_RESULT"], "missing_on_dwh")
        self.assertEqual(by_table["EXTRA"], "missing_on_ofakim")
        self.assertEqual(by_code[("RUN", "PROCEDURE")], "different")
        self.assertEqual(by_code[("OLD", "PACKAGE")], "missing_on_dwh")

    def test_user_table_list_keeps_schema_with_no_tables(self):
        cursor = mock.MagicMock()
        cursor.__iter__.return_value = [
            ("C##SHAY", None, None),
            ("ATE_RESULTS", "UUT_RESULT", "2026-01-01 00:00:00"),
        ]
        result = schema_movement.list_user_tables(cursor)
        self.assertEqual(result["schema_count"], 2)
        self.assertEqual(result["table_count"], 1)
        self.assertEqual(result["schemas"][0]["tables"], [])
        self.assertEqual(result["schemas"][1]["tables"][0]["table_name"], "UUT_RESULT")

    def test_schema_movement_comparison_finds_shared_schema_and_link(self):
        source = {
            "schemas": {
                "ATE_RESULTS": {"table_count": 4, "statistics_num_rows": 100, "segment_bytes": 10},
                "LOCAL_ONLY": {"table_count": 1, "statistics_num_rows": 2, "segment_bytes": 3},
            },
            "database_links": [
                {"owner": "PUBLIC", "db_link": "DWH", "username": "LOAD", "host": "10.103.0.4:1521/dwhcl"},
            ],
            "materialized_views": [],
            "scheduler_jobs": [
                {"owner": "COPY_SCHEMA", "job_name": "PUSH_DWH", "job_action": "begin dbms_datapump.open(); end;"},
            ],
            "datapump_jobs": [],
        }
        target = {
            "schemas": {
                "ATE_RESULTS": {"table_count": 4, "statistics_num_rows": 90, "segment_bytes": 9},
                "DWH_ONLY": {"table_count": 2, "statistics_num_rows": 5, "segment_bytes": 6},
            },
            "database_links": [
                {"owner": "PUBLIC", "db_link": "FLEX", "username": "READ", "host": "es-db2-fl.esi-fl-il.com"},
            ],
            "materialized_views": [
                {"owner": "ATE_RESULTS", "mview_name": "UUT_RESULT", "master_link": "FLEX"},
            ],
            "scheduler_jobs": [],
            "datapump_jobs": [{"owner": "SYS", "job_name": "IMP", "operation": "IMPORT", "job_mode": "SCHEMA", "state": "EXECUTING"}],
        }
        result = schema_movement.compare_inventories(
            source, target, ["es-db2-fl.esi-fl-il.com", "FLEX"], ["10.103.0.4", "dwhcl"]
        )
        self.assertEqual(result["schemas_only_on_source"], ["LOCAL_ONLY"])
        self.assertEqual(result["schemas_only_on_target"], ["DWH_ONLY"])
        self.assertEqual(result["schemas_on_both"][0]["schema"], "ATE_RESULTS")
        self.assertEqual(result["source_links_to_target"][0]["db_link"], "DWH")
        self.assertEqual(result["target_links_to_source"][0]["db_link"], "FLEX")
        self.assertEqual(result["source_movement_jobs"][0]["job_name"], "PUSH_DWH")
        self.assertEqual(result["materialized_views_using_a_database_link"][0]["mview_name"], "UUT_RESULT")

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

    def test_spain_refresh_mv_alerts_reports_stuck_workers_first(self):
        with mock.patch.object(
            server,
            "inspect_saved_sync_process_status",
            return_value={
                "status": "stuck",
                "stuck_workers": [
                    {"site": "Hungary", "sid": 1833, "serial": 38788,
                     "event": "SQL*Net more data from dblink", "wait_class": "Network",
                     "seconds_in_wait": 307081, "sql_id": "abc"},
                ],
                "recent_runs": [],
            },
        ):
            alerts = server._spain_refresh_mv_alerts()
        self.assertEqual(alerts[0]["type"], "refresh_mv_stuck")
        self.assertEqual(alerts[0]["site"], "Hungary")
        self.assertEqual(alerts[0]["seconds_in_wait"], 307081)

    def test_sync_process_status_rejects_bad_stuck_threshold(self):
        with self.assertRaises(ValueError):
            server.inspect_saved_sync_process_status("es_db2_orclsp_sys", stuck_threshold_seconds=10)
        with self.assertRaises(ValueError):
            server.inspect_saved_sync_process_status("es_db2_orclsp_sys", stuck_threshold_seconds=9999999)

    def test_sync_process_status_flags_stuck_workers_per_site(self):
        result_sets = {
            "workers": [
                (1833, 38788, "ACTIVE", "SYS", "Hungary", "abc", "SQL*Net more data from dblink", "Network", 307081),
                (1835, 37014, "ACTIVE", "SYS", "RH", "def", None, None, 12),
            ],
            "longops": [],
            "runs": [
                ("End", "2026-10-05 22:00:02", "2026-10-05 22:00:49", "RH:Ok;", None, None, "DAILY_TRANSFER"),
                ("Error", "2026-10-05 22:00:02", "2026-10-06 01:00:06", "Hungary:", "timeout", None, "DAILY_TRANSFER"),
            ],
            "mviews": [],
        }

        class _FakeCursor:
            def __init__(self, sets):
                self._sets = sets
                self._current = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, query, *args, **kwargs):
                if "session_longops" in query:
                    self._current = self._sets["longops"]
                elif "log_procedure" in query:
                    self._current = self._sets["runs"]
                elif "dba_mviews" in query:
                    self._current = self._sets["mviews"]
                else:
                    self._current = self._sets["workers"]
                return self

            def __iter__(self):
                return iter(self._current)

        class _FakeConnection:
            def __init__(self, sets):
                self._sets = sets

            def cursor(self):
                return _FakeCursor(self._sets)

            def close(self):
                pass

        with mock.patch.object(
            server, "_connect_saved_oracle", return_value=_FakeConnection(result_sets)
        ):
            result = server.inspect_saved_sync_process_status("es_db2_orclsp_sys")

        self.assertEqual(result["status"], "stuck")
        self.assertEqual(len(result["stuck_workers"]), 1)
        self.assertEqual(result["stuck_workers"][0]["site"], "Hungary")
        self.assertTrue(result["active_workers"][0]["stuck"])
        self.assertFalse(result["active_workers"][1]["stuck"])
        self.assertEqual(result["sites"]["Hungary"]["state"], "stuck")
        self.assertEqual(result["sites"]["Hungary"]["last_error_at"], "2026-10-06 01:00:06")
        self.assertEqual(result["sites"]["RH"]["state"], "running")
        self.assertEqual(result["sites"]["RH"]["last_success_at"], "2026-10-05 22:00:49")

        with mock.patch.object(
            server, "_connect_saved_oracle", return_value=_FakeConnection(result_sets)
        ):
            result = server.inspect_saved_sync_process_status(
                "es_db2_orclsp_sys", stuck_threshold_seconds=400000
            )
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["stuck_workers"], [])

    def test_drop_saved_materialized_view_requires_confirmation(self):
        with self.assertRaises(ValueError):
            server.drop_saved_materialized_view(
                "es_db2_orclsp_sys", "TRANSFER_USER", "OFAKIM_UUT_ATTRUBUTES", False
            )

    def test_drop_saved_materialized_view_rejects_bad_identifier(self):
        with self.assertRaises(ValueError):
            server.drop_saved_materialized_view(
                "es_db2_orclsp_sys", "TRANSFER_USER", "bad name!", True
            )

    def test_drop_saved_materialized_view_refuses_dependents(self):
        class _RefuseCursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, query, *args, **kwargs):
                return self

            def fetchone(self):
                return ("2026-07-20 00:07:48", "UNDEFINED", "VALID")

            def __iter__(self):
                return iter([("OTHER", "SOME_VIEW", "MATERIALIZED VIEW")])

        class _RefuseConnection:
            def cursor(self):
                return _RefuseCursor()

            def close(self):
                pass

        with mock.patch.object(
            server, "_connect_saved_oracle", return_value=_RefuseConnection()
        ):
            with self.assertRaises(ValueError):
                server.drop_saved_materialized_view(
                    "es_db2_orclsp_sys", "TRANSFER_USER", "OFAKIM_NKEYS_ALLOCATED2", True
                )

    def test_drop_saved_materialized_view_drops_when_unused(self):
        statements = []

        class _DropCursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, query, *args, **kwargs):
                statements.append(query)
                return self

            def fetchone(self):
                if "count(*)" in statements[-1]:
                    return (0,)
                return ("2026-07-20 00:07:48", "UNDEFINED", "VALID")

            def __iter__(self):
                return iter([])

        class _DropConnection:
            def cursor(self):
                return _DropCursor()

            def commit(self):
                pass

            def close(self):
                pass

        with mock.patch.object(
            server, "_connect_saved_oracle", return_value=_DropConnection()
        ):
            result = server.drop_saved_materialized_view(
                "es_db2_orclsp_sys", "TRANSFER_USER", "OFAKIM_NKEYS_ALLOCATED2", True
            )
        self.assertEqual(result["status"], "dropped")
        self.assertTrue(any(s.startswith("DROP MATERIALIZED VIEW") for s in statements))

    def test_set_saved_scheduled_task_run_whether_logged_on_keeps_password_off_the_command(self):
        password = "stored-secret"

        class _Channel:
            def shutdown_write(self):
                return None

            def recv_exit_status(self):
                return 0

        class _Stdin:
            def __init__(self):
                self.written = ""
                self.channel = _Channel()

            def write(self, text):
                self.written += text

            def flush(self):
                return None

        class _Reader:
            def __init__(self, payload):
                self.payload = payload
                self.channel = _Channel()

            def read(self):
                return self.payload

        class _Client:
            def __init__(self):
                self.command = ""
                self.stdin = _Stdin()
                self.closed = False

            def exec_command(self, command, timeout=None, get_pty=False):
                self.command = command
                self.timeout = timeout
                self.pty = get_pty
                body = (
                    b'{"task":"\\\\ORCL\\\\Refresh-Materialized-Views",'
                    b'"user":"ESSENCESECURITY\\\\brillix","logon_type":"Password"}\n'
                )
                return self.stdin, _Reader(body), _Reader(b"")

            def close(self):
                self.closed = True

        client = _Client()
        with mock.patch.object(server, "_read_connection", return_value={"host": "es-db2-sp"}), \
             mock.patch.object(server, "_ssh_settings", return_value=("brillix", "SSH/es-db2-sp", 22)), \
             mock.patch.object(server, "_read_windows_credential", return_value=password), \
             mock.patch.object(server, "_open_ssh", return_value=client):
            result = server.set_saved_scheduled_task_run_whether_logged_on(
                "es_db2_orclsp_sys", r"\ORCL\Refresh-Materialized-Views"
            )
        self.assertEqual(result["logon_type"], "Password")
        self.assertEqual(result["user"], r"ESSENCESECURITY\brillix")
        self.assertNotIn(password, client.command)
        self.assertFalse(client.pty)
        self.assertTrue(client.stdin.written.startswith(password))
        self.assertTrue(client.closed)
        with self.assertRaises(ValueError):
            scheduled_task_logon.split_task_name("Refresh-Materialized-Views")

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

    def test_daily_routine_writes_markdown_report(self):
        result = {
            "minimum_free_percent": 15.0,
            "target_count": 1,
            "ok_count": 0,
            "issue_count": 1,
            "failed_count": 0,
            "targets": [{
                "connection_name": "FLEX",
                "status": "issues",
                "space_issues": [{
                    "tablespace_name": "OFAKIM_TBS",
                    "free_percent": 11.37,
                    "issue": "free_percent_below_threshold",
                }],
                "backup_alerts": [],
                "alert_log_alerts": [],
                "refresh_mv_alerts": [],
            }],
        }
        with TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.md"
            with mock.patch.object(server, "REPOSITORY_ROOT", Path(directory)):
                report = server._write_daily_routine_report(result)
            self.assertEqual(report["file"], "report.md")
            content = report_path.read_text(encoding="utf-8")
            self.assertIn("# Daily Routine Report", content)
            self.assertIn("`OFAKIM_TBS`: 11.37% free", content)

    def test_daily_routine_notification_lists_unreachable_databases(self):
        result = {
            "minimum_free_percent": 15.0,
            "target_count": 2,
            "ok_count": 1,
            "issue_count": 0,
            "failed_count": 1,
            "targets": [
                {"connection_name": "FLEX", "status": "ok"},
                {
                    "connection_name": "DWH",
                    "status": "failed",
                    "error": "OperationalError: DPY-6005: cannot connect to database",
                },
            ],
        }
        message = "\n".join(server._daily_routine_notification_messages(result))
        self.assertIn("Unreachable: 1", message)
        self.assertIn("DWH — NOT CONNECTED", message)
        self.assertIn("Connection ALERT: OperationalError: DPY-6005", message)
        self.assertNotIn("FLEX —", message)

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

    def test_daily_routine_notification_falls_back_to_compact_when_detailed_overflows(self):
        detailed = {
            "space_issues": [
                {"tablespace_name": "FLEXDWH_CL", "free_percent": 14.99, "issue": "free_percent_below_threshold"},
                {"tablespace_name": "SPAIN_TBS", "free_percent": 14.79, "issue": "free_percent_below_threshold"},
            ],
            "backup_alerts": [
                {"type": "missing_full", "incremental_level": 0, "days": 14},
                {"type": "missing_incremental", "incremental_level": 1, "days": 3},
            ],
            "alert_log_alerts": [
                {"type": "alert_log_error", "code": code, "count": 100 + number}
                for number, code in enumerate(("TNS-12170", "ORA-06512", "ORA-12012", "ORA-38153", "ORA-12008", "ORA-3136", "ORA-609", "TNS-12547"))
            ],
            "refresh_mv_alerts": [
                {
                    "type": "refresh_mv_error",
                    "ended_at": "2026-11-02 14:00:07",
                    "error": "DatabaseError: ORA-12008: error in materialized view refresh path " + "x" * 260,
                },
                {
                    "type": "refresh_mv_error",
                    "ended_at": "2026-11-01 20:00:10",
                    "error": "DatabaseError: ORA-12008: error in materialized view refresh path " + "y" * 260,
                },
            ],
        }
        real = {
            "space_issues": [
                {"tablespace_name": "SPAIN_TBS", "free_percent": 14.79, "issue": "free_percent_below_threshold"},
            ],
            "backup_alerts": [],
            "alert_log_alerts": [
                {"type": "alert_log_error", "code": "TNS-12170", "count": 131},
                {"type": "alert_log_error", "code": "ORA-06512", "count": 81},
            ],
            "refresh_mv_alerts": [
                {"type": "refresh_mv_error", "ended_at": "2026-11-02 14:00:07", "error": "ORA-01555 snapshot too old"},
            ],
        }

        # The 03 Nov 2026 run produced six findings-bearing targets; four were
        # small enough that only the large ones needed the detailed form.
        def target(name, payload):
            return {"connection_name": name, "status": "issues", **payload}

        targets = [
            target("DWH_CL", detailed),
            target("FLEX", real),
            target("HUN", real),
            target("PH", real),
            target("RH", real),
            target("es_db2_orclsp_sys", detailed),
        ]
        result = {
            "minimum_free_percent": 15.0,
            "target_count": 7,
            "ok_count": 0,
            "issue_count": 6,
            "failed_count": 1,
            "targets": [
                {
                    "connection_name": "DWH",
                    "status": "failed",
                    "error": "OperationalError: DPY-6005: cannot connect to database. timed out",
                },
                *targets,
            ],
        }
        messages = server._daily_routine_notification_messages(result)
        self.assertLessEqual(len(messages), 3)
        joined = "\n".join(messages)
        self.assertIn("DWH — NOT CONNECTED", joined)
        for name in ("DWH_CL", "FLEX", "HUN", "PH", "RH", "es_db2_orclsp_sys"):
            self.assertIn(f"{name} — ISSUES", joined)
        self.assertIn("SPAIN_TBS 14.79%", joined)
        self.assertIn("no L0 in 14d", joined)
        self.assertIn("RefreshMV ERROR", joined)

    def test_local_current_date_is_iso_format(self):
        result = server.get_local_current_date()
        self.assertRegex(result["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_oracle_connectivity_uses_saved_connection(self):
        connection = {"host": "db.example", "port": 1521, "sid": "ORCL", "database": "ORCL"}
        with mock.patch.object(server, "_read_connection", return_value=connection):
            with mock.patch.object(server, "_connect", return_value=mock.MagicMock()) as connect:
                result = server.check_saved_oracle_connectivity("RH")
        connect.assert_called_once_with(connection)
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["sid"], "ORCL")

    def test_alert_log_alerts_count_distinct_codes(self):
        scanned = {
            "matches": [
                {"text": "ORA-04036: PGA memory used by the instance exceeds PGA_AGGREGATE_LIMIT"},
                {"text": {"value": "ORA-04036: PGA memory used by the instance exceeds PGA_AGGREGATE_LIMIT"}},
                {"text": "Fatal NI connect error 12170."},
                {"text": "Errors in file C:\\alert.log:"},
            ]
        }
        with mock.patch.object(server, "inspect_saved_alert_log_errors", return_value=scanned):
            alerts = server._alert_log_alerts("HUN")
        self.assertEqual(
            alerts,
            [
                {"type": "alert_log_error", "code": "ORA-04036", "count": 2},
                {"type": "alert_log_error", "code": "TNS-12170", "count": 1},
            ],
        )


class PublicDatabaseLinkTests(unittest.TestCase):
    def test_public_link_copy_requires_confirmation_and_full_source_name(self):
        with self.assertRaisesRegex(ValueError, "confirmed must be true"):
            public_database_link.create_public_link_from_existing(
                "es_db2_orclsp_sys", "TRANSFER_USER", "PH_DB.SP.ESSENCESECURITY.COM", "PH_DB", False, lambda name: None
            )
        with self.assertRaisesRegex(ValueError, "full database-link name"):
            public_database_link.create_public_link_from_existing(
                "es_db2_orclsp_sys", "TRANSFER_USER", "PH_DB", "PH_DB", True, lambda name: None
            )

    def test_public_link_copy_uses_database_side_verifier(self):
        cursor = _PublicLinkCursor()
        connection = _RecordingConnection(cursor)
        result = public_database_link.create_public_link_from_existing(
            "es_db2_orclsp_sys",
            "transfer_user",
            "ph_db.sp.essencesecurity.com",
            "ph_db",
            True,
            lambda name: connection,
        )
        text = "\n".join(cursor.statements)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["public_link"], "PH_DB.SP.ESSENCESECURITY.COM")
        self.assertIn("insert into sys.link$", text)
        self.assertNotIn("identified by", text.lower())
        connection.close_called.assert_called_once()

    def test_public_link_recreate_drops_the_existing_link_before_copying(self):
        cursor = _PublicLinkCursor()
        connection = _RecordingConnection(cursor)
        result = public_database_link.recreate_public_link_from_existing(
            "es_db2_orclsp_sys",
            "TRANSFER_USER",
            "PH_DB.SP.ESSENCESECURITY.COM",
            "PH_DB",
            True,
            lambda name: connection,
        )
        self.assertEqual(result["status"], "recreated")
        self.assertEqual(result["remote_user"], "ATE_RESULTS")
        self.assertIn("drop public database link PH_DB", "\n".join(cursor.statements))


class _PublicLinkCursor:
    def __init__(self):
        self.statements: list[str] = []
        self.rowcount = 1
        self._fetches = [(0,), ("PH_DB.SP.ESSENCESECURITY.COM", "ATE_RESULTS")]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter([
            ("OWNER#",), ("NAME",), ("USERID",), ("PASSWORD",), ("HOST",), ("PASSWORDX",),
        ])

    def execute(self, sql, *_args, **_binds):
        self.statements.append(" ".join(str(sql).split()))

    def fetchone(self):
        return self._fetches.pop(0)


class PhilippinesPublicLinkTests(unittest.TestCase):
    def test_philippines_transfer_summary_requires_a_timestamp(self):
        with self.assertRaisesRegex(ValueError, "started_at"):
            philippines_refresh.summarize_philippines_transfer(lambda name: None, "today")

    def test_unlock_ate_results_requires_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirmed must be true"):
            philippines_refresh.unlock_ate_results(False, lambda name: None)

    def test_ate_results_link_reset_requires_confirmation_and_safe_password(self):
        with self.assertRaisesRegex(ValueError, "confirmed must be true"):
            public_database_link.reset_ate_results_password_and_recreate_links(
                "postgres1", False, lambda name: None
            )
        with self.assertRaisesRegex(ValueError, "cannot quote safely"):
            public_database_link.reset_ate_results_password_and_recreate_links(
                "bad password", True, lambda name: None
            )

    def test_philippines_public_link_requires_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirmed must be true"):
            public_database_link.create_philippines_public_link(False, lambda name: None)

    def test_philippines_public_link_sql_names_the_remote_user(self):
        statement = public_database_link.philippines_link_sql(
            "(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=ph.example)(PORT=1521)))",
            "SecretValue1",
        )
        self.assertIn("create public database link PH_DB", statement)
        self.assertIn("connect to PH_DBLINK", statement)
        self.assertIn("HOST=ph.example", statement)
        self.assertEqual(
            public_database_link._without_password(f"ORA-01017 SecretValue1", "SecretValue1"),
            "ORA-01017 [redacted]",
        )


class DatabaseLinkCheckTests(unittest.TestCase):
    def test_link_name_must_be_a_simple_identifier(self):
        with self.assertRaisesRegex(ValueError, "simple Oracle identifier"):
            server.check_saved_database_link("es_db2_orclsp_sys", "HUNGARY_DB;drop")

    def test_link_probe_selects_from_dual(self):
        cursor = _LinkCursor()
        connection = _RecordingConnection(cursor)
        with mock.patch.object(server, "_connect_saved_oracle", return_value=connection):
            result = server.check_saved_database_link("es_db2_orclsp_sys", "hungary_db")
        self.assertTrue(result["ok"])
        self.assertEqual(result["db_link"], "HUNGARY_DB")
        self.assertIn("select 1 from dual@HUNGARY_DB", cursor.statements)
        self.assertEqual(result["probes"][0]["as_user"], "CURRENT")
        self.assertEqual(result["visible_links"], [
            {"owner": "TRANSFER_USER", "db_link": "HUNGARY_DB.SP.ESSENCESECURITY.COM", "username": "ATE_RESULTS"},
        ])
        connection.close_called.assert_called_once()

    def test_object_privilege_lookup_rejects_unsafe_names(self):
        with self.assertRaisesRegex(ValueError, "grantee"):
            server.inspect_saved_object_privileges("PH", "PH_DBLINK;drop")

    def test_object_privilege_lookup_returns_direct_grants(self):
        cursor = mock.MagicMock()
        cursor.__iter__.return_value = iter([
            ("ATE_RESULTS", "VW_TRANSFER_SITE_UUT_ATTRIBUTES", "SELECT", "NO"),
        ])
        connection = mock.MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        with mock.patch.object(server, "_connect_saved_oracle", return_value=connection):
            result = server.inspect_saved_object_privileges(
                "PH", "ph_dblink", "vw_transfer_site_uut_attributes"
            )
        self.assertEqual(result["grantee"], "PH_DBLINK")
        self.assertEqual(result["grants"][0]["privilege"], "SELECT")
        connection.close.assert_called_once()


class _LinkCursor:
    def __init__(self):
        self.statements: list[str] = []
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, *_args, **_binds):
        self.statements.append(" ".join(str(sql).split()))
        self._rows = []
        if "from dba_db_links" in self.statements[-1]:
            self._rows = [("TRANSFER_USER", "HUNGARY_DB.SP.ESSENCESECURITY.COM", "ATE_RESULTS")]

    def fetchone(self):
        return (1,)

    def __iter__(self):
        return iter(self._rows)


class ReadonlyUserTests(unittest.TestCase):
    def test_requires_confirmation_and_safe_names(self):
        with self.assertRaisesRegex(ValueError, "confirmed must be true"):
            readonly_user.create_readonly_user("PH", "MONITOR_PRTG", "safe-pass", False, lambda name: None)
        with self.assertRaisesRegex(ValueError, "simple Oracle identifier"):
            readonly_user.create_readonly_user("PH", "bad;name", "safe-pass", True, lambda name: None)
        with self.assertRaisesRegex(ValueError, "password"):
            readonly_user.create_readonly_user("PH", "MONITOR_PRTG", "", True, lambda name: None)

    def test_create_grants_select_any_table_and_verifies(self):
        cursor = _ReadonlyCursor(exists=False)
        connection = _RecordingConnection(cursor)
        result = readonly_user.create_readonly_user(
            "PH", "monitor_prtg", "SafePass1", True, lambda name: connection
        )
        text = "\n".join(cursor.statements)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["username"], "MONITOR_PRTG")
        self.assertIn("create user MONITOR_PRTG", text)
        self.assertIn("grant CREATE SESSION to MONITOR_PRTG", text)
        self.assertIn("grant SELECT ANY TABLE to MONITOR_PRTG", text)
        self.assertNotIn("SafePass1", str(result))
        self.assertEqual(result["system_privileges"], ["CREATE SESSION", "SELECT ANY TABLE"])
        connection.close_called.assert_called_once()

    def test_reset_unlocks_existing_user(self):
        cursor = _ReadonlyCursor(exists=True)
        connection = _RecordingConnection(cursor)
        result = readonly_user.create_readonly_user(
            "PH", "MONITOR_PRTG", "SafePass1", True, lambda name: connection
        )
        text = "\n".join(cursor.statements)
        self.assertEqual(result["status"], "reset")
        self.assertTrue(result["existed_before"])
        self.assertIn("alter user MONITOR_PRTG", text)
        connection.close_called.assert_called_once()


class _ReadonlyCursor:
    def __init__(self, exists=False):
        self.statements: list[str] = []
        self._exists = exists
        self._sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, *_args, **_binds):
        self.statements.append(" ".join(str(sql).split()))
        self._sql = self.statements[-1]

    def fetchone(self):
        if "from dba_users where username" in self._sql and "count(*)" in self._sql:
            return (1,) if self._exists else (0,)
        if "from database_properties" in self._sql:
            return ("USERS",)
        if "from dba_users" in self._sql:
            return ("MONITOR_PRTG", "OPEN", "USERS")
        return (0,)

    def __iter__(self):
        if "from dba_sys_privs" in self._sql:
            return iter([("CREATE SESSION",), ("SELECT ANY TABLE",)])
        return iter(())


class PhilippinesRefreshTests(unittest.TestCase):
    def test_confirmation_and_connection_are_required(self):
        with self.assertRaisesRegex(ValueError, "confirmed must be true"):
            philippines_refresh.create_objects("es_db2_orclsp_sys", False, lambda name: None)
        with self.assertRaisesRegex(ValueError, "Repair Center"):
            philippines_refresh.create_objects("PH", True, lambda name: None)

    def test_create_statements_cover_tables_index_and_remote_views(self):
        cursor = _RecordingCursor()
        connection = _RecordingConnection(cursor)
        result = philippines_refresh.create_objects(
            "es_db2_orclsp_sys", True, lambda name: connection
        )
        text = "\n".join(cursor.statements)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["created_tables"], [
            "PH_UUT_ATTRUBUTES", "PH_UUT_ATTRIBUTES_UPDATE", "PH_NKEYS_ALLOCATED",
        ])
        self.assertEqual(result["created_index"], "IDX_PH_UUT_ATTRUBUTES_1SN")
        self.assertIn("create table TRANSFER_USER.PH_UUT_ATTRUBUTES", text)
        self.assertIn("create index TRANSFER_USER.IDX_PH_UUT_ATTRUBUTES_1SN", text)
        self.assertIn("VW_TRANSFER_SITE_UUT_ATTRIBUTES@PH_DB", text)
        self.assertIn("SERIAL_NUMBER.NKEYS_ALLOCATED@PH_DB", text)
        self.assertIn("drop procedure TRANSFER_USER.CREATE_PH_REFRESH_MVIEWS", text)
        connection.close_called.assert_called_once()


class _RecordingCursor:
    def __init__(self):
        self.statements: list[str] = []
        self._sql = ""
        self.mviews: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, **_binds):
        self.statements.append(" ".join(str(sql).split()))
        self._sql = self.statements[-1]
        if "begin TRANSFER_USER.CREATE_PH_REFRESH_MVIEWS" in self._sql:
            self.mviews = list(philippines_refresh.MVIEW_QUERIES)

    def fetchone(self):
        return (0,)

    def __iter__(self):
        if "from dba_mviews" in self._sql:
            return iter((name,) for name in self.mviews)
        return iter(())


class _RecordingConnection:
    def __init__(self, cursor):
        self.cursor_impl = cursor
        self.call_timeout = 0
        self.close_called = mock.Mock()

    def cursor(self):
        return self.cursor_impl

    def close(self):
        self.close_called()

    def commit(self):
        return None


class EphemeralOracleTests(unittest.TestCase):
    def test_host_override_keeps_saved_port_and_closes(self):
        seen = {}

        class _Connection:
            def close(self):
                seen["closed"] = True

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return _Connection()

        base = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        result = ephemeral_oracle.check_host("FLEX", base, "10.103.0.7", None, fake_connect)
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["host"], "10.103.0.7")
        self.assertEqual(result["port"], 1521)
        self.assertEqual(seen["effective"]["host"], "10.103.0.7")
        self.assertTrue(seen["closed"])

    def test_port_override_is_applied(self):
        def fake_connect(effective):
            self.assertEqual(effective["port"], 1522)
            return mock.MagicMock()

        base = {"host": "old.example", "port": 1521, "database": "FLEX"}
        result = ephemeral_oracle.check_host("FLEX", base, "10.103.0.7", 1522, fake_connect)
        self.assertEqual(result["port"], 1522)

    def test_invalid_host_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "host"):
            ephemeral_oracle.check_host(
                "FLEX", {"host": "x", "port": 1521}, "not a host!!", None, lambda effective: None
            )

    def test_server_tool_reuses_saved_template(self):
        template = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        with mock.patch.object(server, "_read_connection", return_value=template) as read_connection:
            with mock.patch.object(server, "_connect", return_value=mock.MagicMock()) as connect:
                result = server.check_ephemeral_oracle_connectivity("FLEX", "10.103.0.7")
        read_connection.assert_called_once_with("FLEX")
        effective = connect.call_args.args[0]
        self.assertEqual(effective["host"], "10.103.0.7")
        self.assertEqual(effective["port"], 1521)
        self.assertEqual(result["status"], "connected")

    def test_last_scn_reads_scn_timestamp_and_database_time(self):
        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                seen["sql"] = " ".join(str(sql).split())

            def fetchone(self):
                return ("2026-10-06 10:30:00", "2026-10-06 10:31:00", 987654321)

        class _Connection:
            def __init__(self):
                self.closed = False

            def cursor(self):
                return _Cursor()

            def close(self):
                self.closed = True

        seen = {}
        connection = _Connection()

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return connection

        base = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        result = ephemeral_oracle.last_scn_date("FLEX", base, None, None, fake_connect)
        self.assertEqual(result["current_scn"], 987654321)
        self.assertEqual(result["scn_timestamp"], "2026-10-06 10:30:00")
        self.assertEqual(result["database_time"], "2026-10-06 10:31:00")
        self.assertEqual(seen["effective"]["host"], "old.example")
        self.assertIn("from v$database", seen["sql"])
        self.assertIn("scn_to_timestamp", seen["sql"])
        self.assertTrue(connection.closed)

    def test_last_scn_host_override_is_not_persisted_and_validated(self):
        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                pass

            def fetchone(self):
                return ("2026-10-06 10:30:00", "2026-10-06 10:31:00", 42)

        class _Connection:
            def cursor(self):
                return _Cursor()

            def close(self):
                pass

        def fake_connect(effective):
            self.assertEqual(effective["host"], "10.103.0.7")
            return _Connection()

        base = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        result = ephemeral_oracle.last_scn_date("FLEX", base, "10.103.0.7", None, fake_connect)
        self.assertEqual(result["host"], "10.103.0.7")
        with self.assertRaisesRegex(ValueError, "host"):
            ephemeral_oracle.last_scn_date(
                "FLEX", {"host": "x", "port": 1521}, "not a host!!", None, fake_connect
            )

    def test_server_scn_tool_uses_saved_template(self):
        template = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        with mock.patch.object(server, "_read_connection", return_value=template) as read_connection:
            with mock.patch.object(
                server.ephemeral_oracle, "last_scn_date", return_value={"ok": True}
            ) as last_scn:
                result = server.check_saved_last_scn_date("FLEX", "10.103.0.7")
        read_connection.assert_called_once_with("FLEX")
        last_scn.assert_called_once_with(
            "FLEX", template, "10.103.0.7", None, server._connect
        )
        self.assertEqual(result, {"ok": True})

    def test_timestamp_ranges_order_by_size_and_aggregate_columns(self):
        class _Cursor:
            call_timeout = 0

            def __init__(self, rows_by_key):
                self._rows = rows_by_key
                self._pending = None
                self.executed = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                text = " ".join(str(sql).split()).lower()
                self.executed.append(text)
                if "from dba_tab_columns" in text:
                    self._pending = "columns"
                elif "from dba_segments" in text:
                    self._pending = "sizes"
                elif 'from "app"."events"' in text:
                    self._pending = "events"
                elif 'from "app"."small"' in text:
                    self._pending = "small"
                elif 'from "app"."odd name"' in text:
                    self._pending = "odd"
                else:
                    self._pending = None

            def fetchone(self):
                return self._rows.get(self._pending)

            def __iter__(self):
                return iter(self._rows.get(self._pending) or [])

        rows = {
            "columns": [
                ("APP", "EVENTS", "CREATED_AT", "DATE", 1),
                ("APP", "EVENTS", "UPDATED_AT", "TIMESTAMP(6)", 2),
                ("APP", "SMALL", "TS", "DATE", 1),
                ("APP", "ODD NAME", "TS", "DATE", 1),
                ("APP", "MLOG$_STEP_RESULT", "SNAPTIME$$", "DATE", 1),
                ("APP", "RUPD$_STEP_RESULT", "SNAPTIME$$", "DATE", 1),
                ("APP", "WEIRD$NAME", "TS", "DATE", 1),
            ],
            "sizes": [
                ("APP", "SMALL", 1024 * 1024),
                ("APP", "EVENTS", 4 * 1024 * 1024),
                ("APP", "MLOG$_STEP_RESULT", 99 * 1024 * 1024),
            ],
            "events": (None, None, "2026-10-06 10:00:00", "2020-01-01 00:00:00"),
            "small": (None, None),
        }
        connection = mock.MagicMock()
        cursor = _Cursor(rows)
        connection.cursor.return_value.__enter__.return_value = cursor
        seen = {}

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return connection

        base = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        result = table_timestamps.list_timestamp_ranges("FLEX", base, None, None, fake_connect)
        self.assertTrue(
            any("instr(c.table_name, '$') = 0" in statement for statement in cursor.executed)
        )
        self.assertEqual(seen["effective"]["host"], "old.example")
        self.assertEqual(result["tables_with_timestamp_columns"], 3)
        self.assertEqual(result["tables_excluded_dollar_or_mv_log"], 3)
        tables = result["tables"]
        self.assertEqual(
            [entry["table_name"] for entry in tables], ["EVENTS", "SMALL", "ODD NAME"]
        )
        self.assertNotIn("MLOG$_STEP_RESULT", [entry["table_name"] for entry in tables])
        self.assertEqual(tables[0]["size_mb"], 4.0)
        self.assertEqual(tables[0]["max_timestamp"], "2026-10-06 10:00:00")
        self.assertEqual(tables[0]["min_timestamp"], "2020-01-01 00:00:00")
        self.assertEqual(tables[0]["columns"], ["CREATED_AT", "UPDATED_AT"])
        self.assertIsNone(tables[1]["max_timestamp"])
        self.assertIn("note", tables[1])
        self.assertIn("error", tables[2])
        self.assertTrue(connection.close.called)

    def test_timestamp_ranges_reject_bad_max_tables_and_host(self):
        base = {"host": "old.example", "port": 1521, "database": "FLEX"}
        with self.assertRaisesRegex(ValueError, "max_tables"):
            table_timestamps.list_timestamp_ranges("FLEX", base, None, None, lambda effective: None, 0)
        with self.assertRaisesRegex(ValueError, "host"):
            table_timestamps.list_timestamp_ranges("FLEX", base, "bad host!!", None, lambda effective: None)

    def test_server_timestamp_tool_uses_saved_template(self):
        template = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        with mock.patch.object(server, "_read_connection", return_value=template) as read_connection:
            with mock.patch.object(
                server.table_timestamps, "list_timestamp_ranges", return_value={"tables": []}
            ) as list_ranges:
                result = server.list_saved_table_timestamp_ranges("FLEX", "10.103.0.7", None, 5)
        read_connection.assert_called_once_with("FLEX")
        list_ranges.assert_called_once_with(
            "FLEX", template, "10.103.0.7", None, server._connect, 5
        )
        self.assertEqual(result, {"tables": []})


class CloneTimeTests(unittest.TestCase):
    def _connection(self, startup_row, clone_row, last_before=None,
                    spanning=(), first_after=()):
        cursor = mock.MagicMock()
        cursor.fetchone.side_effect = [startup_row, clone_row, last_before]
        cursor.fetchmany.side_effect = [list(spanning), list(first_after)]
        connection = mock.MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        return connection

    def test_reports_clone_time_and_startup_time(self):
        startup_row = ("FLEX", "CLONE-VM", "2026-10-06 10:55:36", "2026-10-06 11:00:00")
        clone_row = (37432879591546, 37432879591546, "2026-10-06 06:07:13", "2026-10-06 06:07:13", 69)
        connection = self._connection(startup_row, clone_row)
        seen = {}

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return connection

        base = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        result = clone_time.clone_and_start_time("FLEX", base, None, None, fake_connect)
        self.assertEqual(seen["effective"]["host"], "old.example")
        self.assertEqual(result["startup_time"], "2026-10-06 10:55:36")
        self.assertEqual(result["clone_time"], "2026-10-06 06:07:13")
        self.assertTrue(result["clone_time_is_snapshot_consistent"])
        self.assertEqual(result["checkpoint_scn_min"], result["checkpoint_scn_max"])
        self.assertEqual(result["datafile_count"], 69)
        self.assertTrue(connection.close.called)
        cursor = connection.cursor.return_value.__enter__.return_value
        self.assertIn("v$instance", cursor.execute.call_args_list[0].args[0])
        self.assertIn("v$datafile_header", cursor.execute.call_args_list[1].args[0])

    def test_frozen_headers_before_startup_are_reported_as_snapshot(self):
        startup_row = ("FLEX", "CLONE-VM", "2026-10-06 10:55:36", "2026-10-06 11:00:00")
        clone_row = (100, 100, "2026-10-06 06:07:13", "2026-10-06 06:07:13", 69)
        connection = self._connection(startup_row, clone_row)
        result = clone_time.clone_and_start_time(
            "FLEX", {"host": "h", "port": 1521, "sid": "FLEX"}, None, None, lambda e: connection
        )
        self.assertFalse(result["clone_time_looks_advanced"])
        self.assertIn("VM snapshot", result["interpretation"])
        self.assertEqual(result["snapshot_time"], "2026-10-06 06:07:13")
        self.assertEqual(result["snapshot_method"], "datafile_header_frozen")
        self.assertEqual(result["snapshot_window_start"], "2026-10-06 06:07:13")
        self.assertEqual(result["snapshot_window_end"], "2026-10-06 06:07:13")
        cursor = connection.cursor.return_value.__enter__.return_value
        self.assertEqual(cursor.fetchmany.call_count, 0)

    def test_aged_clone_derives_snapshot_window_from_own_archived_logs(self):
        startup_row = ("FLEX", "CLONE-VM", "2026-09-29 10:37:33", "2026-10-06 11:00:00")
        clone_row = (37432879591546, 37432879591546, "2026-10-06 06:07:13", "2026-10-06 06:07:13", 69)
        last_before = (15162, 37432874731999, 37432874769421,
                       "2026-09-28 01:09:45", "2026-09-28 06:24:15")
        spanning = [(15163, 37432874769421, 37432874907228,
                     "2026-09-28 06:24:15", "2026-09-29 10:38:58")]
        first_after = [
            (15163, 37432874769421, 37432874907228,
             "2026-09-28 06:24:15", "2026-09-29 10:38:58"),
            (15164, 37432874907228, 37432875015644,
             "2026-09-29 10:38:58", "2026-09-30 01:07:26"),
        ]
        connection = self._connection(startup_row, clone_row, last_before,
                                      spanning, first_after)
        result = clone_time.clone_and_start_time(
            "FLEX", {"host": "h", "port": 1521, "sid": "FLEX"}, None, None, lambda e: connection
        )
        self.assertTrue(result["clone_time_looks_advanced"])
        self.assertIn("v$archived_log", result["interpretation"])
        self.assertIsNone(result["snapshot_time"])
        self.assertEqual(result["snapshot_method"], "archived_log_window")
        self.assertEqual(result["snapshot_window_start"], "2026-09-28 06:24:15")
        self.assertEqual(result["snapshot_window_end"], "2026-09-29 10:37:33")
        self.assertEqual(result["last_source_scn_archived"], 37432874769421)
        self.assertEqual(result["last_log_before_startup"]["sequence#"], 15162)
        self.assertEqual(len(result["spanning_logs"]), 1)
        self.assertEqual(result["spanning_logs"][0]["sequence#"], 15163)
        self.assertEqual(len(result["first_logs_after_startup"]), 2)
        self.assertIsNone(result["archive_error"])
        cursor = connection.cursor.return_value.__enter__.return_value
        executed = " ".join(
            call.args[0] for call in cursor.execute.call_args_list
        ).lower()
        self.assertIn("v$archived_log", executed)

    def test_aged_clone_without_archive_history_falls_back_to_alert_log(self):
        startup_row = ("FLEX", "CLONE-VM", "2026-09-29 10:37:33", "2026-10-06 11:00:00")
        clone_row = (37432879591546, 37432879591546, "2026-10-06 06:07:13", "2026-10-06 06:07:13", 69)
        connection = self._connection(startup_row, clone_row, None, [], [])
        result = clone_time.clone_and_start_time(
            "FLEX", {"host": "h", "port": 1521, "sid": "FLEX"}, None, None, lambda e: connection
        )
        self.assertTrue(result["clone_time_looks_advanced"])
        self.assertIsNone(result["snapshot_time"])
        self.assertEqual(result["snapshot_method"], "unknown")
        self.assertIn("alert log", result["interpretation"])

    def test_archive_query_failure_is_captured_not_raised(self):
        startup_row = ("FLEX", "CLONE-VM", "2026-09-29 10:37:33", "2026-10-06 11:00:00")
        clone_row = (37432879591546, 37432879591546, "2026-10-06 06:07:13", "2026-10-06 06:07:13", 69)
        cursor = mock.MagicMock()
        cursor.fetchone.side_effect = [startup_row, clone_row]
        cursor.execute.side_effect = [None, None, RuntimeError("denied")]
        connection = mock.MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        result = clone_time.clone_and_start_time(
            "FLEX", {"host": "h", "port": 1521, "sid": "FLEX"}, None, None, lambda e: connection
        )
        self.assertTrue(result["clone_time_looks_advanced"])
        self.assertEqual(result["snapshot_method"], "unknown")
        self.assertIn("denied", result["archive_error"])
        self.assertEqual(result["startup_time"], "2026-09-29 10:37:33")
        self.assertTrue(connection.close.called)

    def test_inconsistent_checkpoint_times_are_flagged(self):
        startup_row = ("FLEX", "CLONE-VM", "2026-10-06 10:55:36", "2026-10-06 11:00:00")
        clone_row = (100, 200, "2026-10-06 06:07:13", "2026-10-06 07:30:00", 69)
        connection = self._connection(startup_row, clone_row, None, [], [])
        result = clone_time.clone_and_start_time(
            "FLEX", {"host": "h", "port": 1521, "sid": "FLEX"}, None, None, lambda e: connection
        )
        self.assertFalse(result["clone_time_is_snapshot_consistent"])
        self.assertEqual(result["clone_time"], "2026-10-06 07:30:00")
        self.assertIsNone(result["snapshot_time"])
        self.assertIn("differ between files", result["interpretation"])

    def test_host_override_is_validated(self):
        connection = self._connection(("FLEX", "h", "s", "d"), (1, 1, "a", "b", 1))
        with self.assertRaisesRegex(ValueError, "host"):
            clone_time.clone_and_start_time(
                "FLEX", {"host": "h", "port": 1521}, "bad host!!", None, lambda e: connection
            )

    def test_server_clone_tool_uses_saved_template(self):
        template = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        with mock.patch.object(server, "_read_connection", return_value=template) as read_connection:
            with mock.patch.object(
                server.clone_time, "clone_and_start_time", return_value={"clone_time": "x"}
            ) as clone_tool:
                result = server.check_saved_clone_and_start_time("FLEX", "10.103.0.7")
        read_connection.assert_called_once_with("FLEX")
        clone_tool.assert_called_once_with("FLEX", template, "10.103.0.7", None, server._connect)
        self.assertEqual(result, {"clone_time": "x"})


class SavedQueryTests(unittest.TestCase):
    def _connection(self, rows, columns=("name", "ckpt_time")):
        cursor = mock.MagicMock()
        cursor.description = [(column.upper(),) for column in columns]
        cursor.fetchmany.return_value = rows
        connection = mock.MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        return connection

    def test_rejects_non_select_statements(self):
        with self.assertRaisesRegex(ValueError, "SELECT or WITH"):
            saved_query.run_saved_query(
                "FLEX", {}, "delete from sys.aud$", 500, lambda effective: None
            )
        with self.assertRaisesRegex(ValueError, "sql must not be empty"):
            saved_query.run_saved_query("FLEX", {}, "", 500, lambda effective: None)

    def test_rejects_for_update_and_multiple_statements(self):
        with self.assertRaisesRegex(ValueError, "forbidden"):
            saved_query.run_saved_query(
                "FLEX", {}, "select name from v$controlfile for update", 500, lambda e: None
            )
        with self.assertRaisesRegex(ValueError, "single statement"):
            saved_query.run_saved_query(
                "FLEX", {}, "select 1 from dual; select 2 from dual", 500, lambda e: None
            )

    def test_rejects_bad_max_rows(self):
        with self.assertRaisesRegex(ValueError, "max_rows"):
            saved_query.run_saved_query(
                "FLEX", {}, "select 1 from dual", 0, lambda effective: None
            )
        with self.assertRaisesRegex(ValueError, "max_rows"):
            saved_query.run_saved_query(
                "FLEX", {}, "select 1 from dual", 5001, lambda effective: None
            )

    def test_runs_select_and_returns_rows_as_values(self):
        connection = self._connection([("SYSTEM", "2026-09-28 14:00:00")], ("name", "ckpt_time"))
        seen = {}

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return connection

        base = {"host": "old.example", "port": 1521, "database": "DWH_CL", "sid": "dwhcl"}
        result = saved_query.run_saved_query(
            "DWH_CL",
            base,
            "select name, to_char(checkpoint_time) from v$controlfile order by checkpoint_time desc",
            500,
            fake_connect,
        )
        self.assertEqual(seen["effective"]["host"], "old.example")
        self.assertEqual(result["connection_name"], "DWH_CL")
        self.assertEqual(result["sid"], "dwhcl")
        self.assertEqual(result["columns"], ["name", "ckpt_time"])
        self.assertEqual(result["row_count"], 1)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["rows"], [["SYSTEM", "2026-09-28 14:00:00"]])
        connection.close.assert_called_once()

    def test_truncates_to_max_rows(self):
        connection = self._connection([(index,) for index in range(3)], ("x",))
        result = saved_query.run_saved_query(
            "FLEX", {"host": "h", "port": 1521, "sid": "FLEX"}, "select x from t", 2, lambda e: connection
        )
        connection.cursor.return_value.__enter__.return_value.fetchmany.assert_called_once_with(3)
        self.assertEqual(result["row_count"], 2)
        self.assertTrue(result["truncated"])

    def test_host_override_is_applied_and_validated(self):
        seen = {}

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return self._connection([])

        base = {"host": "old.example", "port": 1521, "sid": "FLEX"}
        result = saved_query.run_saved_query(
            "FLEX", base, "select 1 as x from dual", 500, fake_connect, "10.103.0.7", 1522
        )
        self.assertEqual(seen["effective"]["host"], "10.103.0.7")
        self.assertEqual(seen["effective"]["port"], 1522)
        self.assertEqual(result["host"], "10.103.0.7")
        with self.assertRaisesRegex(ValueError, "host"):
            saved_query.run_saved_query(
                "FLEX", base, "select 1 as x from dual", 500, fake_connect, "bad host!!"
            )

    def test_server_query_tool_uses_saved_template(self):
        template = {"host": "old.example", "port": 1521, "database": "FLEX", "sid": "FLEX"}
        with mock.patch.object(server, "_read_connection", return_value=template) as read_connection:
            with mock.patch.object(
                server.saved_query, "run_saved_query", return_value={"rows": []}
            ) as run_query:
                result = server.run_saved_oracle_query("FLEX", "select 1 as x from dual", 10)
        read_connection.assert_called_once_with("FLEX")
        run_query.assert_called_once_with(
            "FLEX", template, "select 1 as x from dual", 10, server._connect, None, None, None, None
        )
        self.assertEqual(result, {"rows": []})

    def test_sid_override_replaces_saved_sid(self):
        seen = {}

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return self._connection([])

        base = {"host": "h", "port": 1521, "sid": "dwhcl"}
        saved_query.run_saved_query(
            "DWH_CL", base, "select 1 as x from dual", 500, fake_connect,
            None, None, None, "FLEX",
        )
        self.assertEqual(seen["effective"]["sid"], "FLEX")

    def test_service_name_override_replaces_saved_service(self):
        seen = {}

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return self._connection([])

        base = {"host": "h", "port": 1521, "sid": "dwhcl", "service_name": "saved.service"}
        saved_query.run_saved_query(
            "DWH_CL", base, "select 1 as x from dual", 500, fake_connect,
            None, None, "clone.service",
        )
        self.assertEqual(seen["effective"]["service_name"], "clone.service")

    def test_empty_service_name_connects_by_sid(self):
        seen = {}

        def fake_connect(effective):
            seen["effective"] = dict(effective)
            return self._connection([])

        base = {"host": "h", "port": 1521, "sid": "dwhcl", "service_name": "saved.service"}
        saved_query.run_saved_query(
            "DWH_CL", base, "select 1 as x from dual", 500, fake_connect,
            None, None, " ",
        )
        self.assertNotIn("service_name", seen["effective"])

    def test_migration_removes_placeholder_and_imports_bookmark(self):
        import xml.etree.ElementTree as ElementTree

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "MobaXterm.ini"
            source.write_text(
                "[Bookmarks]\n"
                "My_SSH=#109#0%10.0.0.99%22%[miguser]%%-1%0%\n",
                encoding="utf-8",
            )
            destination = Path(tmp) / "confCons.xml"
            destination.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<mrng:Connections xmlns:mrng="http://mremoteng.org" '
                'Name="Connections" ConfVersion="2.6">'
                '<Node Name="test" Type="Connection" Hostname="" />'
                "</mrng:Connections>",
                encoding="utf-8",
            )
            with mock.patch.object(
                connection_migration, "_windows_credentials", return_value=[]
            ):
                result = connection_migration.migrate_mobaxterm_to_mremoteng(
                    str(source), str(destination), remove_names=["test"]
                )
            self.assertEqual(result["removed_names"], ["test"])
            self.assertEqual(result["imported_count"], 1)
            names = [
                node.attrib.get("Name")
                for node in ElementTree.parse(destination).getroot().iter()
            ]
            self.assertIn("My_SSH", names)
            self.assertNotIn("test", names)

    def test_file_password_rejects_the_default_key(self):
        import xml.etree.ElementTree as ElementTree

        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "confCons.xml"
            destination.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<mrng:Connections xmlns:mrng="http://mremoteng.org" '
                'Name="Connections" ConfVersion="2.6" Protected="" />',
                encoding="utf-8",
            )
            connection_migration.set_mremoteng_file_password(str(destination), "admin")
            protected = ElementTree.parse(destination).getroot().attrib["Protected"]
            self.assertTrue(
                destination.read_text(encoding="utf-8").startswith(
                    '<?xml version="1.0" encoding="utf-8"?>'
                )
            )
            self.assertEqual(
                connection_migration._decrypt_text(protected, b"admin"),
                "ThisIsProtected",
            )
            with self.assertRaises(Exception):
                connection_migration._decrypt_text(protected)

    def test_mobaxterm_credential_decrypts_published_example(self):
        plain = connection_migration.decrypt_mobaxterm_credential(
            "bSj4VWbHezNH3tTY9Nil2RzJX57p7/S6KqMw8VsiT/WH+I8p03pqnInAu",
            "165821882556840",
        )
        self.assertEqual(plain, "HyperSine")


class _ScriptCursor:
    def __init__(self, fetches: list[object]):
        self.fetches = list(fetches)
        self.statements: list[str] = []
        self.rowcount = 2

    def execute(self, statement, binds=None):
        del binds
        self.statements.append(" ".join(str(statement).split()))
        self._next = self.fetches.pop(0)

    def fetchone(self):
        return self._next

    def __iter__(self):
        return iter(self._next)


class TransferQueueTests(unittest.TestCase):
    def test_new_queue_is_backfilled_and_trigger_writes_log_and_queue(self):
        cursor = _ScriptCursor([
            ("TABLE",),
            [("LAST_UUT_NAME",)],
            None,
            None,
            None,
            (2,),
            None,
            [("TRG_TP_INS_LOG_FLEX",)],
            None,
            ("ENABLED",),
        ])
        result = transfer_queue.ensure_transfer_products_queue(cursor)
        text = "\n".join(cursor.statements)
        self.assertTrue(result["queue_created"])
        self.assertEqual(result["backfilled_rows"], 2)
        self.assertEqual(result["trigger"], "ATE_RESULTS.TRG_TP_INS_LOG_FLEX")
        self.assertIn("create table ATE_RESULTS.TRANSFER_PRODUCTS_QUEUE", text)
        self.assertIn("insert into ATE_RESULTS.TRANSFER_PRODUCTS_QUEUE", text)
        self.assertIn("select LAST_UUT_NAME, TIME_STAMP from ATE_RESULTS.TRANSFER_PRODUCTS_LOG", text)
        self.assertIn("insert into ATE_RESULTS.TRANSFER_PRODUCTS_LOG (LAST_UUT_NAME)", text)
        self.assertIn("insert into ATE_RESULTS.TRANSFER_PRODUCTS_QUEUE (LAST_UUT_NAME)", text)
        self.assertNotIn("delete from ATE_RESULTS.TRANSFER_PRODUCTS_LOG", text)

    def test_existing_queue_is_not_backfilled_again(self):
        cursor = _ScriptCursor([
            ("TABLE",),
            [("LAST_UUT_NAME",)],
            ("TABLE",),
            [],
            None,
            ("ENABLED",),
        ])
        result = transfer_queue.ensure_transfer_products_queue(cursor)
        text = "\n".join(cursor.statements)
        self.assertFalse(result["queue_created"])
        self.assertEqual(result["backfilled_rows"], 0)
        self.assertEqual(result["trigger"], "ATE_RESULTS.TRG_TP_INS_QUEUE")
        self.assertNotIn("create table ATE_RESULTS.TRANSFER_PRODUCTS_QUEUE", text)

    def test_enqueue_writes_only_names_missing_from_log_and_queue(self):
        cursor = _EnqueueCursor([("ES700EPA-EN-K30",), ("ES8502HC-SP-K01",)])
        result = transfer_queue.enqueue_unlogged_products(cursor)
        self.assertEqual(result["products"], ["ES700EPA-EN-K30", "ES8502HC-SP-K01"])
        self.assertEqual(result["logged"], 2)
        self.assertEqual(result["queued"], 2)
        text = "\n".join(cursor.statements)
        self.assertIn("not exists", text.lower())
        self.assertIn("insert into ATE_RESULTS.TRANSFER_PRODUCTS_LOG (LAST_UUT_NAME)", text)
        self.assertIn("insert into ATE_RESULTS.TRANSFER_PRODUCTS_QUEUE (LAST_UUT_NAME)", text)
        self.assertEqual(cursor.inserted[0], [{"name": "ES700EPA-EN-K30"}, {"name": "ES8502HC-SP-K01"}])
        self.assertEqual(cursor.inserted[0], cursor.inserted[1])

    def test_enqueue_does_nothing_when_every_name_is_already_recorded(self):
        cursor = _EnqueueCursor([])
        result = transfer_queue.enqueue_unlogged_products(cursor)
        self.assertEqual(result, {"logged": 0, "queued": 0, "products": []})
        self.assertEqual(len(cursor.statements), 1)


class _EnqueueCursor:
    def __init__(self, rows):
        self.rows = rows
        self.statements: list[str] = []
        self.inserted: list[list[dict[str, str]]] = []
        self.rowcount = 0

    def execute(self, statement, binds=None):
        del binds
        self.statements.append(" ".join(str(statement).split()))
        pending = getattr(self, "rowcounts", None)
        if pending:
            self.rowcount = pending.pop(0)

    def executemany(self, statement, binds):
        self.statements.append(" ".join(str(statement).split()))
        rows = list(binds)
        self.inserted.append(rows)
        self.rowcount = len(rows)

    def __iter__(self):
        batches = getattr(self, "batches", None)
        if batches:
            return iter(batches.pop(0))
        return iter(self.rows)


class RemainingPhCopyTests(unittest.TestCase):
    def test_copy_inserts_skipped_units_and_logs_them(self):
        cursor = _EnqueueCursor([])
        cursor.batches = [[("6600000000147", "0226055B0043402E")], [("ION2633000002",)]]
        cursor.rowcounts = [0, 0, 1, 0, 1]
        result = ph_remaining_copy.copy_remaining_ph_units(cursor)
        self.assertEqual(result["inserted_from_materialized_view"], 0)
        self.assertEqual(result["inserted_from_first_name"], 1)
        self.assertEqual(result["logged"], 1)
        self.assertEqual(result["blocked_by_existing_rf"], [
            {"uut_serial_number": "6600000000147", "rf_number": "0226055B0043402E"},
        ])
        text = "\n".join(cursor.statements)
        self.assertIn("existing_rf.RF_NUMBER", text)
        self.assertIn("FIRST_UUT_NAME", text)


class HungaryTargetedCopyTests(unittest.TestCase):
    def test_copy_inserts_only_listed_rf_numbers_and_logs_them(self):
        cursor = _EnqueueCursor([])
        cursor.batches = [
            [("4226014B9000CB7B",), ("4226015B9000C603",)],
            [],
            [("5602263428519",), ("5602256682446",)],
        ]
        cursor.rowcounts = [2, 0, 0, 0, 2, 0, 0]
        result = hungary_targeted_copy.copy_hungary_units_by_rf(
            cursor, [" 4226014b9000cb7b ", "4226015B9000C603"]
        )
        self.assertEqual(result["rf_numbers"], ["4226014B9000CB7B", "4226015B9000C603"])
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(result["logged"], 2)
        self.assertEqual(result["serials"], ["5602263428519", "5602256682446"])
        self.assertEqual(result["blocked_by_existing_rf"], [])
        self.assertEqual(result["missing_in_source"], [])
        text = "\n".join(cursor.statements)
        self.assertIn("HUNGARY_UUT_ATTRUBUTES", text)
        self.assertIn("TRANSFER_USER.TRANSFER_LOG", text)
        self.assertNotIn("delete from", text.lower())

    def test_copy_reports_missing_source_rows(self):
        cursor = _EnqueueCursor([])
        cursor.batches = [[("4226014B9000CB7B",)], [], []]
        cursor.rowcounts = [1, 0, 0, 0, 1, 0, 0]
        result = hungary_targeted_copy.copy_hungary_units_by_rf(
            cursor, ["4226014B9000CB7B", "4226015B9000C603"]
        )
        self.assertEqual(result["missing_in_source"], ["4226015B9000C603"])

    def test_invalid_rf_numbers_are_rejected(self):
        cursor = _EnqueueCursor([])
        with self.assertRaisesRegex(ValueError, "Invalid RF_NUMBER"):
            hungary_targeted_copy.copy_hungary_units_by_rf(cursor, ["bad rf!"])
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            hungary_targeted_copy.copy_hungary_units_by_rf(cursor, [])

    def test_remaining_copy_inserts_everything_missing_and_logs_it(self):
        cursor = _EnqueueCursor([])
        cursor.rowcounts = [26151, 0, 26151, 0, 0]
        cursor.fetchone = lambda: (0,)
        result = hungary_targeted_copy.copy_hungary_remaining_units(cursor)
        self.assertEqual(result["inserted"], 26151)
        self.assertEqual(result["logged"], 26151)
        self.assertEqual(result["blocked_by_existing_rf"], 0)
        text = "\n".join(cursor.statements)
        self.assertIn("HUNGARY_UUT_ATTRUBUTES", text)
        self.assertIn("TRANSFER_USER.TRANSFER_LOG", text)
        self.assertNotIn("delete from", text.lower())
        self.assertNotIn(":rf0", text)


class _KwargsCursor(_EnqueueCursor):
    def execute(self, statement, binds=None, **kwargs):
        if kwargs:
            binds = kwargs
        return super().execute(statement, binds)

    class connection:  # noqa: D401 - minimal stand-in for the real connection
        @staticmethod
        def commit():
            return None


class SiteForceRefreshTests(unittest.TestCase):
    def test_force_refresh_runs_gated_free_copy_and_writes_audit_record(self):
        cursor = _KwargsCursor([])
        cursor.rowcounts = [0, 0, 0, 0, 0, 0, 0]
        result = site_force_refresh.force_site_refresh(cursor, "RH")
        self.assertEqual(result["site"], "RH")
        self.assertEqual(
            [entry["view"] for entry in result["refreshed"]],
            ["RH_UUT_ATTRUBUTES", "RH_UUT_ATTRIBUTES_UPDATE", "RH_NKEYS_ALLOCATED"],
        )
        text = "\n".join(cursor.statements)
        self.assertIn("dbms_mview.refresh", text)
        self.assertIn("RH_UUT_ATTRUBUTES source", text)
        self.assertIn("RH_NKEYS_ALLOCATED source", text)
        self.assertIn("TRANSFER_LOG_SERIAL", text)
        self.assertIn("insert into TRANSFER_USER.LOG_PROCEDURE values", text)
        self.assertNotIn("TRANSFER_PRODUCTS_QUEUE", text)

    def test_unknown_site_and_missing_confirmation_are_rejected(self):
        cursor = _EnqueueCursor([])
        with self.assertRaisesRegex(ValueError, "Unknown site"):
            site_force_refresh.force_site_refresh(cursor, "Mars")


class _ExactStatsCursor:
    def __init__(self, tables, stats, fail=None, clock=None):
        self.tables = tables
        self.stats = stats
        self.fail = fail or {}
        self.clock = clock
        self.call_timeout = 0
        self.statements: list[str] = []
        self.binds: list[dict] = []
        self._mode = ""

    def execute(self, sql, binds=None):
        text = " ".join(str(sql).split())
        self.statements.append(text)
        self.binds.append(dict(binds or {}))
        if "from dba_tables t" in text:
            self._mode = "list"
        elif "gather_table_stats" in text:
            self._mode = "gather"
            key = (binds["owner"], binds["table_name"])
            if self.clock is not None:
                self.clock.t = 100
            if key in self.fail:
                raise RuntimeError(self.fail[key])
        else:
            self._mode = "read"
            self._key = (binds["owner"], binds["table_name"])

    def __iter__(self):
        return iter(self.tables)

    def fetchone(self):
        return self.stats[self._key]


class _ExactStatsConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def close(self):
        self.closed = True


class ExactTableStatsTests(unittest.TestCase):
    def test_rejects_unconfirmed_and_bad_limits(self):
        with self.assertRaisesRegex(ValueError, "confirmed"):
            server.gather_saved_exact_table_statistics(["DWH"], confirmed=False)
        with self.assertRaisesRegex(ValueError, "degree"):
            exact_table_stats.validate_request(["DWH"], 0, 10)
        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            exact_table_stats.validate_request(["DWH"], 10, 10801)
        with self.assertRaisesRegex(ValueError, "duplicates"):
            exact_table_stats.validate_request(["DWH", "DWH"], 10, 60)

    def test_gathers_exact_counts_and_stops_at_timeout(self):
        clock = type("Clock", (), {"t": 0})()

        def now():
            return clock.t

        cursor = _ExactStatsCursor(
            [("APP", "SMALL"), ("APP", "BIG")],
            {("APP", "SMALL"): (4, "2026-10-13 12:00:00"), ("APP", "BIG"): (9, None)},
            clock=clock,
        )
        result = exact_table_stats.gather_on_cursor(
            cursor, degree=10, timeout_seconds=10, now=now
        )
        self.assertEqual(result["tables_gathered"], 1)
        self.assertEqual(result["tables_not_started"], 1)
        self.assertEqual(result["tables"][0]["exact_row_count"], 4)
        self.assertEqual(result["tables"][0]["status"], "gathered")
        self.assertEqual(result["tables"][1]["status"], "not_started")
        self.assertIn("estimate_percent => :estimate_percent", cursor.statements[1])
        self.assertEqual(cursor.binds[1]["degree"], 10)
        self.assertEqual(cursor.binds[1]["estimate_percent"], 100)
        self.assertGreater(cursor.call_timeout, 0)

    def test_table_failure_continues_and_connections_run_together(self):
        first = _ExactStatsCursor(
            [("APP", "OK"), ("APP", "BAD")],
            {("APP", "OK"): (3, "2026-10-13 12:00:00")},
            fail={("APP", "BAD"): "ORA-20000: locked"},
        )
        second = _ExactStatsCursor(
            [("APP", "OTHER")],
            {("APP", "OTHER"): (8, "2026-10-13 12:01:00")},
        )
        cursors = {"DWH": first, "FLEX": second}
        connections = {}

        def connect(name):
            cursor = cursors[name]
            database = _ExactStatsConnection(cursor)
            connections[name] = database
            return database, cursor

        result = exact_table_stats.gather_parallel(
            ["DWH", "FLEX"], connect, 10, 10800, now=lambda: 0
        )
        by_name = {item["connection"]: item for item in result["connections"]}
        self.assertEqual(result["parallel_connections"], 2)
        self.assertEqual(by_name["DWH"]["tables"][0]["exact_row_count"], 3)
        self.assertEqual(by_name["DWH"]["tables"][1]["status"], "failed")
        self.assertEqual(by_name["FLEX"]["tables"][0]["exact_row_count"], 8)
        self.assertTrue(connections["DWH"].closed)
        self.assertTrue(connections["FLEX"].closed)

    def test_connection_failure_is_written_to_progress(self):
        def connect(name):
            raise RuntimeError("timed out")

        with TemporaryDirectory() as tmp:
            result = exact_table_stats.gather_parallel(
                ["DWH"], connect, 10, 60, progress_dir=Path(tmp), now=lambda: 0
            )
            progress = Path(tmp) / "DWH.jsonl"
            self.assertIn("timed out", progress.read_text(encoding="utf-8"))
        self.assertEqual(result["connections"][0]["status"], "failed")

    def test_resume_skips_tables_already_recorded(self):
        cursor = _ExactStatsCursor(
            [("APP", "SMALL"), ("APP", "BIG")],
            {
                ("APP", "SMALL"): (4, "2026-10-13 12:00:00"),
                ("APP", "BIG"): (9, "2026-10-13 12:05:00"),
            },
        )

        def connect(name):
            return _ExactStatsConnection(cursor), cursor

        with TemporaryDirectory() as tmp:
            progress = Path(tmp) / "FLEX.jsonl"
            progress.write_text(
                '{"connection": "FLEX", "owner": "APP", "table_name": "SMALL", '
                '"status": "gathered", "exact_row_count": 4}\n',
                encoding="utf-8",
            )
            result = exact_table_stats.gather_parallel(
                ["FLEX"], connect, 10, 60, progress_dir=Path(tmp), now=lambda: 0, resume=True
            )
            text = progress.read_text(encoding="utf-8")
        self.assertEqual(result["connections"][0]["tables_skipped"], 1)
        self.assertEqual(result["connections"][0]["tables"][0]["table_name"], "BIG")
        self.assertEqual(text.count('"table_name": "SMALL"'), 1)
        self.assertIn('"table_name": "BIG"', text)

    def test_server_tool_requires_confirmation_then_delegates(self):
        with mock.patch.object(
            server.exact_table_stats, "start_background", return_value={"status": "started"}
        ) as start:
            result = server.gather_saved_exact_table_statistics(
                ["DWH", "FLEX"], degree=10, timeout_seconds=10800, confirmed=True, resume=True
            )
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0], ["DWH", "FLEX"])
        self.assertEqual(start.call_args.args[2], 10)
        self.assertEqual(start.call_args.args[3], 10800)
        self.assertIs(start.call_args.args[5], True)
        self.assertEqual(result, {"status": "started"})

    def test_unlocks_locked_tables_then_samples_two_percent(self):
        cursor = _ExactStatsCursor(
            [("APP", "LOCKED")],
            {("APP", "LOCKED"): (20, "2026-10-13 16:30:00")},
        )
        result = exact_table_stats.gather_on_cursor(
            cursor,
            degree=10,
            timeout_seconds=60,
            now=lambda: 0,
            estimate_percent=2,
            unlock_statistics=True,
            locked_only=True,
        )
        self.assertEqual(result["estimate_percent"], 2)
        self.assertEqual(result["tables"][0]["exact_row_count"], 20)
        self.assertIn("stattype_locked is not null", cursor.statements[0])
        self.assertIn("unlock_table_stats", cursor.statements[1])
        self.assertEqual(cursor.binds[2]["estimate_percent"], 2)


class SchemaDatapumpTests(unittest.TestCase):
    def test_rejects_unsafe_schema_names_and_builds_a_zip_command(self):
        with self.assertRaisesRegex(ValueError, "simple Oracle identifier"):
            schema_datapump.normalize_schemas(["OPDI2_SYSTEM;drop"])
        command = schema_datapump.zip_command(
            r"D:\pump\OPDI2_SYSTEM_20261013T130000.dmp",
            r"D:\pump\OPDI2_SYSTEM_20261013T130000.dmp.zip",
        )
        self.assertIn("Compress-Archive", command)
        self.assertIn(r"'D:\pump\OPDI2_SYSTEM_20261013T130000.dmp'", command)
        self.assertNotIn("password", command.lower())

    def test_stops_before_export_when_the_destination_schema_exists(self):
        source = _PumpDatabase(
            {
                "dba_users": [("OPDI2_SYSTEM", "N")],
                "tablespaces": ["RH_TBS"],
                "segments": ["RH_TBS"],
                "directory": r"D:\pump",
            }
        )
        target = _PumpDatabase(
            {
                "dba_users": [("OPDI2_SYSTEM", "N")],
                "tablespaces": ["HUNG_TBS"],
                "segments": [],
                "directory": r"F:\pump",
            }
        )
        databases = {"RH": source, "HUN": target}

        def connect(name):
            return databases[name]

        result = schema_datapump.copy_schemas(
            "RH",
            "HUN",
            ["OPDI2_SYSTEM"],
            confirmed=True,
            tablespace_remap={"RH_TBS": "HUNG_TBS"},
            directory_name="PUMP_DIR",
            connect=connect,
            open_ssh=lambda name: databases[name],
            now=lambda: datetime(2026, 10, 13, 13, 0, 0),
        )
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["existing_on_target"], ["OPDI2_SYSTEM"])
        self.assertEqual(source.datapump_calls, [])
        self.assertEqual(target.commands, [])

    def test_zips_before_transfer_and_imports_with_tablespace_remap(self):
        source = _PumpDatabase(
            {
                "dba_users": [("OPDI2_SYSTEM", "N")],
                "tablespaces": ["RH_TBS"],
                "segments": ["RH_TBS"],
                "directory": r"D:\pump",
            }
        )
        target = _PumpDatabase(
            {
                "dba_users": [],
                "tablespaces": ["HUNG_TBS"],
                "segments": [],
                "directory": r"F:\pump",
                "objects": 102,
            }
        )
        databases = {"RH": source, "HUN": target}

        result = schema_datapump.copy_schemas(
            "RH",
            "HUN",
            ["opdi2_system"],
            confirmed=True,
            tablespace_remap={"RH_TBS": "HUNG_TBS"},
            directory_name="PUMP_DIR",
            connect=lambda name: databases[name],
            open_ssh=lambda name: databases[name],
            now=lambda: datetime(2026, 10, 13, 13, 0, 0),
        )
        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["tablespace_remap"], {"RH_TBS": "HUNG_TBS"})
        self.assertEqual(source.commands[0], schema_datapump.directory_probe_command(r"D:\pump"))
        self.assertEqual(source.commands[1], schema_datapump.zip_command(
            r"D:\pump\OPDI2_SYSTEM_20261013T130000.dmp",
            r"D:\pump\OPDI2_SYSTEM_20261013T130000.dmp.zip",
        ))
        self.assertLess(source.commands.index(source.commands[1]), len(source.downloads) + 1)
        self.assertEqual(source.downloads, [r"D:/pump/OPDI2_SYSTEM_20261013T130000.dmp.zip"])
        self.assertEqual(target.uploads[0][0].endswith(r"OPDI2_SYSTEM_20261013T130000.dmp.zip"), True)
        self.assertIn("REMAP_TABLESPACE", target.datapump_calls[0][0])
        self.assertEqual(target.datapump_calls[0][1]["old_0"], "RH_TBS")
        self.assertEqual(target.datapump_calls[0][1]["new_0"], "HUNG_TBS")
        self.assertEqual(result["object_counts"], {"OPDI2_SYSTEM": 102})


class _PumpCursor:
    def __init__(self, owner: "_PumpDatabase") -> None:
        self.owner = owner
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, binds=None):
        self.owner.statements.append(sql)
        if binds and "job_state" in binds:
            self.owner.datapump_calls.append((sql, {key: value for key, value in binds.items() if key != "job_state"}))
            return
        text = " ".join(sql.split())
        if "from dba_users" in text and "oracle_maintained" in text:
            requested = set(re.findall(r"'([^']+)'", text))
            self._rows = [row for row in self.owner.users if row[0] in requested]
        elif "default_tablespace" in text:
            self._rows = [(name,) for name in self.owner.segment_tablespaces]
        elif "contents = 'PERMANENT'" in text or "from dba_tablespaces" in text:
            requested = set(re.findall(r"'([^']+)'", text))
            self._rows = [(name,) for name in self.owner.tablespaces if name in requested]
        elif "from dba_directories" in text:
            self._rows = [(self.owner.directory,)]
        elif "from dba_objects" in text:
            self._rows = [(self.owner.objects,)]
        else:
            self._rows = []

    def fetchall(self):
        return list(self._rows)

    def var(self, _kind):
        return self.owner._state_holder


class _PumpState:
    def getvalue(self) -> str:
        return "COMPLETED"


class _PumpDatabase:
    def __init__(self, data: dict) -> None:
        self.users = list(data["dba_users"])
        self.tablespaces = list(data["tablespaces"])
        self.segment_tablespaces = list(data["segments"])
        self.directory = data["directory"]
        self.objects = data.get("objects", 0)
        self.statements: list[str] = []
        self.datapump_calls: list[tuple] = []
        self.commands: list[str] = []
        self.downloads: list[str] = []
        self.uploads: list[tuple[str, str]] = []
        self.closed = False
        self.call_timeout = 0
        self._state_holder = _PumpState()

    def cursor(self):
        return _PumpCursor(self)

    def run(self, command: str) -> str:
        self.commands.append(command)
        return "DIRECTORY_OK\n"

    def download(self, remote, local):
        self.downloads.append(remote)
        Path(local).write_bytes(b"zip")

    def upload(self, local, remote):
        self.uploads.append((local, remote))

    def read_text(self, _remote) -> str:
        return "Job successfully completed\n"

    def close(self):
        self.closed = True


class SchemaSqlCopyTests(unittest.TestCase):
    def test_remap_replaces_only_quoted_tablespace_names(self):
        ddl = 'CREATE TABLE "OPDI2_SYSTEM"."LIMITS" ("ID" NUMBER) TABLESPACE "RH_TBS"'
        remapped = schema_sql_copy.remap_ddl(ddl, {"RH_TBS": "HUNG_TBS"})
        self.assertIn('TABLESPACE "HUNG_TBS"', remapped)
        self.assertNotIn("RH_TBS", remapped)
        self.assertNotIn("PCTUSED", schema_sql_copy.remap_ddl("PCTFREE 10 PCTUSED 0 INITRANS 1", {}))

    def test_splits_table_metadata_into_separate_statements(self):
        ddl = (
            'CREATE TABLE "OPDI2_SYSTEM"."MESSAGE_TYPE" ("ID" NUMBER) TABLESPACE "RH_TBS" \n'
            '  CREATE UNIQUE INDEX "OPDI2_SYSTEM"."MESSAGE_TYPE_PK" ON "OPDI2_SYSTEM"."MESSAGE_TYPE" ("ID") \n'
            'ALTER TABLE "OPDI2_SYSTEM"."MESSAGE_TYPE" ADD CONSTRAINT "MESSAGE_TYPE_PK" PRIMARY KEY ("ID")'
        )
        statements = schema_sql_copy.sql_statements(schema_sql_copy.remap_ddl(ddl, {"RH_TBS": "HUNG_TBS"}))
        self.assertEqual(len(statements), 3)
        self.assertTrue(statements[0].startswith("CREATE TABLE"))
        self.assertTrue(statements[1].startswith("CREATE UNIQUE INDEX"))
        self.assertTrue(statements[2].startswith("ALTER TABLE"))
        inline = schema_sql_copy.sql_statements(
            'CREATE TABLE "S"."T" ("ID" NUMBER) TABLESPACE "HUNG_TBS" CREATE UNIQUE INDEX "S"."T_PK" ON "S"."T" ("ID")'
        )
        self.assertEqual(len(inline), 2)
        self.assertTrue(inline[1].startswith("CREATE UNIQUE INDEX"))

    def test_stops_when_the_destination_schema_exists(self):
        source = _SqlCopyDatabase(["OPDI2_SYSTEM"])
        target = _SqlCopyDatabase(["OPDI2_SYSTEM"])

        result = schema_sql_copy.copy_schema(
            "RH",
            "HUN",
            "OPDI2_SYSTEM",
            confirmed=True,
            tablespace_remap={"RH_TBS": "HUNG_TBS"},
            connect=lambda name: {"RH": source, "HUN": target}[name],
        )
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(target.executed, [])


class _SqlCopyCursor:
    def __init__(self, owner: "_SqlCopyDatabase") -> None:
        self.owner = owner
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, binds=None):
        text = " ".join(str(sql).split())
        if "from dba_users where username = :schema" in text:
            schema = (binds or {}).get("schema")
            self._rows = [(schema,)] if schema in self.owner.users else []
            return
        self.owner.executed.append(text)
        self._rows = []

    def fetchall(self):
        return list(self._rows)


class _SqlCopyDatabase:
    def __init__(self, users: list[str]) -> None:
        self.users = users
        self.executed: list[str] = []
        self.call_timeout = 0

    def cursor(self):
        return _SqlCopyCursor(self)

    def close(self):
        return None

    def commit(self):
        return None


class PackageOverloadTests(unittest.TestCase):
    def test_replaces_every_contiguous_overload(self):
        source = [
            "PACKAGE DEMO IS\n",
            " PROCEDURE KEEP_ME;\n",
            " PROCEDURE INSERT_SITE_ATE_RESULT(a number);\n",
            " PROCEDURE INSERT_SITE_ATE_RESULT(a number, b varchar2);\n",
            " PROCEDURE AFTER_ME;\n",
            "END;\n",
        ]
        target = [
            "PACKAGE DEMO IS\n",
            " PROCEDURE KEEP_ME;\n",
            " PROCEDURE INSERT_SITE_ATE_RESULT(a number);\n",
            " PROCEDURE AFTER_ME;\n",
            "END;\n",
        ]
        merged, copied = package_overloads.replace_overloads(
            target, source, "INSERT_SITE_ATE_RESULT"
        )
        text = "".join(merged)
        self.assertEqual(copied, 2)
        self.assertEqual(text.count("PROCEDURE INSERT_SITE_ATE_RESULT"), 2)
        self.assertIn("PROCEDURE KEEP_ME", text)
        self.assertIn("PROCEDURE AFTER_ME", text)
        self.assertIn("b varchar2", text)


if __name__ == "__main__":
    unittest.main()
