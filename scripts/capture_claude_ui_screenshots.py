import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "docs" / "assets" / "screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def capture_claude_suite():
    print("[*] Launching Playwright browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)

        # 1. Desktop Context (1920x1080)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1.25)
        page = context.new_page()

        print("[*] Navigating to http://localhost:3000...")
        page.goto("http://localhost:3000", wait_until="domcontentloaded")
        time.sleep(2.0)

        # 1. Main Welcome Screen
        p1 = OUTPUT_DIR / "01_claude_welcome_screen.png"
        page.screenshot(path=str(p1), full_page=False)
        print(f"[+] Saved {p1.name}")

        # 2. Open Model Selector Dropdown
        page.locator(".claude-model-pill").click()
        time.sleep(0.8)
        p2 = OUTPUT_DIR / "02_claude_model_selector.png"
        page.screenshot(path=str(p2), full_page=False)
        print(f"[+] Saved {p2.name}")
        page.locator(".claude-model-pill").click() # Close

        # 3. Scope Popover
        page.locator("button.scope-pill").click()
        time.sleep(0.8)
        p3 = OUTPUT_DIR / "03_claude_scope_popover.png"
        page.screenshot(path=str(p3), full_page=False)
        print(f"[+] Saved {p3.name}")
        page.locator(".scope-popover button").click() # Close

        # 4. Trigger a prompt via Starter Card & Send to capture conversation turn
        page.locator(".claude-starter-card").first.click()
        time.sleep(0.5)
        # Click send
        page.locator("button.send-btn").click()
        time.sleep(2.0)
        p4 = OUTPUT_DIR / "04_claude_chat_messages.png"
        page.screenshot(path=str(p4), full_page=False)
        print(f"[+] Saved {p4.name}")

        # 5. Open Advanced Drawer
        page.locator("button:has-text('⚙ Advanced')").click()
        time.sleep(1.2)

        # System Tab
        p5_sys = OUTPUT_DIR / "05_claude_console_system.png"
        page.screenshot(path=str(p5_sys), full_page=False)
        print(f"[+] Saved {p5_sys.name}")

        # Terminal Tab
        page.locator(".drawer-nav-item:has-text('Terminal')").click()
        time.sleep(1.2)
        p5_term = OUTPUT_DIR / "06_claude_console_terminal.png"
        page.screenshot(path=str(p5_term), full_page=False)
        print(f"[+] Saved {p5_term.name}")

        # Screen Tab
        page.locator(".drawer-nav-item:has-text('Screen')").click()
        time.sleep(1.2)
        p5_screen = OUTPUT_DIR / "07_claude_console_screen.png"
        page.screenshot(path=str(p5_screen), full_page=False)
        print(f"[+] Saved {p5_screen.name}")

        # Task Graph Tab
        page.locator(".drawer-nav-item:has-text('Task Graph')").click()
        time.sleep(1.2)
        p5_graph = OUTPUT_DIR / "08_claude_console_task_graph.png"
        page.screenshot(path=str(p5_graph), full_page=False)
        print(f"[+] Saved {p5_graph.name}")

        # Audit Tab
        page.locator(".drawer-nav-item:has-text('Audit')").click()
        time.sleep(1.0)
        p5_audit = OUTPUT_DIR / "09_claude_console_audit.png"
        page.screenshot(path=str(p5_audit), full_page=False)
        print(f"[+] Saved {p5_audit.name}")

        # Benchmarks Tab
        page.locator(".drawer-nav-item:has-text('Benchmarks')").click()
        time.sleep(1.0)
        p5_bench = OUTPUT_DIR / "10_claude_console_benchmarks.png"
        page.screenshot(path=str(p5_bench), full_page=False)
        print(f"[+] Saved {p5_bench.name}")

        # Close drawer
        page.locator(".drawer-header button[aria-label='Close Advanced Drawer']").click()
        time.sleep(0.8)
        context.close()

        # 6. Mobile Viewport (375x812)
        print("[*] Testing Mobile (375x812)...")
        mob_context = browser.new_context(viewport={"width": 375, "height": 812}, device_scale_factor=2)
        mob_page = mob_context.new_page()
        mob_page.goto("http://localhost:3000", wait_until="domcontentloaded")
        time.sleep(1.5)

        p_mob = OUTPUT_DIR / "11_claude_mobile_view.png"
        mob_page.screenshot(path=str(p_mob), full_page=False)
        print(f"[+] Saved {p_mob.name}")
        mob_context.close()

        browser.close()
    print("[*] All Claude UI screenshots captured successfully!")

if __name__ == "__main__":
    capture_claude_suite()
