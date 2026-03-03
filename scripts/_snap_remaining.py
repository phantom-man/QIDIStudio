"""Snap Wireless > Additional Settings and System > Reboot (after enabling schedule)."""

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


async def dump_controls(page, label, path):
    h = await page.evaluate("() => window.location.hash")
    print(f"\n{'='*60}")
    print(f"  {label}  hash={h}")
    print(f"{'='*60}")
    await page.screenshot(path=path, full_page=True)

    controls = await page.evaluate(
        """
        () => [...document.querySelectorAll('input, select, textarea, button')]
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 || el.type === 'checkbox' || el.type === 'radio';
            })
            .map(el => {
                let label = el.ariaLabel || el.getAttribute('aria-label') || el.placeholder || '';
                if (!label) {
                    let p = el.parentElement;
                    for (let i=0; i<5 && p; i++, p=p.parentElement) {
                        const t = (p.innerText||'').trim().split('\\n')[0].trim().slice(0,60);
                        if (t) { label = t; break; }
                    }
                }
                const r = el.getBoundingClientRect();
                return {
                    tag: el.tagName, type: el.type||'', id: el.id||'',
                    cls: el.className.slice(0,60), label: label.slice(0,80),
                    value: (el.value||'').slice(0,40),
                    checked: (el.type==='checkbox'||el.type==='radio') ? el.checked : null,
                    options: el.tagName==='SELECT' ? [...el.options].map(o=>o.text).slice(0,10) : null,
                    x: Math.round(r.x), y: Math.round(r.y),
                };
            })
    """
    )
    for c in controls:
        checked = f" checked={c['checked']}" if c["checked"] is not None else ""
        opts = f"\n      options={c['options']}" if c["options"] else ""
        print(
            f"  [{c['tag']}:{c['type']}] ({c['x']},{c['y']}) id={c['id']!r}  cls={c['cls']!r}"
        )
        print(f"    label={c['label']!r}  value={c['value']!r}{checked}{opts}")

    labels = await page.evaluate(
        """
        () => [...document.querySelectorAll('.su-form-item__label')]
            .filter(el => {const r=el.getBoundingClientRect(); return r.width>0;})
            .map(el => ({text: (el.innerText||'').trim(), x: Math.round(el.getBoundingClientRect().x), y: Math.round(el.getBoundingClientRect().y)}))
    """
    )
    print(f"\n  Form item labels:")
    for l in labels:
        print(f"    ({l['x']},{l['y']}) {l['text']!r}")


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False, slow_mo=80)
        ctx = await b.new_context(ignore_https_errors=True)
        page = await ctx.new_page()
        page.set_default_timeout(15_000)

        await login(page)

        # ─── Wireless > Additional Settings ────────────────────────────────
        await nav_to(page, "Wireless", "Additional Settings")
        await dump_controls(
            page, "Wireless > Additional Settings", "scripts/snap_wireless_adv.png"
        )

        # ─── DHCP Server (for DNS) ──────────────────────────────────────────
        await nav_to(page, "Network", "DHCP Server")
        await dump_controls(page, "Network > DHCP Server", "scripts/snap_dhcp.png")

        # ─── System > Reboot — enable checkbox — then dump again ───────────
        await nav_to(page, "System", "Reboot")
        await dump_controls(
            page, "System > Reboot (before enable)", "scripts/snap_reboot_pre.png"
        )

        # Enable schedule if not already
        item = page.locator(".su-form-item").filter(has_text="Reboot Schedule:").first
        toggle = item.locator("input.su-checkbox__original").first
        if not await toggle.is_checked():
            await toggle.click(force=True)
            await page.wait_for_timeout(2000)

        await dump_controls(
            page, "System > Reboot (after enable)", "scripts/snap_reboot_post.png"
        )

        input("\nPress Enter to close ...")
        await b.close()


asyncio.run(main())
