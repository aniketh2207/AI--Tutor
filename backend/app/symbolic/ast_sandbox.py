"""Isolated subprocess sandbox runner for Track 2 Python code verification."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def run_code_in_sandbox(
    code_str: str,
    function_name: str,
    test_cases: list[dict[str, Any]],
    timeout_seconds: float = 2.0,
) -> tuple[bool, str]:
    """Execute student code against `test_cases` inside an isolated 2.0s subprocess."""
    payload_json = json.dumps(
        {
            "code": code_str,
            "function_name": function_name,
            "test_cases": test_cases,
        }
    )

    runner_script = (
        "import json, sys\n"
        f"payload = json.loads({payload_json!r})\n"
        "ns = {}\n"
        "try:\n"
        "    exec(payload['code'], ns)\n"
        "except Exception as exc:\n"
        "    print(json.dumps({'passed': False, 'detail': f'RUNTIME_ERROR: {exc}'}))\n"
        "    sys.exit(0)\n"
        "fn_name = payload['function_name']\n"
        "if fn_name and fn_name not in ns:\n"
        "    print(json.dumps({'passed': False, 'detail': f'MISSING_FUNCTION: {fn_name} not defined'}))\n"
        "    sys.exit(0)\n"
        "fn = ns.get(fn_name)\n"
        "for idx, tc in enumerate(payload['test_cases']):\n"
        "    args = tc.get('input', [])\n"
        "    expected = tc.get('expected')\n"
        "    try:\n"
        "        actual = fn(*args) if isinstance(args, list) else fn(args)\n"
        "    except Exception as exc:\n"
        "        print(json.dumps({'passed': False, 'detail': f'TEST_{idx}_EXCEPTION: {exc}'}))\n"
        "        sys.exit(0)\n"
        "    if actual != expected:\n"
        "        print(json.dumps({'passed': False, 'detail': f'TEST_{idx}_FAILED: expected {expected!r}, got {actual!r}'}))\n"
        "        sys.exit(0)\n"
        "print(json.dumps({'passed': True, 'detail': 'ALL_TESTS_PASSED'}))\n"
    )

    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", runner_script],
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            f"SANDBOX_TIMEOUT: Execution exceeded {timeout_seconds}s time limit.",
        )

    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0 or not stdout:
        stderr = (completed.stderr or "").strip()
        return False, f"SANDBOX_ERROR: {stderr or 'Subprocess exited abnormally.'}"

    try:
        last_line = stdout.splitlines()[-1]
        data = json.loads(last_line)
        return bool(data.get("passed", False)), str(data.get("detail", ""))
    except Exception as exc:
        return False, f"SANDBOX_OUTPUT_ERROR: {exc}"
