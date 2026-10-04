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

try:
    from events.db import Artifact, insert_artifact, compute_sha256
except ImportError:
    Artifact = None
    insert_artifact = None
    compute_sha256 = None

logger = logging.getLogger("orchestrator.process_supervisor")


@dataclass
class ResourceLimits:
    """Resource caps enforced per task by the process supervisor."""
    max_memory_mb: float = 512.0          # Max Resident Set Size (RSS) in MB across process tree
    max_cpu_percent: float = 95.0         # Max CPU% across process tree
    max_disk_mb: float = 100.0            # Max cumulative artifact disk bytes in MB
    max_file_count: int = 100             # Max artifact files generated
    max_output_bytes: int = 10 * 1024 * 1024 # Max stdout/stderr capture buffer (10MB)
    cpu_grace_sec: float = 3.0            # Grace period for sustained high CPU before kill

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ResourceLimits":
        if not data:
            return cls()
        return cls(
            max_memory_mb=float(data.get("max_memory_mb", 512.0)),
            max_cpu_percent=float(data.get("max_cpu_percent", 95.0)),
            max_disk_mb=float(data.get("max_disk_mb", 100.0)),
            max_file_count=int(data.get("max_file_count", 100)),
            max_output_bytes=int(data.get("max_output_bytes", 10 * 1024 * 1024)),
            cpu_grace_sec=float(data.get("cpu_grace_sec", 3.0)),
        )


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
    resource_limit_exceeded: bool = False
    violation_reason: Optional[str] = None
    peak_memory_mb: float = 0.0
    peak_cpu_percent: float = 0.0
    artifacts: List[Dict[str, Any]] = field(default_factory=list)


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
    status: str = "running"  # running, paused, stopped, completed, resource_limit_exceeded, timeout, error
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    done_event: threading.Event = field(default_factory=threading.Event)
    _seq: int = 0
    limits: Optional[ResourceLimits] = None
    artifact_dir: Optional[str] = None
    peak_memory_mb: float = 0.0
    peak_cpu_percent: float = 0.0
    violation_reason: Optional[str] = None

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
        limits: Optional[ResourceLimits | Dict[str, Any]] = None,
        artifact_dir: Optional[str] = None,
    ) -> ProcessResult:
        """
        Executes command with args list, supervised by hard timeout and tracked by task_id.
        Enforces resource limits (CPU/RAM/disk/file-count/output size) and records artifact hashes.
        Streams stdout/stderr into chunks as they arrive.
        """
        args = args or []
        full_cmd = [command] + [str(a) for a in args]
        timeout_sec = max(0.1, timeout_ms / 1000.0)

        if isinstance(limits, dict):
            res_limits = ResourceLimits.from_dict(limits)
        elif isinstance(limits, ResourceLimits):
            res_limits = limits
        else:
            res_limits = ResourceLimits()

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
            limits=res_limits,
            artifact_dir=artifact_dir,
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
        limit_violated = False
        violation_reason = None
        cpu_high_start = None

        start_wait = time.time()
        while proc.poll() is None:
            now = time.time()
            # 1. Timeout Check
            if now - start_wait > timeout_sec:
                timed_out = True
                logger.warning(f"[Supervisor] Task {task_id} (PID {proc.pid}) timed out after {timeout_sec}s. Terminating.")
                record.add_chunk("system", f"\n[Supervisor Timeout] Process exceeded hard timeout of {timeout_ms}ms and was killed.\n")
                self._kill_proc(proc)
                break

            # 2. Output Buffer Size Cap
            out_bytes = sum(len(s.encode("utf-8", errors="ignore")) for s in stdout_list) + sum(len(s.encode("utf-8", errors="ignore")) for s in stderr_list)
            if out_bytes > res_limits.max_output_bytes:
                limit_violated = True
                violation_reason = f"Output size cap exceeded: {out_bytes} bytes > {res_limits.max_output_bytes} bytes"
                logger.warning(f"[Supervisor] Task {task_id} {violation_reason}. Killing.")
                record.add_chunk("system", f"\n[Supervisor Resource Cap] {violation_reason}. Terminating process...\n")
                self._kill_proc(proc)
                break

            # 3. CPU and RAM Limits (psutil)
            if psutil:
                try:
                    p = psutil.Process(proc.pid)
                    children = p.children(recursive=True)
                    all_procs = [p] + children
                    total_rss_bytes = 0
                    total_cpu_pct = 0.0
                    for cp in all_procs:
                        try:
                            if cp.is_running():
                                total_rss_bytes += cp.memory_info().rss
                                total_cpu_pct += cp.cpu_percent(interval=None)
                        except Exception:
                            pass
                    total_rss_mb = total_rss_bytes / (1024.0 * 1024.0)
                    record.peak_memory_mb = max(record.peak_memory_mb, total_rss_mb)
                    record.peak_cpu_percent = max(record.peak_cpu_percent, total_cpu_pct)

                    # Check RAM Limit
                    if total_rss_mb > res_limits.max_memory_mb:
                        limit_violated = True
                        violation_reason = f"Memory cap exceeded: {total_rss_mb:.1f}MB > {res_limits.max_memory_mb}MB"
                        logger.warning(f"[Supervisor] Task {task_id} {violation_reason}. Killing PID {proc.pid}.")
                        record.add_chunk("system", f"\n[Supervisor Resource Cap] {violation_reason}. Terminating process...\n")
                        self._kill_proc(proc)
                        break

                    # Check CPU Limit with grace period
                    if total_cpu_pct > res_limits.max_cpu_percent:
                        if cpu_high_start is None:
                            cpu_high_start = now
                        elif now - cpu_high_start > res_limits.cpu_grace_sec:
                            limit_violated = True
                            violation_reason = f"CPU cap exceeded: sustained {total_cpu_pct:.1f}% > {res_limits.max_cpu_percent}% for >{res_limits.cpu_grace_sec}s"
                            logger.warning(f"[Supervisor] Task {task_id} {violation_reason}. Killing PID {proc.pid}.")
                            record.add_chunk("system", f"\n[Supervisor Resource Cap] {violation_reason}. Terminating process...\n")
                            self._kill_proc(proc)
                            break
                    else:
                        cpu_high_start = None
                except Exception:
                    pass

            # 4. Disk and File-count Limits (Artifact Directory)
            if artifact_dir and os.path.exists(artifact_dir):
                try:
                    f_count = 0
                    total_disk_bytes = 0
                    for root, _, files in os.walk(artifact_dir):
                        f_count += len(files)
                        for f in files:
                            try:
                                total_disk_bytes += os.path.getsize(os.path.join(root, f))
                            except Exception:
                                pass
                    disk_mb = total_disk_bytes / (1024.0 * 1024.0)

                    if f_count > res_limits.max_file_count:
                        limit_violated = True
                        violation_reason = f"File-count cap exceeded: {f_count} files > {res_limits.max_file_count} files"
                        logger.warning(f"[Supervisor] Task {task_id} {violation_reason}. Killing PID {proc.pid}.")
                        record.add_chunk("system", f"\n[Supervisor Resource Cap] {violation_reason}. Terminating process...\n")
                        self._kill_proc(proc)
                        break

                    if disk_mb > res_limits.max_disk_mb:
                        limit_violated = True
                        violation_reason = f"Disk cap exceeded: {disk_mb:.1f}MB > {res_limits.max_disk_mb}MB"
                        logger.warning(f"[Supervisor] Task {task_id} {violation_reason}. Killing PID {proc.pid}.")
                        record.add_chunk("system", f"\n[Supervisor Resource Cap] {violation_reason}. Terminating process...\n")
                        self._kill_proc(proc)
                        break
                except Exception:
                    pass

            time.sleep(0.05)

        proc.wait()
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

        exit_code = proc.returncode if not (timed_out or limit_violated) else (124 if timed_out else 137)
        if record.status != "stopped":
            if limit_violated:
                record.status = "resource_limit_exceeded"
            elif timed_out:
                record.status = "timeout"
            else:
                record.status = "completed" if exit_code == 0 else "error"

        record.violation_reason = violation_reason
        record.done_event.set()

        with self._lock:
            self._active.pop(task_id, None)

        stdout = "".join(stdout_list)
        stderr = "".join(stderr_list)
        if timed_out:
            stderr += f"\n[Supervisor Timeout] Process exceeded hard timeout of {timeout_ms}ms and was killed."
        if limit_violated and violation_reason:
            stderr += f"\n[Supervisor Resource Cap] {violation_reason} and was terminated."

        # Scan artifact directory and compute SHA-256 for all captured output files
        captured_artifacts: List[Dict[str, Any]] = []
        if artifact_dir and os.path.exists(artifact_dir):
            try:
                for root, _, files in os.walk(artifact_dir):
                    for f in files:
                        fpath = os.path.join(root, f)
                        try:
                            fsize = os.path.getsize(fpath)
                            if compute_sha256:
                                sha = compute_sha256(fpath)
                            else:
                                import hashlib
                                hasher = hashlib.sha256()
                                with open(fpath, "rb") as fp:
                                    for chk in iter(lambda: fp.read(65536), b""):
                                        hasher.update(chk)
                                sha = hasher.hexdigest()

                            art_record = {
                                "task_id": task_id,
                                "filename": f,
                                "filepath": os.path.abspath(fpath),
                                "size_bytes": fsize,
                                "sha256": sha,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            }
                            if Artifact and insert_artifact:
                                try:
                                    art_obj = Artifact(
                                        task_id=task_id,
                                        filename=f,
                                        filepath=os.path.abspath(fpath),
                                        size_bytes=fsize,
                                        sha256=sha,
                                        created_at=art_record["created_at"],
                                    )
                                    insert_artifact(art_obj)
                                except Exception as db_err:
                                    logger.warning(f"Could not insert artifact into db: {db_err}")
                            captured_artifacts.append(art_record)
                        except Exception as file_err:
                            logger.warning(f"Could not hash artifact file {fpath}: {file_err}")
            except Exception as scan_err:
                logger.warning(f"Could not scan artifact_dir {artifact_dir}: {scan_err}")

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
            resource_limit_exceeded=limit_violated,
            violation_reason=violation_reason,
            peak_memory_mb=round(record.peak_memory_mb, 2),
            peak_cpu_percent=round(record.peak_cpu_percent, 1),
            artifacts=captured_artifacts,
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
