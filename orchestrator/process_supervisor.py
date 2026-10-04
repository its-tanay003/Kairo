"""
Process supervisor for shell.run.v1 adapter & host processes.
Enforces hard timeouts, output capture (stdout/stderr/exit_code),
process tracking by task_id, process tree inspection (parent/child/background),
and interactive controls: pause (suspend), resume, stop (SIGKILL), retry.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import psutil
except ImportError:
    psutil = None

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
    cwd: Optional[str] = None
    status: str = "running"  # running, paused, stopped, completed
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    done_event: threading.Event = field(default_factory=threading.Event)
    _seq: int = 0

    def add_chunk(self, stream_type: str, text: str):
        if not text:
            return
        with self.lock:
            self._seq += 1
            self.chunks.append({
                "seq": self._seq,
                "stream": stream_type,
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def get_chunks_since(self, since_seq: int) -> List[Dict[str, Any]]:
        with self.lock:
            return [c for c in self.chunks if c["seq"] > since_seq]


class ProcessSupervisor:
    def __init__(self):
        self._active: Dict[str, ActiveProcessRecord] = {}
        self._history: Dict[str, ActiveProcessRecord] = {}
        self._lock = threading.Lock()

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
        Streams stdout/stderr into chunks as they arrive.
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
                bufsize=1,
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
            cwd=cwd,
            status="running",
        )
        record.add_chunk("system", f"[Supervisor] Process started PID={proc.pid} Command={' '.join(full_cmd)}\n")

        with self._lock:
            self._active[task_id] = record
            self._history[task_id] = record

        stdout_list = []
        stderr_list = []

        def read_stream(stream, stream_name, collector):
            try:
                for line in iter(stream.readline, ""):
                    if not line:
                        break
                    collector.append(line)
                    record.add_chunk(stream_name, line)
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        t_out = threading.Thread(target=read_stream, args=(proc.stdout, "stdout", stdout_list), daemon=True)
        t_err = threading.Thread(target=read_stream, args=(proc.stderr, "stderr", stderr_list), daemon=True)
        t_out.start()
        t_err.start()

        timed_out = False
        killed = False

        start_wait = time.time()
        while proc.poll() is None:
            if time.time() - start_wait > timeout_sec:
                timed_out = True
                logger.warning(f"[Supervisor] Task {task_id} (PID {proc.pid}) timed out after {timeout_sec}s. Terminating.")
                record.add_chunk("system", f"\n[Supervisor Timeout] Process exceeded hard timeout of {timeout_ms}ms and was killed.\n")
                self._kill_proc(proc)
                break
            time.sleep(0.05)

        proc.wait()
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

        exit_code = proc.returncode if not timed_out else 124
        if record.status != "stopped":
            record.status = "timeout" if timed_out else ("completed" if exit_code == 0 else "error")

        record.done_event.set()

        with self._lock:
            self._active.pop(task_id, None)

        stdout = "".join(stdout_list)
        stderr = "".join(stderr_list)
        if timed_out:
            stderr += f"\n[Supervisor Timeout] Process exceeded hard timeout of {timeout_ms}ms and was killed."

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

    def pause_by_task_id(self, task_id: str) -> Dict[str, Any]:
        """Pauses a running process and its children."""
        with self._lock:
            record = self._active.get(task_id)
        if not record:
            return {"status": "not_found", "task_id": task_id, "message": f"Task not running: {task_id}"}

        try:
            if psutil:
                p = psutil.Process(record.pid)
                for child in p.children(recursive=True):
                    try:
                        child.suspend()
                    except Exception:
                        pass
                p.suspend()
            record.status = "paused"
            record.add_chunk("system", f"\n[Supervisor] Process PID={record.pid} PAUSED.\n")
            return {"status": "paused", "task_id": task_id, "process_id": record.pid}
        except Exception as e:
            return {"status": "error", "task_id": task_id, "error": str(e)}

    def resume_by_task_id(self, task_id: str) -> Dict[str, Any]:
        """Resumes a paused process and its children."""
        with self._lock:
            record = self._active.get(task_id)
        if not record:
            return {"status": "not_found", "task_id": task_id, "message": f"Task not running: {task_id}"}

        try:
            if psutil:
                p = psutil.Process(record.pid)
                p.resume()
                for child in p.children(recursive=True):
                    try:
                        child.resume()
                    except Exception:
                        pass
            record.status = "running"
            record.add_chunk("system", f"\n[Supervisor] Process PID={record.pid} RESUMED.\n")
            return {"status": "running", "task_id": task_id, "process_id": record.pid}
        except Exception as e:
            return {"status": "error", "task_id": task_id, "error": str(e)}

    def kill_by_task_id(self, task_id: str) -> Dict[str, Any]:
        """Kill switch endpoint helper: SIGKILL any running process by task_id."""
        with self._lock:
            record = self._active.get(task_id)
        if not record:
            return {
                "status": "not_found",
                "task_id": task_id,
                "message": f"No active running process found for task_id: {task_id}",
            }

        pid = record.pid
        logger.info(f"[Supervisor] Kill switch activated for task_id={task_id}, PID={pid}")
        record.status = "stopped"
        record.add_chunk("system", f"\n[Supervisor] Process PID={pid} terminated by SIGKILL.\n")
        record.done_event.set()
        self._kill_proc(record.process)

        with self._lock:
            self._active.pop(task_id, None)

        return {
            "status": "killed",
            "task_id": task_id,
            "process_id": pid,
            "signal": "SIGKILL",
            "message": f"Process {pid} terminated forcibly by kill switch",
        }

    def stop_by_task_id(self, task_id: str) -> Dict[str, Any]:
        return self.kill_by_task_id(task_id)

    def retry_by_task_id(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._history.get(task_id)
        if not record:
            return {"status": "not_found", "task_id": task_id, "message": "Original task not found in history"}

        if task_id in self._active:
            self.stop_by_task_id(task_id)
            time.sleep(0.2)

        # Launch fresh thread
        t = threading.Thread(
            target=self.execute,
            args=(task_id, record.command, record.args, int(record.timeout_sec * 1000), record.cwd),
            daemon=True,
        )
        t.start()
        return {"status": "started", "task_id": task_id, "message": f"Task {task_id} restarted cleanly"}

    def get_process_tree(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._active.get(task_id) or self._history.get(task_id)

        if not record:
            return {"task_id": task_id, "status": "not_found", "nodes": []}

        nodes = []
        root_pid = record.pid

        if psutil:
            try:
                parent_proc = psutil.Process(root_pid)
                is_running = parent_proc.is_running()
                status_str = "running"
                if record.status == "paused":
                    status_str = "paused"
                elif not is_running:
                    status_str = record.status

                root_node = {
                    "pid": parent_proc.pid,
                    "ppid": parent_proc.ppid(),
                    "name": parent_proc.name(),
                    "cmd": " ".join(parent_proc.cmdline()) if parent_proc.cmdline() else parent_proc.name(),
                    "type": "parent",
                    "state": status_str,
                    "is_background": False,
                    "cpu_pct": round(parent_proc.cpu_percent(interval=None), 1),
                    "mem_pct": round(parent_proc.memory_percent(), 1),
                    "children": [],
                }

                try:
                    for child in parent_proc.children(recursive=True):
                        try:
                            is_bg = child.ppid() != root_pid
                            c_node = {
                                "pid": child.pid,
                                "ppid": child.ppid(),
                                "name": child.name(),
                                "cmd": " ".join(child.cmdline()) if child.cmdline() else child.name(),
                                "type": "background" if is_bg else "child",
                                "state": status_str,
                                "is_background": is_bg,
                                "cpu_pct": round(child.cpu_percent(interval=None), 1),
                                "mem_pct": round(child.memory_percent(), 1),
                                "children": [],
                            }
                            root_node["children"].append(c_node)
                        except Exception:
                            continue
                except Exception:
                    pass

                nodes.append(root_node)
            except Exception:
                nodes.append({
                    "pid": root_pid,
                    "ppid": 1,
                    "name": record.command,
                    "cmd": f"{record.command} {' '.join(record.args)}",
                    "type": "parent",
                    "state": record.status,
                    "is_background": False,
                    "cpu_pct": 0.0,
                    "mem_pct": 0.0,
                    "children": [],
                })
        else:
            nodes.append({
                "pid": root_pid,
                "ppid": 1,
                "name": record.command,
                "cmd": f"{record.command} {' '.join(record.args)}",
                "type": "parent",
                "state": record.status,
                "is_background": False,
                "cpu_pct": 0.0,
                "mem_pct": 0.0,
                "children": [],
            })

        return {
            "task_id": task_id,
            "status": record.status,
            "root_pid": root_pid,
            "nodes": nodes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def list_active(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "task_id": r.task_id,
                    "process_id": r.pid,
                    "command": r.command,
                    "args": r.args,
                    "start_time": r.start_time,
                    "timeout_sec": r.timeout_sec,
                    "status": r.status,
                }
                for r in self._active.values()
            ]

    def _kill_proc(self, proc: subprocess.Popen) -> None:
        try:
            if sys.platform == "win32":
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
