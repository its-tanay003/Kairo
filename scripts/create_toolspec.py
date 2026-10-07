#!/usr/bin/env python3
"""
CLI entry point for `create-toolspec`.
Usage: python create_toolspec.py my-tool [options]
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sdk.cli import run_create

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python create_toolspec.py <tool_id> [--category <cat>] [--binary <bin>] [--output-dir <dir>]")
        print("Example: python create_toolspec.py dnsrecon.enum.v1 --category recon --binary dnsrecon")
        sys.exit(0)

    tool_id = sys.argv[1]
    category = "recon"
    binary = None
    output_dir = None

    idx = 2
    while idx < len(sys.argv):
        if sys.argv[idx] == "--category" and idx + 1 < len(sys.argv):
            category = sys.argv[idx + 1]
            idx += 2
        elif sys.argv[idx] == "--binary" and idx + 1 < len(sys.argv):
            binary = sys.argv[idx + 1]
            idx += 2
        elif sys.argv[idx] == "--output-dir" and idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]
            idx += 2
        else:
            idx += 1

    run_create(tool_id=tool_id, category=category, binary=binary, output_dir=output_dir)
