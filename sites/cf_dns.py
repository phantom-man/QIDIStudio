"""
Cloudflare DNS — add all Nexus Workshop CNAME records.
Reads CLOUDFLARE_API_TOKEN from environment / .env
"""
import sys, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

# Load .env manually (no dotenv dep needed)
env = {}
env_file = pathlib.Path(__file__).parents[1] / '.env'
for line in env_file.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        env[k.strip()] = v.strip().strip('"')

TOKEN = env['CLOUDFLARE_API_TOKEN']
EMAIL = env['CLOUDFLARE_EMAIL']

import urllib.request, urllib.error

HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Content-Type':  'application/json',
}

def cf(method, path, data=None):
    url = f'https://api.cloudflare.com/client/v4{path}'
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(url, method=method, data=body, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), f'HTTP {e.code}'
    except Exception as ex:
        return None, str(ex)

# ─── verify token ─────────────────────────────────────────────
tok_resp, tok_err = cf('GET', '/user/tokens/verify')
if tok_err:
    print(f'ERROR verifying token: {tok_err}')
else:
    print(f'Token status: {tok_resp.get("result", {}).get("status")}')

# ─── get all zones ────────────────────────────────────────────
resp, err = cf('GET', '/zones?per_page=50')
if err:
    print(f'ERROR listing zones: {err}'); sys.exit(1)

if not resp.get('success'):
    print(f'Zones API errors: {resp.get("errors")}'); sys.exit(1)

zones = {z['name']: z['id'] for z in resp.get('result', [])}
print(f'Found zones: {list(zones.keys())}')

# Try per-zone lookup as fallback if global list is empty
if not zones:
    print('Global zone list empty — trying per-name lookups...')
    for domain in ('nexusslicer.com', 'nexusmill.com', 'nexusgauge.com'):
        r2, e2 = cf('GET', f'/zones?name={domain}&per_page=5')
        if r2 and r2.get('success') and r2.get('result'):
            for z in r2['result']:
                zones[z['name']] = z['id']
                print(f'  Found zone {z["name"]} = {z["id"]}')
        else:
            print(f'  Not found: {domain}  errors={r2.get("errors") if r2 else e2}')
    if not zones:
        print('No zones accessible with this token. Check token permissions (Zone:Read required).')
        sys.exit(1)
print(f'Working zones: {list(zones.keys())}')

# ─── records to create ───────────────────────────────────────
RECORDS = [
    # zone_name              name                             content
    ('nexusslicer.com',      'nexusslicer.com',               'nexuicer.web.app'),
    ('nexusslicer.com',      'www.nexusslicer.com',           'nexuicer.web.app'),
    ('nexusslicer.com',      'desktop.nexusslicer.com',       'nexuicer-desktop.web.app'),
    ('nexusmill.com',        'nexusmill.com',                 'nexusmill-app.web.app'),
    ('nexusmill.com',        'www.nexusmill.com',             'nexusmill-app.web.app'),
    ('nexusgauge.com',       'nexusgauge.com',                'nexusgauge-app.web.app'),
    ('nexusgauge.com',       'www.nexusgauge.com',            'nexusgauge-app.web.app'),
]

for zone_name, rec_name, content in RECORDS:
    zid = zones.get(zone_name)
    if not zid:
        print(f'  SKIP  {rec_name} — zone {zone_name!r} not found in account')
        continue

    # Check if record already exists
    resp, _ = cf('GET', f'/zones/{zid}/dns_records?type=CNAME&name={rec_name}')
    existing = resp.get('result', []) if resp else []

    if existing:
        # Update existing
        rid   = existing[0]['id']
        old   = existing[0]['content']
        if old == content:
            print(f'  =     {rec_name} -> {content}  (unchanged)')
            continue
        resp, err = cf('PUT', f'/zones/{zid}/dns_records/{rid}', {
            'type': 'CNAME', 'name': rec_name, 'content': content,
            'ttl': 1, 'proxied': False
        })
        ok = resp.get('success') if resp else False
        print(f'  UPD   {rec_name} -> {content}  {"OK" if ok else f"ERR {err} {resp}"}')
    else:
        # Create new
        resp, err = cf('POST', f'/zones/{zid}/dns_records', {
            'type': 'CNAME', 'name': rec_name, 'content': content,
            'ttl': 1, 'proxied': False
        })
        ok = resp.get('success') if resp else False
        print(f'  ADD   {rec_name} -> {content}  {"OK" if ok else f"ERR {err} {resp}"}')

print('\nDone.')
