# QIDIStudio Auth Keys

This directory holds RSA-2048 key pair used for RS256 JWT signing.

## Files

| File | Description | Gitignored? |
|------|-------------|-------------|
| `private.pem` | RSA private key — **server-side only** | ✅ Yes — never committed |
| `public.pem` | RSA public key — safe to embed in client | No |

## Re-generating the key pair

```python
memory_env\Scripts\python.exe -B -c "
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import pathlib

k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pathlib.Path('keys/private.pem').write_bytes(
    k.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption()))
pathlib.Path('keys/public.pem').write_bytes(
    k.public_key().public_bytes(serialization.Encoding.PEM,
                                serialization.PublicFormat.SubjectPublicKeyInfo))
print('Done')
"
```

## Usage

### Server (issue token)
```python
import os; os.environ['JWT_PRIVATE_KEY_PATH'] = 'keys/private.pem'
from services.auth.token import issue_token

token = issue_token(user_id="uuid-here", fingerprint="sha256hex", tier="monthly")
```

### Client (verify token)
```python
import os; os.environ['JWT_PUBLIC_KEY_PATH'] = 'keys/public.pem'
from services.auth.token import verify_token

claims = verify_token(token, expected_fingerprint="sha256hex")
# returns {'sub': ..., 'tier': ..., 'fp': ..., 'exp': ...}
```

## Rotation process

1. Generate new key pair (above command)
2. Deploy new `public.pem` to auth service
3. Issue all new tokens with new `private.pem`
4. Old tokens (signed with old key) will fail verification after their `exp` — no revocation needed
5. For immediate revocation: invalidate via `issued_tokens` table `revoked_at` column
