"""
Kairo Worker Agent (runs inside isolated Kali Linux VM)
Listens on port 9999 (and/or local Unix socket) to receive typed ToolSpec execution requests.
Features:
- Real-time line-by-line / chunk streaming of stdout and stderr
- Server-Sent Events (SSE) /stream/{task_id} and /poll/{task_id}
- Hierarchical Process Tree View (parent, child, background processes)
- Process Supervisor controls: pause (SIGSTOP), resume (SIGCONT), stop (SIGKILL), retry
"""

from datetime import datetime, timezone
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import urllib.parse

try:
    import psutil
except ImportError:
    psutil = None

PORT = int(os.environ.get("WORKER_PORT", "9999"))
HOST = os.environ.get("WORKER_HOST", "0.0.0.0")


class TaskExecutionRecord:
    def __init__(
        self,
        task_id: str,
        tool_id: str,
        tool_version: str,
        command: str,
        args: List[Any],
        cwd: str,
        env_extra: Dict[str, str],
        timeout_ms: int,
        limits: Optional[Dict[str, Any]] = None,
        artifact_dir: Optional[str] = None,
    ):
        self.task_id = task_id
        self.tool_id = tool_id
        self.tool_version = tool_version
        self.command = command
        self.args = [str(a) for a in args]
        self.cwd = cwd
        self.env_extra = env_extra
        self.timeout_ms = timeout_ms

        # Resource caps per task
        self.limits = limits or {}
        self.max_memory_mb = float(self.limits.get("max_memory_mb", 512.0))
        self.max_cpu_percent = float(self.limits.get("max_cpu_percent", 95.0))
        self.max_disk_mb = float(self.limits.get("max_disk_mb", 100.0))
        self.max_file_count = int(self.limits.get("max_file_count", 100))
        self.max_output_bytes = int(self.limits.get("max_output_bytes", 10 * 1024 * 1024))
        self.cpu_grace_sec = float(self.limits.get("cpu_grace_sec", 3.0))

        self.artifact_dir = artifact_dir or f"/tmp/kairo_artifacts/{task_id}"
        self.artifacts: List[Dict[str, Any]] = []
        self.resource_limit_exceeded = False
        self.violation_reason: Optional[str] = None
        self.peak_memory_mb = 0.0
        self.peak_cpu_percent = 0.0

        self.proc: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.pgid: Optional[int] = None

        self.start_time = datetime.now(timezone.utc).isoformat()
        self.end_time: Optional[str] = None
        self.duration_ms: int = 0
        self.exit_code: Optional[int] = None
        self.status: str = "pending"  # pending, running, paused, stopped, completed, resource_limit_exceeded, timeout, error
        self.timed_out: bool = False

        self.chunks: List[Dict[str, Any]] = []
        self._seq = 0
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.done_event = threading.Event()

        self.stdout_full = []
        self.stderr_full = []

    def add_chunk(self, stream_type: str, text: str):
        if not text:
            return
        with self.lock:
            self._seq += 1
            chunk = {
                "seq": self._seq,
                "stream": stream_type,
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.chunks.append(chunk)
            if stream_type == "stdout":
                self.stdout_full.append(text)
            elif stream_type == "stderr":
                self.stderr_full.append(text)
            self.cond.notify_all()

    def get_chunks_since(self, since_seq: int) -> List[Dict[str, Any]]:
        with self.lock:
            return [c for c in self.chunks if c["seq"] > since_seq]

    def get_combined_stdout(self) -> str:
        return "".join(self.stdout_full)

    def get_combined_stderr(self) -> str:
        return "".join(self.stderr_full)


# Global task registry: task_id -> TaskExecutionRecord
task_records: Dict[str, TaskExecutionRecord] = {}
tasks_lock = threading.Lock()


class WorkerExecutionSupervisor:
    @staticmethod
    def start_task(
        task_id: str,
        tool_id: str,
        tool_version: str,
        args: Dict[str, Any],
        timeout_ms: int = 30000,
        limits: Optional[Dict[str, Any]] = None,
        artifact_dir: Optional[str] = None,
    ) -> TaskExecutionRecord:
        command = args.get("command", "")
        cmd_args = args.get("args", [])
        cwd = args.get("cwd", "/home/kali")
        env_extra = args.get("env", {})

        record = TaskExecutionRecord(
            task_id=task_id,
            tool_id=tool_id,
            tool_version=tool_version,
            command=command,
            args=cmd_args,
            cwd=cwd,
            env_extra=env_extra,
            timeout_ms=timeout_ms,
            limits=limits,
            artifact_dir=artifact_dir,
        )

        with tasks_lock:
            task_records[task_id] = record

        # Launch runner thread
        t = threading.Thread(target=WorkerExecutionSupervisor._run_process, args=(record,), daemon=True)
        t.start()
        return record

    @staticmethod
    def _run_process(record: TaskExecutionRecord):
        t0 = time.perf_counter()
        if not record.command:
            record.status = "error"
            record.exit_code = 1
            record.add_chunk("stderr", "Missing required 'command'\n")
            record.end_time = datetime.now(timezone.utc).isoformat()
            record.done_event.set()
            return

        full_cmd = [record.command] + record.args
        env = os.environ.copy()
        if record.env_extra and isinstance(record.env_extra, dict):
            env.update({str(k): str(v) for k, v in record.env_extra.items()})

        # Ensure artifact directory exists and is exported
        try:
            os.makedirs(record.artifact_dir, exist_ok=True)
            env["KAIRO_ARTIFACT_DIR"] = record.artifact_dir
        except Exception:
            pass

        cwd = record.cwd
        if not os.path.exists(cwd):
            cwd = "/home/kali" if os.path.exists("/home/kali") else "/root"

        try:
            proc = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                cwd=cwd,
                env=env,
                preexec_fn=os.setsid,  # New process group
            )
            record.proc = proc
            record.pid = proc.pid
            try:
                record.pgid = os.getpgid(proc.pid)
            except Exception:
                record.pgid = proc.pid

            record.status = "running"
            record.add_chunk("system", f"[Worker] Process started PID={proc.pid} PGID={record.pgid} Command={' '.join(full_cmd)}\n")

            # Threads to stream stdout and stderr
            def read_stream(stream, stream_name):
                try:
                    for line in iter(stream.readline, ""):
                        if not line:
                            break
                        record.add_chunk(stream_name, line)
                except Exception as ex:
                    record.add_chunk("stderr", f"[Stream error {stream_name}]: {ex}\n")
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass

            t_out = threading.Thread(target=read_stream, args=(proc.stdout, "stdout"), daemon=True)
            t_err = threading.Thread(target=read_stream, args=(proc.stderr, "stderr"), daemon=True)
            t_out.start()
            t_err.start()

            # Timeout monitor
            timeout_sec = max(0.1, record.timeout_ms / 1000.0)

            # Wait with poll and active resource monitoring
            start_wait = time.time()
            cpu_high_start = None

            while proc.poll() is None:
                now = time.time()
                # 1. Hard Timeout Check
                if now - start_wait > timeout_sec:
                    record.timed_out = True
                    record.status = "timeout"
                    record.add_chunk("system", f"\n[Supervisor Timeout] Process exceeded hard timeout of {record.timeout_ms}ms. Terminating...\n")
                    try:
                        os.killpg(record.pgid, signal.SIGKILL)
                    except Exception:
                        proc.kill()
                    break

                # 2. Output Buffer Size Cap
                out_bytes = sum(len(s.encode("utf-8", errors="ignore")) for s in record.stdout_full) + sum(len(s.encode("utf-8", errors="ignore")) for s in record.stderr_full)
                if out_bytes > record.max_output_bytes:
                    record.resource_limit_exceeded = True
                    record.violation_reason = f"Output size cap exceeded: {out_bytes} > {record.max_output_bytes} bytes"
                    record.add_chunk("system", f"\n[Supervisor Resource Cap] {record.violation_reason}. Terminating PGID {record.pgid}...\n")
                    try:
                        os.killpg(record.pgid, signal.SIGKILL)
                    except Exception:
                        proc.kill()
                    break

                # 3. CPU and RAM Limits (psutil)
                if psutil:
                    try:
                        p = psutil.Process(proc.pid)
                        all_p = [p] + p.children(recursive=True)
                        rss_bytes = sum(cp.memory_info().rss for cp in all_p if cp.is_running())
                        cpu_pct = sum(cp.cpu_percent(interval=None) for cp in all_p if cp.is_running())
                        rss_mb = rss_bytes / (1024.0 * 1024.0)
                        record.peak_memory_mb = max(record.peak_memory_mb, rss_mb)
                        record.peak_cpu_percent = max(record.peak_cpu_percent, cpu_pct)

                        # Check RAM Limit
                        if rss_mb > record.max_memory_mb:
                            record.resource_limit_exceeded = True
                            record.violation_reason = f"Memory cap exceeded: {rss_mb:.1f}MB > {record.max_memory_mb}MB"
                            record.add_chunk("system", f"\n[Supervisor Resource Cap] {record.violation_reason}. Terminating PGID {record.pgid}...\n")
                            try:
                                os.killpg(record.pgid, signal.SIGKILL)
                            except Exception:
                                proc.kill()
                            break

                        # Check CPU Limit with grace period
                        if cpu_pct > record.max_cpu_percent:
                            if cpu_high_start is None:
                                cpu_high_start = now
                            elif now - cpu_high_start > record.cpu_grace_sec:
                                record.resource_limit_exceeded = True
                                record.violation_reason = f"CPU cap exceeded: sustained {cpu_pct:.1f}% > {record.max_cpu_percent}% for >{record.cpu_grace_sec}s"
                                record.add_chunk("system", f"\n[Supervisor Resource Cap] {record.violation_reason}. Terminating PGID {record.pgid}...\n")
                                try:
                                    os.killpg(record.pgid, signal.SIGKILL)
                                except Exception:
                                    proc.kill()
                                break
                        else:
                            cpu_high_start = None
                    except Exception:
                        pass

                # 4. Disk and File-count Limits (Artifact Directory)
                if os.path.exists(record.artifact_dir):
                    try:
                        f_count = 0
                        total_disk_bytes = 0
                        for r, _, fnames in os.walk(record.artifact_dir):
                            f_count += len(fnames)
                            for fn in fnames:
                                try:
                                    total_disk_bytes += os.path.getsize(os.path.join(r, fn))
                                except Exception:
                                    pass
                        disk_mb = total_disk_bytes / (1024.0 * 1024.0)

                        if f_count > record.max_file_count:
                            record.resource_limit_exceeded = True
                            record.violation_reason = f"File-count cap exceeded: {f_count} files > {record.max_file_count} files"
                            record.add_chunk("system", f"\n[Supervisor Resource Cap] {record.violation_reason}. Terminating PGID {record.pgid}...\n")
                            try:
                                os.killpg(record.pgid, signal.SIGKILL)
                            except Exception:
                                proc.kill()
                            break

                        if disk_mb > record.max_disk_mb:
                            record.resource_limit_exceeded = True
                            record.violation_reason = f"Disk cap exceeded: {disk_mb:.1f}MB > {record.max_disk_mb}MB"
                            record.add_chunk("system", f"\n[Supervisor Resource Cap] {record.violation_reason}. Terminating PGID {record.pgid}...\n")
                            try:
                                os.killpg(record.pgid, signal.SIGKILL)
                            except Exception:
                                proc.kill()
                            break
                    except Exception:
                        pass

                time.sleep(0.05)

            proc.wait()
            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)

            if record.resource_limit_exceeded:
                record.status = "resource_limit_exceeded"
                record.exit_code = 137
            elif record.timed_out:
                record.status = "timeout"
                record.exit_code = 124
            elif record.status != "stopped":
                record.status = "completed" if proc.returncode == 0 else "error"
                record.exit_code = proc.returncode

            record.add_chunk("system", f"\n[Worker] Process finished with exit code {record.exit_code} (Status: {record.status})\n")

            # Scan artifact directory and compute SHA-256 for all captured output files
            if os.path.exists(record.artifact_dir):
                for r, _, fnames in os.walk(record.artifact_dir):
                    for fn in fnames:
                        fpath = os.path.join(r, fn)
                        try:
                            fsize = os.path.getsize(fpath)
                            hasher = hashlib.sha256()
                            with open(fpath, "rb") as fp:
                                for chk in iter(lambda: fp.read(65536), b""):
                                    hasher.update(chk)
                            record.artifacts.append({
                                "task_id": record.task_id,
                                "filename": fn,
                                "filepath": os.path.abspath(fpath),
                                "size_bytes": fsize,
                                "sha256": hasher.hexdigest(),
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            })
                        except Exception:
                            pass

        except Exception as e:
            record.status = "error"
            record.exit_code = -1
            record.add_chunk("stderr", f"Subprocess spawn failure: {e}\n")

        finally:
            record.end_time = datetime.now(timezone.utc).isoformat()
            record.duration_ms = int((time.perf_counter() - t0) * 1000)
            record.done_event.set()


    @staticmethod
    def get_process_tree(task_id: str) -> Dict[str, Any]:
        with tasks_lock:
            record = task_records.get(task_id)

        if not record or not record.pid:
            return {"task_id": task_id, "status": "not_found", "nodes": []}

        nodes = []
        root_pid = record.pid
        pgid = record.pgid or root_pid

        if psutil:
            try:
                parent_proc = psutil.Process(root_pid)
                # Check root proc
                is_running = parent_proc.is_running()
                p_status = parent_proc.status()
                # Status translation
                state_str = "running"
                if p_status in (psutil.STATUS_STOPPED, "stopped"):
                    state_str = "paused"
                elif not is_running or p_status in (psutil.STATUS_ZOMBIE, "zombie", psutil.STATUS_DEAD):
                    state_str = "completed" if record.status == "completed" else "stopped"
                elif record.status == "paused":
                    state_str = "paused"

                root_node = {
                    "pid": parent_proc.pid,
                    "ppid": parent_proc.ppid(),
                    "pgid": pgid,
                    "name": parent_proc.name(),
                    "cmd": " ".join(parent_proc.cmdline()) if parent_proc.cmdline() else parent_proc.name(),
                    "type": "parent",
                    "state": state_str,
                    "is_background": False,
                    "cpu_pct": round(parent_proc.cpu_percent(interval=None), 1),
                    "mem_pct": round(parent_proc.memory_percent(), 1),
                    "children": [],
                }

                # Find all children and grandchildren
                try:
                    children = parent_proc.children(recursive=True)
                    for child in children:
                        try:
                            c_status = child.status()
                            c_state = "running"
                            if c_status in (psutil.STATUS_STOPPED, "stopped") or state_str == "paused":
                                c_state = "paused"
                            elif c_status in (psutil.STATUS_ZOMBIE, "zombie", psutil.STATUS_DEAD):
                                c_state = "stopped"

                            # Is it a background process? (e.g. child whose parent is not the immediate shell, or detached)
                            is_bg = child.ppid() != root_pid or "background" in child.name().lower()

                            c_node = {
                                "pid": child.pid,
                                "ppid": child.ppid(),
                                "pgid": pgid,
                                "name": child.name(),
                                "cmd": " ".join(child.cmdline()) if child.cmdline() else child.name(),
                                "type": "background" if is_bg else "child",
                                "state": c_state,
                                "is_background": is_bg,
                                "cpu_pct": round(child.cpu_percent(interval=None), 1),
                                "mem_pct": round(child.memory_percent(), 1),
                                "children": [],
                            }
                            root_node["children"].append(c_node)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                except Exception:
                    pass

                nodes.append(root_node)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process already terminated
                nodes.append({
                    "pid": root_pid,
                    "ppid": 1,
                    "pgid": pgid,
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
            # Fallback without psutil
            nodes.append({
                "pid": root_pid,
                "ppid": 1,
                "pgid": pgid,
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

    @staticmethod
    def pause_task(task_id: str) -> Dict[str, Any]:
        with tasks_lock:
            record = task_records.get(task_id)
        if not record or not record.pid:
            return {"task_id": task_id, "success": False, "message": "No active process found"}

        try:
            if psutil:
                try:
                    p = psutil.Process(record.pid)
                    for c in p.children(recursive=True):
                        try:
                            c.suspend()
                        except Exception:
                            pass
                    p.suspend()
                except Exception:
                    os.killpg(record.pgid or record.pid, signal.SIGSTOP)
            else:
                os.killpg(record.pgid or record.pid, signal.SIGSTOP)

            record.status = "paused"
            record.add_chunk("system", f"\n[Supervisor] Process group PGID={record.pgid} PAUSED via SIGSTOP.\n")
            return {"task_id": task_id, "success": True, "status": "paused", "pid": record.pid}
        except Exception as e:
            return {"task_id": task_id, "success": False, "error": str(e)}

    @staticmethod
    def resume_task(task_id: str) -> Dict[str, Any]:
        with tasks_lock:
            record = task_records.get(task_id)
        if not record or not record.pid:
            return {"task_id": task_id, "success": False, "message": "No active process found"}

        try:
            if psutil:
                try:
                    p = psutil.Process(record.pid)
                    p.resume()
                    for c in p.children(recursive=True):
                        try:
                            c.resume()
                        except Exception:
                            pass
                except Exception:
                    os.killpg(record.pgid or record.pid, signal.SIGCONT)
            else:
                os.killpg(record.pgid or record.pid, signal.SIGCONT)

            record.status = "running"
            record.add_chunk("system", f"\n[Supervisor] Process group PGID={record.pgid} RESUMED via SIGCONT.\n")
            return {"task_id": task_id, "success": True, "status": "running", "pid": record.pid}
        except Exception as e:
            return {"task_id": task_id, "success": False, "error": str(e)}

    @staticmethod
    def stop_task(task_id: str) -> Dict[str, Any]:
        with tasks_lock:
            record = task_records.get(task_id)
        if not record or not record.pid:
            return {"task_id": task_id, "success": False, "message": "No active process found"}

        try:
            try:
                os.killpg(record.pgid or record.pid, signal.SIGKILL)
            except Exception:
                if record.proc:
                    record.proc.kill()

            record.status = "stopped"
            record.exit_code = -9
            record.add_chunk("system", f"\n[Supervisor] Process group PGID={record.pgid} forcibly STOPPED via SIGKILL.\n")
            record.done_event.set()
            return {"task_id": task_id, "success": True, "status": "stopped", "pid": record.pid}
        except Exception as e:
            return {"task_id": task_id, "success": False, "error": str(e)}

    @staticmethod
    def retry_task(task_id: str) -> Dict[str, Any]:
        with tasks_lock:
            record = task_records.get(task_id)
        if not record:
            return {"task_id": task_id, "success": False, "message": "Original task not found to retry"}

        # Stop existing if still running
        if record.status in ("running", "paused") and record.proc and record.proc.poll() is None:
            WorkerExecutionSupervisor.stop_task(task_id)
            time.sleep(0.2)

        # Launch fresh execution under same task_id
        new_record = WorkerExecutionSupervisor.start_task(
            task_id=task_id,
            tool_id=record.tool_id,
            tool_version=record.tool_version,
            args={
                "command": record.command,
                "args": record.args,
                "cwd": record.cwd,
                "env": record.env_extra,
            },
            timeout_ms=record.timeout_ms,
        )
        new_record.add_chunk("system", f"[Supervisor] Task {task_id} RETRIED by user request.\n")
        return {
            "task_id": task_id,
            "success": True,
            "status": "started",
            "message": f"Task {task_id} restarted cleanly",
        }


class WorkerHTTPHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: Dict[str, Any]):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/health" or path == "/":
            with tasks_lock:
                active_count = sum(1 for r in task_records.values() if r.status in ("running", "paused"))
            self._send_json(
                200,
                {
                    "status": "ready",
                    "agent": "kairo-worker-agent",
                    "version": "1.2.0",
                    "os": "Kali Linux",
                    "kernel": os.uname().release,
                    "active_tasks": active_count,
                    "supported_tools": ["shell.run.v1", "kali.exec.v1"],
                    "features": ["live_stream", "process_tree", "supervisor_controls"],
                },
            )
            return

        if path == "/tasks" or path == "/processes":
            with tasks_lock:
                task_list = [
                    {
                        "task_id": r.task_id,
                        "pid": r.pid,
                        "pgid": r.pgid,
                        "command": r.command,
                        "args": r.args,
                        "status": r.status,
                        "start_time": r.start_time,
                        "duration_ms": r.duration_ms,
                    }
                    for r in task_records.values()
                ]
            self._send_json(200, {"tasks": task_list})
            return

        # Process Tree: /tree or /tree/<task_id> or /process_tree
        if path.startswith("/tree") or path.startswith("/process_tree"):
            parts = [p for p in path.split("/") if p]
            task_id = query.get("task_id", [""])[0]
            if len(parts) >= 2 and parts[1] not in ("tree", "process_tree"):
                task_id = parts[1]

            if not task_id:
                # Return tree for all active tasks
                with tasks_lock:
                    active_tids = [tid for tid, r in task_records.items() if r.status in ("running", "paused")]
                if active_tids:
                    task_id = active_tids[-1]
                elif task_records:
                    task_id = list(task_records.keys())[-1]

            tree = WorkerExecutionSupervisor.get_process_tree(task_id) if task_id else {"nodes": []}
            self._send_json(200, tree)
            return

        # Poll endpoint: /poll/<task_id>?since=N
        if path.startswith("/poll"):
            parts = [p for p in path.split("/") if p]
            task_id = parts[1] if len(parts) >= 2 else query.get("task_id", [""])[0]
            since_seq = int(query.get("since", [0])[0])

            with tasks_lock:
                record = task_records.get(task_id)

            if not record:
                self._send_json(404, {"error": "Task not found", "task_id": task_id})
                return

            chunks = record.get_chunks_since(since_seq)
            tree = WorkerExecutionSupervisor.get_process_tree(task_id)
            self._send_json(
                200,
                {
                    "task_id": task_id,
                    "status": record.status,
                    "exit_code": record.exit_code,
                    "chunks": chunks,
                    "completed": record.done_event.is_set(),
                    "tree": tree.get("nodes", []),
                },
            )
            return

        # SSE Stream: /stream/<task_id>
        if path.startswith("/stream"):
            parts = [p for p in path.split("/") if p]
            task_id = parts[1] if len(parts) >= 2 else query.get("task_id", [""])[0]

            with tasks_lock:
                record = task_records.get(task_id)

            if not record:
                self._send_json(404, {"error": "Task not found for streaming", "task_id": task_id})
                return

            # Initiate SSE response
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            cur_seq = 0
            while True:
                # Grab any new chunks
                chunks = record.get_chunks_since(cur_seq)
                for chunk in chunks:
                    cur_seq = max(cur_seq, chunk["seq"])
                    payload = json.dumps(chunk)
                    msg = f"event: {chunk['stream']}\ndata: {payload}\n\n".encode("utf-8")
                    try:
                        self.wfile.write(msg)
                        self.wfile.flush()
                    except Exception:
                        return

                if record.done_event.is_set() and cur_seq >= record._seq:
                    # Final event
                    tree = WorkerExecutionSupervisor.get_process_tree(task_id)
                    final_payload = json.dumps({
                        "task_id": task_id,
                        "status": record.status,
                        "exit_code": record.exit_code,
                        "duration_ms": record.duration_ms,
                        "tree": tree.get("nodes", []),
                    })
                    try:
                        self.wfile.write(f"event: done\ndata: {final_payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        pass
                    break

                with record.lock:
                    if not record.done_event.is_set() and cur_seq >= record._seq:
                        record.cond.wait(timeout=0.2)
            return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"

        try:
            payload = json.loads(raw_body)
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON body: {e}"})
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/execute":
            task_id = payload.get("task_id", f"task_{int(time.time()*1000)}")
            tool_id = payload.get("tool_id", "shell.run.v1")
            tool_version = payload.get("tool_version", "1.0.0")
            args = payload.get("arguments") or payload.get("requested_args") or payload.get("args") or {}
            timeout_ms = int(payload.get("timeout_ms", args.get("timeout_ms", 30000)))
            is_async = payload.get("async", False)
            resource_limits = payload.get("resource_limits") or args.get("resource_limits")
            artifact_dir = payload.get("artifact_dir") or args.get("artifact_dir")

            record = WorkerExecutionSupervisor.start_task(
                task_id=task_id,
                tool_id=tool_id,
                tool_version=tool_version,
                args=args,
                timeout_ms=timeout_ms,
                limits=resource_limits,
                artifact_dir=artifact_dir,
            )

            if is_async:
                # Return immediately
                self._send_json(200, {
                    "task_id": task_id,
                    "status": "started",
                    "pid": record.pid,
                    "stream_url": f"/stream/{task_id}",
                    "poll_url": f"/poll/{task_id}",
                })
                return

            # Wait for completion (backward compatibility for synchronous tool adapters)
            record.done_event.wait(timeout=max(1.0, (timeout_ms / 1000.0) + 5.0))
            tree = WorkerExecutionSupervisor.get_process_tree(task_id)

            self._send_json(200, {
                "task_id": task_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "status": record.status,
                "exit_code": record.exit_code,
                "process_id": record.pid,
                "stdout": record.get_combined_stdout(),
                "stderr": record.get_combined_stderr(),
                "start_time": record.start_time,
                "end_time": record.end_time,
                "duration_ms": record.duration_ms,
                "timed_out": record.timed_out,
                "resource_limit_exceeded": record.resource_limit_exceeded,
                "violation_reason": record.violation_reason,
                "resource_usage": {
                    "peak_memory_mb": round(record.peak_memory_mb, 2),
                    "peak_cpu_percent": round(record.peak_cpu_percent, 1),
                },
                "artifacts": record.artifacts,
                "command": record.command,
                "args": record.args,
                "process_tree": tree.get("nodes", []),
            })
            return

        # Supervisor controls: /pause, /resume, /stop, /kill, /retry
        target_task_id = payload.get("task_id")
        parts = [p for p in path.split("/") if p]
        if not target_task_id and len(parts) >= 2:
            target_task_id = parts[1]

        if path.startswith("/pause"):
            res = WorkerExecutionSupervisor.pause_task(target_task_id)
            self._send_json(200, res)
            return

        if path.startswith("/resume"):
            res = WorkerExecutionSupervisor.resume_task(target_task_id)
            self._send_json(200, res)
            return

        if path.startswith("/stop") or path.startswith("/kill"):
            res = WorkerExecutionSupervisor.stop_task(target_task_id)
            self._send_json(200, res)
            return

        if path.startswith("/retry"):
            res = WorkerExecutionSupervisor.retry_task(target_task_id)
            self._send_json(200, res)
            return

        self._send_json(404, {"error": "Not Found"})

    def log_message(self, format, *args):
        sys.stderr.write(f"[WorkerAgent] {format % args}\n")


def run_server():
    server = ThreadingHTTPServer((HOST, PORT), WorkerHTTPHandler)
    print(f"[WorkerAgent] Starting Kairo Worker Agent on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[WorkerAgent] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    run_server()
