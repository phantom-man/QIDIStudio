"""Snap the router dashboard after login — dumps sidebar nav items and screenshots each settings section."""

import asyncio, sys, os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
from playwright.async_api import async_playwright
from urllib.parse import urlparse

ROUTER_URL = os.getenv("TP_LINK_HOST", "https://192.168.0.1")
USERNAME = os.getenv("TP_LINK_USERNAME", "")
PASSWORD = os.getenv("TP_LINK_PASSWORD", "")
_p = urlparse(ROUTER_URL)
BASE = f"https://{_p.netloc}"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=100)
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()

        # --- Login ---
        print("Logging in ...")
        await page.goto(
            f"{BASE}/webpages/index.html#/login", wait_until="domcontentloaded"
        )
        await page.wait_for_timeout(2000)

        # Click TP-Link ID
        await page.locator("button.btn-switch").first.click()
        await page.wait_for_timeout(3000)

        # Find cloud iframe
        cloud_frame = None
        for _ in range(20):
            for f in page.frames:
                if "tplinkcloud.com" in f.url:
                    cloud_frame = f
                    break
            if cloud_frame:
                break
            await page.wait_for_timeout(500)
        assert cloud_frame, "Cloud iframe not found"

        await cloud_frame.locator("input[type='text'], input[type='email']").first.fill(
            USERNAME
        )
        await cloud_frame.locator("input[type='password']").first.fill(PASSWORD)
        await cloud_frame.locator("button:has-text('LOG IN')").first.click()

        # Wait for dashboard
        await page.wait_for_function(
            "() => !window.location.hash.includes('/login')", timeout=20_000
        )
        await page.wait_for_timeout(3000)

        await page.screenshot(path="scripts/dashboard.png", full_page=False)
        print(f"Dashboard screenshot saved. URL: {page.url}")

        # Dump all nav/menu elements (sidebar links, buttons with route-like text)
        print("\n--- Sidebar / nav elements ---")
        nav_items = await page.evaluate(
            """
            () => {
                const results = [];
                // Get all <a> and sidebar items
                document.querySelectorAll('a, [class*="nav"], [class*="menu"], [class*="sidebar"]').forEach(el => {
                    const text = (el.innerText || '').trim();
                    const href = el.getAttribute('href') || '';
                    const r = el.getBoundingClientRect();
                    if (text && text.length < 60 && r.width > 0 && r.height > 0) {
                        results.push({tag: el.tagName, text, href, class: el.className, x: Math.round(r.x), y: Math.round(r.y)});
                    }
                });
                return results;
            }
        """
        )
        seen = set()
        for n in nav_items:
            key = (n["text"], n["href"])
            if key not in seen:
                seen.add(key)
                print(
                    f"  [{n['tag']}] ({n['x']},{n['y']}) href={n['href']!r} class_snippet={n['class'][:60]!r} -> {n['text']!r}"
                )

        cur_hash = await page.evaluate("() => window.location.hash")
        print(f"\nCurrent hash: {cur_hash}")

        # ── Click "Advanced" top nav and discover sub-menu ──────────────────
        print("\nClicking 'Advanced' nav tab ...")
        await page.locator(".pc-nav__btn").filter(has_text="Advanced").first.click()
        await page.wait_for_timeout(3000)
        await page.screenshot(path="scripts/advanced_menu.png", full_page=False)
        cur_hash = await page.evaluate("() => window.location.hash")
        print(f"Hash after Advanced click: {cur_hash}")

        # Dump anything on the left side (x < 300) — sidebar items
        sidebar = await page.evaluate(
            """
            () => [...document.querySelectorAll('*')]
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    const t = (el.innerText || '').trim();
                    return t && t.length > 0 && t.length < 80
                        && r.width > 0 && r.height > 0
                        && r.x < 280 && r.x >= 0 && r.y > 100;
                })
                .map(el => ({
                    tag: el.tagName,
                    text: (el.innerText||'').trim().split('\\n')[0],
                    cls: el.className.slice(0, 80),
                    x: Math.round(el.getBoundingClientRect().x),
                    y: Math.round(el.getBoundingClientRect().y),
                }))
        """
        )
        print("\nLeft sidebar items (x < 280, y > 100):")
        seen_txt = set()
        for s in sidebar:
            if s["text"] not in seen_txt:
                seen_txt.add(s["text"])
                print(
                    f"  [{s['tag']}] ({s['x']},{s['y']}) cls={s['cls']!r:60s} -> {s['text']!r}"
                )

        # Probe: click each sidebar item, record hash, screenshot
        print("\nProbing sidebar clicks ...")
        sidebar_els = await page.locator(
            "[class*='side'], [class*='nav-item'], [class*='menu']"
        ).all()
        probed = set()
        for el in sidebar_els[:30]:
            try:
                txt = (await el.inner_text()).strip().split("\n")[0]
                if not txt or txt in probed or len(txt) > 60:
                    continue
                r = await el.bounding_box()
                if r is None or r["x"] > 280 or r["y"] < 100:
                    continue
                probed.add(txt)
                await el.click()
                await page.wait_for_timeout(1200)
                h = await page.evaluate("() => window.location.hash")
                print(f"  {txt!r:40s} -> {h}")
            except Exception as ex:
                pass

        await page.screenshot(path="scripts/advanced_probed.png", full_page=False)
        input("Press Enter to close browser ...")
        await browser.close()


asyncio.run(main())
