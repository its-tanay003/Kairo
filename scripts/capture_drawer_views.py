import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        print("Navigating to http://localhost:3000...")
        await page.goto("http://localhost:3000", wait_until="networkidle")
        await asyncio.sleep(2)

        # Look for the drawer open toggle
        # Check drawer button in layout/header/sidebar
        drawer_btn = await page.query_selector(".btn-open-drawer, .header-drawer-btn, button[title*='Drawer'], button[title*='Inspect'], .sidebar-footer button, .drawer-toggle")
        if drawer_btn:
            print("Clicking drawer button...")
            await drawer_btn.click()
            await asyncio.sleep(1)
        else:
            # Let's check all buttons to see which one opens the drawer
            buttons = await page.query_selector_all("button")
            for b in buttons:
                text = await b.inner_text()
                title = await b.get_attribute("title") or ""
                if "drawer" in text.lower() or "audit" in text.lower() or "advanced" in text.lower() or "drawer" in title.lower():
                    print(f"Found candidate button: text='{text}', title='{title}'")
                    await b.click()
                    await asyncio.sleep(1)
                    break

        # Check if drawer-container is open
        drawer_pane = await page.query_selector(".drawer-container")
        print(f"Drawer container present: {drawer_pane is not None}")

        # Now click the Audit nav rail item
        audit_tab = await page.query_selector("button.drawer-nav-item:has-text('Audit')")
        if audit_tab:
            print("Clicking Audit tab in nav rail...")
            await audit_tab.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scripts/audit_explorer_styled.png", full_page=False)
            print("Saved scripts/audit_explorer_styled.png")

        # Now click the Benchmarks nav rail item
        benchmarks_tab = await page.query_selector("button.drawer-nav-item:has-text('Benchmarks')")
        if benchmarks_tab:
            print("Clicking Benchmarks tab in nav rail...")
            await benchmarks_tab.click()
            await asyncio.sleep(2)
            await page.screenshot(path="scripts/benchmark_leaderboard_styled.png", full_page=False)
            print("Saved scripts/benchmark_leaderboard_styled.png")

            # Try clicking the other tabs in the leaderboard
            prog_tab = await page.query_selector("button.lb-tab:has-text('Progression')")
            if prog_tab:
                await prog_tab.click()
                await asyncio.sleep(1)
                await page.screenshot(path="scripts/benchmark_progression_styled.png", full_page=False)
                print("Saved scripts/benchmark_progression_styled.png")

        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
