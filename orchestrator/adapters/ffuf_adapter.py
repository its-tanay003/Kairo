"""
FFUF Adapter: web fuzzer with JSON output parser.
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class FfufAdapter(ToolAdapter):
    tool_id = "ffuf.fuzz.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "ffuf"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        url = inputs["url"]
        wordlist = inputs.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
        method = inputs.get("method", "GET")
        headers = inputs.get("headers", {})
        data = inputs.get("data", "")
        filter_status = inputs.get("filter_status", "404")
        match_status = inputs.get("match_status", "")
        threads = int(inputs.get("threads", 40))
        timeout = int(inputs.get("timeout_s", 10))
        out_file = "/tmp/ffuf_out.json"
        extra = inputs.get("extra_args", [])

        args = [
            "-u", url,
            "-w", wordlist,
            "-X", method,
            "-t", str(threads),
            "-timeout", str(timeout),
            "-of", "json",
            "-o", out_file,
            "-s",  # silent mode for cleaner output
        ]
        if filter_status:
            args += ["-fc", filter_status]
        if match_status:
            args += ["-mc", match_status]
        if data:
            args += ["-d", data]
        for k, v in (headers or {}).items():
            args += ["-H", f"{k}: {v}"]
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        results = []
        # ffuf writes JSON to -o file; we can also try parsing stdout JSON
        try:
            data = json.loads(stdout)
            raw_results = data.get("results", [])
            for r in raw_results:
                results.append({
                    "url": r.get("url", ""),
                    "input": r.get("input", {}),
                    "position": r.get("position", 0),
                    "status": r.get("status", 0),
                    "length": r.get("length", 0),
                    "words": r.get("words", 0),
                    "lines": r.get("lines", 0),
                    "duration": r.get("duration", 0),
                })
            command_line = data.get("commandline", "")
        except (json.JSONDecodeError, TypeError):
            # Text fallback: parse progress lines
            command_line = ""
            for line in stdout.splitlines():
                # [Status: 200, Size: 1234, Words: 100, Lines: 50]
                m = re.search(r"\[Status:\s*(\d+),\s*Size:\s*(\d+)", line)
                if m:
                    url_m = re.search(r"http\S+", line)
                    results.append({
                        "url": url_m.group(0) if url_m else "",
                        "status": int(m.group(1)),
                        "length": int(m.group(2)),
                    })

        return {
            "tool": "ffuf",
            "target_url": meta.get("inputs", {}).get("url", ""),
            "results": results,
            "total_found": len(results),
            "command_line": command_line,
        }
