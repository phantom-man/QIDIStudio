"""
Discovers form controls on each target settings page.
Run: .venv/Scripts/python scripts/_snap_settings_pages.py
"""

import asyncio, sys, os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
from playwright.async_api import async_playwright
from urllib.parse import urlparse

ROUTER_URL = os.getenv("TP_LINK_HOST", "https://192.168.0.1")
USERNAME = os.getenv("TP_LINK_USERNAME", "")
PASSWORD = os.getenv("TP_LINK_PASSWORD", "")
BASE = f"https://{urlparse(ROUTER_URL).netloc}"


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
    assert cf, "Cloud iframe not found"
    await cf.locator("input[type='text'], input[type='email']").first.fill(USERNAME)
    await cf.locator("input[type='password']").first.fill(PASSWORD)
    await cf.locator("button:has-text('LOG IN')").first.click()
    await page.wait_for_function(
        "() => !window.location.hash.includes('/login')", timeout=20_000
    )
    await page.wait_for_timeout(2500)
    print("Login OK")


async def ensure_advanced(page):
    await page.locator(".pc-nav__btn").filter(has_text="Advanced").first.click()
    await page.wait_for_timeout(1800)


async def nav_to(page, sub_menu, child):
    await ensure_advanced(page)
    parent = page.locator("li.su-sub-menu").filter(has_text=sub_menu).first
    cls = await parent.get_attribute("class") or ""
    if "is-opened" not in cls:
        await parent.click()
        await page.wait_for_timeout(1200)
    child_el = parent.locator("li.su-menu-item").filter(has_text=child).first
    await child_el.click()
    await page.wait_for_timeout(2500)


async def dump_page(page, label, screenshot_path):
    h = await page.evaluate("() => window.location.hash")
    print(f"\n{'='*60}")
    print(f"  {label}  (hash={h})")
    print(f"{'='*60}")
    await page.screenshot(path=screenshot_path, full_page=True)

    # Dump all input/select/button/textarea controls
    controls = await page.evaluate(
        """
        () => {
            const results = [];
            document.querySelectorAll('input, select, textarea, button[type="submit"], button[type="button"]').forEach(el => {
                if (!el.offsetParent && el.type !== 'checkbox' && el.type !== 'radio') return; // skip hidden
                const r = el.getBoundingClientRect();
                if (r.width === 0 && el.type !== 'checkbox' && el.type !== 'radio') return;

                // Find nearest label text
                let label = el.ariaLabel || el.getAttribute('aria-label') || el.placeholder || '';
                if (!label) {
                    // Walk up tree to find sibling label or parent text
                    let p = el.parentElement;
                    for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
                        const t = (p.innerText || '').trim().split('\\n')[0].trim().slice(0, 60);
                        if (t) { label = t; break; }
                    }
                }

                results.push({
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    cls: el.className.slice(0, 60),
                    label: label.slice(0, 80),
                    value: (el.value || '').slice(0, 40),
                    checked: el.type === 'checkbox' || el.type === 'radio' ? el.checked : null,
                    options: el.tagName === 'SELECT'
                        ? [...el.options].map(o => o.text).slice(0, 8)
                        : null,
                    x: Math.round(r.x),
                    y: Math.round(r.y),
                    inner: (el.innerText || '').trim().slice(0, 40),
                });
            });
            return results;
        }
    """
    )

    for c in controls:
        checked = f" checked={c['checked']}" if c["checked"] is not None else ""
        opts = f" options={c['options']}" if c["options"] else ""
        print(
            f"  [{c['tag']}:{c['type']}] ({c['x']},{c['y']}) id={c['id']!r} name={c['name']!r}"
            f" cls={c['cls']!r}{checked}{opts}"
        )
        print(f"    label={c['label']!r}  value={c['value']!r}  inner={c['inner']!r}")

    # Also dump visible text blocks that might be labels
    text_blocks = await page.evaluate(
        """
        () => [...document.querySelectorAll('[class*="label"], [class*="title"], [class*="setting"]')]
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            })
            .map(el => ({
                cls: el.className.slice(0,60),
                text: (el.innerText||'').trim().split('\\n')[0].slice(0,80),
                x: Math.round(el.getBoundingClientRect().x),
                y: Math.round(el.getBoundingClientRect().y),
            }))
    """
    )
    print(f"\n  Visible label/title/setting elements:")
    seen_t = set()
    for t in text_blocks:
        if t["text"] and t["text"] not in seen_t:
            seen_t.add(t["text"])
            print(f"    ({t['x']},{t['y']}) cls={t['cls']!r} -> {t['text']!r}")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=80)
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()
        page.set_default_timeout(15_000)

        await login(page)

        pages_to_snap = [
            (
                "Network > Internet (NAT Boost + DNS)",
                "Network",
                "Internet",
                "scripts/snap_internet.png",
            ),
            ("HomeShield > QoS", "HomeShield", "QoS", "scripts/snap_qos.png"),
            (
                "Security > Firewall (DoS)",
                "Security",
                "Firewall",
                "scripts/snap_firewall.png",
            ),
            (
                "Wireless > Wireless Settings",
                "Wireless",
                "Wireless Settings",
                "scripts/snap_wireless.png",
            ),
            ("System > Reboot", "System", "Reboot", "scripts/snap_reboot.png"),
            (
                "System > Firmware Update",
                "System",
                "Firmware Update",
                "scripts/snap_firmware.png",
            ),
        ]

        for label, sub, child, path in pages_to_snap:
            try:
                await nav_to(page, sub, child)
                await dump_page(page, label, path)
            except Exception as ex:
                print(f"\n!! {label} FAILED: {ex}")
                await page.screenshot(path=path.replace(".png", "_fail.png"))

        input("\nPress Enter to close ...")
        await browser.close()


asyncio.run(main())
