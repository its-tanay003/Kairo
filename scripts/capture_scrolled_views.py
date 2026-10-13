import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        await page.goto("http://localhost:3000", wait_until="networkidle")
        await asyncio.sleep(2)

        # Open drawer
        btn = await page.query_selector("button:has-text('⚙ Advanced')")
        if btn:
            await btn.click()
            await asyncio.sleep(1)

        # Expand drawer if expand button exists
        expand_btn = await page.query_selector("button:has-text('Expand'), button:has-text('Collapse')")
        if expand_btn:
            await expand_btn.click()
            await asyncio.sleep(1)

        # Audit tab
        audit_tab = await page.query_selector("button.drawer-nav-item:has-text('Audit')")
        if audit_tab:
            await audit_tab.click()
            await asyncio.sleep(1)

            # Scroll down to show timeline events
            content_pane = await page.query_selector(".drawer-content-pane")
            if content_pane:
                await content_pane.evaluate("el => el.scrollTop = 500")
                await asyncio.sleep(1)

            await page.screenshot(path="scripts/audit_explorer_scrolled.png")
            print("Saved scripts/audit_explorer_scrolled.png")

        # Benchmarks tab
        benchmarks_tab = await page.query_selector("button.drawer-nav-item:has-text('Benchmarks')")
        if benchmarks_tab:
            await benchmarks_tab.click()
            await asyncio.sleep(1)

            # Scroll down to show table
            content_pane = await page.query_selector(".drawer-content-pane")
            if content_pane:
                await content_pane.evaluate("el => el.scrollTop = 480")
                await asyncio.sleep(1)

            await page.screenshot(path="scripts/benchmark_table_scrolled.png")
            print("Saved scripts/benchmark_table_scrolled.png")

        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
