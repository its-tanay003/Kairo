"""
ExifTool Adapter: file metadata extractor with JSON output parser.
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List

from orchestrator.adapters.base import ToolAdapter

# Tags that may leak sensitive information
SENSITIVE_TAGS = {
    "gpslatitude", "gpslongitude", "gpsposition", "gpsdestlatitude", "gpsdestlongitude",
    "author", "creator", "lastmodifiedby", "company", "software",
    "username", "hostname", "documentname",
}

class ExiftoolAdapter(ToolAdapter):
    tool_id = "exiftool.extract.v1"
    tool_version = "1.0.0"

    def _binary(self) -> str:
        return "exiftool"

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        file_path = inputs["file_path"]
        tags = inputs.get("tags", [])
        recursive = inputs.get("recursive", False)
        extra = inputs.get("extra_args", [])

        args = ["-json", "-l", "-charset", "utf8"]
        if recursive:
            args.append("-r")
        for tag in tags:
            args += [f"-{tag}"]
        args.append(file_path)
        args += [str(a) for a in extra]
        return args

    def parse(self, stdout: str, stderr: str, exit_code: int, meta: Dict[str, Any]) -> Dict[str, Any]:
        files_parsed = []
        sensitive_findings = []

        try:
            data = json.loads(stdout)
            if not isinstance(data, list):
                data = [data]

            for file_entry in data:
                normalized: Dict[str, Any] = {
                    "source_file": file_entry.get("SourceFile", ""),
                    "make": file_entry.get("Make", ""),
                    "model": file_entry.get("Model", ""),
                    "gps_latitude": file_entry.get("GPSLatitude", ""),
                    "gps_longitude": file_entry.get("GPSLongitude", ""),
                    "create_date": file_entry.get("CreateDate", file_entry.get("DateTimeOriginal", "")),
                    "software": file_entry.get("Software", ""),
                    "author": file_entry.get("Author", file_entry.get("Creator", "")),
                    "file_size": file_entry.get("FileSize", ""),
                    "file_type": file_entry.get("FileType", ""),
                    "mime_type": file_entry.get("MIMEType", ""),
                    "all_tags": file_entry,
                }

                # Identify sensitive tags
                for key, val in file_entry.items():
                    if key.lower().replace(" ", "") in SENSITIVE_TAGS and val:
                        sensitive_findings.append({
                            "file": normalized["source_file"],
                            "tag": key,
                            "value": str(val)[:200],
                        })

                files_parsed.append(normalized)

        except (json.JSONDecodeError, TypeError):
            # Text fallback
            current: Dict[str, Any] = {"source_file": meta.get("inputs", {}).get("file_path", ""), "all_tags": {}}
            for line in stdout.splitlines():
                m = re.match(r"(.+?)\s*:\s+(.+)", line)
                if m:
                    key = m.group(1).strip()
                    val = m.group(2).strip()
                    current["all_tags"][key] = val
                    if key.lower().replace(" ", "") in SENSITIVE_TAGS:
                        sensitive_findings.append({"file": current["source_file"], "tag": key, "value": val})
            if current["all_tags"]:
                files_parsed.append(current)

        return {
            "tool": "exiftool",
            "target": meta.get("inputs", {}).get("file_path", ""),
            "files": files_parsed,
            "files_processed": len(files_parsed),
            "sensitive_findings": sensitive_findings,
        }
