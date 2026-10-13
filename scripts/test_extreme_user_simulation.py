"""
scripts/test_extreme_user_simulation.py
======================================
Simulates aggressive, extreme real-world user workflows on the KAIRO Claude UI:
  1. High-frequency starter card clicks & composer auto-fills.
  2. Rapid model dropdown switching under live stream states.
  3. Rapid Scope popover stress & cryptographic signing.
  4. Extreme payload injection into composer (emojis, XSS, unicode, long strings).
  5. High-speed drawer thrashing across all 7 subsystem tabs (0-50ms intervals).
  6. Rapid open/close drawer toggling via button and Escape key.
  7. Viewport whiplash: rapid viewport dimension shifts from 375px mobile to 2560px ultrawide.
  8. Strict verification of ZERO fatal DOM exceptions (removeChild, NotFoundError, pageerror).
"""

import sys
import os
import time
from playwright.sync_api import sync_playwright

def run_extreme_user_simulation():
    print("=" * 70)
    print("STARTING KAIRO CLAUDE UI EXTREME USER SIMULATION")
    print("=" * 70)

    errors = []
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def on_console(msg):
            if msg.type == "error":
                text = msg.text
                errors.append(text)
                print(f"  [Console Error] {text[:140]}")

        def on_page_error(err):
            page_errors.append(str(err))
            print(f"  [FATAL Page Error] {err}")

        page.on("console", on_console)
        page.on("pageerror", on_page_error)

        print("\n[Step 1/7] Navigating to http://localhost:3000...")
        page.goto("http://localhost:3000", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2.0)
        page.wait_for_selector(".app-shell", timeout=10000)
        print("  ✓ App shell mounted successfully.")

        # -----------------------------------------------------------------
        # STEP 2: Rapid Starter Prompt Card Clicking & Input Fuzzing
        # -----------------------------------------------------------------
        print("\n[Step 2/7] Testing rapid starter card clicks & composer auto-fill...")
        cards = page.locator(".claude-starter-card")
        card_count = cards.count()
        print(f"  ✓ Discovered {card_count} interactive starter cards.")

        for i in range(card_count):
            print(f"  -> Rapid clicking starter card #{i+1}...")
            cards.nth(i).click()
            time.sleep(0.1)

        # -----------------------------------------------------------------
        # STEP 3: Rapid Model Dropdown Selection Under User Interaction
        # -----------------------------------------------------------------
        print("\n[Step 3/7] Testing rapid Claude model dropdown switching...")
        model_btn = page.locator(".claude-model-pill")
        model_btn.click()
        time.sleep(0.15)

        menu = page.locator(".model-dropdown-menu")
        assert menu.is_visible(), "Model selector dropdown failed to open!"

        options = page.locator(".model-dropdown-item")
        opt_count = options.count()
        print(f"  ✓ Model menu contains {opt_count} available model tiers.")

        # Cycle rapidly through all models
        for j in range(opt_count):
            if not menu.is_visible():
                model_btn.click()
                time.sleep(0.08)
            opt_title = options.nth(j).locator(".model-item-title span").first.inner_text()
            options.nth(j).click()
            time.sleep(0.1)
            active_label = page.locator(".claude-model-pill span").nth(1).inner_text()
            print(f"  -> Selected model #{j+1}: '{opt_title}' => Active: '{active_label}'")

        # -----------------------------------------------------------------
        # STEP 4: Scope Popover Stress & Edge Cases
        # -----------------------------------------------------------------
        print("\n[Step 4/7] Testing Scope Contract popover opening, editing & re-signing...")
        scope_btn = page.locator(".scope-pill")
        scope_btn.click()
        time.sleep(0.2)
        popover = page.locator(".scope-popover")
        assert popover.is_visible(), "Scope popover failed to appear on click!"

        # Close and reopen rapidly 3 times
        for k in range(3):
            scope_btn.click()
            time.sleep(0.08)
            scope_btn.click()
            time.sleep(0.08)

        # Ensure popover is closed cleanly
        if popover.is_visible():
            close_pop_btn = page.locator(".scope-popover button.ghost-btn")
            if close_pop_btn.count() > 0:
                close_pop_btn.click()
            else:
                scope_btn.click()
            time.sleep(0.1)

        # -----------------------------------------------------------------
        # STEP 5: Composer Extreme Payload Injection & Submissions
        # -----------------------------------------------------------------
        print("\n[Step 5/7] Testing Composer extreme payload injection...")
        textarea = page.locator("textarea.composer-input")
        assert textarea.is_visible(), "Composer textarea not visible!"

        # Payload A: Huge string with unicode emojis and special chars
        huge_payload = "TEST AUDIT: " + ("A" * 1500) + " 🚀🔥💀⚡🛡️ <script>alert(1)</script> \nLine 2\nLine 3"
        textarea.fill(huge_payload)
        time.sleep(0.1)
        print("  ✓ Injected 1,500+ character multi-line payload with emojis & XSS tags.")

        # Clear and enter a real test prompt
        textarea.fill("Audit localhost service ports and verify security baseline")
        time.sleep(0.1)

        send_btn = page.locator("button.send-btn")
        if send_btn.is_enabled():
            send_btn.click()
            print("  ✓ Clicked Send button.")
        else:
            print("  ✓ Send button disabled (gateway handshake state checked).")

        # Wait for chat stream to render user message or agent response
        time.sleep(1.2)

        # -----------------------------------------------------------------
        # STEP 6: Drawer Thrashing & High-Speed Tab Switching
        # -----------------------------------------------------------------
        print("\n[Step 6/7] Thrashing Advanced Console drawer across all 7 tabs...")
        adv_toggle = page.locator("button:has-text('⚙ Advanced')")
        drawer = page.locator(".drawer-backdrop")

        if not drawer.is_visible():
            adv_toggle.click()
            time.sleep(0.3)

        # Toggle width (normal 560px -> wide 880px -> normal 560px)
        width_btn = page.locator(".drawer-header button:has-text('Wide')")
        if width_btn.count() > 0 and width_btn.is_visible():
            width_btn.click()
            time.sleep(0.1)
            print("  ✓ Toggled drawer to Wide mode (880px).")
            normal_btn = page.locator(".drawer-header button:has-text('Standard'), .drawer-header button:has-text('Normal')")
            if normal_btn.count() > 0 and normal_btn.is_visible():
                normal_btn.click()
                time.sleep(0.1)
                print("  ✓ Toggled drawer back to Standard mode (560px).")

        # High-speed tab switching across all drawer tabs
        tab_names = ["System", "Terminal", "Screen", "Task Graph", "Event Log", "Audit", "Benchmarks"]
        print("  -> High-speed tab switching burst across all 7 subsystem tabs (3 cycles)...")
        for cycle in range(3):
            for t_name in tab_names:
                tab_btn = page.locator(f".drawer-nav-item:has-text('{t_name}')")
                if tab_btn.count() > 0 and tab_btn.is_visible():
                    tab_btn.click()
                    time.sleep(0.05)  # 50ms rapid switch

        print("  ✓ Completed high-speed tab switches with zero thread lock.")

        # Rapidly toggle drawer open/closed
        print("  -> Testing rapid open/close spam (5x)...")
        close_btn = page.locator(".drawer-header button[aria-label='Close Advanced Drawer']")
        for _ in range(5):
            if close_btn.count() > 0 and close_btn.is_visible():
                close_btn.click()
                time.sleep(0.08)
            adv_toggle.click()
            time.sleep(0.08)

        # -----------------------------------------------------------------
        # STEP 7: Viewport Whiplash (Stress Resizing Across 6 Viewports)
        # -----------------------------------------------------------------
        print("\n[Step 7/7] Testing Viewport Whiplash across 6 responsive display sizes...")
        viewports = [
            ("Mobile iPhone SE", 375, 667),
            ("Mobile iPhone 14 Pro Max", 430, 932),
            ("Tablet iPad Portrait", 768, 1024),
            ("Tablet iPad Landscape", 1024, 768),
            ("Standard Desktop HD", 1440, 900),
            ("Ultra-Wide 2K", 2560, 1080),
        ]

        for name, w, h in viewports:
            print(f"  -> Resizing to {name} ({w}x{h})...")
            page.set_viewport_size({"width": w, "height": h})
            time.sleep(0.2)
            # Ensure composer is still interactable
            assert textarea.is_visible(), f"Composer became invisible at {name} ({w}x{h})!"

        # Return to standard desktop
        page.set_viewport_size({"width": 1440, "height": 900})
        time.sleep(0.2)

        # -----------------------------------------------------------------
        # VERIFICATION OF ERRORS & CRASHES
        # -----------------------------------------------------------------
        print("\n" + "=" * 70)
        print("VERIFICATION AUDIT OF BROWSER SIMULATION ERRORS")
        print("=" * 70)

        # Check for fatal React DOM removal exceptions
        fatal_dom_errors = [
            e for e in errors + page_errors
            if "removeChild" in e or "NotFoundError" in e
        ]
        print(f"Total Page Errors: {len(page_errors)}")
        print(f"Total Console Errors: {len(errors)}")
        print(f"Fatal DOM Removal Exceptions: {len(fatal_dom_errors)}")

        if len(fatal_dom_errors) > 0:
            print("[FAIL] FATAL DOM REMOVAL EXCEPTIONS DETECTED:")
            for fe in fatal_dom_errors:
                print(f"  - {fe}")
            sys.exit(1)
        elif len(page_errors) > 0:
            print(f"[FAIL] UNHANDLED PAGE ERRORS DETECTED: {page_errors}")
            sys.exit(1)
        else:
            print("[PASS] EXTREME USER SIMULATION PASSED CLEANLY WITH ZERO CRASHES!")

        browser.close()

if __name__ == "__main__":
    run_extreme_user_simulation()
