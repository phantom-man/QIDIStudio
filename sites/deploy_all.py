"""
Firebase Hosting REST API — full deploy for all 4 Nexus sites.
Run with:  python sites\deploy_all.py

Existing Firebase sites (project: nexuicer):
  nexuicer           -> https://nexuicer.web.app
  nexuicer-desktop   -> https://nexuicer-desktop.web.app
  nexusmill-app      -> https://nexusmill-app.web.app
  nexusgauge-app     -> https://nexusgauge-app.web.app
"""

import subprocess, json, gzip, hashlib, pathlib, sys, time
import requests as _requests

# Force line-buffered stdout even when redirected
sys.stdout.reconfigure(line_buffering=True)

PROJECT_ID = "nexuicer"
SITES_DIR = pathlib.Path(__file__).parent
LOG_FILE = SITES_DIR / "deploy_result.txt"

# site_id (Firebase) -> local folder (all sites already exist)
SITES = [
    ("nexuicer", "nexusslicer"),
    ("nexuicer-desktop", "nexusslicer-desktop"),
    ("nexusmill-app", "nexusmill"),
    ("nexusgauge-app", "nexusgauge"),
]
_log_fh = None


def log(msg: str = ""):
    print(msg, flush=True)
    if _log_fh:
        print(msg, file=_log_fh, flush=True)


def get_token() -> str:
    r = subprocess.run(
        "gcloud auth print-access-token",
        capture_output=True,
        text=True,
        shell=True,
        timeout=15,
    )
    tok = r.stdout.strip()
    if not tok:
        raise RuntimeError("gcloud returned empty token — are you logged in?")
    return tok


def api(url: str, method: str = "GET", data=None, raw=None):
    tok = get_token()
    headers = {
        "Authorization": f"Bearer {tok}",
        "x-goog-user-project": PROJECT_ID,
    }
    kwargs = dict(headers=headers, timeout=90)
    if raw is not None:
        headers["Content-Type"] = "application/octet-stream"
        kwargs["data"] = raw
    elif data is not None:
        kwargs["json"] = data

    try:
        resp = _requests.request(method, url, **kwargs)
        if resp.status_code >= 400:
            return None, f"HTTP {resp.status_code}: {resp.text[:400]}"
        return resp.json() if resp.content else {}, None
    except Exception as ex:
        return None, str(ex)


# ──────────────────────────────────────────────────────────────
def create_site(site_id: str) -> bool:
    url = (
        f"https://firebasehosting.googleapis.com/v1beta1"
        f"/projects/{PROJECT_ID}/sites?siteId={site_id}"
    )
    resp, err = api(url, method="POST", data={})
    if err:
        if "409" in err or "already exists" in err.lower():
            print(f"  [{site_id}] already exists — skipping creation")
            return True
        print(f"  [{site_id}] CREATE ERROR: {err}")
        return False
    print(f'  [{site_id}] created -> {resp.get("defaultUrl", "?")}')
    return True


def deploy_site(site_id: str, folder: str) -> bool:
    site_path = SITES_DIR / folder
    html_files = sorted(site_path.glob("**/*.html"))
    if not html_files:
        log(f"  [{site_id}] No HTML files in {site_path} — skipping")
        return False

    log(f"\n--- Deploying {site_id} ({folder}/) —  {len(html_files)} file(s) ---")

    # Gzip + SHA-256 every file
    file_map: dict[str, tuple[bytes, str]] = {}
    for f in html_files:
        raw = f.read_bytes()
        gz = gzip.compress(raw, compresslevel=9)
        sha = hashlib.sha256(gz).hexdigest()
        rel = "/" + f.relative_to(site_path).as_posix()
        file_map[rel] = (gz, sha)
        log(f"     {rel}  ({len(gz):,} bytes gzipped)  hash={sha[:12]}...")

    # 1. Create version
    resp, err = api(
        f"https://firebasehosting.googleapis.com/v1beta1/sites/{site_id}/versions",
        method="POST",
        data={
            "config": {
                "headers": [
                    {
                        "glob": "**",
                        "headers": {
                            "Cache-Control": "public,max-age=300,must-revalidate"
                        },
                    }
                ],
                "rewrites": [{"glob": "**", "path": "/index.html"}],
            }
        },
    )
    if err:
        log(f"  Create version ERROR: {err}")
        return False
    version_name = resp["name"]
    log(f'  Version: {version_name.split("/")[-1]}')

    # 2. Populate files (returns upload URL + required hashes)
    resp, err = api(
        f"https://firebasehosting.googleapis.com/v1beta1/{version_name}:populateFiles",
        method="POST",
        data={"files": {rel: sha for rel, (gz, sha) in file_map.items()}},
    )
    if err:
        log(f"  populateFiles ERROR: {err}")
        return False
    upload_url = resp.get("uploadUrl", "")
    required_hashes = set(resp.get("uploadRequiredHashes", []))
    log(f"  Upload required: {len(required_hashes)} / {len(file_map)} file(s)")

    # 3. Upload files that Firebase needs
    for rel, (gz, sha) in file_map.items():
        if sha in required_hashes:
            _, err = api(f"{upload_url}/{sha}", method="POST", raw=gz)
            if err:
                log(f"  Upload {rel} ERROR: {err}")
                return False
            log(f"  Uploaded: {rel}")

    # 4. Finalize version
    resp, err = api(
        f"https://firebasehosting.googleapis.com/v1beta1/{version_name}?updateMask=status",
        method="PATCH",
        data={"status": "FINALIZED"},
    )
    if err:
        log(f"  Finalize ERROR: {err}")
        return False
    log(f'  Status: {resp.get("status")}')

    # 5. Create release
    resp, err = api(
        f"https://firebasehosting.googleapis.com/v1beta1/sites/{site_id}/releases?versionName={version_name}",
        method="POST",
    )
    if err:
        log(f"  Release ERROR: {err}")
        return False
    log(f"  LIVE -> https://{site_id}.web.app/")
    return True


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _log_fh = open(LOG_FILE, "w", buffering=1)

    log("=" * 60)
    log(f"Firebase project : {PROJECT_ID}")
    log(f"Sites dir        : {SITES_DIR}")
    log("=" * 60)

    # All 4 sites already exist — skip creation, go straight to deploy
    log("\n=== Deploying all 4 sites ===")
    results = {}
    for site_id, folder in SITES:
        ok = deploy_site(site_id, folder)
        results[site_id] = "OK" if ok else "FAILED"
        time.sleep(0.3)

    log("\n" + "=" * 60)
    log("DEPLOYMENT SUMMARY")
    log("=" * 60)
    for site_id, status in results.items():
        log(f"  {status:6s}  {site_id:<25s}  https://{site_id}.web.app/")

    _log_fh.close()
    failed = [k for k, v in results.items() if v != "OK"]
    sys.exit(1 if failed else 0)
