"""
Metasploit JSON-RPC Adapter: connects to msfrpcd and runs auxiliary modules.
Uses msgpack+HTTP for RPC calls. Falls back to msfconsole resource script if RPC is unavailable.
"""
from __future__ import annotations
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from orchestrator.adapters.base import ToolAdapter, ToolObservation

logger = logging.getLogger("orchestrator.adapters.metasploit")

# Supported modules for the MVP connector
SUPPORTED_MODULES = {
    "auxiliary/scanner/portscan/tcp": {"RPORT": 0, "THREADS": 4},
    "auxiliary/scanner/http/http_version": {"RPORT": 80, "THREADS": 4},
    "auxiliary/scanner/smb/smb_version": {"RPORT": 445, "THREADS": 4},
    "auxiliary/scanner/ssh/ssh_version": {"RPORT": 22, "THREADS": 4},
    "auxiliary/scanner/discovery/udp_sweep": {"THREADS": 4},
}


class MetasploitRpcAdapter(ToolAdapter):
    tool_id = "metasploit.rpc.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "msfconsole"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        """For fallback msfconsole resource script mode."""
        module = inputs["module"]
        rhosts = inputs["rhosts"]
        rport = inputs.get("rport", "")
        threads = inputs.get("threads", 4)
        opts = inputs.get("options", {})

        rc_lines = [
            f"use {module}",
            f"set RHOSTS {rhosts}",
            f"set THREADS {threads}",
        ]
        if rport:
            rc_lines.append(f"set RPORT {rport}")
        for k, v in (opts or {}).items():
            rc_lines.append(f"set {k} {v}")
        rc_lines += ["run -j", "sleep 5", "vulns -j", "exit -y"]

        # Write resource file and use -r flag
        rc_content = "\n".join(rc_lines)
        rc_path = f"/tmp/kairo_msf_{int(time.time())}.rc"
        return ["-q", "-x", rc_content]

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        inputs = meta.get("inputs", {})
        module = inputs.get("module", "unknown")
        rhosts = inputs.get("rhosts", "")

        results = []
        # Parse msfconsole text output - look for host/result lines
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # [*] 192.168.56.1:22 - SSH-2.0-OpenSSH_8.4p1
            m = re.search(r"\[\*\]\s+(\d{1,3}(?:\.\d{1,3}){3})(?::(\d+))?\s+-\s+(.+)", line)
            if m:
                results.append({
                    "host": m.group(1),
                    "port": int(m.group(2)) if m.group(2) else None,
                    "banner": m.group(3).strip(),
                    "status": "open",
                })
            # [+] lines indicate positive findings
            m2 = re.search(r"\[\+\]\s+(.+)", line)
            if m2:
                results.append({
                    "finding": m2.group(1).strip(),
                    "status": "positive",
                })

        return {
            "tool": "metasploit",
            "module": module,
            "rhosts": rhosts,
            "results": results,
            "results_count": len(results),
            "rpc_mode": "msfconsole_fallback",
        }

    def execute_via_rpc(
        self,
        inputs: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Direct JSON-RPC call to msfrpcd. Returns raw response dict or None if unavailable.
        Protocol: HTTP POST to /api/1.0 with msgpack payload (simplified to JSON for MVP).
        """
        rpc_host = inputs.get("rpc_host", "127.0.0.1")
        rpc_port = int(inputs.get("rpc_port", 55553))
        rpc_pass = inputs.get("rpc_pass", "msf")
        module = inputs["module"]
        rhosts = inputs["rhosts"]
        rport = inputs.get("rport")
        threads = int(inputs.get("threads", 4))
        options = dict(inputs.get("options", {}))

        try:
            # Auth token acquire
            auth_payload = json.dumps(["auth.login", "msf", rpc_pass]).encode()
            req = urllib.request.Request(
                f"http://{rpc_host}:{rpc_port}/api/1.0",
                data=auth_payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                auth_res = json.loads(resp.read())
                if auth_res.get("result") != "success":
                    return None
                token = auth_res.get("token", "")

            # Module options
            mod_opts: Dict[str, Any] = {
                "RHOSTS": rhosts,
                "THREADS": threads,
                **options,
            }
            if rport:
                mod_opts["RPORT"] = rport

            # Execute module
            run_payload = json.dumps([
                "module.execute", "auxiliary", module, mod_opts
            ]).encode()
            req2 = urllib.request.Request(
                f"http://{rpc_host}:{rpc_port}/api/1.0",
                data=run_payload,
                headers={"Content-Type": "application/json", "X-Auth-Token": token},
            )
            with urllib.request.urlopen(req2, timeout=30) as resp2:
                return json.loads(resp2.read())

        except Exception as e:
            logger.debug(f"[MetasploitRPC] RPC unavailable: {e}")
            return None

    def execute(
        self,
        inputs: Dict[str, Any],
        task_id: Optional[str] = None,
        target: str = "vm",
        timeout_ms: int = 90000,
        snapshot_before: bool = True,
    ) -> ToolObservation:
        """Try RPC first, fall back to base VM/supervisor execution."""
        rpc_result = self.execute_via_rpc(inputs, task_id)
        if rpc_result:
            obs_data = {
                "tool": "metasploit",
                "module": inputs.get("module"),
                "rhosts": inputs.get("rhosts"),
                "rpc_mode": "msfrpc",
                "results": rpc_result,
                "results_count": len(rpc_result) if isinstance(rpc_result, list) else 1,
            }
            return ToolObservation(
                tool_id=self.tool_id,
                tool_version=self.tool_version,
                task_id=task_id or "rpc_task",
                status="success",
                exit_code=0,
                raw_stdout=json.dumps(rpc_result),
                raw_stderr="",
                duration_ms=0.0,
                observation=obs_data,
            )
        # Fallback: run via VM
        return super().execute(inputs, task_id, target, timeout_ms, snapshot_before)
