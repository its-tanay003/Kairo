"""
WhatWeb Adapter: technology fingerprinting with JSON output parser.
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class WhatWebAdapter(ToolAdapter):
    tool_id = "whatweb.scan.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "whatweb"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        url = inputs["url"]
        aggression = int(inputs.get("aggression", 1))
        plugins = inputs.get("plugins", "")
        proxy = inputs.get("proxy", "")
        extra = inputs.get("extra_args", [])

        args = [
            url,
            f"-a{aggression}",
            "--log-json=-",  # log JSON to stdout
            "--no-errors",
        ]
        if plugins:
            args += ["--plugins", plugins]
        if proxy:
            args += ["--proxy", proxy]
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        plugins_found = []
        http_status = None
        title = ""
        target = meta.get("inputs", {}).get("url", "")

        # Try JSON parse first
        try:
            # whatweb --log-json=- outputs one JSON object per line
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                target = entry.get("target", target)
                http_status = entry.get("http_status")
                plugins = entry.get("plugins", {})
                for name, info in plugins.items():
                    plugin_entry: Dict[str, Any] = {
                        "name": name,
                        "confidence": 100,
                        "version": "",
                        "string": "",
                    }
                    if isinstance(info, dict):
                        if "version" in info:
                            plugin_entry["version"] = str(info["version"][0]) if info["version"] else ""
                        if "string" in info:
                            plugin_entry["string"] = str(info["string"][0]) if info["string"] else ""
                    plugins_found.append(plugin_entry)
                # Extract title from Title plugin
                title_plugin = plugins.get("Title", {})
                if isinstance(title_plugin, dict) and title_plugin.get("string"):
                    title = title_plugin["string"][0]
        except (json.JSONDecodeError, TypeError, IndexError):
            # Text fallback
            for line in stdout.splitlines():
                m = re.search(r"\[(.+?)\]", line)
                if m:
                    plugins_found.append({"name": m.group(1), "confidence": 80, "version": "", "string": ""})
                m2 = re.search(r"Title\[(.+?)\]", line)
                if m2:
                    title = m2.group(1)

        return {
            "tool": "whatweb",
            "target": target,
            "http_status": http_status,
            "title": title,
            "plugins_found": plugins_found,
            "total_plugins": len(plugins_found),
        }
