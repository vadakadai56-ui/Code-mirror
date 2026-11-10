"""Stage 2 (parent side): start tracer.py in a separate process and collect its trace.

    trace = run_code(source)
    # -> {"steps": [...], "stdout": "...", "truncated": bool, "error": None or {kind, message, line}}

Error kinds the frontend shows: "syntax", "blocked", "runtime", "timeout", "crash".
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mirror.tracer import BlockedCode, check_code

TRACER = Path(__file__).with_name("tracer.py")
TIMEOUT_SECONDS = 3
MAX_STEPS = 500


def run_code(source, timeout=TIMEOUT_SECONDS, max_steps=MAX_STEPS):
    # Cheap checks first, so obvious problems don't need a process at all.
    try:
        check_code(ast.parse(source))
    except SyntaxError as e:
        return _error("syntax", f"SyntaxError: {e.msg}", e.lineno)
    except BlockedCode as e:
        return _error("blocked", str(e), e.line)

    # -I: isolated mode (ignores PYTHON* env vars and user site-packages, no cwd on sys.path)
    # -S: don't import the `site` module
    command = [sys.executable, "-I", "-S", str(TRACER)]
    env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT",)}  # Windows needs SYSTEMROOT
    try:
        proc = subprocess.run(
            command,
            input=json.dumps({"code": source, "max_steps": max_steps}),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired:
        return _error(
            "timeout",
            f"Your code ran for more than {timeout} seconds and was stopped. "
            "Look for a loop that never ends or a very slow calculation.",
            None,
        )

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        # No JSON means the process died: e.g. out of memory or CPU limit reached.
        if proc.returncode in (-24, 152):  # SIGXCPU: CPU time limit
            return _error("timeout", "Your code used too much CPU time and was stopped.", None)
        detail = (proc.stderr.strip().splitlines() or ["unknown error"])[-1]
        return _error("crash", f"The program crashed ({detail}). It may have used too much memory.", None)


def _error(kind, message, line):
    return {"steps": [], "stdout": "", "truncated": False, "error": {"kind": kind, "message": message, "line": line}}
