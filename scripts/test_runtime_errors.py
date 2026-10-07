from playwright.sync_api import sync_playwright
import time
import sys

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append(f"PageError: {e}"))
    page.on("console", lambda msg: errors.append(f"ConsoleError: {msg.text}") if msg.type == "error" else None)

    print("[*] Navigating to http://localhost:3000...")
    page.goto("http://localhost:3000", wait_until="networkidle")
    time.sleep(1.5)

    print("[*] Opening Advanced drawer...")
    page.locator("button:has-text('⚙ Advanced')").click()
    time.sleep(1.0)

    print("[*] Testing Screen (VNC) tab...")
    page.locator(".drawer-nav-item:has-text('Screen')").click()
    time.sleep(1.2)

    print("[*] Testing Terminal tab...")
    page.locator(".drawer-nav-item:has-text('Terminal')").click()
    time.sleep(1.2)

    print("[*] Testing Event Log tab...")
    page.locator(".drawer-nav-item:has-text('Event Log')").click()
    time.sleep(1.0)

    print("[*] Closing drawer...")
    page.locator(".drawer-header button").click()
    time.sleep(1.0)

    print("[*] Testing Scope popover...")
    page.locator(".scope-pill").click()
    time.sleep(0.8)
    page.locator(".scope-popover button").click()
    time.sleep(0.8)

    browser.close()

# Filter out harmless 404s like missing favicon or backend fetch retries
real_fatal_errors = [e for e in errors if "Failed to execute 'removeChild'" in e or "NotFoundError" in e or "Uncaught" in e]

print(f"\n--- Total Errors: {len(errors)}, Fatal DOM Errors: {len(real_fatal_errors)} ---")
if errors:
    for e in errors:
        print("  -", e)

if real_fatal_errors:
    print("[FAIL] Fatal DOM removal errors found!")
    sys.exit(1)
else:
    print("[PASS] Verified: Zero removeChild or NotFoundError exceptions!")
    sys.exit(0)
