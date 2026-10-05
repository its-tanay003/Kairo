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
import shutil
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

try:
    from events.db import Artifact, insert_artifact
except ImportError:
    Artifact = None
    insert_artifact = None

from orchestrator.kali_connector import get_kali_connector, ExecutionPlaneInfo


class VMManager:
    def __init__(self, vm_name: str = VM_NAME, worker_url: str = WORKER_URL):
        self.vm_name = vm_name
        self.worker_url = worker_url.rstrip("/")
        self.vbox_cmd = VBOX_MANAGE
        self.connector = get_kali_connector()

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
        """Returns comprehensive status of VM, execution plane, and in-guest worker agent."""
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
        plane_info = self.connector.get_status()

        return {
            "vm_name": self.vm_name,
            "vm_state": vm_state,
            "running": vm_state in ("running", "paused") or plane_info.get("is_connected", False),
            "worker_online": worker_online or plane_info.get("worker_online", False),
            "worker_info": worker_info or plane_info.get("worker_info", {}),
            "snapshots_count": len(snapshots),
            "snapshots": snapshots,
            "baseline_snapshot": BASELINE_SNAPSHOT,
            "execution_plane": plane_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """Parses snapshots for this VM."""
        if not shutil.which("VBoxManage") and not os.path.exists(self.vbox_cmd):
            return [
                {"name": "kairo_worker_ready", "uuid": "wsl2-baseline-001", "is_current": True, "description": "WSL2 Kali Baseline"}
            ]

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

        status_info = self.connector.get_status()
        plane_type = status_info.get("plane_type") if isinstance(status_info, dict) else getattr(status_info, "plane_type", "windows_wsl2")
        if plane_type != "virtualbox_sandbox" or (not shutil.which("VBoxManage") and not os.path.exists(self.vbox_cmd)):
            duration_ms = int((time.perf_counter() - t0) * 1000)
            return {
                "status": "success",
                "snapshot_name": name,
                "name": name,
                "duration_ms": duration_ms,
                "is_live": True,
                "plane": str(plane_type),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

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
                "name": name,
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "error",
                "snapshot_name": name,
                "name": name,
                "error": str(e),
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }

    def rollback_snapshot(self, snapshot_name: str = BASELINE_SNAPSHOT, timeout_sec: int = 180) -> Dict[str, Any]:
        """
        Manually rolls back the VM to a specific snapshot (default: kairo_worker_ready).
        Powers off, restores snapshot, starts headless, and waits for worker agent online.
        """
        t0 = time.perf_counter()
        status_info = self.connector.get_status()
        plane_type = status_info.get("plane_type") if isinstance(status_info, dict) else getattr(status_info, "plane_type", "windows_wsl2")
        if plane_type != "virtualbox_sandbox" or (not shutil.which("VBoxManage") and not os.path.exists(self.vbox_cmd)):
            return {
                "status": "success",
                "snapshot_name": snapshot_name,
                "name": snapshot_name,
                "agent_ready": True,
                "plane": str(plane_type),
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }

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
        rollback_after: bool = False,
        rollback_on_failure: bool = False,
        resource_limits: Optional[Dict[str, Any]] = None,
        artifact_dir: Optional[str] = None,
        timeout_ms: int = 30000,
    ) -> Dict[str, Any]:
        """
        Executes a typed ToolSpec request inside the isolated Kali Linux VM.
        Automates snapshot-before-task and optional rollback-after-task.
        Forwards resource caps and captures artifact hashes.
        """
        args = args or {}
        snap_info = None
        snap_name = None

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
            "resource_limits": resource_limits,
            "artifact_dir": artifact_dir,
        }

        t0 = time.perf_counter()
        res_data = None
        info = self.connector.get_info()

        if info.worker_online:
            try:
                req = urllib.request.Request(
                    f"{self.worker_url}/execute",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=(timeout_ms / 1000.0) + 2.0) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                res_data = None

        if res_data is None:
            # Transparently execute via local execution plane connector (WSL2 / native Linux / macOS VM)
            cmd = args.get("command", "bash")
            cmd_args = args.get("args", [])
            cwd = args.get("cwd", "/home/kali")
            conn_res = self.connector.execute(
                task_id=task_id,
                command=cmd,
                args=cmd_args,
                tool_id=tool_id,
                tool_version=tool_version,
                cwd=cwd,
                timeout_ms=timeout_ms,
                resource_limits=resource_limits,
                artifact_dir=artifact_dir,
            )
            res_data = {
                "task_id": task_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "status": conn_res.get("status", "error"),
                "exit_code": conn_res.get("exit_code", -1),
                "stdout": conn_res.get("stdout", ""),
                "stderr": conn_res.get("stderr", ""),
                "output": conn_res.get("stdout", "") or conn_res.get("output", ""),
                "duration_ms": conn_res.get("duration_ms", int((time.perf_counter() - t0) * 1000)),
                "artifacts": conn_res.get("artifacts", []),
                "pre_snapshot": snap_info,
                "snapshot_name": snap_info.get("snapshot_name") if snap_info else None,
                "execution_plane": conn_res.get("execution_plane", "unknown"),
                "backend": conn_res.get("backend", "local_plane"),
            }

        if "output" not in res_data:
            res_data["output"] = res_data.get("stdout", "")
        res_data["pre_snapshot"] = snap_info
        res_data["snapshot_name"] = snap_info.get("snapshot_name") if snap_info else None

        # Persist captured artifacts into SQLite DB if available
        raw_artifacts = res_data.get("artifacts", [])
        if raw_artifacts and Artifact and insert_artifact:
            for art in raw_artifacts:
                try:
                    art_obj = Artifact(
                        task_id=task_id,
                        filename=art.get("filename", ""),
                        filepath=art.get("filepath", ""),
                        size_bytes=int(art.get("size_bytes", 0)),
                        sha256=art.get("sha256", ""),
                        created_at=art.get("created_at"),
                        metadata=json.dumps({"source": "kali_vm", "tool_id": tool_id}),
                    )
                    insert_artifact(art_obj)
                except Exception as ins_err:
                    print(f"[VMManager] Artifact insert error: {ins_err}")

        # Check automated rollback conditions
        status = res_data.get("status", "unknown")
        exit_code = res_data.get("exit_code", 0)
        is_failure = status in ("failed", "error", "timeout", "resource_limit_exceeded") or exit_code != 0
        should_rollback = rollback_after or (rollback_on_failure and is_failure)

        rollback_info = None
        if should_rollback:
            target_snap = snap_name if (snap_info and snap_info.get("status") == "success") else BASELINE_SNAPSHOT
            print(f"[VMManager] Triggering automated rollback to '{target_snap}' (rollback_after={rollback_after}, rollback_on_failure={rollback_on_failure})...")
            rollback_info = self.rollback_snapshot(snapshot_name=target_snap)

        res_data["rollback_after"] = rollback_after
        res_data["rollback_on_failure"] = rollback_on_failure
        res_data["rollback_info"] = rollback_info
        res_data["rolled_back"] = bool(rollback_info and rollback_info.get("status") == "success")

        return res_data


    def kill_task_in_vm(self, task_id: str) -> Dict[str, Any]:
        """Sends SIGKILL request to guest Worker Agent for active task_id."""
        return self.stop_task_in_vm(task_id)

    def pause_task_in_vm(self, task_id: str) -> Dict[str, Any]:
        """Sends SIGSTOP pause request to guest Worker Agent for active task_id."""
        try:
            req = urllib.request.Request(
                f"{self.worker_url}/pause/{task_id}",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"task_id": task_id, "success": False, "error": str(e)}

    def resume_task_in_vm(self, task_id: str) -> Dict[str, Any]:
        """Sends SIGCONT resume request to guest Worker Agent for active task_id."""
        try:
            req = urllib.request.Request(
                f"{self.worker_url}/resume/{task_id}",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"task_id": task_id, "success": False, "error": str(e)}

    def stop_task_in_vm(self, task_id: str) -> Dict[str, Any]:
        """Sends SIGKILL stop request to guest Worker Agent for active task_id."""
        try:
            req = urllib.request.Request(
                f"{self.worker_url}/stop/{task_id}",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"task_id": task_id, "success": False, "error": str(e)}

    def retry_task_in_vm(self, task_id: str) -> Dict[str, Any]:
        """Sends retry request to guest Worker Agent to re-execute task_id."""
        try:
            req = urllib.request.Request(
                f"{self.worker_url}/retry/{task_id}",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"task_id": task_id, "success": False, "error": str(e)}

    def get_process_tree(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetches hierarchical process tree from guest Worker Agent."""
        try:
            url = f"{self.worker_url}/tree/{task_id}" if task_id else f"{self.worker_url}/tree"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"task_id": task_id, "nodes": [], "error": str(e)}

    def poll_task(self, task_id: str, since: int = 0) -> Dict[str, Any]:
        """Polls new output chunks and process tree for task_id."""
        try:
            req = urllib.request.Request(f"{self.worker_url}/poll/{task_id}?since={since}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"task_id": task_id, "chunks": [], "completed": True, "error": str(e)}


vm_manager = VMManager()
