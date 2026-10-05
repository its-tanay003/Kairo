"""
Kali Worker Connection Layer & Cross-Platform Execution Plane Detection.

Abstracts execution environment across host operating systems:
- Linux: Direct local execution in Kali Linux / container / local worker socket.
- Windows: Automatic detection and connection to Kali via WSL2 (with Win-KeX GUI readiness for Phase 5).
- macOS: Connection to Linux VM via Apple Virtualization-framework-compatible backends (Colima/Lima/Tart/Multipass).

The UI and orchestrator do not need to know which platform they are on;
only this Kali worker connection layer branches.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

logger = logging.getLogger("orchestrator.kali_connector")


class ExecutionPlaneType(str, Enum):
    LINUX_NATIVE = "linux_native"
    WINDOWS_WSL2 = "windows_wsl2"
    MACOS_VIRTUALIZATION = "macos_virtualization"
    VIRTUALBOX_SANDBOX = "virtualbox_sandbox"
    SIMULATED_MOCK = "simulated_mock"


@dataclass
class WinKexStatus:
    installed: bool = False
    version: Optional[str] = None
    binary_path: Optional[str] = None
    mode: str = "none"  # "win", "seamless", "esm", or "none"
    ready_for_phase5_gui: bool = False
    install_hint: str = "sudo apt update && sudo apt install -y kali-win-kex"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionPlaneInfo:
    platform: str
    plane_type: ExecutionPlaneType
    backend_name: str
    is_connected: bool
    host_os: str
    host_arch: str
    distro_name: Optional[str] = None
    wsl_version: Optional[int] = None
    win_kex: Optional[Dict[str, Any]] = None
    macos_backend: Optional[str] = None
    worker_url: str = "http://127.0.0.1:9999"
    worker_online: bool = False
    worker_info: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["plane_type"] = self.plane_type.value
        return data


class KaliWorkerConnector:
    """
    Unified Kali Worker Connection Layer.
    Detects local execution plane and branches execution transparently.
    """

    def __init__(
        self,
        worker_url: Optional[str] = None,
        force_plane: Optional[ExecutionPlaneType] = None,
    ):
        self.worker_url = (worker_url or os.environ.get("KAIRO_WORKER_URL", "http://127.0.0.1:9999")).rstrip("/")
        self.force_plane = force_plane or self._get_env_plane_override()
        self._cached_info: Optional[ExecutionPlaneInfo] = None
        self._last_detection_time: float = 0.0
        self._cache_ttl_seconds: float = 120.0

    @staticmethod
    def _get_env_plane_override() -> Optional[ExecutionPlaneType]:
        override = os.environ.get("KAIRO_EXECUTION_PLANE_OVERRIDE", "").lower()
        if override == "wsl2" or override == "windows_wsl2":
            return ExecutionPlaneType.WINDOWS_WSL2
        elif override == "linux" or override == "linux_native":
            return ExecutionPlaneType.LINUX_NATIVE
        elif override == "macos" or override == "macos_virtualization":
            return ExecutionPlaneType.MACOS_VIRTUALIZATION
        elif override == "vbox" or override == "virtualbox":
            return ExecutionPlaneType.VIRTUALBOX_SANDBOX
        elif override == "mock" or override == "simulated":
            return ExecutionPlaneType.SIMULATED_MOCK
        return None

    def get_info(self, force_refresh: bool = False) -> ExecutionPlaneInfo:
        """Returns the current ExecutionPlaneInfo dataclass."""
        now = time.time()
        if not force_refresh and self._cached_info and (now - self._last_detection_time < self._cache_ttl_seconds):
            return self._cached_info

        info = self._detect_plane()
        self._cached_info = info
        self._last_detection_time = now
        return info

    def get_status(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Returns the current execution plane status, checking health and backends."""
        return self.get_info(force_refresh=force_refresh).to_dict()

    def _detect_plane(self) -> ExecutionPlaneInfo:
        host_system = sys.platform
        host_arch = platform.machine()
        t0 = time.perf_counter()

        # Check in-guest HTTP worker health first (shared across all modes)
        worker_online, worker_info = self._check_worker_health()

        # Check explicit override if provided
        if self.force_plane:
            return self._build_forced_plane_info(self.force_plane, host_system, host_arch, worker_online, worker_info, t0)

        # 1. WINDOWS BRANCH: Detect WSL2 and Kali Linux distribution
        if host_system == "win32":
            return self._detect_windows_wsl2(host_system, host_arch, worker_online, worker_info, t0)

        # 2. LINUX BRANCH: Direct native Kali execution or local container/socket
        elif host_system.startswith("linux"):
            return self._detect_linux_native(host_system, host_arch, worker_online, worker_info, t0)

        # 3. MACOS BRANCH: Apple Virtualization-framework backend (Colima, Lima, Tart, Multipass)
        elif host_system == "darwin":
            return self._detect_macos_virtualization(host_system, host_arch, worker_online, worker_info, t0)

        # Fallback / generic
        return ExecutionPlaneInfo(
            platform=host_system,
            plane_type=ExecutionPlaneType.SIMULATED_MOCK,
            backend_name="Generic Host Plane",
            is_connected=worker_online,
            host_os=platform.platform(),
            host_arch=host_arch,
            worker_url=self.worker_url,
            worker_online=worker_online,
            worker_info=worker_info,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )

    def _check_worker_health(self) -> Tuple[bool, Dict[str, Any]]:
        """Tests the in-guest or local Kairo Worker Agent on port 9999."""
        try:
            req = urllib.request.urlopen(f"{self.worker_url}/health", timeout=1.5)
            if req.status == 200:
                data = json.loads(req.read().decode("utf-8"))
                return True, data
        except Exception:
            pass
        return False, {}

    # --- Windows WSL2 Detection ---

    def _detect_windows_wsl2(
        self,
        host_system: str,
        host_arch: str,
        worker_online: bool,
        worker_info: Dict[str, Any],
        t0: float,
    ) -> ExecutionPlaneInfo:
        wsl_path = shutil.which("wsl.exe") or r"C:\Windows\System32\wsl.exe"
        wsl_available = os.path.exists(wsl_path) if os.path.isabs(wsl_path) else bool(wsl_path)

        distros: List[Dict[str, Any]] = []
        kali_distro: Optional[str] = None
        wsl_version: Optional[int] = None

        if wsl_available:
            try:
                proc = subprocess.run(
                    [wsl_path, "-l", "-v"],
                    capture_output=True,
                    timeout=4.0,
                    check=False,
                )
                raw_bytes = proc.stdout
                # Windows WSL outputs UTF-16 LE
                try:
                    text = raw_bytes.decode("utf-16le")
                except Exception:
                    text = raw_bytes.decode("utf-8", errors="ignore")

                # Clean null characters and carriage returns
                clean_text = re.sub(r"[\x00\r]", "", text)
                for line in clean_text.splitlines():
                    line = line.strip()
                    if not line or "NAME" in line or "STATE" in line:
                        continue
                    # Parse: [*] <name> <state> <version>
                    parts = re.split(r"\s{2,}", line)
                    if len(parts) >= 3:
                        name_raw = parts[0].replace("*", "").strip()
                        state = parts[1].strip()
                        version_str = parts[2].strip()
                        v_num = int(version_str) if version_str.isdigit() else 2
                        distros.append({"name": name_raw, "state": state, "version": v_num})
                        if "kali" in name_raw.lower():
                            kali_distro = name_raw
                            wsl_version = v_num

                if not kali_distro and distros:
                    # If specific kali not named, find default or first WSL2
                    for d in distros:
                        if d["version"] == 2:
                            kali_distro = d["name"]
                            wsl_version = 2
                            break
            except Exception as e:
                logger.warning(f"Error querying WSL2 distributions: {e}")

        # Check Win-KeX in Kali WSL (for Phase 5 GUI mode readiness)
        win_kex = WinKexStatus()
        if wsl_available and kali_distro:
            try:
                kex_proc = subprocess.run(
                    [wsl_path, "-d", kali_distro, "--", "which", "kex"],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                    check=False,
                )
                if kex_proc.returncode == 0 and kex_proc.stdout.strip():
                    win_kex.installed = True
                    win_kex.binary_path = kex_proc.stdout.strip()
                    win_kex.mode = "win"  # default standard Win-KeX mode
                    win_kex.ready_for_phase5_gui = True
                else:
                    win_kex.installed = False
                    win_kex.ready_for_phase5_gui = False
            except Exception:
                pass

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        is_connected = bool(worker_online or (wsl_available and kali_distro))

        return ExecutionPlaneInfo(
            platform=host_system,
            plane_type=ExecutionPlaneType.WINDOWS_WSL2,
            backend_name=f"WSL2 Kali Linux ({kali_distro or 'WSL2-Ready'})",
            is_connected=is_connected,
            host_os=f"Windows ({platform.platform()})",
            host_arch=host_arch,
            distro_name=kali_distro or "kali-linux",
            wsl_version=wsl_version or 2,
            win_kex=win_kex.to_dict(),
            worker_url=self.worker_url,
            worker_online=worker_online,
            worker_info=worker_info,
            latency_ms=latency_ms,
            details={
                "wsl_path": wsl_path,
                "wsl_available": wsl_available,
                "detected_distros": distros,
                "phase5_gui_ready": win_kex.ready_for_phase5_gui,
            },
        )

    # --- Linux Native Detection ---

    def _detect_linux_native(
        self,
        host_system: str,
        host_arch: str,
        worker_online: bool,
        worker_info: Dict[str, Any],
        t0: float,
    ) -> ExecutionPlaneInfo:
        os_name = "Linux"
        is_kali = False
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    content = f.read()
                    if "kali" in content.lower():
                        is_kali = True
                        os_name = "Kali GNU/Linux"
                    elif "PRETTY_NAME=" in content:
                        m = re.search(r'PRETTY_NAME="([^"]+)"', content)
                        if m:
                            os_name = m.group(1)
        except Exception:
            pass

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        is_connected = True  # Native Linux has direct execution plane

        return ExecutionPlaneInfo(
            platform=host_system,
            plane_type=ExecutionPlaneType.LINUX_NATIVE,
            backend_name=f"Native {os_name}",
            is_connected=is_connected,
            host_os=os_name,
            host_arch=host_arch,
            distro_name="kali" if is_kali else "linux",
            worker_url=self.worker_url,
            worker_online=worker_online,
            worker_info=worker_info,
            latency_ms=latency_ms,
            details={
                "is_kali_native": is_kali,
                "shell": os.environ.get("SHELL", "/bin/bash"),
                "ipc_socket": "/run/kairo/worker.sock" if os.path.exists("/run/kairo/worker.sock") else None,
            },
        )

    # --- macOS Virtualization Detection ---

    def _detect_macos_virtualization(
        self,
        host_system: str,
        host_arch: str,
        worker_online: bool,
        worker_info: Dict[str, Any],
        t0: float,
    ) -> ExecutionPlaneInfo:
        mac_ver = platform.mac_ver()[0]
        backends = []

        # Check popular Apple Virtualization Framework compatible frontends
        candidate_backends = [
            ("colima", "Colima (Virtualization.framework / QEMU)"),
            ("limactl", "Lima / macOS Virtualization VM"),
            ("tart", "Tart (Apple Virtualization Framework)"),
            ("multipass", "Canonical Multipass Linux VM"),
            ("utmctl", "UTM Virtual Machine Manager"),
        ]

        active_backend = None
        for cmd, label in candidate_backends:
            if shutil.which(cmd):
                backends.append({"command": cmd, "label": label})
                if not active_backend:
                    active_backend = cmd

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        is_connected = bool(worker_online or active_backend)

        return ExecutionPlaneInfo(
            platform=host_system,
            plane_type=ExecutionPlaneType.MACOS_VIRTUALIZATION,
            backend_name=f"macOS Apple Virtualization ({active_backend or 'VM-Bridge'})",
            is_connected=is_connected,
            host_os=f"macOS {mac_ver}",
            host_arch=host_arch,
            macos_backend=active_backend or "apple_vf",
            worker_url=self.worker_url,
            worker_online=worker_online,
            worker_info=worker_info,
            latency_ms=latency_ms,
            details={
                "available_vm_backends": backends,
                "apple_vf_supported": True,
            },
        )

    def _build_forced_plane_info(
        self,
        forced: ExecutionPlaneType,
        host_system: str,
        host_arch: str,
        worker_online: bool,
        worker_info: Dict[str, Any],
        t0: float,
    ) -> ExecutionPlaneInfo:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        backend_names = {
            ExecutionPlaneType.WINDOWS_WSL2: "WSL2 Kali Linux (Forced Override)",
            ExecutionPlaneType.LINUX_NATIVE: "Native Kali Linux Environment (Forced Override)",
            ExecutionPlaneType.MACOS_VIRTUALIZATION: "macOS Virtualization Framework (Forced Override)",
            ExecutionPlaneType.VIRTUALBOX_SANDBOX: "VirtualBox Kali VM Sandbox",
            ExecutionPlaneType.SIMULATED_MOCK: "Simulated Mock Plane",
        }
        return ExecutionPlaneInfo(
            platform=host_system,
            plane_type=forced,
            backend_name=backend_names.get(forced, "Custom Execution Plane"),
            is_connected=True,
            host_os=f"Emulated ({forced.value})",
            host_arch=host_arch,
            distro_name="kali-linux",
            wsl_version=2 if forced == ExecutionPlaneType.WINDOWS_WSL2 else None,
            win_kex=WinKexStatus(installed=True, ready_for_phase5_gui=True).to_dict() if forced == ExecutionPlaneType.WINDOWS_WSL2 else None,
            worker_url=self.worker_url,
            worker_online=worker_online,
            worker_info=worker_info,
            latency_ms=latency_ms,
            details={"forced_override": True},
        )

    # --- Transparent Execution Abstraction ---

    def execute(
        self,
        task_id: str,
        command: str,
        args: Optional[List[str]] = None,
        tool_id: str = "kali.exec.v1",
        tool_version: str = "1.0.0",
        cwd: str = "/home/kali",
        timeout_ms: int = 30000,
        resource_limits: Optional[Dict[str, Any]] = None,
        artifact_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transparently executes a command on the detected execution plane.
        Callers (orchestrator, tool adapters, UI) receive the exact same structured
        result dictionary regardless of whether it ran on Linux, Windows WSL2, or macOS VM.
        """
        args = args or []
        info = self._cached_info or self._detect_plane()
        t0 = time.perf_counter()

        # Route 1: If HTTP worker is active on port 9999, use typed ToolSpec HTTP execution
        if info.worker_online:
            try:
                payload = {
                    "task_id": task_id,
                    "tool_id": tool_id,
                    "tool_version": tool_version,
                    "arguments": {
                        "command": command,
                        "args": args,
                        "cwd": cwd,
                    },
                    "timeout_ms": timeout_ms,
                    "resource_limits": resource_limits,
                    "artifact_dir": artifact_dir,
                }
                req = urllib.request.Request(
                    f"{self.worker_url}/execute",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=(timeout_ms / 1000.0) + 5.0) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    res_data["execution_plane"] = info.plane_type.value
                    return res_data
            except Exception as e:
                logger.warning(f"Worker HTTP execution failed ({e}), falling back to direct plane execution")

        # Route 2: Platform-specific direct plane execution
        if info.plane_type == ExecutionPlaneType.WINDOWS_WSL2:
            return self._execute_wsl2(task_id, command, args, cwd, timeout_ms, info)
        elif info.plane_type == ExecutionPlaneType.LINUX_NATIVE:
            return self._execute_linux_native(task_id, command, args, cwd, timeout_ms)
        elif info.plane_type == ExecutionPlaneType.MACOS_VIRTUALIZATION:
            return self._execute_macos_vf(task_id, command, args, cwd, timeout_ms, info)
        else:
            return self._execute_fallback_host(task_id, command, args, cwd, timeout_ms)

    def _execute_wsl2(
        self,
        task_id: str,
        command: str,
        args: List[str],
        cwd: str,
        timeout_ms: int,
        info: ExecutionPlaneInfo,
    ) -> Dict[str, Any]:
        """Executes directly inside Kali WSL2 on Windows."""
        t0 = time.perf_counter()
        wsl_path = shutil.which("wsl.exe") or r"C:\Windows\System32\wsl.exe"
        distro = info.distro_name or "kali-linux"

        # Build WSL command line
        cmd_line = [wsl_path, "-d", distro, "--", command] + args
        try:
            proc = subprocess.run(
                cmd_line,
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000.0,
                check=False,
            )
            dur_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "task_id": task_id,
                "status": "success" if proc.returncode == 0 else "error",
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "duration_ms": dur_ms,
                "execution_plane": "windows_wsl2",
                "backend": f"WSL2 ({distro})",
                "timed_out": False,
                "artifacts": [],
            }
        except subprocess.TimeoutExpired:
            dur_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "task_id": task_id,
                "status": "timeout",
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout_ms}ms in WSL2",
                "duration_ms": dur_ms,
                "execution_plane": "windows_wsl2",
                "backend": f"WSL2 ({distro})",
                "timed_out": True,
                "artifacts": [],
            }
        except Exception as e:
            dur_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "task_id": task_id,
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "duration_ms": dur_ms,
                "execution_plane": "windows_wsl2",
                "backend": f"WSL2 ({distro})",
                "timed_out": False,
                "artifacts": [],
            }

    def _execute_linux_native(
        self,
        task_id: str,
        command: str,
        args: List[str],
        cwd: str,
        timeout_ms: int,
    ) -> Dict[str, Any]:
        """Executes natively on Linux host."""
        t0 = time.perf_counter()
        full_cmd = [command] + args
        work_dir = cwd if os.path.exists(cwd) else None
        try:
            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000.0,
                cwd=work_dir,
                check=False,
            )
            dur_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "task_id": task_id,
                "status": "success" if proc.returncode == 0 else "error",
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "duration_ms": dur_ms,
                "execution_plane": "linux_native",
                "backend": "Local Linux",
                "timed_out": False,
                "artifacts": [],
            }
        except subprocess.TimeoutExpired:
            return {
                "task_id": task_id,
                "status": "timeout",
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout_ms}ms",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "execution_plane": "linux_native",
                "backend": "Local Linux",
                "timed_out": True,
                "artifacts": [],
            }
        except Exception as e:
            return {
                "task_id": task_id,
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "execution_plane": "linux_native",
                "backend": "Local Linux",
                "timed_out": False,
                "artifacts": [],
            }

    def _execute_macos_vf(
        self,
        task_id: str,
        command: str,
        args: List[str],
        cwd: str,
        timeout_ms: int,
        info: ExecutionPlaneInfo,
    ) -> Dict[str, Any]:
        """Dispatches execution across macOS Virtualization framework bridge."""
        backend = info.macos_backend or "colima"
        t0 = time.perf_counter()

        if backend == "colima" and shutil.which("colima"):
            cmd = ["colima", "ssh", "--", command] + args
        elif backend == "limactl" and shutil.which("limactl"):
            cmd = ["limactl", "shell", "default", command] + args
        elif backend == "multipass" and shutil.which("multipass"):
            cmd = ["multipass", "exec", "kairo-kali", "--", command] + args
        else:
            return self._execute_fallback_host(task_id, command, args, cwd, timeout_ms)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000.0,
                check=False,
            )
            return {
                "task_id": task_id,
                "status": "success" if proc.returncode == 0 else "error",
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "execution_plane": "macos_virtualization",
                "backend": f"macOS ({backend})",
                "timed_out": False,
                "artifacts": [],
            }
        except Exception as e:
            return {
                "task_id": task_id,
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": f"macOS Virtualization dispatch error: {e}",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "execution_plane": "macos_virtualization",
                "backend": f"macOS ({backend})",
                "timed_out": False,
                "artifacts": [],
            }

    def _execute_fallback_host(
        self,
        task_id: str,
        command: str,
        args: List[str],
        cwd: str,
        timeout_ms: int,
    ) -> Dict[str, Any]:
        """Fallback direct host execution when no VM/WSL is reachable."""
        t0 = time.perf_counter()
        try:
            full_cmd = [command] + args
            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000.0,
                check=False,
            )
            return {
                "task_id": task_id,
                "status": "success" if proc.returncode == 0 else "error",
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "execution_plane": "host_fallback",
                "backend": "Direct Host",
                "timed_out": False,
                "artifacts": [],
            }
        except Exception as e:
            return {
                "task_id": task_id,
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "execution_plane": "host_fallback",
                "backend": "Direct Host",
                "timed_out": False,
                "artifacts": [],
            }


# Global singleton instance
kali_connector = KaliWorkerConnector()


def get_kali_connector() -> KaliWorkerConnector:
    return kali_connector
