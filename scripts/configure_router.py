"""
configure_router.py - Playwright automation for TP-Link Archer BE230
Applies all recommended settings to fix NAT conntrack exhaustion.

Run with:
    .venv/Scripts/python configure_router.py
    # or
    python3 configure_router.py

Requires: pip install playwright && playwright install chromium
"""

import asyncio
import os
import sys
import time

# Fix Windows CP1252 console encoding (Unicode arrows/checkmarks crash otherwise)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..\\", ".env"), override=True)

try:
    from playwright.async_api import async_playwright, Page, expect
except ImportError:
    print(
        "playwright not installed. Run: pip install playwright && playwright install chromium"
    )
    sys.exit(1)

ROUTER_URL = os.getenv("TP_LINK_HOST", "http://192.168.0.1")
USERNAME = os.getenv("TP_LINK_USERNAME", "")
PASSWORD = os.getenv("TP_LINK_PASSWORD", "")
HEADLESS = "--headless" in sys.argv  # pass --headless to run without a browser window

# ── Make the base URL clean (strip path, keep scheme+host) ──────────────────
from urllib.parse import urlparse

_p = urlparse(ROUTER_URL)
# Always use https:// — BE230 uses a self-signed cert on 192.168.0.1
BASE = f"https://{_p.netloc}"


async def wait_and_click(page: Page, selector: str, timeout: int = 10_000):
    await page.wait_for_selector(selector, timeout=timeout)
    await page.click(selector)


async def _ensure_advanced(page: Page):
    """Click the 'Advanced' top-nav tab.  Safe to call even when already there."""
    adv = page.locator(".pc-nav__btn").filter(has_text="Advanced")
    try:
        await adv.first.click()
        await page.wait_for_timeout(2000)
    except Exception:
        pass  # already there


async def nav_to(page: Page, sub_menu: str, child: str):
    """Navigate Advanced > sub_menu > child by clicking sidebar items.

    Example:
        await nav_to(page, "System", "Firmware Update")
        await nav_to(page, "Wireless", "Wireless Settings")
    """
    await _ensure_advanced(page)

    # Find the collapsible LI for the sub-menu
    parent = page.locator("li.su-sub-menu").filter(has_text=sub_menu).first

    # Expand only if not already open
    cls = await parent.get_attribute("class") or ""
    if "is-opened" not in cls:
        await parent.click()
        await page.wait_for_timeout(1200)

    # Click the child item WITHIN the parent scope (avoids matching stale outer elements)
    child_el = parent.locator("li.su-menu-item").filter(has_text=child).first
    await child_el.click()
    await page.wait_for_timeout(2500)


async def login(page: Page):
    print("-> Navigating to router admin ...")
    await page.goto(f"{BASE}/webpages/index.html#/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)

    # Dismiss splash page ("Click here to continue") if present
    try:
        cont = page.locator("button, a").filter(has_text="Click here to continue").first
        if await cont.is_visible(timeout=3000):
            print("  Splash detected - clicking 'Click here to continue'")
            await cont.click()
            await page.wait_for_timeout(2000)
    except Exception:
        pass

    # Click "TP-Link ID" button (class=btn-switch, confirmed on BE230/BE3600)
    # This switches from Local Admin mode to TP-Link cloud login
    print("  Clicking TP-Link ID (bottom-right of login form) ...")
    tplink_id_btn = None
    for sel in [
        "button.btn-switch",
        "button:has-text('TP-Link ID')",
        "text=TP-Link ID",
        "[class*='btn-switch']",
    ]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                tplink_id_btn = el
                print(f"  Found TP-Link ID via: {sel!r}")
                break
        except Exception:
            continue

    if not tplink_id_btn:
        await page.screenshot(path="router_login_tplinkid.png")
        raise RuntimeError(
            "Cannot find TP-Link ID button. See router_login_tplinkid.png"
        )

    await tplink_id_btn.click()
    await page.wait_for_timeout(3000)  # wait for cloud iframe to load

    # After clicking, TP-Link ID form loads in a cross-origin iframe from tplinkcloud.com
    print("  Waiting for TP-Link cloud iframe ...")
    cloud_frame = None
    for _ in range(20):
        for f in page.frames:
            if "tplinkcloud.com" in f.url:
                cloud_frame = f
                break
        if cloud_frame:
            break
        await page.wait_for_timeout(500)

    if not cloud_frame:
        await page.screenshot(path="router_login_iframe.png")
        raise RuntimeError(
            "TP-Link cloud iframe not found. See router_login_iframe.png"
        )

    print(f"  Cloud iframe: {cloud_frame.url}")
    await cloud_frame.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1000)

    print(f"  Filling credentials for {USERNAME} ...")
    await cloud_frame.locator("input[type='text'], input[type='email']").first.fill(
        USERNAME
    )
    await cloud_frame.locator("input[type='password']").first.fill(PASSWORD)

    # Submit inside the iframe — "LOG IN" button (type='button', not type='submit')
    submit = cloud_frame.locator(
        "button:has-text('LOG IN'), button:has-text('Log In'), button:has-text('SIGN IN')"
    ).first
    await submit.click()

    # Wait for dashboard
    try:
        await page.wait_for_function(
            "() => !window.location.hash.includes('/login')", timeout=20_000
        )
        await page.wait_for_timeout(2000)
        print("  LOGIN SUCCESS")
    except Exception:
        try:
            await page.wait_for_selector(
                ".side-bar, .main-content, [class*='nav']", timeout=10_000
            )
            print("  LOGIN SUCCESS (detected dashboard)")
        except Exception as e:
            print(f"  Login may have failed: {e}")
            await page.screenshot(path="router_login_fail.png")
            raise RuntimeError("Login failed. See router_login_fail.png")


async def apply_nat_boost(page: Page):
    """Advanced → Network → Internet → verify 'Enable NAT' is checked.

    The BE3600 calls this simply 'NAT' (≠ legacy 'NAT Boost').  It should already
    be on, but we force-click if somehow disabled.
    """
    print("\n[1/7] Verifying NAT is enabled …")
    await nav_to(page, "Network", "Internet")

    try:
        # The NAT card has a su-form-item with label 'NAT:' and a su-checkbox
        item = page.locator(".su-form-item").filter(has_text="NAT:").last
        toggle = item.locator("input.su-checkbox__original").first
        checked = await toggle.is_checked(timeout=6000)
        if not checked:
            await toggle.click(force=True)
            await page.wait_for_timeout(500)
            print("  ✓ NAT enabled")
            await _save(page)
        else:
            print("  ✓ NAT already enabled (confirmed)")
    except Exception as e:
        print(f"  ⚠ NAT check: {e}")
        await page.screenshot(path="router_nat.png")


async def disable_qos(page: Page):
    """Advanced → HomeShield → QoS → uncheck 'Enabled'."""
    print("\n[2/7] Disabling QoS …")
    await nav_to(page, "HomeShield", "QoS")

    try:
        item = page.locator(".su-form-item").filter(has_text="QoS:").first
        toggle = item.locator("input.su-checkbox__original").first
        checked = await toggle.is_checked(timeout=6000)
        if checked:
            await toggle.click(force=True)
            await page.wait_for_timeout(500)
            print("  ✓ QoS disabled")
            await _save(page)
        else:
            print("  ✓ QoS already disabled")
    except Exception as e:
        print(f"  ⚠ QoS control: {e}")
        await page.screenshot(path="router_qos.png")


async def set_dns(page: Page):
    """Advanced → Network → DHCP Server → set Primary / Secondary DNS for LAN.

    The WAN/Internet page shows DHCP-assigned DNS as read-only.  The editable
    DNS for LAN clients lives in the DHCP Server settings.
    """
    print("\n[3/7] Setting DHCP DNS to 1.1.1.1 / 1.0.0.1 …")
    await nav_to(page, "Network", "DHCP Server")

    try:
        dns1_item = page.locator(".su-form-item").filter(has_text="Primary DNS").first
        dns1 = dns1_item.locator("input.su-input__content").first
        await dns1.fill("1.1.1.1")

        dns2_item = page.locator(".su-form-item").filter(has_text="Secondary DNS").first
        dns2 = dns2_item.locator("input.su-input__content").first
        await dns2.fill("1.0.0.1")

        print("  ✓ DNS set to 1.1.1.1 / 1.0.0.1")
        await _save(page)
    except Exception as e:
        print(f"  ⚠ DNS fields: {e}")
        await page.screenshot(path="router_dns.png")


async def raise_dos_thresholds(page: Page):
    """Advanced → Security → Firewall: report status.

    The BE3600 Firewall page has only SPI + Ping controls; per-flood thresholds
    are managed by HomeShield (cloud).  We just verify the SPI firewall is ON.
    """
    print("\n[4/7] Verifying SPI Firewall is enabled …")
    await nav_to(page, "Security", "Firewall")

    try:
        item = page.locator(".su-form-item").filter(has_text="SPI Firewall:").first
        # SPI uses a su-switch button element (not input.su-checkbox__original)
        btn = item.locator("button.su-switch").first
        cls = await btn.get_attribute("class") or ""
        if "su-switch-checked" in cls:
            print("  ✓ SPI Firewall already ON")
        else:
            await btn.click()
            await page.wait_for_timeout(500)
            print("  ✓ SPI Firewall enabled")
            await _save(page)
    except Exception as e:
        print(f"  ⚠ SPI Firewall check: {e}")
        await page.screenshot(path="router_firewall.png")


async def set_wireless_5ghz_160mhz(page: Page):
    """BE3600 note: Wi-Fi 7 MLO auto-selects the optimal channel width per band.

    'Additional Settings' and 'Wireless Settings' have no manual Channel Width
    dropdown when MLO is active.  We log this and skip the step.
    """
    print("\n[5/7] 5 GHz channel width check …")
    await nav_to(page, "Wireless", "Additional Settings")

    items = await page.locator(".su-form-item").filter(has_text="Channel Width").all()
    if items:
        cw = items[-1].locator("select").first
        opts = await cw.locator("option").all_text_contents()
        print(f"    Options: {opts}")
        target = next((o for o in opts if "160" in o), None) or next(
            (o for o in opts if "Auto" in o), None
        )
        if target:
            await cw.select_option(label=target)
            print(f"  ✓ 5 GHz width → {target}")
            await _save(page)
        else:
            print(f"  ⚠ 160 MHz option not listed: {opts}")
    else:
        print("  ℹ No manual Channel Width control found.")
        print("  ℹ BE3600 MLO auto-selects 160 MHz on 5 GHz — nothing to change.")


async def set_scheduled_reboot(page: Page):
    """Advanced → System → Reboot → enable weekly 3:00 AM Monday reboot.

    After enabling the schedule the defaults are already 3:00 AM / Monday /
    Every Week — so we only click the su-select pickers if the current value
    differs from what we want.
    """
    print("\n[6/7] Scheduling weekly reboot (Monday 03:00) …")
    await nav_to(page, "System", "Reboot")

    try:
        item = page.locator(".su-form-item").filter(has_text="Reboot Schedule:").first
        toggle = item.locator("input.su-checkbox__original").first

        if not await toggle.is_checked(timeout=6000):
            await toggle.click(force=True)
            await page.wait_for_timeout(2000)  # time/day pickers animate in
            print("  Reboot Schedule enabled")
        else:
            print("  Reboot Schedule already enabled")

    except Exception as e:
        print(f"  ⚠ Reboot toggle: {e}")
        await page.screenshot(path="router_reboot_toggle.png")
        return

    # ── Read current picker values ─────────────────────────────────────────
    async def su_select_val(sel: str) -> str:
        try:
            return (await page.locator(sel).first.inner_text(timeout=3000)).strip()
        except Exception:
            return ""

    async def su_select_set(trigger_sel: str, option_text: str):
        """Click a su-select trigger, then click the desired option li."""
        await page.locator(trigger_sel).first.click()
        await page.wait_for_timeout(700)
        await page.locator(
            f"li.su-select__option:text-is('{option_text}')"
        ).first.click()
        await page.wait_for_timeout(400)

    h_val = await su_select_val(".su-time-picker__hour  .su-select__content")
    m_val = await su_select_val(".su-time-picker__min   .su-select__content")
    ampm = await su_select_val(".su-time-picker__ampm  .su-select__content")
    day = await su_select_val("div[aria-label='Repeat Day'] .su-select__content")
    repeat = await su_select_val("div[aria-label='Repeat:']   .su-select__content")

    print(f"  Current: {h_val}:{m_val} {ampm}  Repeat={repeat}  Day={day}")

    try:
        if h_val != "3":
            await su_select_set(".su-time-picker__hour", "3")
        if m_val != "00":
            await su_select_set(".su-time-picker__min", "00")
        if ampm and ampm != "AM":
            await su_select_set(".su-time-picker__ampm", "AM")
        if repeat and "Week" not in repeat:
            await su_select_set("div[aria-label='Repeat:']", "Every Week")
        if day and "Monday" not in day:
            await su_select_set("div[aria-label='Repeat Day']", "Monday")

        print("  ✓ Weekly reboot Monday 03:00 AM")
        await _save(page)
    except Exception as e:
        print(f"  ⚠ Reboot time/day picker: {e}")
        await page.screenshot(path="router_reboot_sched.png")


async def check_firmware(page: Page):
    """Advanced → System → Firmware Update → click 'CHECK FOR UPDATES'."""
    print("\n[7/7] Checking for firmware update …")
    await nav_to(page, "System", "Firmware Update")

    try:
        # Click the Online Update 'CHECK FOR UPDATES' button (the first one)
        online_card = (
            page.locator(".su-card, [class*='card']")
            .filter(has_text="Online Update")
            .first
        )
        check_btn = online_card.locator("button:has-text('CHECK FOR UPDATES')").first
        await check_btn.wait_for(timeout=6000)
        await check_btn.click()
        print("  Waiting for update check (20s) …")
        await page.wait_for_timeout(20_000)

        # Read firmware version label
        try:
            ver_item = (
                page.locator(".su-form-item").filter(has_text="Firmware Version").first
            )
            ver = await ver_item.locator(".su-form-item__content").first.inner_text(
                timeout=5000
            )
            print(f"  Firmware Version: {ver.strip()}")
        except Exception:
            pass

        print("  ✓ Firmware check done")
    except Exception as e:
        print(f"  ⚠ Firmware check: {e}")
        await page.screenshot(path="router_firmware.png")


async def _save(page: Page):
    """Click Save/Apply if visible."""
    for label in ["Save", "Apply", "OK"]:
        try:
            btn = page.locator(f"button:text('{label}'):visible").first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await page.wait_for_timeout(1000)  # self-signed cert on 192.168.0.1
                print(f"  [saved]")
                return
        except Exception:
            pass


async def main():
    if not USERNAME or not PASSWORD:
        print("ERROR: TP_LINK_USERNAME / TP_LINK_PASSWORD not set in .env")
        sys.exit(1)

    print("=" * 60)
    print("  TP-Link Archer BE230 — Automated Configuration")
    print(f"  Target: {BASE}")
    print("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=80)
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()
        page.set_default_timeout(15_000)

        try:
            await login(page)
            await apply_nat_boost(page)
            await disable_qos(page)
            await set_dns(page)
            await raise_dos_thresholds(page)
            await set_wireless_5ghz_160mhz(page)
            await set_scheduled_reboot(page)
            await check_firmware(page)

            print("\n" + "=" * 60)
            print("  ✓  All settings applied.")
            print("  Router may reboot. Speed should be restored after.")
            print("=" * 60)

        except Exception as e:
            print(f"\n✗ Script stopped: {e}")
            await page.screenshot(path="router_error.png")
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
