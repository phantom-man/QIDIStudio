# Nexus Workshop — Product Websites

Three static landing pages deployed to Firebase Hosting.

## Structure

```
sites/
  nexusslicer/   → nexusslicer.com
  nexusmill/     → nexusmill.com
  nexusgauge/    → nexusgauge.com
  firebase.json
  .firebaserc
```

## First-time setup

### 1. Install Firebase CLI

```bash
npm install -g firebase-tools
```

### 2. Login

```bash
firebase login
```

### 3. Create Firebase project

Go to https://console.firebase.google.com → New project → Name it `nexus-workshop`

### 4. Create three Hosting sites in the project

Firebase Console → Hosting → Add another site:

- `nexusslicer-com`
- `nexusmill-com`
- `nexusgauge-com`

### 5. Deploy all three

```bash
cd sites
firebase deploy --only hosting
```

Or deploy one at a time:

```bash
firebase deploy --only hosting:nexusslicer
firebase deploy --only hosting:nexusmill
firebase deploy --only hosting:nexusgauge
```

## Custom domains (do this after first deploy)

In Firebase Console → Hosting → each site → Add custom domain:

- `nexusslicer-com` → `nexusslicer.com` + `www.nexusslicer.com`
- `nexusmill-com` → `nexusmill.com` + `www.nexusmill.com`
- `nexusgauge-com` → `nexusgauge.com` + `www.nexusgauge.com`

Firebase will give you DNS records (TXT + A records). Add them in Cloudflare.
SSL is automatic — provisioned within minutes.

## materials subdomain

Add separately in Cloudflare DNS for nexusslicer.com:

- Type: CNAME
- Name: materials
- Target: (your API backend — Render/Railway/Cloud Run hostname)
- Proxy: ON

This gives you `materials.nexusslicer.com` for the MaterialsDatabaseClient API.

## Updates

Just edit the HTML and re-run `firebase deploy`. No build step needed — pure static HTML/CSS.
