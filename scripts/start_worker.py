#!/usr/bin/env python3
"""
Kairo Worker & Sandbox Auto-Starter CLI.
Quickly boots and verifies the isolated Kali Linux VM (or WSL2 worker agent)
so that tool executions run in the isolated sandbox rather than host fallback.

Usage:
    python scripts/start_worker.py          # Auto-starts worker and displays status
    python scripts/start_worker.py --status # Displays current sandbox & worker status
    python scripts/start_worker.py --poweroff # Powers off the VirtualBox Kali VM
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

# Ensure repo root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.vm_manager import vm_manager
from orchestrator.kali_connector import get_kali_connector


BANNER = r"""
  _  __     _             __          __        _             
 | |/ /    (_)           \ \        / /       | |            
 | ' / __ _ _ _ __ ___    \ \  /\  / /__  _ __| | _____ _ __ 
 |  < / _` | | '__/ _ \    \ \/  \/ / _ \| '__| |/ / _ \ '__|
 | . \ (_| | | | | (_) |    \  /\  / (_) | |  |   <  __/ |   
 |_|\_\__,_|_|_|  \___/      \/  \/ \___/|_|  |_|\_\___|_|   
                     ISOLATED SANDBOX
"""


def show_status():
    status = vm_manager.get_status()
    plane_raw = status.get("execution_plane", "unknown")
    if isinstance(plane_raw, dict):
        plane_desc = f"{plane_raw.get('backend_name', plane_raw.get('plane_type', 'unknown'))} ({plane_raw.get('plane_type', '')})"
    else:
        plane_desc = str(plane_raw)
    vbox_avail = status.get("virtualbox_available", False)
    vm_running = status.get("vm_running", False)
    worker_online = status.get("worker_online", False)
    worker_url = status.get("worker_url", "http://127.0.0.1:9999")
    worker_info = status.get("worker_info") or {}

    print("\n" + "=" * 65)
    print(" KAIRO EXECUTION PLANE & WORKER STATUS")
    print("=" * 65)
    print(f"  Execution Plane:        {plane_desc}")
    print(f"  VirtualBox Registered:  {'YES' if vbox_avail else 'NO'}")
    print(f"  Kali VM Running:        {'YES' if vm_running else 'NO'}")
    print(f"  Worker Agent Online:    {'ONLINE [200 OK]' if worker_online else 'OFFLINE'}")
    print(f"  Worker URL:             {worker_url}")
    if worker_info:
        print(f"  Worker OS / Kernel:     {worker_info.get('os')} ({worker_info.get('kernel')})")
        print(f"  Worker Agent Version:   {worker_info.get('version')}")
        print(f"  Supported ToolSpecs:    {', '.join(worker_info.get('supported_tools', []))}")
    print("=" * 65 + "\n")
    return worker_online


def main():
    parser = argparse.ArgumentParser(description="Kairo Sandbox Worker Auto-Starter")
    parser.add_argument("--status", action="store_true", help="Show current worker status and exit")
    parser.add_argument("--poweroff", action="store_true", help="Power off the VirtualBox VM")
    parser.add_argument("--timeout", type=int, default=50, help="Wait timeout in seconds (default: 50)")
    args = parser.parse_args()

    print(BANNER)

    if args.status:
        online = show_status()
        sys.exit(0 if online else 1)

    if args.poweroff:
        print("[*] Powering off VirtualBox VM...")
        res = vm_manager.poweroff_vm()
        print(f"    Result: {res}")
        sys.exit(0)

    # 1. Fast check if already online
    if vm_manager.is_worker_online(timeout_sec=1.5):
        print("[+] Worker agent is ALREADY ONLINE on port 9999!")
        show_status()
        return

    # 2. Start VM or worker daemon
    print(f"[*] Worker is offline. Auto-starting isolated sandbox (timeout: {args.timeout}s)...")
    success = vm_manager.ensure_worker_online(timeout_sec=args.timeout, auto_start=True)

    if success:
        print("\n[+] Sandbox and Worker Agent successfully initialized!")
        show_status()
        print("[+] Ready for isolated ToolSpec execution without host fallback.")
        sys.exit(0)
    else:
        print(f"\n[!] Failed to reach worker agent within {args.timeout}s.")
        show_status()
        print("[!] Commands will fall back to local execution with honest notice banner.")
        sys.exit(1)


if __name__ == "__main__":
    main()
