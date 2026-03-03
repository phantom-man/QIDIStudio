"""Quick diagnostic: screenshot the login page and dump all visible text/links."""

import asyncio, sys, os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
from playwright.async_api import async_playwright
from urllib.parse import urlparse

ROUTER_URL = os.getenv("TP_LINK_HOST", "https://192.168.0.1")
_p = urlparse(ROUTER_URL)
BASE = f"https://{_p.netloc}"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=200)
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()

        # Go directly to the login page
        await page.goto(
            f"{BASE}/webpages/index.html#/login", wait_until="domcontentloaded"
        )
        await page.wait_for_timeout(3000)
        print(f"Page 1 URL: {page.url}")

        # Step through "Click here to continue" splash if present
        try:
            cont = (
                page.locator("button, a")
                .filter(has_text="Click here to continue")
                .first
            )
            if await cont.is_visible(timeout=3000):
                print("Splash detected — clicking 'Click here to continue'")
                await cont.click()
                await page.wait_for_timeout(3000)
                print(f"After click URL: {page.url}")
        except Exception as e:
            print(f"No splash button: {e}")

        await page.screenshot(path="scripts/login_page.png", full_page=True)
        print(f"Screenshot saved: scripts/login_page.png  (URL: {page.url})")

        if tplink_btn := page.locator("button.btn-switch").first:
            if await tplink_btn.is_visible(timeout=3000):
                print("Clicking TP-Link ID button ...")
                await tplink_btn.click()
                await page.wait_for_timeout(3000)  # wait for iframe/form to load
                await page.screenshot(path="scripts/login_tplinkid.png", full_page=True)
                print("Screenshot after TP-Link ID click: scripts/login_tplinkid.png")

                # Check for iframes (TP-Link ID form may load in an iframe)
                frames = page.frames
                print(f"  Frames on page: {len(frames)}")
                for i, frame in enumerate(frames):
                    print(f"    Frame {i}: url={frame.url!r}")
                    try:
                        frame_inputs = await frame.evaluate(
                            """
                            () => [...document.querySelectorAll('input, button, a')]
                                .filter(el => el.getBoundingClientRect().width > 0)
                                .map(el => ({
                                    tag: el.tagName,
                                    type: el.type || '',
                                    name: el.name || '',
                                    placeholder: el.placeholder || '',
                                    id: el.id,
                                    class: el.className,
                                    text: (el.innerText||'').trim().slice(0,60),
                                }))
                        """
                        )
                        for inp in frame_inputs:
                            print(
                                f"      [{inp['tag']}] type={inp['type']!r} text={inp['text']!r} name={inp['name']!r} placeholder={inp['placeholder']!r} id={inp['id']!r}"
                            )
                    except Exception as fe:
                        print(f"      (cannot read frame: {fe})")

        # Dump all visible text nodes and links so we know exact text to target
        texts = await page.evaluate(
            """
            () => [...document.querySelectorAll('a, button, span, div, p, input')]
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                })
                .map(el => ({
                    tag: el.tagName,
                    text: (el.innerText || el.value || el.placeholder || '').trim().slice(0, 80),
                    class: el.className,
                    id: el.id,
                    type: el.type || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    x: Math.round(el.getBoundingClientRect().x),
                    y: Math.round(el.getBoundingClientRect().y),
                }))
                .filter(el => el.text || el.tag === 'INPUT')
        """
        )
        seen = set()
        for t in texts:
            key = (t["text"], t["tag"], t["x"], t["y"])
            if key not in seen:
                seen.add(key)
                if t["tag"] == "INPUT":
                    print(
                        f"  [INPUT] ({t['x']},{t['y']}) type={t['type']!r} name={t['name']!r} placeholder={t['placeholder']!r} class={t['class']!r}"
                    )
                else:
                    print(
                        f"  [{t['tag']}] ({t['x']},{t['y']}) id={t['id']!r} class={t['class']!r} -> {t['text']!r}"
                    )

        await browser.close()


asyncio.run(main())
