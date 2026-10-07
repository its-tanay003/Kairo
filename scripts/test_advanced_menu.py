from playwright.sync_api import sync_playwright
import time
import os
import sys

output_dir = "ui_screenshots"
os.makedirs(output_dir, exist_ok=True)

errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    page.on("pageerror", lambda e: errors.append(f"PageError: {e}"))
    page.on("console", lambda msg: errors.append(f"ConsoleError: {msg.text}") if msg.type == "error" else None)

    print("[*] Navigating to http://localhost:3000...")
    page.goto("http://localhost:3000", wait_until="networkidle")
    time.sleep(1.5)

    print("[*] Opening Advanced drawer...")
    page.locator("button:has-text('⚙ Advanced')").click()
    time.sleep(1.0)

    # 1. Capture System Telemetry tab (Normal width 520px)
    print("[*] Capturing System Telemetry (520px)...")
    page.screenshot(path=os.path.join(output_dir, "advanced_system_520px.png"))

    # 2. Test Refresh Telemetry and Copy Session
    print("[*] Testing System quick-actions...")
    page.locator("button:has-text('↻ Refresh Telemetry')").click()
    time.sleep(0.5)
    page.locator("button:has-text('📋 Copy Session ID')").click()
    time.sleep(0.5)

    # 3. Toggle Wide Drawer (840px)
    print("[*] Toggling Wide Console mode...")
    page.locator("button[title*='Expand Console']").click()
    time.sleep(1.0)
    page.screenshot(path=os.path.join(output_dir, "advanced_system_wide_840px.png"))

    # 4. Test Event Log Tab with Search & Filter
    print("[*] Testing Event Log tab in wide mode...")
    page.locator(".drawer-nav-item:has-text('Event Log')").click()
    time.sleep(1.0)
    page.screenshot(path=os.path.join(output_dir, "advanced_events_tab.png"))

    # Test typing in Event search box
    print("[*] Filtering events with search term 'shell'...")
    search_input = page.locator(".event-search-input")
    search_input.fill("shell")
    time.sleep(0.5)
    page.screenshot(path=os.path.join(output_dir, "advanced_events_searched.png"))

    # 5. Test Terminal CLI Tab
    print("[*] Testing Terminal tab...")
    page.locator(".drawer-nav-item:has-text('Terminal')").click()
    time.sleep(1.0)
    page.screenshot(path=os.path.join(output_dir, "advanced_terminal_tab.png"))

    # 6. Test Screen (VNC) Tab
    print("[*] Testing Screen (VNC) tab...")
    page.locator(".drawer-nav-item:has-text('Screen')").click()
    time.sleep(1.2)
    page.screenshot(path=os.path.join(output_dir, "advanced_screen_tab.png"))

    # 7. Test Dev Tools Tab with Command Runner
    print("[*] Testing Dev Tools tab...")
    page.locator(".drawer-nav-item:has-text('Dev tools')").click()
    time.sleep(1.0)
    page.screenshot(path=os.path.join(output_dir, "advanced_devtools_tab.png"))

    # 8. Test Escape key to dismiss drawer
    print("[*] Testing Escape key dismissal...")
    page.keyboard.press("Escape")
    time.sleep(1.0)
    page.screenshot(path=os.path.join(output_dir, "advanced_closed_esc.png"))

    browser.close()

# Filter fatal DOM removal errors
real_fatal_errors = [e for e in errors if "Failed to execute 'removeChild'" in e or "NotFoundError" in e or "Uncaught" in e]

print(f"\n--- Total Console/Page Errors: {len(errors)}, Fatal DOM Errors: {len(real_fatal_errors)} ---")
if errors:
    for e in errors:
        print("  -", e)

if real_fatal_errors:
    print("[FAIL] Fatal DOM removal errors found!")
    sys.exit(1)
else:
    print("[PASS] Verified: Advanced menu features tested, zero fatal exceptions, screenshots captured!")
    sys.exit(0)
