"""
Kairo Worker Agent (runs inside isolated Kali Linux VM)
Listens on port 9999 (and/or local Unix socket) to receive typed ToolSpec execution requests.
Executes commands inside the VM with process supervision, hard timeouts, and SIGKILL kill switch.
"""

from datetime import datetime, timezone
import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("WORKER_PORT", "9999"))
HOST = os.environ.get("WORKER_HOST", "0.0.0.0")

# Active process tracking: task_id -> subprocess.Popen
active_processes: Dict[str, subprocess.Popen] = {}
process_lock = threading.Lock()


class WorkerExecutionSupervisor:
    @staticmethod
    def run_tool_spec(
        task_id: str,
        tool_id: str,
        tool_version: str,
        args: Dict[str, Any],
        timeout_ms: int = 30000,
    ) -> Dict[str, Any]:
        start_time = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()

        command = args.get("command", "")
        cmd_args = args.get("args", [])
        cwd = args.get("cwd", "/home/kali")
        env_extra = args.get("env", {})

        if not command:
            return {
                "task_id": task_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "status": "error",
                "exit_code": 1,
                "error": "Missing required 'command' in arguments",
                "stdout": "",
                "stderr": "Missing required 'command'",
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc).isoformat(),
                "duration_ms": 0,
                "timed_out": False,
            }

        full_cmd = [command] + [str(a) for a in cmd_args]
        env = os.environ.copy()
        if env_extra and isinstance(env_extra, dict):
            env.update({str(k): str(v) for k, v in env_extra.items()})

        # Ensure cwd exists, fallback to /home/kali or /root
        if not os.path.exists(cwd):
            cwd = "/home/kali" if os.path.exists("/home/kali") else "/root"

        timeout_sec = max(0.1, timeout_ms / 1000.0)

        try:
            proc = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                env=env,
                preexec_fn=os.setsid,  # create new process group for clean kill
            )

            with process_lock:
                active_processes[task_id] = proc

            timed_out = False
            stdout, stderr = "", ""

            try:
                stdout, stderr = proc.communicate(timeout=timeout_sec)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                print(f"[Worker] Task {task_id} (PID {proc.pid}) timed out after {timeout_sec}s. Issuing SIGKILL.")
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
                stdout, stderr = proc.communicate()
                stderr = (stderr or "") + f"\n[Supervisor] Process forcibly terminated after {timeout_ms}ms timeout."
                exit_code = -9

            with process_lock:
                active_processes.pop(task_id, None)

            t1 = time.perf_counter()
            duration_ms = int((t1 - t0) * 1000)
            end_time = datetime.now(timezone.utc).isoformat()

            return {
                "task_id": task_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "status": "timeout" if timed_out else ("success" if exit_code == 0 else "error"),
                "exit_code": exit_code,
                "process_id": proc.pid,
                "stdout": stdout or "",
                "stderr": stderr or "",
                "start_time": start_time,
                "end_time": end_time,
                "duration_ms": duration_ms,
                "timed_out": timed_out,
                "command": command,
                "args": cmd_args,
            }

        except Exception as e:
            with process_lock:
                active_processes.pop(task_id, None)
            t1 = time.perf_counter()
            return {
                "task_id": task_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "status": "failed",
                "exit_code": -1,
                "error": str(e),
                "stdout": "",
                "stderr": f"Subprocess spawn failure: {e}",
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc).isoformat(),
                "duration_ms": int((t1 - t0) * 1000),
                "timed_out": False,
            }

    @staticmethod
    def kill_task(task_id: str) -> Dict[str, Any]:
        with process_lock:
            proc = active_processes.get(task_id)
            if not proc:
                return {"task_id": task_id, "killed": False, "message": "No active process found for task_id"}

            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()

            active_processes.pop(task_id, None)
            return {"task_id": task_id, "killed": True, "pid": proc.pid, "message": "Process killed via SIGKILL"}


class WorkerHTTPHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: Dict[str, Any]):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            self._send_json(
                200,
                {
                    "status": "ready",
                    "agent": "kairo-worker-agent",
                    "version": "1.0.0",
                    "os": "Kali Linux",
                    "kernel": os.uname().release,
                    "active_tasks": len(active_processes),
                    "supported_tools": ["shell.run.v1", "kali.exec.v1"],
                },
            )
            return

        if self.path == "/tasks":
            with process_lock:
                tasks = [{"task_id": tid, "pid": p.pid} for tid, p in active_processes.items()]
            self._send_json(200, {"active_tasks": tasks})
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

        if self.path == "/execute":
            # Typed ToolSpec execution request
            task_id = payload.get("task_id", f"task_{int(time.time()*1000)}")
            tool_id = payload.get("tool_id", "shell.run.v1")
            tool_version = payload.get("tool_version", "1.0.0")
            args = payload.get("arguments") or payload.get("requested_args") or payload.get("args") or {}
            timeout_ms = int(payload.get("timeout_ms", args.get("timeout_ms", 30000)))

            result = WorkerExecutionSupervisor.run_tool_spec(
                task_id=task_id,
                tool_id=tool_id,
                tool_version=tool_version,
                args=args,
                timeout_ms=timeout_ms,
            )
            self._send_json(200, result)
            return

        if self.path.startswith("/kill"):
            task_id = payload.get("task_id")
            if not task_id and "/" in self.path.strip("/"):
                parts = self.path.strip("/").split("/")
                if len(parts) >= 2:
                    task_id = parts[1]

            if not task_id:
                self._send_json(400, {"error": "Missing task_id"})
                return

            res = WorkerExecutionSupervisor.kill_task(task_id)
            self._send_json(200, res)
            return

        self._send_json(404, {"error": "Not Found"})

    def log_message(self, format, *args):
        # Concise logging
        sys.stderr.write(f"[WorkerAgent] {format % args}\n")


def run_server():
    server = HTTPServer((HOST, PORT), WorkerHTTPHandler)
    print(f"[WorkerAgent] Starting Kairo Worker Agent on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[WorkerAgent] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    run_server()
