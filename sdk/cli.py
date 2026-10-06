"""
Kairo ToolSpec SDK - CLI Interface (`create-toolspec` and `verify-toolspec`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sdk.conformance import ToolSpecConformanceRunner
from sdk.generator import ToolSpecGenerator, to_class_name, to_slug
from sdk.registry_bridge import load_module_from_file


def run_create(tool_id: str, category: str = "recon", binary: Optional[str] = None, output_dir: Optional[str] = None):
    generator = ToolSpecGenerator()
    generated = generator.generate(
        tool_id=tool_id,
        category=category,
        binary=binary,
        output_dir=output_dir,
    )
    print(f"\n=======================================================")
    print(f" 🚀 Generated Kairo ToolSpec Package: {tool_id}")
    print(f"=======================================================")
    for k, v in generated.items():
        print(f"  [{k.upper():<7}] -> {v}")
    print(f"\nNext Steps:")
    print(f"  1. Review {generated['yaml']}")
    print(f"  2. Implement specific CLI arguments in {generated['adapter']}")
    print(f"  3. Implement output regexes in {generated['parser']}")
    print(f"  4. Certify 'TRUSTED' status with: python -m sdk verify-toolspec {generated['yaml']}\n")
    return generated


def run_verify(yaml_path: str, adapter_py: Optional[str] = None):
    p_yaml = Path(yaml_path).resolve()
    if not p_yaml.exists():
        print(f"❌ Error: ToolSpec YAML not found at: {p_yaml}")
        sys.exit(1)

    import yaml
    with open(p_yaml, "r", encoding="utf-8") as f:
        spec_data = yaml.safe_load(f)

    tool_id = spec_data.get("id")
    slug = to_slug(tool_id)
    cls_name = to_class_name(slug)

    # Locate adapter file
    if adapter_py:
        p_adapter = Path(adapter_py).resolve()
    else:
        # Check standard SDK tools location
        p_adapter = ROOT_DIR / "sdk" / "tools" / slug / f"{slug}_adapter.py"
        if not p_adapter.exists():
            # Check same folder as yaml
            p_adapter = p_yaml.parent / f"{slug}_adapter.py"

    if not p_adapter.exists():
        print(f"❌ Error: Adapter file not found at: {p_adapter}")
        sys.exit(1)

    # Load adapter class dynamically
    mod = load_module_from_file(p_adapter)
    adapter_cls = getattr(mod, cls_name, None)
    if not adapter_cls:
        # Fallback: search any ToolAdapter in module
        from orchestrator.adapters.base import ToolAdapter
        for attr in dir(mod):
            cand = getattr(mod, attr)
            if isinstance(cand, type) and issubclass(cand, ToolAdapter) and cand is not ToolAdapter:
                adapter_cls = cand
                break

    if not adapter_cls:
        print(f"❌ Error: Could not locate ToolAdapter class '{cls_name}' in {p_adapter}")
        sys.exit(1)

    runner = ToolSpecConformanceRunner()
    report = runner.run_conformance(yaml_path=p_yaml, adapter_cls=adapter_cls)

    print(f"\n=======================================================")
    print(f" 🛡️  Kairo ToolSpec Conformance Certification Report")
    print(f"=======================================================")
    print(f" Tool ID:       {report.tool_id}")
    print(f" Version:       {report.tool_version}")
    print(f" Spec SHA-256:  {report.sha256_spec[:16]}...")
    print(f" Adapter SHA:   {report.sha256_adapter[:16]}...")
    print(f" Gates Passed:  {report.passed_gates}/{report.total_gates} ({report.score_pct}%)")
    print(f"-------------------------------------------------------")
    for g in report.gate_results:
        icon = "✅" if g.passed else "❌"
        print(f" {icon} {g.name}: {g.details}")
        if g.errors:
            for err in g.errors:
                print(f"     ↳ [ERROR] {err}")
    print(f"=======================================================")
    if report.trusted:
        print(f" 🏆 STATUS: TRUSTED (Certified for Autonomous Orchestration)")
    else:
        print(f" ⚠️ STATUS: UNTRUSTED (Rejected by Security Engine)")
    print(f"=======================================================\n")
    return report


def main():
    parser = argparse.ArgumentParser(
        prog="kairo-toolspec",
        description="Kairo ToolSpec SDK - Developer CLI for tool authoring and verification",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Command: create-toolspec
    create_parser = subparsers.add_parser("create-toolspec", help="Scaffold a new ToolSpec package")
    create_parser.add_argument("tool_id", type=str, help="Tool ID (e.g., dnsrecon.enum.v1)")
    create_parser.add_argument("--category", type=str, default="recon", help="Tool category (e.g., recon, web, analysis)")
    create_parser.add_argument("--binary", type=str, default=None, help="Binary name")
    create_parser.add_argument("--output-dir", type=str, default=None, help="Output directory")

    # Command: verify-toolspec
    verify_parser = subparsers.add_parser("verify-toolspec", help="Execute 7-Gate conformance tests")
    verify_parser.add_argument("spec_yaml", type=str, help="Path to ToolSpec YAML file")
    verify_parser.add_argument("--adapter-py", type=str, default=None, help="Optional path to adapter Python file")

    args = parser.parse_args()

    if args.command == "create-toolspec":
        run_create(
            tool_id=args.tool_id,
            category=args.category,
            binary=args.binary,
            output_dir=args.output_dir,
        )
    elif args.command == "verify-toolspec":
        report = run_verify(yaml_path=args.spec_yaml, adapter_py=args.adapter_py)
        if not report.trusted:
            sys.exit(1)
    else:
        # Default help
        parser.print_help()


if __name__ == "__main__":
    main()
