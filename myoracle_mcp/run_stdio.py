#!/usr/bin/env python3
"""Cross-platform stdio launcher for the myoracle MCP server."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("MYORACLE_REPOSITORY_ROOT", str(REPO))

if os.name == "nt":
    venv_python = REPO / "myoracle_mcp" / ".venv" / "Scripts" / "python.exe"
else:
    venv_python = REPO / "myoracle_mcp" / ".venv" / "bin" / "python"

python = venv_python if venv_python.is_file() else Path(sys.executable)
server = REPO / "myoracle_mcp" / "server.py"
raise SystemExit(subprocess.call([str(python), str(server)], env=os.environ))