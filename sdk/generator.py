"""
Kairo ToolSpec SDK - CLI Generator (`create-toolspec`).
Generates a complete, blueprint-conformant ToolSpec package:
  1. <tool_id>.yaml (16-field blueprint schema)
  2. <tool_slug>_adapter.py (ToolAdapter implementation)
  3. <tool_slug>_parser.py (Structured output parser)
  4. test_<tool_slug>_conformance.py (Automated conformance test suite)
  5. README.md (Tool documentation & usage)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent


def to_slug(tool_id: str) -> str:
    """Converts a tool_id like 'dnsrecon.enum.v1' into 'dnsrecon_enum_v1'."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", tool_id).strip("_").lower()


def to_class_name(tool_slug: str) -> str:
    """Converts 'dnsrecon_enum_v1' into 'DnsreconEnumV1Adapter'."""
    parts = tool_slug.split("_")
    return "".join(p.capitalize() for p in parts) + "Adapter"


class ToolSpecGenerator:
    """Scaffolds complete third-party ToolSpec packages."""

    def __init__(self, root_dir: Optional[Path | str] = None):
        self.root_dir = Path(root_dir) if root_dir else ROOT_DIR

    def generate(
        self,
        tool_id: str,
        category: str = "recon",
        binary: Optional[str] = None,
        output_dir: Optional[Path | str] = None,
        target_in_registry: bool = True,
    ) -> Dict[str, Path]:
        slug = to_slug(tool_id)
        cls_name = to_class_name(slug)
        bin_name = binary or tool_id.split(".")[0]

        # Determine target paths
        out_dir = Path(output_dir) if output_dir else self.root_dir / "sdk" / "tools" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "__init__.py").touch(exist_ok=True)

        # If target_in_registry is True, also place YAML directly in registry/tools/
        yaml_path = (
            self.root_dir / "registry" / "tools" / f"{slug}.yaml"
            if target_in_registry
            else out_dir / f"{slug}.yaml"
        )
        yaml_path.parent.mkdir(parents=True, exist_ok=True)

        adapter_path = out_dir / f"{slug}_adapter.py"
        parser_path = out_dir / f"{slug}_parser.py"
        test_path = out_dir / f"test_{slug}_conformance.py"
        readme_path = out_dir / "README.md"

        parser_cls_name = cls_name.replace("Adapter", "Parser")

        # 1. Generate ToolSpec YAML (16 Blueprint Fields)
        spec_content = {
            "id": tool_id,
            "name": f"{tool_id.split('.')[0].capitalize()} Security Tool",
            "version": "1.0.0",
            "binary": bin_name,
            "category": category,
            "description": f"Automated execution and evidence gathering adapter for {bin_name}.",
            "capabilities": [
                f"{category}_scan",
                "structured_observation",
                "evidence_collection",
            ],
            "inputs": {
                "type": "object",
                "required": ["target"],
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Target host, IP, or domain",
                        "default": "127.0.0.1",
                    },
                    "options": {
                        "type": "string",
                        "description": "Optional flags for tool execution",
                        "default": "",
                    },
                    "timeout_s": {
                        "type": "integer",
                        "description": "Per-command execution timeout in seconds",
                        "default": 30,
                    },
                },
            },
            "outputs": {
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "raw_output": {"type": "string"},
                },
            },
            "side_effects": [
                "network_traffic",
                "log_generation",
            ],
            "privilege": "user",
            "gui": False,
            "parser": f"{slug}_parser",
            "prerequisites": [bin_name],
            "docs": {
                "summary": f"Runs {bin_name} against target within authorized Scope Contract.",
                "examples": [
                    {
                        "description": "Default local scan",
                        "command": f"{bin_name} 127.0.0.1",
                    }
                ],
            },
            "success_signals": {
                "exit_codes": [0],
                "stdout_contains": [],
            },
            "failure_signals": {
                "exit_codes": [1, 2, 127],
                "stderr_contains": ["error", "command not found"],
            },
            "rollback": {
                "strategy": "none",
                "description": "Read-only inspection tool; no active persistence state changes.",
            },
            "version_compatibility": {
                "min_agent_version": "1.0.0",
                "os": ["linux", "darwin", "windows"],
            },
            "timeout_ms": 30000,
        }

        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(spec_content, f, sort_keys=False, indent=2)

        # 2. Generate Parser Module
        parser_code = f'''"""
Parser for {tool_id}.
Extracts structured observation facts from {bin_name} stdout/stderr.
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List


class {parser_cls_name}:
    """Parses raw {bin_name} outputs into structured finding dictionaries."""

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        findings: List[Dict[str, Any]] = []
        hosts: List[str] = []
        technologies: List[str] = []

        # Extract targets or IP addresses
        ip_matches = re.findall(r"\\b(?:\\d{{1,3}}\\.)*\\d{{1,3}}\\b", stdout)
        if ip_matches:
            hosts.extend(list(set(ip_matches)))

        # Handle JSON output if available
        parsed_json = None
        if stdout.strip().startswith("{{") or stdout.strip().startswith("["):
            try:
                parsed_json = json.loads(stdout)
            except Exception:
                pass

        return {{
            "tool_id": "{tool_id}",
            "exit_code": exit_code,
            "hosts": hosts,
            "findings": findings,
            "parsed_json": parsed_json,
            "raw_stdout_sample": stdout[:500],
            "raw_stderr": stderr[:500] if stderr else "",
        }}
'''
        with open(parser_path, "w", encoding="utf-8") as f:
            f.write(parser_code)

        # 3. Generate Adapter Module
        adapter_code = f'''"""
Adapter for {tool_id}.
Implements Kairo ToolAdapter interface.
"""

from __future__ import annotations
from typing import Any, Dict, List
from sdk.base import BaseToolAdapter
from sdk.registry_bridge import register_adapter
from .{slug}_parser import {parser_cls_name}


class {cls_name}(BaseToolAdapter):
    tool_id = "{tool_id}"
    tool_version = "1.0.0"

    def __init__(self, vm_manager=None, supervisor=None):
        super().__init__(vm_manager=vm_manager, supervisor=supervisor, parser={parser_cls_name}())

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        args: List[str] = []
        target = inputs.get("target") or inputs.get("domain") or inputs.get("url") or inputs.get("path") or ""
        if target:
            args.append(str(target))

        options = inputs.get("options", "")
        if options:
            for opt in options.split():
                if opt:
                    args.append(opt)

        return args if args else ["--help"]

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.custom_parser.parse(stdout, stderr, exit_code, meta)


# Self-register into runtime adapter registry
register_adapter({cls_name})
'''
        with open(adapter_path, "w", encoding="utf-8") as f:
            f.write(adapter_code)

        # 4. Generate Conformance Test
        test_code = f'''"""
Conformance test suite for {tool_id}.
Verifies compliance with Kairo 7-Gate Conformance Standards.
"""

import pytest
from pathlib import Path
from sdk.conformance import ToolSpecConformanceRunner
from sdk.tools.{slug}.{slug}_adapter import {cls_name}

SPEC_PATH = Path(r"{yaml_path.resolve()}")


def test_{slug}_conformance_gates():
    runner = ToolSpecConformanceRunner()
    report = runner.run_conformance(
        yaml_path=SPEC_PATH,
        adapter_cls={cls_name},
        sample_inputs={{"target": "127.0.0.1"}},
        sample_stdout="Execution finished with exit code 0",
        sample_exit_code=0,
    )
    assert report.trusted is True, f"Conformance failed: {{[g.name + ': ' + g.details for g in report.gate_results if not g.passed]}}"
    assert report.passed_gates == report.total_gates
    assert report.score_pct == 100.0
'''
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(test_code)

        # 5. Generate Tool README
        readme_code = f"""# {tool_id} (Kairo ToolSpec Package)

- **Binary**: `{bin_name}`
- **Category**: `{category}`
- **Adapter**: `{cls_name}`

## Conformance Verification
To verify this ToolSpec and earn 'TRUSTED' status:
```bash
python -m sdk verify-toolspec "{yaml_path}"
```
"""
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(readme_code)

        return {
            "yaml": yaml_path,
            "adapter": adapter_path,
            "parser": parser_path,
            "test": test_path,
            "readme": readme_path,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Kairo ToolSpec Generator (create-toolspec)")
    parser.add_argument("tool_id", type=str, help="Tool ID (e.g. dnsrecon.enum.v1)")
    parser.add_argument("--category", type=str, default="recon", help="Tool category (e.g. recon, web, analysis)")
    parser.add_argument("--binary", type=str, default=None, help="Binary executable name")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory")
    args = parser.parse_args()

    generator = ToolSpecGenerator()
    generated = generator.generate(
        tool_id=args.tool_id,
        category=args.category,
        binary=args.binary,
        output_dir=args.output_dir,
    )
    print(f"✅ Generated ToolSpec package for '{args.tool_id}':")
    for k, v in generated.items():
        print(f"  - {k.capitalize()}: {v}")


if __name__ == "__main__":
    main()
