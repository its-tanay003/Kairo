"""
SearchSploit Adapter: Exploit-DB search with --json output parser.
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class SearchsploitAdapter(ToolAdapter):
    tool_id = "searchsploit.search.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "searchsploit"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        query = inputs["query"]
        exact = inputs.get("exact", False)
        exclude = inputs.get("exclude", "")
        search_type = inputs.get("type", "")
        extra = inputs.get("extra_args", [])

        args = ["--json"]
        if exact:
            args.append("-e")
        if exclude:
            args += ["--exclude", exclude]
        if search_type == "shellcodes":
            args.append("--shellcodes")
        elif search_type == "papers":
            args.append("--papers")

        args += query.split()
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        exploits = []
        try:
            data = json.loads(stdout)
            for item in data.get("RESULTS_EXPLOIT", []):
                exploits.append({
                    "title": item.get("Title", ""),
                    "edb_id": str(item.get("EDB-ID", "")),
                    "date": item.get("Date", ""),
                    "author": item.get("Author", ""),
                    "type": item.get("Type", ""),
                    "platform": item.get("Platform", ""),
                    "path": item.get("Path", ""),
                    "verified": bool(item.get("Verified", False)),
                })
        except (json.JSONDecodeError, TypeError):
            # Text fallback
            for line in stdout.splitlines():
                m = re.match(r"\s*(.+?)\s+\|\s+(.+)", line)
                if m and "Exploit Title" not in m.group(1):
                    exploits.append({
                        "title": m.group(1).strip(),
                        "path": m.group(2).strip(),
                        "edb_id": "",
                        "date": "",
                        "author": "",
                        "type": "",
                        "platform": "",
                    })

        return {
            "tool": "searchsploit",
            "query": meta.get("inputs", {}).get("query", ""),
            "exploits": exploits,
            "total_found": len(exploits),
        }
