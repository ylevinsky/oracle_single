"""Copy schemas between saved Oracle databases with Data Pump.

The dump is created on the source directory object, zipped there, and only
the zip is transferred. The target is left unchanged when any requested
schema already exists.
"""

from __future__ import annotations

import base64
import os
import re
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

_IDENTIFIER = re.compile(r"[A-Z][A-Z0-9_$#]{0,127}")
_DIRECTORY_PATH = re.compile(r"[A-Za-z]:\\(?:[A-Za-z0-9_ .()-]+\\?)*")


def normalize_schemas(schemas: list[str]) -> list[str]:
    """Return unique uppercase schema names, or raise when any name is unsafe."""
    if not schemas:
        raise ValueError("schemas must name at least one schema")
    names: list[str] = []
    for schema in schemas:
        name = str(schema or "").strip().upper()
        if not _IDENTIFIER.fullmatch(name):
            raise ValueError(f"schema name is not a simple Oracle identifier: {schema}")
        if name not in names:
            names.append(name)
    return names


def normalize_remap(tablespace_remap: dict[str, str] | None) -> dict[str, str]:
    """Return uppercase tablespace remaps, or raise when a name is unsafe."""
    remap: dict[str, str] = {}
    for old, new in (tablespace_remap or {}).items():
        source = str(old or "").strip().upper()
        target = str(new or "").strip().upper()
        if not _IDENTIFIER.fullmatch(source) or not _IDENTIFIER.fullmatch(target):
            raise ValueError("tablespace_remap keys and values must be simple Oracle identifiers")
        remap[source] = target
    return remap


def normalize_directory(directory_name: str) -> str:
    """Return one uppercase directory-object name."""
    name = str(directory_name or "").strip().upper()
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError("directory_name must be a simple Oracle identifier")
    return name


def _sql_list(names: list[str]) -> str:
    return ", ".join(f"'{name}'" for name in names)


def _windows_directory(path: str) -> str:
    normalized = str(path or "").replace("/", "\\").rstrip("\\")
    if not _DIRECTORY_PATH.fullmatch(normalized + "\\") and not _DIRECTORY_PATH.fullmatch(normalized):
        raise ValueError(f"Data Pump directory path is not a local Windows path: {path}")
    return normalized


def _file_name(kind: str, stamp: str) -> str:
    if not re.fullmatch(r"[A-Z0-9_]+", kind) or not re.fullmatch(r"\d{8}T\d{6}", stamp):
        raise ValueError("dump file name parts are not safe")
    return f"{kind}_{stamp}.dmp"


def _ps_single(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def zip_command(dump_path: str, zip_path: str) -> str:
    """Build a remote PowerShell command that zips one dump file."""
    script = (
        "Compress-Archive -LiteralPath "
        + _ps_single(dump_path)
        + " -DestinationPath "
        + _ps_single(zip_path)
        + " -Force"
    )
    return 'powershell.exe -NoProfile -NonInteractive -Command "' + script + '"'


def unzip_command(zip_path: str, directory: str) -> str:
    """Build a remote PowerShell command that extracts a dump zip."""
    script = (
        "Expand-Archive -LiteralPath "
        + _ps_single(zip_path)
        + " -DestinationPath "
        + _ps_single(directory)
        + " -Force"
    )
    return 'powershell.exe -NoProfile -NonInteractive -Command "' + script + '"'


def directory_probe_command(directory: str) -> str:
    """Build a remote command that succeeds only when a directory exists."""
    shown = f'"{directory}"' if " " in directory else directory
    return f"if exist {shown} (echo DIRECTORY_OK) else (echo DIRECTORY_MISSING & exit /b 2)"


def _export_plsql() -> str:
    return """
declare
  handle number;
  state varchar2(30) := 'UNDEFINED';
begin
  handle := dbms_datapump.open(operation => 'EXPORT', job_mode => 'SCHEMA', job_name => :job_name);
  begin
    dbms_datapump.add_file(handle => handle, filename => :dump_name, directory => :directory_name);
    dbms_datapump.add_file(
      handle => handle,
      filename => :log_name,
      directory => :directory_name,
      filetype => dbms_datapump.ku$_file_type_log_file
    );
    dbms_datapump.metadata_filter(handle => handle, name => 'SCHEMA_EXPR', value => :schema_expr);
    dbms_datapump.start_job(handle => handle);
    dbms_datapump.wait_for_job(handle => handle, job_state => state);
    :job_state := state;
  exception
    when others then
      begin
        dbms_datapump.stop_job(handle => handle, immediate => 1, keep_master => 0);
      exception
        when others then null;
      end;
      raise;
  end;
end;
"""


def _import_plsql(remap_count: int) -> str:
    remaps = "\n".join(
        "    dbms_datapump.metadata_remap("
        "handle => handle, name => 'REMAP_TABLESPACE', "
        f"old_value => :old_{index}, value => :new_{index});"
        for index in range(remap_count)
    )
    return f"""
declare
  handle number;
  state varchar2(30) := 'UNDEFINED';
begin
  handle := dbms_datapump.open(operation => 'IMPORT', job_mode => 'SCHEMA', job_name => :job_name);
  begin
    dbms_datapump.add_file(handle => handle, filename => :dump_name, directory => :directory_name);
    dbms_datapump.add_file(
      handle => handle,
      filename => :log_name,
      directory => :directory_name,
      filetype => dbms_datapump.ku$_file_type_log_file
    );
{remaps}
    dbms_datapump.start_job(handle => handle);
    dbms_datapump.wait_for_job(handle => handle, job_state => state);
    :job_state := state;
  exception
    when others then
      begin
        dbms_datapump.stop_job(handle => handle, immediate => 1, keep_master => 0);
      exception
        when others then null;
      end;
      raise;
  end;
end;
"""


def _ora_lines(log_text: str) -> list[str]:
    return [line.strip() for line in log_text.splitlines() if "ORA-" in line][:40]


def tcp_open(host: str, port: int, timeout: float = 5) -> bool:
    """Return whether a TCP port accepts a connection."""
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


class ParamikoRemote:
    """File and command access over an already open SSH client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def close(self) -> None:
        self._client.close()

    def run(self, command: str) -> str:
        _stdin, stdout, stderr = self._client.exec_command(command, timeout=600, get_pty=False)
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        if exit_status != 0:
            detail = (error or output).strip()
            raise RuntimeError(f"command exited {exit_status}: {detail}")
        return output

    def download(self, remote_path: str, local_path: str) -> None:
        sftp = self._client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()

    def upload(self, local_path: str, remote_path: str) -> None:
        sftp = self._client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def read_text(self, remote_path: str) -> str:
        sftp = self._client.open_sftp()
        try:
            with sftp.open(remote_path, "r") as handle:
                data = handle.read(100_000)
        finally:
            sftp.close()
        if isinstance(data, str):
            return data
        return data.decode("utf-8", errors="replace")


class SmbRemote:
    """Run a command with Task Scheduler and copy files over an admin share.

    SSH is closed on some database hosts. The saved Windows account can still
    reach ``C$`` and ``D$``. The password is passed only through the child
    process environment and is removed from errors.
    """

    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password

    def close(self) -> None:
        self.password = ""

    def _redact(self, text: str) -> str:
        if self.password and self.password in text:
            return text.replace(self.password, "***")
        return text

    def unc(self, windows_path: str) -> str:
        normalized = windows_path.replace("/", "\\")
        if len(normalized) < 3 or normalized[1:3] != ":\\":
            raise ValueError(f"not a Windows path: {windows_path}")
        return "\\\\" + self.host + "\\" + normalized[0] + "$\\" + normalized[3:]

    def _powershell(self, script: str, **env_values: str) -> str:
        env = os.environ.copy()
        env["MYORACLE_REMOTE_PASSWORD"] = self.password
        env["MYORACLE_REMOTE_USER"] = self.username
        env.update(env_values)
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            raise RuntimeError(self._redact(output.strip() or f"powershell exited {completed.returncode}"))
        return self._redact(completed.stdout)

    def _exists(self, windows_path: str) -> bool:
        script = r"""
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
$sec = ConvertTo-SecureString $env:MYORACLE_REMOTE_PASSWORD -AsPlainText -Force
Remove-Item Env:MYORACLE_REMOTE_PASSWORD
$cred = [pscredential]::new($env:MYORACLE_REMOTE_USER, $sec)
if (Get-PSDrive MYORACLE -ErrorAction SilentlyContinue) { Remove-PSDrive MYORACLE -Force }
New-PSDrive -Name MYORACLE -PSProvider FileSystem -Root $env:MYORACLE_UNC_ROOT -Credential $cred | Out-Null
if (Test-Path -LiteralPath $env:MYORACLE_LEAF) { 'YES' } else { 'NO' }
"""
        unc = self.unc(windows_path)
        root, leaf = unc.rsplit("\\", 1)
        answer = self._powershell(script, MYORACLE_UNC_ROOT=root, MYORACLE_LEAF="MYORACLE:\\" + leaf)
        return "YES" in answer

    def run(self, command: str) -> str:
        probe = re.fullmatch(
            r'if exist (?:"([A-Za-z]:\\[^"]+)"|([A-Za-z]:\\[^\s]+)) \(echo DIRECTORY_OK\) else \(echo DIRECTORY_MISSING & exit /b 2\)',
            command,
        )
        if probe:
            if not self._exists(probe.group(1) or probe.group(2)):
                raise RuntimeError(f"directory is missing: {probe.group(1)}")
            return "DIRECTORY_OK\n"
        quoted = re.findall(r"'([A-Za-z]:\\[^']+)'", command)
        if not quoted:
            raise ValueError("remote command has no Windows path to anchor its script")
        folder = str(Path(quoted[0]).parent)
        stamp = str(time.time_ns())
        bat_path = folder + "\\myoracle_" + stamp + ".bat"
        log_path = folder + "\\myoracle_" + stamp + ".log"
        bat = "@echo off\r\n" + command + "\r\necho EXIT_%ERRORLEVEL%> \"" + log_path + "\"\r\n"
        self._write(bat_path, bat)
        task = "MyOracleDp" + stamp[-8:]
        self._schtasks(["/Create", "/TN", task, "/TR", bat_path, "/SC", "ONCE", "/ST", "00:00", "/RL", "HIGHEST", "/F"])
        try:
            self._schtasks(["/Run", "/TN", task])
            deadline = time.time() + 180
            while time.time() < deadline:
                time.sleep(2)
                if self._exists(log_path):
                    log = self.read_text(log_path)
                    if "EXIT_" in log:
                        code = log.strip().split("EXIT_", 1)[1].strip()
                        if code not in {"0", ""}:
                            raise RuntimeError(f"remote command exited {code}")
                        return log
            raise RuntimeError("remote command did not finish within 180 seconds")
        finally:
            subprocess.run(
                ["schtasks.exe", "/Delete", "/S", self.host, "/U", self.username, "/P", self.password, "/TN", task, "/F"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

    def _schtasks(self, args: list[str]) -> None:
        completed = subprocess.run(
            ["schtasks.exe", "/S", self.host, "/U", self.username, "/P", self.password, *args],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            detail = self._redact((completed.stderr or completed.stdout or "").strip())
            raise RuntimeError(f"schtasks exited {completed.returncode}: {detail}")

    def _write(self, windows_path: str, content: str) -> None:
        script = r"""
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
$sec = ConvertTo-SecureString $env:MYORACLE_REMOTE_PASSWORD -AsPlainText -Force
Remove-Item Env:MYORACLE_REMOTE_PASSWORD
$cred = [pscredential]::new($env:MYORACLE_REMOTE_USER, $sec)
if (Get-PSDrive MYORACLE -ErrorAction SilentlyContinue) { Remove-PSDrive MYORACLE -Force }
New-PSDrive -Name MYORACLE -PSProvider FileSystem -Root $env:MYORACLE_UNC_ROOT -Credential $cred | Out-Null
$dest = Join-Path (Get-PSDrive MYORACLE).Root $env:MYORACLE_NAME
[IO.File]::WriteAllBytes($dest, [Convert]::FromBase64String($env:MYORACLE_BODY_B64))
"""
        root, _leaf = self._share_parts(windows_path)
        name = Path(windows_path).name
        encoded = base64.b64encode(content.encode("ascii")).decode("ascii")
        self._powershell(script, MYORACLE_UNC_ROOT=root, MYORACLE_NAME=name, MYORACLE_BODY_B64=encoded)

    def _share_parts(self, windows_path: str) -> tuple[str, str]:
        unc = self.unc(windows_path)
        root, name = unc.rsplit("\\", 1)
        return root, "MYORACLE:\\" + name

    def download(self, remote_path: str, local_path: str) -> None:
        self._copy(self.unc(remote_path.replace("/", "\\")), local_path)

    def upload(self, local_path: str, remote_path: str) -> None:
        self._copy(local_path, self.unc(remote_path.replace("/", "\\")))

    def _copy(self, source: str, destination: str) -> None:
        script = r"""
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
$sec = ConvertTo-SecureString $env:MYORACLE_REMOTE_PASSWORD -AsPlainText -Force
Remove-Item Env:MYORACLE_REMOTE_PASSWORD
$cred = [pscredential]::new($env:MYORACLE_REMOTE_USER, $sec)
if (Get-PSDrive MYORACLE -ErrorAction SilentlyContinue) { Remove-PSDrive MYORACLE -Force }
New-PSDrive -Name MYORACLE -PSProvider FileSystem -Root $env:MYORACLE_UNC_ROOT -Credential $cred | Out-Null
if ($env:MYORACLE_DIRECTION -eq 'download') {
  Copy-Item -LiteralPath $env:MYORACLE_LEAF -Destination $env:MYORACLE_OTHER -Force
} else {
  Copy-Item -LiteralPath $env:MYORACLE_OTHER -Destination $env:MYORACLE_LEAF -Force
}
"""
        remote, local, direction = (source, destination, "download") if source.startswith("\\\\") else (destination, source, "upload")
        root, leaf = self._share_parts_unc(remote)
        self._powershell(
            script,
            MYORACLE_UNC_ROOT=root,
            MYORACLE_LEAF=leaf,
            MYORACLE_OTHER=local,
            MYORACLE_DIRECTION=direction,
        )

    def _share_parts_unc(self, unc: str) -> tuple[str, str]:
        root, name = unc.rsplit("\\", 1)
        return root, "MYORACLE:\\" + name

    def read_text(self, remote_path: str) -> str:
        windows = remote_path.replace("/", "\\")
        script = r"""
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
$sec = ConvertTo-SecureString $env:MYORACLE_REMOTE_PASSWORD -AsPlainText -Force
Remove-Item Env:MYORACLE_REMOTE_PASSWORD
$cred = [pscredential]::new($env:MYORACLE_REMOTE_USER, $sec)
if (Get-PSDrive MYORACLE -ErrorAction SilentlyContinue) { Remove-PSDrive MYORACLE -Force }
New-PSDrive -Name MYORACLE -PSProvider FileSystem -Root $env:MYORACLE_UNC_ROOT -Credential $cred | Out-Null
Get-Content -LiteralPath $env:MYORACLE_LEAF -Raw
"""
        root, leaf = self._share_parts(windows)
        return self._powershell(script, MYORACLE_UNC_ROOT=root, MYORACLE_LEAF=leaf)


class _Database:
    def __init__(self, name: str, connect: Callable[[str], Any], open_ssh: Callable[[str], Any]) -> None:
        self.name = name
        self._connect = connect
        self._open_ssh = open_ssh
        self._connection: Any = None
        self._ssh: Any = None

    def close(self) -> None:
        if self._ssh is not None:
            self._ssh.close()
            self._ssh = None
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _oracle(self) -> Any:
        if self._connection is None:
            self._connection = self._connect(self.name)
            self._connection.call_timeout = 1_800_000
        return self._connection

    def _shell(self) -> Any:
        if self._ssh is None:
            self._ssh = self._open_ssh(self.name)
        return self._ssh

    def query(self, sql: str) -> list[tuple]:
        with self._oracle().cursor() as cursor:
            cursor.execute(sql)
            return list(cursor.fetchall())

    def datapump(self, sql: str, binds: dict[str, Any]) -> str:
        with self._oracle().cursor() as cursor:
            state = cursor.var(str)
            cursor.execute(sql, {**binds, "job_state": state})
            value = state.getvalue()
        return "" if value is None else str(value)

    def run(self, command: str) -> str:
        return self._shell().run(command)

    def download(self, remote_path: str, local_path: str) -> None:
        self._shell().download(remote_path, local_path)

    def upload(self, local_path: str, remote_path: str) -> None:
        self._shell().upload(local_path, remote_path)

    def read_text(self, remote_path: str) -> str:
        return self._shell().read_text(remote_path)


def _users(database: _Database, schemas: list[str]) -> dict[str, str]:
    rows = database.query(
        "select username, nvl(oracle_maintained, 'N') from dba_users "
        f"where username in ({_sql_list(schemas)})"
    )
    return {str(username): str(maintained) for username, maintained in rows}


def _permanent_tablespaces(database: _Database, schemas: list[str]) -> list[str]:
    rows = database.query(
        "select distinct tablespace_name from ("
        "select default_tablespace as tablespace_name from dba_users "
        f"where username in ({_sql_list(schemas)}) "
        "union all select tablespace_name from dba_segments "
        f"where owner in ({_sql_list(schemas)}) and tablespace_name is not null"
        ") order by tablespace_name"
    )
    names = [str(row[0]) for row in rows if row[0]]
    if not names:
        return []
    permanent = database.query(
        "select tablespace_name from dba_tablespaces "
        f"where contents = 'PERMANENT' and tablespace_name in ({_sql_list(names)}) "
        "order by tablespace_name"
    )
    return [str(row[0]) for row in permanent]


def _known_tablespaces(database: _Database, names: list[str]) -> set[str]:
    if not names:
        return set()
    rows = database.query(
        "select tablespace_name from dba_tablespaces "
        f"where tablespace_name in ({_sql_list(names)})"
    )
    return {str(row[0]) for row in rows}


def _directory_path(database: _Database, directory_name: str) -> str:
    rows = database.query(
        "select directory_path from dba_directories "
        f"where directory_name = '{directory_name}'"
    )
    if len(rows) != 1 or not rows[0][0]:
        raise ValueError(f"{database.name} has no directory object {directory_name}")
    return _windows_directory(str(rows[0][0]))


def _object_count(database: _Database, schema: str) -> int:
    rows = database.query(f"select count(*) from dba_objects where owner = '{schema}'")
    return int(rows[0][0])


def copy_schemas(
    source_name: str,
    target_name: str,
    schemas: list[str],
    *,
    confirmed: bool,
    tablespace_remap: dict[str, str] | None,
    directory_name: str,
    source_directory_name: str | None = None,
    target_directory_name: str | None = None,
    connect: Callable[[str], Any],
    open_ssh: Callable[[str], Any],
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Export, zip, transfer, and import schemas. Stop when the target has one."""
    if source_name == target_name:
        raise ValueError("source and target connections must be different")
    names = normalize_schemas(schemas)
    remap = normalize_remap(tablespace_remap)
    directory = normalize_directory(directory_name)
    source_directory_name = normalize_directory(source_directory_name or directory)
    target_directory_name = normalize_directory(target_directory_name or directory)
    source = _Database(source_name, connect, open_ssh)
    target = _Database(target_name, connect, open_ssh)
    try:
        source_users = _users(source, names)
        missing = [name for name in names if name not in source_users]
        if missing:
            raise ValueError(f"{source_name} is missing schemas: {', '.join(missing)}")
        maintained = [name for name, flag in source_users.items() if flag == "Y"]
        if maintained:
            raise ValueError(f"Oracle-maintained schemas cannot be copied: {', '.join(maintained)}")
        existing = [name for name in names if name in _users(target, names)]
        if existing:
            return {
                "status": "stopped",
                "reason": "destination schema already exists",
                "source": source_name,
                "target": target_name,
                "schemas": names,
                "existing_on_target": existing,
            }
        source_tablespaces = _permanent_tablespaces(source, names)
        needed = list(dict.fromkeys([*source_tablespaces, *remap.values()]))
        present = _known_tablespaces(target, needed)
        active_remap = {old: new for old, new in remap.items() if old in source_tablespaces}
        unresolved = [
            tablespace for tablespace in source_tablespaces
            if tablespace not in present and tablespace not in active_remap
        ]
        if unresolved:
            raise ValueError(
                "Target is missing tablespaces with no remap: " + ", ".join(unresolved)
            )
        unknown_remap = [new for new in active_remap.values() if new not in present]
        if unknown_remap:
            raise ValueError("Remap targets do not exist: " + ", ".join(unknown_remap))
        source_directory = _directory_path(source, source_directory_name)
        target_directory = _directory_path(target, target_directory_name)
        stamp = (now or datetime.now)().strftime("%Y%m%dT%H%M%S")
        kind = names[0] if len(names) == 1 else "SCHEMAS"
        dump_name = _file_name(kind, stamp)
        log_name = dump_name[:-4] + ".log"
        import_log_name = dump_name[:-4] + "_imp.log"
        zip_name = dump_name + ".zip"
        plan = {
            "source": source_name,
            "target": target_name,
            "schemas": names,
            "source_directory_object": source_directory_name,
            "target_directory_object": target_directory_name,
            "source_directory": source_directory,
            "target_directory": target_directory,
            "dump_file": dump_name,
            "zip_file": zip_name,
            "tablespace_remap": active_remap,
        }
        if not confirmed:
            return {"status": "not_confirmed", **plan}

        source.run(directory_probe_command(source_directory))
        target.run(directory_probe_command(target_directory))
        schema_expr = "IN (" + _sql_list(names) + ")"
        export_state = source.datapump(
            _export_plsql(),
            {
                "job_name": f"E{stamp.replace('T', '')}",
                "dump_name": dump_name,
                "log_name": log_name,
                "directory_name": source_directory_name,
                "schema_expr": schema_expr,
            },
        )
        source_dump = f"{source_directory}\\{dump_name}"
        source_zip = f"{source_directory}\\{zip_name}"
        source_log = f"{source_directory}\\{log_name}"
        export_log = source.read_text(source_log.replace("\\", "/"))
        export_errors = _ora_lines(export_log)
        if export_state != "COMPLETED":
            raise RuntimeError(
                f"{source_name} export finished as {export_state or 'UNKNOWN'}: {export_errors}"
            )
        source.run(zip_command(source_dump, source_zip))
        with TemporaryDirectory(prefix="schema_datapump_") as temporary:
            local_zip = str(Path(temporary) / zip_name)
            source.download(source_zip.replace("\\", "/"), local_zip)
            target_zip = f"{target_directory}\\{zip_name}"
            target.upload(local_zip, target_zip.replace("\\", "/"))
        target.run(unzip_command(f"{target_directory}\\{zip_name}", target_directory))
        arrived = [name for name in names if name in _users(target, names)]
        if arrived:
            raise RuntimeError(
                "Stopped before import because the destination schema appeared: "
                + ", ".join(arrived)
            )
        import_binds: dict[str, Any] = {
            "job_name": f"I{stamp.replace('T', '')}",
            "dump_name": dump_name,
            "log_name": import_log_name,
            "directory_name": target_directory_name,
        }
        for index, (old, new) in enumerate(sorted(active_remap.items())):
            import_binds[f"old_{index}"] = old
            import_binds[f"new_{index}"] = new
        import_state = target.datapump(_import_plsql(len(active_remap)), import_binds)
        import_log = target.read_text(f"{target_directory}/{import_log_name}")
        import_errors = _ora_lines(import_log)
        if import_state != "COMPLETED":
            raise RuntimeError(
                f"{target_name} import finished as {import_state or 'UNKNOWN'}: {import_errors}"
            )
        return {
            "status": "imported_with_errors" if import_errors else "imported",
            **plan,
            "export_state": export_state,
            "import_state": import_state,
            "export_errors": export_errors,
            "import_errors": import_errors,
            "object_counts": {name: _object_count(target, name) for name in names},
        }
    finally:
        source.close()
        target.close()
