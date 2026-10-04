"""
Process supervisor for shell.run.v1 adapter.
Enforces hard timeouts, output capture (stdout/stderr/exit_code),
process tracking by task_id, and SIGKILL termination switch.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.process_supervisor")


@dataclass
class ProcessResult:
    task_id: str
    process_id: int
    exit_code: int
    stdout: str
    stderr: str
    start_time: str
    end_time: str
    duration_ms: float
    timed_out: bool = False
    killed: bool = False


@dataclass
class ActiveProcessRecord:
    task_id: str
    process: subprocess.Popen
    pid: int
    command: str
    args: List[str]
    start_time: str
    timeout_sec: float


class ProcessSupervisor:
    def __init__(self):
        self._active: Dict[str, ActiveProcessRecord] = {}

    def execute(
        self,
        task_id: str,
        command: str,
        args: Optional[List[str]] = None,
        timeout_ms: int = 10000,
        cwd: Optional[str] = None,
    ) -> ProcessResult:
        """
        Executes command with args list, supervised by hard timeout and tracked by task_id.
        """
        args = args or []
        full_cmd = [command] + [str(a) for a in args]
        timeout_sec = max(0.1, timeout_ms / 1000.0)

        start_time_dt = datetime.now(timezone.utc)
        start_time_iso = start_time_dt.isoformat()
        t0 = time.time()

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            proc = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                creationflags=creationflags,
            )
        except Exception as e:
            end_time_iso = datetime.now(timezone.utc).isoformat()
            duration_ms = round((time.time() - t0) * 1000, 2)
            return ProcessResult(
                task_id=task_id,
                process_id=os.getpid(),
                exit_code=1,
                stdout="",
                stderr=f"Supervisor failed to spawn process: {e}",
                start_time=start_time_iso,
                end_time=end_time_iso,
                duration_ms=duration_ms,
            )

        record = ActiveProcessRecord(
            task_id=task_id,
            process=proc,
            pid=proc.pid,
            command=command,
            args=args,
            start_time=start_time_iso,
            timeout_sec=timeout_sec,
        )
        self._active[task_id] = record

        stdout = ""
        stderr = ""
        exit_code = 0
        timed_out = False
        killed = False

        try:
            stdout, stderr = proc.communicate(timeout=timeout_sec)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            logger.warning(f"[Supervisor] Task {task_id} (PID {proc.pid}) timed out after {timeout_sec}s. Issuing SIGKILL.")
            self._kill_proc(proc)
            try:
                out_extra, err_extra = proc.communicate(timeout=2.0)
                stdout = (stdout or "") + (out_extra or "")
                stderr = (stderr or "") + (err_extra or "") + f"\n[Supervisor Timeout] Process exceeded hard timeout of {timeout_ms}ms and was killed."
            except Exception:
                stderr = (stderr or "") + f"\n[Supervisor Timeout] Process exceeded hard timeout of {timeout_ms}ms and was killed."
            exit_code = 124  # Standard timeout exit code
        except Exception as e:
            self._kill_proc(proc)
            stderr = (stderr or "") + f"\n[Supervisor Error] Execution failed: {e}"
            exit_code = -1
        finally:
            self._active.pop(task_id, None)

        end_time_iso = datetime.now(timezone.utc).isoformat()
        duration_ms = round((time.time() - t0) * 1000, 2)

        return ProcessResult(
            task_id=task_id,
            process_id=proc.pid,
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            start_time=start_time_iso,
            end_time=end_time_iso,
            duration_ms=duration_ms,
            timed_out=timed_out,
            killed=killed,
        )

    def kill_by_task_id(self, task_id: str) -> Dict[str, Any]:
        """
        Kill switch endpoint helper: SIGKILL any running process by task_id.
        """
        record = self._active.get(task_id)
        if not record:
            return {
                "status": "not_found",
                "task_id": task_id,
                "message": f"No active running process found for task_id: {task_id}",
            }

        pid = record.pid
        logger.info(f"[Supervisor] Kill switch activated for task_id={task_id}, PID={pid}")
        self._kill_proc(record.process)
        self._active.pop(task_id, None)

        return {
            "status": "killed",
            "task_id": task_id,
            "process_id": pid,
            "signal": "SIGKILL",
            "message": f"Process {pid} terminated forcibly by kill switch",
        }

    def list_active(self) -> List[Dict[str, Any]]:
        return [
            {
                "task_id": r.task_id,
                "process_id": r.pid,
                "command": r.command,
                "args": r.args,
                "start_time": r.start_time,
                "timeout_sec": r.timeout_sec,
            }
            for r in self._active.values()
        ]

    def _kill_proc(self, proc: subprocess.Popen) -> None:
        try:
            if sys.platform == "win32":
                # Forcibly kill process tree on Windows
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                proc.kill()
        except Exception as e:
            logger.error(f"[Supervisor] Failed to kill process {proc.pid}: {e}")
            try:
                proc.kill()
            except Exception:
                pass


# Global singleton instance
supervisor = ProcessSupervisor()
