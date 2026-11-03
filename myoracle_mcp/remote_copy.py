"""Copy files to a saved Windows SSH host with the OpenSSH scp client."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

SCP_EXE = Path(r"C:\Windows\System32\OpenSSH\scp.exe")
SSH_EXE = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")
CREATE_NO_WINDOW = 0x08000000


def _known_hosts() -> str:
    return str(Path.home() / ".ssh" / "known_hosts").replace("\\", "/")


def _openssh_options(port_flag: str, port: int) -> list[str]:
    return [
        port_flag,
        str(port),
        "-o",
        "BatchMode=no",
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={_known_hosts()}",
    ]


def scp_command(host: str, port: int, username: str, sources: list[Path], remote_directory: str) -> list[str]:
    if not SCP_EXE.is_file():
        raise RuntimeError(f"OpenSSH scp client not found: {SCP_EXE}")
    destination = f"{username}@{host}:{remote_directory.rstrip('/')}/"
    return [str(SCP_EXE), *_openssh_options("-P", port), *[str(source) for source in sources], destination]


def missing_directory(message: str) -> bool:
    text = message.lower()
    return "no such file" in text or "not a directory" in text


def _child_environment(password: str, askpass: str) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("ProgramData", r"C:\ProgramData")
    env["SCP_UPLOAD_SECRET"] = password
    env["SSH_ASKPASS"] = askpass
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DISPLAY"] = "localhost"
    return env


def _askpass_program() -> str:
    target = Path(tempfile.gettempdir()) / "myoracle_scp_askpass.exe"
    if target.is_file():
        return str(target)
    compiler = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not compiler.is_file():
        raise RuntimeError(f"C# compiler not found: {compiler}")
    source = target.with_suffix(".cs")
    source.write_text(
        "using System;\n"
        "class Askpass {\n"
        "  static void Main() {\n"
        '    var value = Environment.GetEnvironmentVariable("SCP_UPLOAD_SECRET");\n'
        "    if (value != null) Console.Out.Write(value);\n"
        "  }\n"
        "}\n",
        encoding="ascii",
    )
    completed = subprocess.run(
        [str(compiler), "/nologo", "/t:winexe", f"/out:{target}", str(source)],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    source.unlink(missing_ok=True)
    if completed.returncode != 0 or not target.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"could not build scp askpass: {detail}")
    return str(target)


def _run_openssh(command: list[str], password: str) -> subprocess.CompletedProcess[str]:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return subprocess.run(
        command,
        env=_child_environment(password, _askpass_program()),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
        startupinfo=startup,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )


def _check(completed: subprocess.CompletedProcess[str], program: str) -> None:
    if completed.returncode == 0:
        return
    detail = (completed.stderr or completed.stdout or "").strip()
    raise RuntimeError(f"{program} exited {completed.returncode}: {detail or '(no output)'}")


def create_remote_directory(host: str, port: int, username: str, password: str, remote_directory: str) -> None:
    if not SSH_EXE.is_file():
        raise RuntimeError(f"OpenSSH ssh client not found: {SSH_EXE}")
    remote = remote_directory.rstrip("/").replace("/", "\\")
    command = [
        str(SSH_EXE),
        *_openssh_options("-p", port),
        f"{username}@{host}",
        "cmd",
        "/c",
        "mkdir",
        remote,
    ]
    _check(_run_openssh(command, password), "ssh")


def upload_with_scp(
    host: str,
    port: int,
    username: str,
    password: str,
    sources: list[Path],
    remote_directory: str,
) -> dict[str, float | list[str]]:
    started = time.perf_counter()
    completed = _run_openssh(scp_command(host, port, username, sources, remote_directory), password)
    _check(completed, "scp")
    remote = remote_directory.rstrip("/")
    return {
        "seconds": round(time.perf_counter() - started, 3),
        "uploaded": [f"{remote}/{source.name}" for source in sources],
    }
