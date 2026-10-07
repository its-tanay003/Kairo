import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "docs" / "assets" / "screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def verify_and_capture():
    print("[*] Launching Playwright browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)

        # 1. Desktop Test (1920x1080)
        print("[*] Testing Desktop (1920x1080)...")
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1.25)
        page = context.new_page()

        page.goto("http://localhost:3000", wait_until="networkidle", timeout=30000)
        time.sleep(2.0)

        # Main Screen (Chat-First)
        main_dest = OUTPUT_DIR / "01_chatgpt_clean_main.png"
        page.screenshot(path=str(main_dest), full_page=False)
        print(f"[+] Saved {main_dest.name}")

        # Open Status Tooltip
        status_pill = page.locator(".status-pill").first
        if status_pill.count() > 0:
            status_pill.click()
            time.sleep(1.0)
            page.screenshot(path=str(OUTPUT_DIR / "01b_status_tooltip.png"), full_page=False)
            status_pill.click() # Close

        # Open Scope Popover
        scope_pill = page.locator(".scope-pill").first
        if scope_pill.count() > 0:
            scope_pill.click()
            time.sleep(1.0)
            page.screenshot(path=str(OUTPUT_DIR / "01c_scope_contract_popover.png"), full_page=False)
            page.locator(".scope-popover button").click() # Close

        # Open Advanced Drawer
        adv_btn = page.locator("button:has-text('⚙ Advanced')").first
        if adv_btn.count() > 0:
            adv_btn.click()
            time.sleep(1.5)
            page.screenshot(path=str(OUTPUT_DIR / "02_advanced_system_telemetry.png"), full_page=False)
            print("[+] Saved 02_advanced_system_telemetry.png")

            # Click through drawer tabs
            tabs = [
                ("Event Log", "03_advanced_event_log.png"),
                ("Terminal", "04_advanced_terminal_stream.png"),
                ("Screen (VNC)", "05_advanced_screen_vnc.png"),
                ("Task Graph", "06_advanced_task_graph.png"),
                ("Benchmarks", "07_advanced_benchmarks.png"),
                ("Audit", "08_advanced_audit_explorer.png"),
                ("Dev tools", "09_advanced_dev_tools.png"),
            ]

            for label, filename in tabs:
                tab_locator = page.locator(f".drawer-nav-item:has-text('{label}')").first
                if tab_locator.count() > 0:
                    tab_locator.click()
                    time.sleep(1.2)
                    page.screenshot(path=str(OUTPUT_DIR / filename), full_page=False)
                    print(f"[+] Saved {filename}")

            # Close drawer
            close_btn = page.locator(".drawer-header button").first
            if close_btn.count() > 0:
                close_btn.click()
                time.sleep(1.0)

        # 2. Mobile Viewport Test (375x812 - iPhone X/12/13/14/15 size)
        print("[*] Testing Mobile Viewport (375x812)...")
        mobile_ctx = browser.new_context(viewport={"width": 375, "height": 812}, device_scale_factor=2.0)
        mobile_page = mobile_ctx.new_page()

        mobile_page.goto("http://localhost:3000", wait_until="networkidle", timeout=30000)
        time.sleep(2.0)
        mobile_page.screenshot(path=str(OUTPUT_DIR / "10_mobile_chat_375px.png"), full_page=False)
        print("[+] Saved 10_mobile_chat_375px.png")

        # Open Mobile Sidebar
        hamb = mobile_page.locator(".mobile-hamburger-btn").first
        if hamb.count() > 0:
            hamb.click()
            time.sleep(1.0)
            mobile_page.screenshot(path=str(OUTPUT_DIR / "11_mobile_sidebar_375px.png"), full_page=False)
            print("[+] Saved 11_mobile_sidebar_375px.png")
            # Close via sidebar header close button
            sb_close = mobile_page.locator(".sidebar-mobile-header button").first
            if sb_close.count() > 0:
                sb_close.click()
                time.sleep(0.8)

        # Open Advanced on Mobile
        mobile_adv = mobile_page.locator("button:has-text('⚙ Advanced')").first
        if mobile_adv.count() > 0:
            mobile_adv.click()
            time.sleep(1.2)
            mobile_page.screenshot(path=str(OUTPUT_DIR / "12_mobile_advanced_375px.png"), full_page=False)
            print("[+] Saved 12_mobile_advanced_375px.png")

        browser.close()
        print("[✓] Verification and screenshot capture completed successfully.")

if __name__ == "__main__":
    verify_and_capture()
