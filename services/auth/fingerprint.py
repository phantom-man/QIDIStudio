"""
services/auth/fingerprint.py — Device fingerprinting for subscription binding.

Generates a SHA-256 hardware fingerprint from:
  - CPU ID (via WMI / /proc/cpuinfo / sysctl)
  - Motherboard serial number
  - OS installation ID / machine GUID
  - Primary MAC address

The fingerprint is stable across software reinstalls but changes on hardware
swap. This binds each subscription to a physical machine.

Usage:
    from services.auth.fingerprint import get_device_fingerprint, get_platform

    fp = get_device_fingerprint()   # "a3f9..." (64-char hex)
    platform = get_platform()       # "windows" | "linux" | "macos"
"""

from __future__ import annotations

import hashlib
import platform
import re
import subprocess
import sys
import uuid


def get_platform() -> str:
    s = sys.platform.lower()
    if s.startswith("win"):
        return "windows"
    if s.startswith("darwin"):
        return "macos"
    return "linux"


# ── Per-platform component collectors ────────────────────────────────────────


def _windows_cpu_id() -> str:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        return val.strip()
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "ProcessorId", "/value"],
            timeout=5,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if "ProcessorId=" in line:
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "cpu-unknown"


def _windows_mb_serial() -> str:
    try:
        out = subprocess.check_output(
            ["wmic", "baseboard", "get", "SerialNumber", "/value"],
            timeout=5,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if "SerialNumber=" in line:
                val = line.split("=", 1)[1].strip()
                if val and val.lower() not in ("", "to be filled by o.e.m.", "none"):
                    return val
    except Exception:
        pass
    return "mb-unknown"


def _windows_os_id() -> str:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        val, _ = winreg.QueryValueEx(key, "MachineGuid")
        return val.strip()
    except Exception:
        pass
    return "os-id-unknown"


def _linux_cpu_id() -> str:
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("serial"):
                    return line.split(":", 1)[1].strip()
        # x86: use vendor + model + flags as a pseudo-id
        model = ""
        vendor = ""
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line.lower() and not model:
                    model = line.split(":", 1)[1].strip()
                if "vendor_id" in line.lower() and not vendor:
                    vendor = line.split(":", 1)[1].strip()
        if vendor or model:
            return f"{vendor}|{model}"
    except Exception:
        pass
    return "cpu-unknown"


def _linux_mb_serial() -> str:
    for path in (
        "/sys/devices/virtual/dmi/id/board_serial",
        "/sys/devices/virtual/dmi/id/product_uuid",
    ):
        try:
            val = open(path).read().strip()
            if val and val.lower() not in ("none", ""):
                return val
        except Exception:
            pass
    return "mb-unknown"


def _linux_os_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            val = open(path).read().strip()
            if val:
                return val
        except Exception:
            pass
    return "os-id-unknown"


def _macos_cpu_id() -> str:
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            timeout=5,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:
        return "cpu-unknown"


def _macos_mb_serial() -> str:
    try:
        out = subprocess.check_output(
            ["system_profiler", "SPHardwareDataType"],
            timeout=10,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if "Serial Number" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "mb-unknown"


def _macos_os_id() -> str:
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            timeout=5,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "os-id-unknown"


def _primary_mac() -> str:
    """Get the MAC address of the first non-loopback network interface."""
    try:
        import socket
        import uuid as _uuid

        mac = _uuid.getnode()
        # getnode() returns a random value if it can't find a real MAC
        if mac >> 40 & 1:  # multicast bit set → random
            return "mac-unknown"
        return ":".join(f"{(mac >> (8 * i)) & 0xFF:02x}" for i in range(5, -1, -1))
    except Exception:
        return "mac-unknown"


# ── Main entry point ──────────────────────────────────────────────────────────


def _collect_components() -> tuple[str, str, str, str]:
    plat = get_platform()
    if plat == "windows":
        return (
            _windows_cpu_id(),
            _windows_mb_serial(),
            _windows_os_id(),
            _primary_mac(),
        )
    if plat == "macos":
        return (
            _macos_cpu_id(),
            _macos_mb_serial(),
            _macos_os_id(),
            _primary_mac(),
        )
    # linux
    return (
        _linux_cpu_id(),
        _linux_mb_serial(),
        _linux_os_id(),
        _primary_mac(),
    )


def get_device_fingerprint() -> str:
    """
    Return a stable 64-char SHA-256 hex fingerprint for the current device.

    Components: CPU ID | MB serial | OS install ID | primary MAC
    """
    cpu_id, mb_serial, os_id, mac = _collect_components()
    raw = f"{cpu_id}|{mb_serial}|{os_id}|{mac}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_fingerprint_debug() -> dict[str, str]:
    """Return the raw components used to build the fingerprint (for diagnostics)."""
    cpu_id, mb_serial, os_id, mac = _collect_components()
    return {
        "cpu_id": cpu_id,
        "mb_serial": mb_serial,
        "os_id": os_id,
        "mac": mac,
        "platform": get_platform(),
        "fingerprint": hashlib.sha256(
            f"{cpu_id}|{mb_serial}|{os_id}|{mac}".encode()
        ).hexdigest(),
    }
