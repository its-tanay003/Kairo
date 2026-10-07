#!/usr/bin/env python3
"""
Automated UI Screenshot Capture for Kairo Platform Documentation.
Uses Playwright to capture high-resolution screenshots of each interface tab and modal.
Reloads per tab to guarantee pristine isolation and rendering.
"""

import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIRS = [
    ROOT / "docs" / "assets" / "screenshots",
    Path(r"C:\Users\hp\.gemini\antigravity-ide\brain\4f309a9e-9d38-441f-a1ab-33a31c2a75ca\screenshots"),
]

for d in OUTPUT_DIRS:
    d.mkdir(parents=True, exist_ok=True)


TAB_SPECS = [
    (0, "02_live_session.png", "Live Session"),
    (1, "03_audit_explorer.png", "Audit Explorer"),
    (2, "04_dataset_curation.png", "Dataset & Training"),
    (3, "05_benchmark_leaderboard.png", "Public Leaderboard"),
    (4, "06_task_graph.png", "Task Graph DAG"),
    (5, "07_terminal_process.png", "Terminal Process Tree"),
    (6, "08_screen_stream.png", "Kali Remote Desktop"),
    (7, "09_security_browser.png", "Security Testing Browser"),
    (8, "10_vm_sandbox.png", "VM Sandbox Manager"),
    (9, "11_model_center.png", "Model Center"),
    (10, "12_latest_event.png", "Latest Event Store"),
]


def capture_all():
    print("[*] Starting Playwright with msedge channel...")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1.25,
        )
        page = context.new_page()

        def save(filename):
            for out_dir in OUTPUT_DIRS:
                dest = out_dir / filename
                page.screenshot(path=str(dest), full_page=False)
            print(f"[+] Saved screenshot: {filename}")

        # Capture Main Dashboard (initial state)
        print("[*] Capturing 01_main_dashboard.png...")
        page.goto("http://localhost:3000", wait_until="networkidle", timeout=30000)
        time.sleep(2.0)
        save("01_main_dashboard.png")

        # Capture each tab by navigating cleanly
        for idx, filename, label in TAB_SPECS:
            try:
                print(f"[*] Capturing tab {idx}: {label} -> {filename}...")
                page.goto("http://localhost:3000", wait_until="networkidle", timeout=30000)
                time.sleep(1.5)
                btns = page.locator(".inspector-header button").all()
                if idx < len(btns):
                    btns[idx].click()
                    time.sleep(2.0)
                    save(filename)
                else:
                    print(f"[-] Index {idx} out of range (found {len(btns)} buttons)")
            except Exception as e:
                print(f"[!] Error on tab {label}: {e}")

        # Scope Contract Modal
        try:
            print("[*] Capturing Scope Contract Modal...")
            page.goto("http://localhost:3000", wait_until="networkidle", timeout=30000)
            time.sleep(1.5)
            scope_btn = page.locator("button:has-text('SCOPE:'), .scope-chip").first
            if scope_btn.count() > 0:
                scope_btn.click()
                time.sleep(1.5)
                save("13_scope_contract_modal.png")
        except Exception as e:
            print(f"[!] Error on Scope Contract Modal: {e}")

        # Why This Tool Drawer / Tool Selection query
        try:
            print("[*] Capturing Why-This-Tool Drawer...")
            page.goto("http://localhost:3000", wait_until="networkidle", timeout=30000)
            time.sleep(1.5)
            # Find any why-this-tool badge or open via JS state if available
            why_btn = page.locator("button:has-text('Why'), .why-btn, .tool-selection-chip").first
            if why_btn.count() > 0 and why_btn.is_visible():
                why_btn.click()
                time.sleep(1.2)
                save("14_why_this_tool_drawer.png")
        except Exception as e:
            print(f"[!] Error on Why-This-Tool: {e}")

        browser.close()
        print("[✓] Complete set of screenshots successfully captured!")


if __name__ == "__main__":
    capture_all()
