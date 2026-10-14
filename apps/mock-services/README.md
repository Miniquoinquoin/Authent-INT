# mock-services

The mock Resource Servers of Authent'INT: **one image**, run twice by
`docker-compose.yml` as `svc-impots` and `svc-cadastre`. Each one receives an
access token and decides **on its own** whether to serve the request: it
downloads the issuer's public keys once, then verifies every token locally,
without calling the auth-server (ADR 0002 §11, `docs/architecture.md` §3).

```
src/mockservices/
├── config.py     SERVICE_NAME · ISSUER · AUDIENCE · CA_BUNDLE (env)
├── jwks.py       discovery → jwks_uri → cache · one refresh per 30 s on an unknown kid
├── auth.py       verify(token) → claims · require_scope("svc:impots.read")
├── resources.py  /dossiers (svc-impots) · /parcelles (svc-cadastre), fake data
└── main.py       create_app(): AUDIENCE picks the routes · /health/live · /health/ready
```

## What is verified, and why

Every line blocks a real attack (ADR §11 table). The service picks the
algorithm, never the token (invariant 6), and authorisation is enforced here,
not in the frontend (invariant 12).

| Check | Blocks | Fails with |
| --- | --- | --- |
| `Authorization: Bearer` present | anonymous calls | 401, bare `WWW-Authenticate: Bearer realm=…` |
| algorithm **pinned** to RS256 | `alg: none` (no signature) and HS256 signed with our *public* key as HMAC secret | 401 `invalid_token` |
| header `typ` is `at+jwt` (RFC 9068) | an ID token, same issuer and key, used as an access token | 401 `invalid_token` |
| `kid` is one of the issuer's keys, signature valid | a token signed by anyone else, a tampered payload | 401 `invalid_token` |
| `iss` equals `ISSUER` exactly | a genuine token from another OpenID Provider | 401 `invalid_token` |
| `aud` contains `AUDIENCE` | a `svc-cadastre` token replayed on `svc-impots` | 401 `invalid_token` |
| `exp` (and `nbf`, `iat` not in the future), 30 s leeway | replay of an old, stolen token | 401 `invalid_token` |
| route scope in `scope` (whole word) | a user who is authenticated but not allowed **here** | 403 `insufficient_scope` |

The reason a token was rejected goes to the logs, never to the caller.
503 means the issuer has not been reached yet: we cannot tell a valid token
from a forged one, and that is our failure, not the token's.

JWKS cache rules (ADR §11):

- the key set is cached; a request costs no network call;
- the discovered `issuer` must equal `ISSUER` character for character, or the
  keys are not loaded;
- an unknown `kid` (likely a rotation) triggers **one** refresh, then none for
  `JWKS_REFRESH_COOLDOWN` seconds (30): random kids can't turn the mocks into a
  denial of service on the auth-server;
- if the issuer is down at boot, the service starts anyway and retries every
  `JWKS_RETRY_DELAY` seconds (2) on the next request or readiness probe;
- TLS to the issuer is verified against `CA_BUNDLE` (Caddy's internal root, see
  `docs/architecture.md` §1.1). There is no switch to turn verification off.

## Routes

| Instance | Route | Scope |
| --- | --- | --- |
| svc-impots | `GET /dossiers` | `svc:impots.read` |
| svc-impots | `POST /dossiers` `{"impot": "revenu", "annee": 2025}` | `svc:impots.write` |
| svc-cadastre | `GET /parcelles` | `svc:cadastre.read` |
| svc-cadastre | `PATCH /parcelles/{id}` `{"nature": "bati"}` | `svc:cadastre.write`, held by **no role** today (ADR §18 q.12): always 403 |
| both | `GET /health/live` · `GET /health/ready` (JWKS loaded) | none |

Data is fake and deterministic; nothing about the user but the opaque `sub`.
Writes are answered, never stored.

## Tests

No Docker, no Postgres, no network: `tests/conftest.py` plays the issuer with
a throwaway RSA key pair generated in memory for each run (seam S2 of ADR §17)
and serves its discovery document and JWKS through `httpx.MockTransport`. No
private key is ever written to disk or committed.

```sh
cd apps/mock-services
uv sync
uv run pytest
```

## Calling it through Caddy

With the stack up (`make up`) and a real access token from the auth-server's
`/token` endpoint (brick B2):

```sh
# Caddy's root CA, so curl can verify TLS (caddy-root.crt is gitignored)
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt

TOKEN=...   # the access_token returned by /token
curl --cacert caddy-root.crt -H "Authorization: Bearer $TOKEN" https://impots.authentint.local/dossiers
curl --cacert caddy-root.crt -i https://impots.authentint.local/dossiers                 # 401
curl --cacert caddy-root.crt -i -H "Authorization: Bearer $TOKEN" \
     -X PATCH -H 'Content-Type: application/json' -d '{"nature": "bati"}' \
     https://cadastre.authentint.local/parcelles/AB-0012       # agent/admin: 403 · contribuable: 401 (aud)
```

The three demonstrations of ADR §11: paste the token in a decoder (the claims
are readable by anyone, so no personal data in them); change one character of
the payload and replay it (401); forge an `alg: none` token and replay it (401).
Each one is also a test in `tests/test_auth.py`.
