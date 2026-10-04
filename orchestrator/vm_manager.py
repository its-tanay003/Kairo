"""
Host VM Manager & Execution Controller for Isolated Kali Linux Sandbox.
Controls VirtualBox VM lifecycle (VBoxManage), snapshot-before-task,
manual rollback, and typed ToolSpec execution via the in-guest Worker Agent.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

VBOX_MANAGE = os.environ.get(
    "VBOX_MANAGE",
    r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
    if os.path.exists(r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe")
    else "VBoxManage",
)
VM_NAME = os.environ.get("KAIRO_VM_NAME", "kali-linux-2026.1-virtualbox-amd64")
WORKER_URL = os.environ.get("KAIRO_WORKER_URL", "http://127.0.0.1:9999")
BASELINE_SNAPSHOT = os.environ.get("KAIRO_BASELINE_SNAPSHOT", "kairo_worker_ready")


class VMManager:
    def __init__(self, vm_name: str = VM_NAME, worker_url: str = WORKER_URL):
        self.vm_name = vm_name
        self.worker_url = worker_url.rstrip("/")
        self.vbox_cmd = VBOX_MANAGE

    def _run_vbox(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        full_cmd = [self.vbox_cmd] + args
        try:
            return subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                check=check,
            )
        except Exception as e:
            if not check:
                return subprocess.CompletedProcess(args=full_cmd, returncode=-1, stdout="", stderr=str(e))
            raise

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status of VM and in-guest worker agent."""
        res = self._run_vbox(["showvminfo", self.vm_name, "--machinereadable"], check=False)
        vm_state = "unknown"
        if res.returncode == 0:
            match = re.search(r'VMState="([^"]+)"', res.stdout)
            if match:
                vm_state = match.group(1)

        worker_online = False
        worker_info = {}
        try:
            req = urllib.request.urlopen(f"{self.worker_url}/health", timeout=2)
            if req.status == 200:
                worker_info = json.loads(req.read().decode())
                worker_online = True
        except Exception:
            worker_online = False

        snapshots = self.list_snapshots()

        return {
            "vm_name": self.vm_name,
            "vm_state": vm_state,
            "running": vm_state in ("running", "paused"),
            "worker_online": worker_online,
            "worker_info": worker_info,
            "snapshots_count": len(snapshots),
            "snapshots": snapshots,
            "baseline_snapshot": BASELINE_SNAPSHOT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """Parses snapshots for this VM."""
        res = self._run_vbox(["snapshot", self.vm_name, "list"], check=False)
        if res.returncode != 0:
            return []

        snapshots: List[Dict[str, Any]] = []
        lines = res.stdout.splitlines()
        current_name = None
        current_uuid = None
        current_desc = ""
        is_current = False

        # Pattern: Name: <name> (UUID: <uuid>) [*]
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("Name:"):
                m = re.search(r"Name:\s+(.*?)\s+\(UUID:\s+([a-f0-9\-]+)\)(\s+\*)?", line_stripped)
                if m:
                    current_name = m.group(1).strip()
                    current_uuid = m.group(2).strip()
                    is_current = bool(m.group(3))
                    snapshots.append({
                        "name": current_name,
                        "uuid": current_uuid,
                        "is_current": is_current,
                        "description": "",
                    })
            elif line_stripped.startswith("Description:") and snapshots:
                desc = line_stripped.split("Description:", 1)[1].strip()
                snapshots[-1]["description"] = desc

        return snapshots

    def take_snapshot(self, name: Optional[str] = None, description: str = "") -> Dict[str, Any]:
        """Creates a snapshot before executing a task."""
        t0 = time.perf_counter()
        if not name:
            name = f"snap_task_{int(time.time()*1000)}"

        # VirtualBox handles live state snapshot natively
        try:
            res = self._run_vbox(
                ["snapshot", self.vm_name, "take", name, "--description", description or f"Pre-task snapshot {name}"],
                check=True,
            )
            duration_ms = int((time.perf_counter() - t0) * 1000)
            return {
                "status": "success",
                "snapshot_name": name,
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "error",
                "snapshot_name": name,
                "error": str(e),
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }

    def rollback_snapshot(self, snapshot_name: str = BASELINE_SNAPSHOT, timeout_sec: int = 180) -> Dict[str, Any]:
        """
        Manually rolls back the VM to a specific snapshot (default: kairo_worker_ready).
        Powers off, restores snapshot, starts headless, and waits for worker agent online.
        """
        t0 = time.perf_counter()
        print(f"[VMManager] Initiating rollback to snapshot '{snapshot_name}'...")

        # 1. Power off cleanly or forcibly
        self._run_vbox(["controlvm", self.vm_name, "poweroff"], check=False)
        time.sleep(1.0)

        # 2. Restore snapshot
        self._run_vbox(["snapshot", self.vm_name, "restore", snapshot_name], check=True)
        time.sleep(0.5)

        # 3. Start VM headless
        self._run_vbox(["startvm", self.vm_name, "--type", "headless"], check=True)

        # 4. Wait for worker agent /health
        agent_ready = False
        deadline = time.time() + timeout_sec
        attempts = 0
        while time.time() < deadline:
            attempts += 1
            try:
                req = urllib.request.urlopen(f"{self.worker_url}/health", timeout=2)
                if req.status == 200:
                    agent_ready = True
                    break
            except Exception:
                time.sleep(1.5)

        duration_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "status": "success" if agent_ready else "partial",
            "snapshot_restored": snapshot_name,
            "agent_online": agent_ready,
            "wait_attempts": attempts,
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def execute_in_vm(
        self,
        task_id: str,
        tool_id: str = "kali.exec.v1",
        tool_version: str = "1.0.0",
        args: Optional[Dict[str, Any]] = None,
        snapshot_before: bool = True,
        timeout_ms: int = 30000,
    ) -> Dict[str, Any]:
        """
        Executes a typed ToolSpec request inside the isolated Kali Linux VM.
        Optionally takes snapshot before running.
        Streams stdout/stderr back in the typed JSON response.
        """
        args = args or {}
        snap_info = None

        if snapshot_before:
            snap_name = f"pre_{task_id.replace('-', '_')}"
            snap_info = self.take_snapshot(
                name=snap_name,
                description=f"Snapshot before task {task_id} ({tool_id})"
            )

        payload = {
            "task_id": task_id,
            "tool_id": tool_id,
            "tool_version": tool_version,
            "arguments": args,
            "timeout_ms": timeout_ms,
        }

        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(
                f"{self.worker_url}/execute",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=(timeout_ms / 1000.0) + 10.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))

            res_data["pre_snapshot"] = snap_info
            res_data["snapshot_name"] = snap_info.get("snapshot_name") if snap_info else None
            return res_data
        except urllib.error.URLError as e:
            return {
                "task_id": task_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "status": "failed",
                "exit_code": -1,
                "error": f"Failed to communicate with guest Worker Agent: {e}",
                "stdout": "",
                "stderr": f"Worker agent connection error on {self.worker_url}: {e}",
                "pre_snapshot": snap_info,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }
        except Exception as e:
            return {
                "task_id": task_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "status": "failed",
                "exit_code": -1,
                "error": str(e),
                "stdout": "",
                "stderr": f"Execution failure: {e}",
                "pre_snapshot": snap_info,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }

    def kill_task_in_vm(self, task_id: str) -> Dict[str, Any]:
        """Sends SIGKILL request to guest Worker Agent for active task_id."""
        try:
            req = urllib.request.Request(
                f"{self.worker_url}/kill/{task_id}",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"task_id": task_id, "killed": False, "error": str(e)}


vm_manager = VMManager()
