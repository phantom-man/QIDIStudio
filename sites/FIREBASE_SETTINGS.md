# Firebase Hosting — Nexus Workshop Settings

## Firebase Project

| Setting          | Value                                                            |
| ---------------- | ---------------------------------------------------------------- |
| Project ID       | `nexuicer`                                                       |
| Project Name     | NexusSlicer                                                      |
| Project Number   | `457376060296`                                                   |
| Google Account   | `damienfosborn@gmail.com`                                        |
| Firebase Console | https://console.firebase.google.com/project/nexuicer             |
| GCP Console      | https://console.cloud.google.com/home/dashboard?project=nexuicer |

> **Note:** Firebase truncated "NexusSlicer" → project ID `nexuicer`.  
> This is the canonical project ID for all API calls.

---

## Hosting Sites

| Firebase Site ID   | web.app URL                      | Local folder                 | Custom domain (Cloudflare) |
| ------------------ | -------------------------------- | ---------------------------- | -------------------------- |
| `nexuicer`         | https://nexuicer.web.app         | `sites/nexusslicer/`         | `nexusslicer.com`          |
| `nexuicer-desktop` | https://nexuicer-desktop.web.app | `sites/nexusslicer-desktop/` | `desktop.nexusslicer.com`  |
| `nexusmill-app`    | https://nexusmill-app.web.app    | `sites/nexusmill/`           | `nexusmill.com`            |
| `nexusgauge-app`   | https://nexusgauge-app.web.app   | `sites/nexusgauge/`          | `nexusgauge.com`           |

---

## Deploy Commands (after `firebase login`)

```powershell
cd c:\Users\User\source\repos\QIDIStudio\sites

# One-time: apply target mappings (already in .firebaserc but safe to re-run)
firebase target:apply hosting nexusslicer         nexuicer
firebase target:apply hosting nexusslicer-desktop nexuicer-desktop
firebase target:apply hosting nexusmill           nexusmill-app
firebase target:apply hosting nexusgauge          nexusgauge-app

# Deploy all 4 sites
firebase deploy --only hosting

# Deploy a single site (faster during iteration)
firebase deploy --only hosting:nexusslicer
firebase deploy --only hosting:nexusslicer-desktop
firebase deploy --only hosting:nexusmill
firebase deploy --only hosting:nexusgauge
```

---

## First-Time Login

```powershell
# In the sites/ directory:
firebase login --no-localhost
# Visit the URL printed, authorize with damienfosborn@gmail.com, paste the code back
```

---

## Cloudflare DNS — Records to Add

After deploying, add these CNAME records in Cloudflare for each domain:

| Domain                    | Type  | Value                      | TTL  |
| ------------------------- | ----- | -------------------------- | ---- |
| `nexusslicer.com` (root)  | CNAME | `nexuicer.web.app`         | Auto |
| `www.nexusslicer.com`     | CNAME | `nexuicer.web.app`         | Auto |
| `desktop.nexusslicer.com` | CNAME | `nexuicer-desktop.web.app` | Auto |
| `nexusmill.com` (root)    | CNAME | `nexusmill-app.web.app`    | Auto |
| `www.nexusmill.com`       | CNAME | `nexusmill-app.web.app`    | Auto |
| `nexusgauge.com` (root)   | CNAME | `nexusgauge-app.web.app`   | Auto |
| `www.nexusgauge.com`      | CNAME | `nexusgauge-app.web.app`   | Auto |

> Cloudflare tip: Set proxy status to **DNS only** (grey cloud) initially while
> verifying. Firebase will provision an SSL cert for each custom domain.  
> Switch to proxied (orange cloud) after SSL certs are issued (~24h).

**Firebase side:** After the Cloudflare CNAMEs are live, add each custom domain in the
Firebase console → Hosting → each site → "Add custom domain".
Firebase will verify the CNAME and issue a managed SSL certificate.

---

## File Structure

```
sites/
├── .firebaserc          ← project + target→siteID mappings
├── firebase.json        ← hosting config (cache headers, rewrites)
├── deploy_all.py        ← Python REST API deploy script (backup)
├── deploy_all.ps1       ← PowerShell curl.exe deploy script (backup)
├── nexusslicer/
│   └── index.html       ← NexusSlicer product page (dark purple)
├── nexusslicer-desktop/
│   └── index.html       ← Desktop app page (blue, bug fix list)
├── nexusmill/
│   └── index.html       ← CNC sim teaser (amber)
└── nexusgauge/
    └── index.html       ← Metrology teaser (teal)
```

---

## REST API Reference (manual deploy without CLI)

All calls use:

```
Authorization: Bearer <gcloud auth print-access-token>
x-goog-user-project: nexuicer
```

```
# List sites
GET  https://firebasehosting.googleapis.com/v1beta1/projects/nexuicer/sites

# Create hosting version
POST https://firebasehosting.googleapis.com/v1beta1/sites/{siteId}/versions

# Populate files (returns uploadUrl + required hashes)
POST https://firebasehosting.googleapis.com/v1beta1/sites/{siteId}/versions/{versionId}:populateFiles

# Upload file (gzip-compressed, SHA256 named)
POST {uploadUrl}/{sha256hash}

# Finalize version
PATCH https://firebasehosting.googleapis.com/v1beta1/sites/{siteId}/versions/{versionId}?updateMask=status
      body: {"status": "FINALIZED"}

# Create release (goes live)
POST  https://firebasehosting.googleapis.com/v1beta1/sites/{siteId}/releases?versionName=sites/{siteId}/versions/{versionId}
```
