"""Probe reboot schedule controls after enabling — dump every element inside the card."""

import asyncio, sys, os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
from playwright.async_api import async_playwright
from urllib.parse import urlparse

BASE = f"https://{urlparse(os.getenv('TP_LINK_HOST','https://192.168.0.1')).netloc}"
USERNAME = os.getenv("TP_LINK_USERNAME", "")
PASSWORD = os.getenv("TP_LINK_PASSWORD", "")


async def login(page):
    await page.goto(f"{BASE}/webpages/index.html#/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await page.locator("button.btn-switch").first.click()
    await page.wait_for_timeout(3000)
    cf = None
    for _ in range(20):
        for f in page.frames:
            if "tplinkcloud.com" in f.url:
                cf = f
                break
        if cf:
            break
        await page.wait_for_timeout(500)
    assert cf
    await cf.locator("input[type='text'], input[type='email']").first.fill(USERNAME)
    await cf.locator("input[type='password']").first.fill(PASSWORD)
    await cf.locator("button:has-text('LOG IN')").first.click()
    await page.wait_for_function(
        "() => !window.location.hash.includes('/login')", timeout=20_000
    )
    await page.wait_for_timeout(2500)
    print("Login OK")


async def nav_to(page, sub_menu, child):
    await page.locator(".pc-nav__btn").filter(has_text="Advanced").first.click()
    await page.wait_for_timeout(1800)
    parent = page.locator("li.su-sub-menu").filter(has_text=sub_menu).first
    cls = await parent.get_attribute("class") or ""
    if "is-opened" not in cls:
        await parent.click()
        await page.wait_for_timeout(1200)
    await parent.locator("li.su-menu-item").filter(has_text=child).first.click()
    await page.wait_for_timeout(2500)


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False, slow_mo=80)
        ctx = await b.new_context(ignore_https_errors=True)
        page = await ctx.new_page()
        page.set_default_timeout(15_000)

        await login(page)
        await nav_to(page, "System", "Reboot")

        # Enable schedule if not already
        item = page.locator(".su-form-item").filter(has_text="Reboot Schedule:").first
        toggle = item.locator("input.su-checkbox__original").first
        if not await toggle.is_checked():
            await toggle.click(force=True)
            await page.wait_for_timeout(2000)
            print("Reboot schedule enabled")

        await page.screenshot(path="scripts/snap_reboot_enabled.png", full_page=True)

        # Dump all elements inside the Reboot Schedule card (second card)
        dump = await page.evaluate(
            """
            () => {
                // Find the card that contains "Reboot Schedule"
                const cards = [...document.querySelectorAll('.su-card')];
                const card = cards.find(c => (c.innerText||'').includes('Reboot Schedule'));
                if (!card) return [{error: 'Reboot Schedule card not found'}];
                return [...card.querySelectorAll('*')]
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    })
                    .map(el => ({
                        tag: el.tagName,
                        type: el.type || '',
                        cls: (el.className?.baseVal || el.className || '').toString().slice(0, 80),
                        text: (el.innerText || '').trim().split('\\n')[0].slice(0, 60),
                        id: el.id || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                        role: el.getAttribute('role') || '',
                        x: Math.round(el.getBoundingClientRect().x),
                        y: Math.round(el.getBoundingClientRect().y),
                    }));
            }
        """
        )

        print(f"\n--- Reboot Schedule card ({len(dump)} elements) ---")
        for el in dump:
            print(
                f"  [{el['tag']}:{el['type']}] ({el['x']},{el['y']}) id={el['id']!r} role={el['role']!r}"
            )
            print(f"    cls={el['cls']!r}")
            print(f"    text={el['text']!r}  aria={el['ariaLabel']!r}")

        # Also try clicking the Reboot Time su-select and see what appears
        print("\n--- Probing Reboot Time click ---")
        time_form = page.locator(".su-form-item").filter(has_text="Reboot Time").first
        all_children = await time_form.locator("*").all()
        print(f"Children in 'Reboot Time' form item: {len(all_children)}")
        for c in all_children[:20]:
            try:
                tag = await c.evaluate("el => el.tagName")
                cls = (await c.get_attribute("class") or "")[:60]
                txt = (await c.inner_text()).strip()[:40]
                r = await c.bounding_box()
                if r and r["width"] > 0:
                    print(
                        f"  [{tag}] ({int(r['x'])},{int(r['y'])}) cls={cls!r} text={txt!r}"
                    )
            except Exception:
                pass

        # Click first su-select (or similar) in the time form item to see dropdown
        try:
            trigger = time_form.locator(
                "[class*='select'], [class*='picker'], [class*='input']"
            ).first
            cls2 = await trigger.get_attribute("class") or ""
            print(f"\nClicking trigger: cls={cls2!r}")
            await trigger.click()
            await page.wait_for_timeout(1000)
            await page.screenshot(path="scripts/snap_reboot_dropdown.png")

            # Dump whatever appeared (dropdown items)
            dropdown_items = await page.evaluate(
                """
                () => [...document.querySelectorAll('[class*="dropdown"] li, [class*="dropdown"] div, [class*="option"]')]
                    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
                    .map(el => ({
                        tag: el.tagName, cls: (el.className?.baseVal || el.className || '').toString().slice(0,50),
                        text: (el.innerText||'').trim().slice(0,40),
                        x: Math.round(el.getBoundingClientRect().x),
                        y: Math.round(el.getBoundingClientRect().y),
                    }))
            """
            )
            print(f"\nDropdown items after click ({len(dropdown_items)}):")
            for d in dropdown_items[:30]:
                print(
                    f"  [{d['tag']}] ({d['x']},{d['y']}) cls={d['cls']!r} text={d['text']!r}"
                )
        except Exception as ex:
            print(f"Trigger click failed: {ex}")

        input("\nPress Enter to close ...")
        await b.close()


asyncio.run(main())
