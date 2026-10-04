"""
Hydra Adapter: multi-protocol password brute-forcer with text output parser.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class HydraAdapter(ToolAdapter):
    tool_id = "hydra.brute.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "hydra"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        target = inputs["target"]
        protocol = inputs["protocol"]
        port = int(inputs.get("port", 0))
        username = inputs.get("username", "")
        username_list = inputs.get("username_list", "")
        password = inputs.get("password", "")
        password_list = inputs.get("password_list", "/usr/share/wordlists/rockyou.txt")
        tasks = int(inputs.get("tasks", 4))
        stop_on_success = inputs.get("stop_on_success", True)
        form_params = inputs.get("form_params", "")
        extra = inputs.get("extra_args", [])

        args = [
            "-t", str(tasks),
            "-I",   # do not restore previous sessions
        ]
        if stop_on_success:
            args.append("-f")   # stop on first found

        # Credentials
        if username:
            args += ["-l", username]
        elif username_list:
            args += ["-L", username_list]

        if password:
            args += ["-p", password]
        else:
            args += ["-P", password_list]

        # Port
        if port:
            args += ["-s", str(port)]

        # Target and protocol
        if protocol in ("http-post-form", "http-get-form") and form_params:
            args += [target, protocol, form_params]
        else:
            args += [target, protocol]

        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        credentials_found = []
        total_attempts = 0

        for line in (stdout + "\n" + stderr).splitlines():
            line = line.strip()
            # "[80][http-get] host: 192.168.56.1   login: admin   password: admin123"
            m = re.search(
                r"\[(\d+)\]\[(.+?)\]\s+host:\s+(\S+)\s+login:\s+(\S+)\s+password:\s+(\S+)",
                line,
            )
            if m:
                credentials_found.append({
                    "host": m.group(3),
                    "port": int(m.group(1)),
                    "protocol": m.group(2),
                    "username": m.group(4),
                    "password": m.group(5),
                })

            # Attempt counts
            m2 = re.search(r"(\d+)\s+of\s+\d+\s+completed", line)
            if m2:
                total_attempts = int(m2.group(1))

        return {
            "tool": "hydra",
            "target": meta.get("inputs", {}).get("target", ""),
            "protocol": meta.get("inputs", {}).get("protocol", ""),
            "credentials_found": credentials_found,
            "total_attempts": total_attempts,
            "success": len(credentials_found) > 0,
        }
