"""Expand every collapsed sub-menu under Advanced and record child items + hashes."""

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


async def login(page):
    await page.goto(f"{BASE}/webpages/index.html#/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await page.locator("button.btn-switch").first.click()
    await page.wait_for_timeout(3000)
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
    await page.wait_for_function(
        "() => !window.location.hash.includes('/login')", timeout=20_000
    )
    await page.wait_for_timeout(3000)
    print("Login OK")


async def get_sidebar_items(page):
    """Return list of {text, cls, y} for all visible LI in sidebar (x < 280)."""
    return await page.evaluate(
        """
        () => [...document.querySelectorAll('li')]
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.x < 280 && r.y > 100;
            })
            .map(el => ({
                text: (el.innerText||'').trim().split('\\n')[0].trim(),
                cls:  el.className,
                y:    Math.round(el.getBoundingClientRect().y),
            }))
    """
    )


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=80)
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()

        await login(page)

        # Go to Advanced
        await page.locator(".pc-nav__btn").filter(has_text="Advanced").first.click()
        await page.wait_for_timeout(2500)

        # Top-level sub-menus to expand (they have class su-sub-menu but are collapsed)
        top_items = [
            "Wireless",
            "USB",
            "NAT Forwarding",
            "HomeShield",
            "Security",
            "VPN Server",
            "Smart Life Assistant",
            "System",
        ]

        print("\n=== Sub-menu expansion map ===\n")

        for item in top_items:
            # Click the sub-menu title to expand it
            li = page.locator("li.su-sub-menu").filter(has_text=item).first
            try:
                await li.click()
                await page.wait_for_timeout(1500)
            except Exception as ex:
                print(f"[{item}] click failed: {ex}")
                continue

            # After click: record hash and visible LI children at depth 1
            h = await page.evaluate("() => window.location.hash")
            children = await page.evaluate(
                f"""
                () => {{
                    // find the LI whose first text line is "{item}"
                    const parent = [...document.querySelectorAll('li.su-sub-menu')]
                        .find(li => (li.innerText||'').trim().split('\\n')[0].trim() === "{item}");
                    if (!parent) return [];
                    const ul = parent.querySelector('ul');
                    if (!ul) return [];
                    return [...ul.querySelectorAll(':scope > li')]
                        .map(li => {{
                            const r = li.getBoundingClientRect();
                            return {{
                                text: (li.innerText||'').trim().split('\\n')[0].trim(),
                                cls: li.className,
                                visible: r.width > 0 && r.height > 0,
                            }};
                        }});
                }}
            """
            )
            print(f"[{item}]  (hash={h})")
            for c in children:
                vis = "✓" if c["visible"] else "·"
                print(f"  {vis}  {c['text']!r:40s}  cls={c['cls']}")

            # Now click each visible child and record its hash
            visible_children = [c for c in children if c["visible"]]
            for c in visible_children:
                child_li = page.locator("li").filter(has_text=c["text"]).first
                try:
                    await child_li.click()
                    await page.wait_for_timeout(1000)
                    ch = await page.evaluate("() => window.location.hash")
                    print(f"       click {c['text']!r:30s} -> {ch}")
                except Exception as ex:
                    print(f"       click {c['text']!r} FAILED: {ex}")

            print()

        await page.screenshot(path="scripts/submenus_final.png", full_page=False)
        print("\nDone. Screenshot: scripts/submenus_final.png")
        input("Press Enter to close ...")
        await browser.close()


asyncio.run(main())
