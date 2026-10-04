"""
HashID Adapter: hash algorithm identifier + optional hashcat dry-run potfile check.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

# Common hashcat mode to hash type mapping for display
HASHCAT_MODES = {
    "0": "MD5",
    "100": "SHA1",
    "900": "MD4",
    "1000": "NTLM",
    "1400": "SHA256",
    "1700": "SHA512",
    "1800": "sha512crypt",
    "3000": "LM",
    "3200": "bcrypt",
    "5600": "NetNTLMv2",
    "13100": "Kerberos 5 TGS-REP etype 23",
    "22000": "WPA-PBKDF2-PMKID+EAPOL",
}

class HashidAdapter(ToolAdapter):
    tool_id = "hashid.identify.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "hashid"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        hash_value = inputs["hash"]
        extra = inputs.get("extra_args", [])
        # -m = include hashcat mode, -j = include john format
        args = ["-m", "-j", hash_value]
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        hash_value = meta.get("inputs", {}).get("hash", "")
        identified_types = []
        confidence = "unknown"

        # hashid output format:
        # Analyzing 'hash_value'
        # [+] MD5 [Hashcat Mode: 0][JtR Format: raw-md5]
        # [+] MD4 [Hashcat Mode: 900]
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("[+]") or line.startswith("[-]"):
                is_match = line.startswith("[+]")
                content = line[3:].strip()
                hc_mode = ""
                john_fmt = ""
                name = content

                m_hc = re.search(r"\[Hashcat Mode:\s*(\d+)\]", content)
                if m_hc:
                    hc_mode = m_hc.group(1)
                    name = name[:m_hc.start()].strip()

                m_jr = re.search(r"\[JtR Format:\s*(.+?)\]", content)
                if m_jr:
                    john_fmt = m_jr.group(1)
                    name = re.sub(r"\[JtR Format:.+?\]", "", name).strip()

                if is_match:
                    identified_types.append({
                        "name": name,
                        "hashcat_mode": hc_mode,
                        "john_format": john_fmt,
                    })

        if identified_types:
            confidence = "high" if len(identified_types) == 1 else "medium"

        obs: Dict[str, Any] = {
            "tool": "hashid",
            "hash": hash_value,
            "hash_length": len(hash_value),
            "identified_types": identified_types,
            "confidence": confidence,
            "hashcat_potfile_match": {},
        }

        # Optionally add hashcat dry-run result if inputs requested it
        # (hashcat --show is run separately by the execute() override if needed)
        return obs

    def execute(self, inputs, task_id=None, target="vm", timeout_ms=30000, snapshot_before=True):
        """Run hashid, then optionally run hashcat --show as a dry-run potfile check."""
        obs = super().execute(inputs, task_id, target, timeout_ms, snapshot_before)

        if inputs.get("hashcat_check") and obs.status != "error":
            # Run hashcat --show (potfile check only - no cracking)
            hash_value = inputs["hash"]
            identified = obs.observation.get("identified_types", [])
            if identified and identified[0].get("hashcat_mode"):
                hc_mode = identified[0]["hashcat_mode"]
                from orchestrator.vm_manager import vm_manager as vmmgr
                hc_result = vmmgr.execute_in_vm(
                    task_id=(task_id or "hc_check") + "_potfile",
                    tool_id="hashid.identify.v1",
                    tool_version="1.0.0",
                    args={
                        "command": "hashcat",
                        "args": ["--show", "-m", hc_mode, hash_value],
                    },
                    snapshot_before=False,
                    timeout_ms=10000,
                )
                stdout = hc_result.get("stdout", "").strip()
                if stdout and ":" in stdout:
                    obs.observation["hashcat_potfile_match"] = {
                        "found": True,
                        "result": stdout,
                        "mode": hc_mode,
                    }
                else:
                    obs.observation["hashcat_potfile_match"] = {
                        "found": False,
                        "mode": hc_mode,
                    }

        return obs
