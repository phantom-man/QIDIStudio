"""
Connect custom domains to Firebase Hosting.
Multi-step:
  1. Create customDomain resource -> Firebase returns required DNS records
  2. Add required TXT/A records to Cloudflare automatically
  3. Firebase verifies async -> provisions SSL -> routes traffic
Re-run to check status after ~10 min.
"""

import subprocess, json, urllib.request, urllib.error, sys, time, pathlib


def gcloud_token():
    r = subprocess.run(
        "gcloud auth print-access-token", shell=True, capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"gcloud error: {r.stderr.strip()}")
        sys.exit(1)
    return r.stdout.strip()


GCP_TOKEN = gcloud_token()
FB_HEADERS = {
    "Authorization": f"Bearer {GCP_TOKEN}",
    "Content-Type": "application/json",
    "x-goog-user-project": "crafty-hook-483415-b3",
}

env_file = pathlib.Path(__file__).parents[1] / ".env"
env = {}
for line in env_file.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"')
CF_TOKEN = env["CLOUDFLARE_API_TOKEN"]
CF_HEADERS = {"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}

PROJECT = "nexuicer"
DOMAIN_MAP = {
    "nexuicer": ["nexusslicer.com", "www.nexusslicer.com"],
    "nexuicer-desktop": ["desktop.nexusslicer.com"],
    "nexusmill-app": ["nexusmill.com", "www.nexusmill.com"],
    "nexusgauge-app": ["nexusgauge.com", "www.nexusgauge.com"],
}

FB_BASE = "https://firebasehosting.googleapis.com/v1beta1"
CF_BASE = "https://api.cloudflare.com/client/v4"


def call(method, url, data=None, headers=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), f"HTTP {e.code}"
    except Exception as ex:
        return None, str(ex)


def fb(method, path, data=None):
    return call(method, f"{FB_BASE}{path}", data, FB_HEADERS)


def cf(method, path, data=None):
    return call(method, f"{CF_BASE}{path}", data, CF_HEADERS)


_zones = {}


def get_zone(domain):
    apex = ".".join(domain.split(".")[-2:])
    if apex not in _zones:
        r, _ = cf("GET", f"/zones?name={apex}&per_page=5")
        _zones[apex] = r["result"][0]["id"] if r and r.get("result") else None
    return _zones.get(apex)


def cf_upsert(zone_id, rtype, name, content, proxied=False):
    r, _ = cf("GET", f"/zones/{zone_id}/dns_records?type={rtype}&name={name}")
    for rec in (r or {}).get("result", []):
        if rec.get("content") == content:
            print(f"    CF {rtype} {name}  already exists")
            return
    d = {
        "type": rtype,
        "name": name,
        "content": content,
        "ttl": 120,
        "proxied": proxied,
    }
    r2, e2 = cf("POST", f"/zones/{zone_id}/dns_records", d)
    if e2:
        print(f"    CF {rtype} {name} ERROR: {e2}")
    else:
        print(f"    CF {rtype} {name} -> {content[:60]}  added")


print("=== Firebase Custom Domain Connector ===\n")

for site, domains in DOMAIN_MAP.items():
    parent = f"/projects/{PROJECT}/sites/{site}"
    print(f"[{site}]")
    existing_resp, _ = fb("GET", f"{parent}/customDomains")
    existing = {}
    for cd in (existing_resp or {}).get("customDomains", []):
        dname = cd.get("name", "").split("/")[-1]
        existing[dname] = cd

    for domain in domains:
        print(f"  {domain}")
        if domain in existing:
            cd = existing[domain]
            state = cd.get("hostState", "?")
            cert = cd.get("certState", "?")
            print(f"    hostState={state}  certState={cert}")
            if state == "HOST_ACTIVE":
                print("    LIVE")
                continue
            dns_updates = cd.get("requiredDnsUpdates", {})
            import pprint

            pprint.pprint(cd)
        else:
            resp, err = fb(
                "POST", f"{parent}/customDomains?customDomainId={domain}", {}
            )
            if err:
                print(
                    f"    CREATE ERROR {err}: {(resp or {}).get('error',{}).get('message','')}"
                )
                continue
            print(f"    created")
            time.sleep(2)
            cd_resp, _ = fb("GET", f"{parent}/customDomains/{domain}")
            dns_updates = (cd_resp or {}).get("requiredDnsUpdates", {})
            import pprint

            pprint.pprint(cd_resp)

        desired = dns_updates.get("desired", [])
        if not desired:
            print("    no DNS updates yet (processing)")
            continue
        zone_id = get_zone(domain)
        if not zone_id:
            print(f"    ERROR: zone not found")
            continue
        for u in desired:
            cf_upsert(
                zone_id, u.get("type", ""), u.get("domainName", ""), u.get("rdata", "")
            )
    print()

print("Done. Re-run in ~10 min to check status.")
