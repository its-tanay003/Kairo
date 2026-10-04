"""
TCPDump Adapter: short packet capture to .pcap artifact with stats parser.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

class TcpdumpAdapter(ToolAdapter):
    tool_id = "tcpdump.capture.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "tcpdump"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        interface = inputs["interface"]
        bpf_filter = inputs.get("filter", "")
        count = int(inputs.get("count", 100))
        duration_s = int(inputs.get("duration_s", 10))
        output_file = inputs.get("output_file", "/tmp/kairo_capture.pcap")
        snap_len = int(inputs.get("snap_len", 262144))
        extra = inputs.get("extra_args", [])

        args = [
            "-i", interface,
            "-s", str(snap_len),
            "-c", str(count),
            "-w", output_file,
            "--immediate-mode",
        ]
        if bpf_filter:
            args += bpf_filter.split()
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        packets_captured = 0
        packets_received = 0
        packets_dropped = 0
        output_file = meta.get("inputs", {}).get("output_file", "/tmp/kairo_capture.pcap")

        # tcpdump writes stats to stderr
        combined = stdout + "\n" + stderr
        for line in combined.splitlines():
            m = re.search(r"(\d+)\s+packets\s+captured", line)
            if m:
                packets_captured = int(m.group(1))
            m2 = re.search(r"(\d+)\s+packets\s+received\s+by\s+filter", line)
            if m2:
                packets_received = int(m2.group(1))
            m3 = re.search(r"(\d+)\s+packets\s+dropped\s+by\s+kernel", line)
            if m3:
                packets_dropped = int(m3.group(1))

        return {
            "tool": "tcpdump",
            "interface": meta.get("inputs", {}).get("interface", ""),
            "filter": meta.get("inputs", {}).get("filter", ""),
            "packets_captured": packets_captured,
            "packets_received": packets_received,
            "packets_dropped": packets_dropped,
            "capture_file": output_file,
            "duration_s": meta.get("inputs", {}).get("duration_s", 10),
            "summary": f"Captured {packets_captured} packets to {output_file}",
            "_artifacts": [output_file],
        }
