"""HumanEval execution with Docker-first isolation and local fallback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import traceback
from typing import Any, Dict, Optional, Tuple


def clean_code_output(text: str) -> str:
    """Strip markdown fences while preserving raw Python code."""

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _build_runner_script() -> str:
    """Return the isolated runner script used by both Docker and local execution."""

    return textwrap.dedent(
        """
        import json
        import traceback
        from pathlib import Path

        candidate = Path("candidate.py").read_text(encoding="utf-8")
        test_code = Path("test.py").read_text(encoding="utf-8")
        entry_point = Path("entry_point.txt").read_text(encoding="utf-8").strip()
        result = {"success": False, "failure_reason": "runtime_error", "format_ok": False, "detail": ""}
        namespace = {}

        try:
            compile(candidate, "candidate.py", "exec")
            result["format_ok"] = True
            exec(candidate, namespace, namespace)
            exec(test_code, namespace, namespace)
            namespace["check"](namespace[entry_point])
            result["success"] = True
            result["failure_reason"] = "ok"
        except AssertionError as exc:
            result["failure_reason"] = "wrong_answer"
            result["detail"] = str(exc)
        except SyntaxError:
            result["failure_reason"] = "syntax_error"
            result["detail"] = traceback.format_exc()
        except Exception:
            result["failure_reason"] = "runtime_error"
            result["detail"] = traceback.format_exc()

        print(json.dumps(result))
        """
    ).strip()


def _write_execution_files(base_dir: str, code: str, test_code: str, entry_point: str) -> str:
    """Write candidate, tests, and runner files into a temporary workspace."""

    os.makedirs(base_dir, exist_ok=True)
    with open(os.path.join(base_dir, "candidate.py"), "w", encoding="utf-8") as handle:
        handle.write(clean_code_output(code))
    with open(os.path.join(base_dir, "test.py"), "w", encoding="utf-8") as handle:
        handle.write(test_code)
    with open(os.path.join(base_dir, "entry_point.txt"), "w", encoding="utf-8") as handle:
        handle.write(entry_point)
    with open(os.path.join(base_dir, "runner.py"), "w", encoding="utf-8") as handle:
        handle.write(_build_runner_script())
    return os.path.join(base_dir, "runner.py")


def humaneval_is_correct(
    code: str,
    test_code: str,
    entry_point: str,
    timeout_s: int = 5,
    executor: str = "docker",
    docker_image: str = "python:3.11-slim",
    temp_root: str = ".cache/humaneval",
    memory: str = "512m",
    cpus: str = "1.0",
    pids_limit: int = 64,
) -> Tuple[bool, str, bool, Dict[str, Any]]:
    """Execute HumanEval tests in Docker if possible, else fall back to a local subprocess."""

    cleaned_code = clean_code_output(code)
    temp_root_abs = os.path.abspath(temp_root)
    os.makedirs(temp_root_abs, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=temp_root_abs) as work_dir:
        _write_execution_files(work_dir, cleaned_code, test_code, entry_point)
        if executor == "docker":
            docker_path = shutil.which("docker")
            if docker_path:
                result = _run_in_docker(
                    work_dir=work_dir,
                    docker_image=docker_image,
                    timeout_s=timeout_s,
                    memory=memory,
                    cpus=cpus,
                    pids_limit=pids_limit,
                )
                if result is not None:
                    return result
        return _run_locally(work_dir=work_dir, timeout_s=timeout_s)


def _run_in_docker(
    work_dir: str,
    docker_image: str,
    timeout_s: int,
    memory: str,
    cpus: str,
    pids_limit: int,
) -> Optional[Tuple[bool, str, bool, Dict[str, Any]]]:
    """Run the HumanEval payload in a locked-down Docker container."""

    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cpus",
        cpus,
        "--memory",
        memory,
        "--pids-limit",
        str(pids_limit),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--mount",
        f"type=bind,src={work_dir},dst=/workspace,readonly",
        "-w",
        "/workspace",
        docker_image,
        "python",
        "runner.py",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s + 2,
            check=False,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return False, "timeout", False, {"executor": "docker"}

    if completed.returncode != 0 and not completed.stdout.strip():
        return None

    parsed = _parse_runner_output(completed.stdout, default_reason="runtime_error")
    parsed[3]["executor"] = "docker"
    return parsed


def _run_locally(work_dir: str, timeout_s: int) -> Tuple[bool, str, bool, Dict[str, Any]]:
    """Run the HumanEval payload in a local child process."""

    try:
        completed = subprocess.run(
            [sys.executable, "runner.py"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout", False, {"executor": "local"}
    except Exception:
        return False, "runtime_error", False, {"executor": "local", "detail": traceback.format_exc()}

    parsed = _parse_runner_output(completed.stdout, default_reason="runtime_error")
    parsed[3]["executor"] = "local"
    if completed.stderr:
        parsed[3]["stderr"] = completed.stderr
    return parsed


def _parse_runner_output(stdout: str, default_reason: str) -> Tuple[bool, str, bool, Dict[str, Any]]:
    """Parse the runner JSON output and convert it into evaluator fields."""

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return False, default_reason, False, {"detail": "empty_stdout"}
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return False, default_reason, False, {"detail": stdout[-2000:]}

    return (
        bool(payload.get("success", False)),
        str(payload.get("failure_reason", default_reason)),
        bool(payload.get("format_ok", False)),
        payload,
    )
