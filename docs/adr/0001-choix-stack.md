# Authent'INT — Plan d'implémentation

> Companion document to the project brief (`README.md`).
> Audience: the dev team + AI coding assistants (Claude Code).
> Scope: how to build a self-hosted OpenID Connect Provider for the DGFiP brief.

---

## 0. How to use this document

This is the **implementation contract**. The brief says *what* the client wants;
this says *what we build, with which tools, in which order*.

When working with Claude Code, point it at a specific section rather than the
whole file:

```
Read IMPLEMENTATION_PLAN.md §6 (Data model) and §7 (Endpoints),
then scaffold the Prisma schema for the OAuth state tables only.
```

Anything marked **[À VALIDER]** is a question for the client, not a decision we
have already made.

---

## 1. Core decision: we build the Authorization Server

We are **not** deploying Keycloak/Authentik and configuring it. We implement the
OpenID Provider ourselves.

**What "implement OAuth2/OIDC" does and does not mean:**

| We write | We do NOT write |
| --- | --- |
| The `/authorize` state machine | RSA / SHA-256 / HMAC primitives |
| The `/token` grant handlers | JWT serialisation & signature verification |
| Code + refresh token lifecycle | Argon2id password hashing |
| Discovery + JWKS documents | TLS |
| MFA stages, consent, sessions | Base64url, CSPRNG |

Cryptography comes from audited libraries. Hand-rolling it would be a defect,
not a demonstration of skill. What we own is **protocol logic and state
management** — which is exactly where real-world IdP vulnerabilities live.

### Specifications we implement against

| Spec | Use |
| --- | --- |
| RFC 6749 | OAuth 2.0 core |
| RFC 6750 | Bearer token usage |
| RFC 7636 | PKCE (mandatory for all clients) |
| RFC 7009 | Token revocation |
| RFC 7662 | Token introspection |
| RFC 8414 | Authorization Server Metadata |
| RFC 9700 (BCP) | OAuth 2.0 Security Best Current Practice |
| OIDC Core 1.0 | ID tokens, UserInfo, `sub` semantics |
| OIDC Discovery 1.0 | `/.well-known/openid-configuration` |
| OIDC RP-Initiated Logout | `/end-session` |

Target conformance profile: **Basic OP** + **Config OP** (see §17).

---

## 2. Container topology

Everything runs in Docker. One external entry point; every backing service binds
internally only.

```
                    ┌──────────────────────────┐
   browser ────────▶│  caddy (TLS, :443)       │
                    └────┬────────┬────────┬───┘
                         │        │        │
        ┌────────────────┘        │        └────────────────┐
        ▼                         ▼                         ▼
┌───────────────┐        ┌────────────────┐        ┌────────────────┐
│ auth-frontend │        │  auth-server   │        │ portal-frontend│
│ (login UI)    │        │  (the IdP)     │        │ (page d'accueil)│
└───────────────┘        └───┬────────┬───┘        └────────────────┘
                             │        │
              ┌──────────────┘        └──────────────┐
              ▼                                      ▼
     ┌─────────────────┐                    ┌─────────────────┐
     │  postgres:16    │                    │  valkey (cache) │
     └─────────────────┘                    └─────────────────┘
              │
              ▼
     ┌─────────────────┐   ┌──────────────┐   ┌──────────────────┐
     │ mailpit (SMTP)  │   │ svc-impots   │   │ svc-cadastre     │
     │ dev only        │   │ (mock RS)    │   │ (mock RS)        │
     └─────────────────┘   └──────────────┘   └──────────────────┘
```

| Container | Role | Image / base |
| --- | --- | --- |
| `caddy` | TLS termination, single ingress, routes by host | `caddy:2-alpine` |
| `auth-server` | The OpenID Provider. All protocol + admin endpoints | Node 22 (built) |
| `auth-frontend` | Login, MFA, consent, activation, reset UI | `caddy:2-alpine` serving Vite build |
| `portal-frontend` | *Page d'accueil* listing services per role | `caddy:2-alpine` serving Vite build |
| `svc-impots`, `svc-cadastre`, … | **Mocked** services (brief: *services externes à mocker*) | small Fastify apps |
| `postgres` | Single source of truth for identity state | `postgres:16-alpine` |
| `valkey` | OTP storage, rate limit counters, session index | `valkey/valkey:8-alpine` |
| `mailpit` | Dev SMTP catcher for A2F + activation mails | `axllent/mailpit` |
| `openldap` | **Test fixture only** — stands in for the client's directory. Compose profile `ldap`, never deployed | see §5b |
| `conformance-suite` | OIDF tests, separate compose profile | see §17 |

**Networking rules**
- Only `caddy` publishes ports to the host.
- `postgres` and `valkey` are on an internal network, never published.
- Mock services validate tokens against `auth-server`'s JWKS — they are Resource
  Servers, so they exercise the real integration path.

### Why an edge proxy at all

Not for load balancing — for **issuer identity**. Three things must agree
byte-for-byte: the `iss` claim, the Discovery document, and the URL the
conformance suite hits. Without a proxy, the browser sees `localhost:3000` while
containers see `auth-server:3000`, and you patch around that mismatch for the
rest of the project. Secondary reasons: TLS terminated once instead of in five
services, and correct cookie scoping (on bare `localhost`, cookies ignore the
port, so the SSO cookie leaks across every service — it appears to work locally
and breaks in the cluster).

### Why Caddy rather than Traefik or nginx

`tls internal` runs a local CA and issues certificates automatically. That
removes the mkcert step entirely (§13). Traefik's Docker-label discovery is its
main advantage and we don't need it — six services, all known upfront. The whole
edge config is:

```caddyfile
auth.authentint.local {
    tls internal
    reverse_proxy auth-server:3000
}

login.authentint.local {
    tls internal
    reverse_proxy auth-frontend:80
}

portal.authentint.local {
    tls internal
    reverse_proxy portal-frontend:80
}

impots.authentint.local {
    tls internal
    reverse_proxy svc-impots:4000
}
```

Add the hostnames to `/etc/hosts` pointing at `127.0.0.1`.

Inside the frontend containers, Caddy also serves the static Vite build with SPA
fallback:

```caddyfile
:80
root * /usr/share/caddy
try_files {path} /index.html
file_server
```

**This is dev scaffolding, not architecture.** In Kubernetes the cluster's
ingress controller replaces it (§12). Do not spend a session debating it.

**Why a separate `auth-frontend`:** keeping login UI out of the auth server means
the server stays a pure API and is far easier to conformance-test and to reason
about. It also mirrors how Ory Hydra separates the login/consent app.

---

## 3. Tech stack

### Recommended

| Layer | Choice | Rationale |
| --- | --- | --- |
| Language | **TypeScript** (Node 22) | Strong typing on token/claim shapes; best OIDC library ecosystem for learning |
| HTTP | **Fastify** | Fast, schema-first validation (JSON Schema per route) |
| ORM / migrations | **Prisma** | Declarative schema = a real deliverable (*schéma de BDD*) |
| JOSE | **`jose`** (panva) | The reference JS JOSE implementation; JWT sign/verify, JWKS |
| Password hashing | **`@node-rs/argon2`** | Argon2id, native speed |
| Validation | **`zod`** | Runtime validation of every protocol parameter |
| Frontend | **React + Vite + TypeScript** | Fast dev loop; two separate SPA builds |
| Styling | Tailwind or plain CSS modules | Team preference |
| Tests | **Vitest** + **Supertest**, **Playwright** (e2e) | |
| Load testing | **k6** | Scripts the *pics fiscaux* scenario |
| Observability | **OpenTelemetry** → Prometheus + Grafana + Loki | Needed to defend the resilience claim |

### Viable alternatives

- **Python**: FastAPI + SQLAlchemy + Alembic + `joserfc` + `argon2-cffi`.
  Pick this if the team is stronger in Python. `authlib` can supply grant
  plumbing if you want a middle path.
- **Java**: Spring Boot + Spring Authorization Server. Closest to what a real
  French public-sector project would ship, but the framework does so much that
  you learn less about the protocol.
- **Go**: excellent for the scaling story, weaker library ergonomics for
  building an AS from scratch.

**[À VALIDER — équipe]** Lock the language in session 1. Do not revisit.

### Deliberately not used

`node-oidc-provider`, Keycloak, Hydra, Authentik — these *are* the thing we're
building. They remain useful as **reference implementations to read** when a
spec detail is ambiguous.

---

## 4. Repository layout

```
authentint/
├── README.md                    # brief + fonctionnalités (livrable)
├── IMPLEMENTATION_PLAN.md       # this file
├── docker-compose.yml           # dev stack
├── docker-compose.conformance.yml
├── .env.example
├── docs/
│   ├── architecture.md
│   ├── db-schema.md             # livrable
│   ├── api-endpoints.md         # livrable
│   ├── threat-model.md
│   └── conformance-results/     # OIDF exports
├── apps/
│   ├── auth-server/
│   │   ├── src/
│   │   │   ├── oidc/            # authorize, token, discovery, jwks, userinfo
│   │   │   ├── flows/           # login, mfa, activation, reset (staged)
│   │   │   ├── admin/           # user CRUD, client CRUD
│   │   │   ├── domain/          # entities, scope resolution
│   │   │   ├── infra/           # db, cache, mailer, keystore
│   │   │   └── audit/
│   │   ├── prisma/schema.prisma
│   │   └── test/
│   ├── auth-frontend/
│   ├── portal-frontend/
│   └── mock-services/
├── packages/
│   └── shared-types/            # claim & scope types shared FE/BE
├── k8s/                         # manifests / Helm chart
├── fixtures/
│   └── ldap/                    # LDIF seed data for the OpenLDAP test fixture
└── load/                        # k6 scripts
```

---

## 5. Identity & authorization model

### The three levels

| Niveau | `role` claim | Droits |
| --- | --- | --- |
| Admin | `admin` | CRUD utilisateurs, CRUD clients, lecture audit |
| Agent | `agent` | Accès étendu aux services |
| Contribuable | `contribuable` | Accès restreint |

All three authenticate identically: **numéro fiscal + mot de passe**.

### Critical identifier rule

The **numéro fiscal is a login identifier, never the `sub` claim.**

- `sub` = an opaque UUIDv4, stable per user, meaningless outside our system.
- The numéro fiscal is PII (it is a French tax identifier). It must not leak into
  JWTs handed to relying parties, logs, URLs, or error messages.
- Store it hashed-and-indexed if the threat model demands it, or encrypted at
  rest at minimum. **[À VALIDER — client]**

Given the brief opens with *"système d'information précédemment compromis"*, this
is the single most defensible design decision in the project. Say so in the
README.

### Scopes

Two families:

```
# OIDC standard
openid, profile, email, offline_access

# Service access (granularité fine)
svc:impots.read      svc:impots.write
svc:cadastre.read    svc:cadastre.write
svc:admin.users      svc:admin.audit
```

Role → allowed scopes is a **server-side table**, never client-supplied. The
`/authorize` handler computes `granted = requested ∩ allowed(role) ∩ client.allowed_scopes`
and issues only that intersection. Downgrading silently is correct per RFC 6749;
log every downgrade.

### Claims in the ID token

```json
{
  "iss": "https://auth.authentint.local",
  "sub": "9f1c...uuid",
  "aud": "portal-web",
  "exp": 1750000000, "iat": 1749999700,
  "auth_time": 1749999700,
  "nonce": "<echoed>",
  "acr": "urn:authentint:acr:mfa",
  "amr": ["pwd", "otp"],
  "name": "Marie Dupont",
  "given_name": "Marie", "family_name": "Dupont",
  "role": "agent",
  "sid": "<session id, for logout>"
}
```

`amr` and `acr` are how a Resource Server proves MFA actually happened — needed
for *traçabilité totale*.

---

## 5b. Annuaire LDAP — intégration en lecture seule

### The constraint

**We do not operate the directory.** In the target architecture it is an external
system, owned by the client, and our access to it is **read-only**. We never
create, modify, or delete an entry. Our adapter exposes no write method — this is
enforced by the interface shape, not by convention.

For development and pre-launch testing we run **our own OpenLDAP instance** as a
fixture: seeded with representative entries so we can build and test the adapter
without access to the real directory. It is infrastructure in the same category
as Mailpit — never a deliverable, never deployed.

### What read-only implies about passwords

This resolves a tension in the brief. Read-only access means we cannot write a
password to the directory. Since *réinitialisation de mot de passe* and
*activation de compte* are both **in scope** and both are writes, the credential
store must be **ours**.

Therefore:

| Concern | Owner |
| --- | --- |
| Password hash (Argon2id) | **Our Postgres** |
| Activation & reset tokens | **Our Postgres** |
| MFA factors | **Our Postgres** |
| Sessions, audit, consents | **Our Postgres** |
| nom, prénom, mail, affiliation | **LDAP** (read) |
| Group membership → role | **LDAP** (read), mapped server-side |

Everything in §6 stands unchanged. LDAP is an *identity attribute source and
provisioning feed*, not the authentication backend.

**[À VALIDER — client, priorité haute]** Confirm the directory is not expected to
verify credentials via `bind`. If the client does expect delegated bind, then
password reset leaves our scope and §6/§9 need rework. This is the single
highest-impact open question in the project.

### The port

One interface, no write methods:

```ts
/** Read-only view of the client's directory. */
interface UserDirectory {
  /** Attribute lookup. Never verifies credentials. */
  findByNumeroFiscal(nf: string): Promise<DirectoryUser | null>;

  /** Incremental provisioning feed. */
  list(modifiedSince?: Date): AsyncIterable<DirectoryUser>;
}

interface DirectoryUser {
  externalId: string;   // LDAP entryUUID — the join key
  numeroFiscal: string;
  nom: string;
  prenom: string;
  email: string;
  groups: string[];     // raw group DNs, mapped to role by us
}
```

Two implementations: `LdapDirectory` (production) and `FixtureDirectory`
(unit tests, no container needed). The `openldap` container exercises
`LdapDirectory` in integration tests.

**Use `entryUUID` as the join key, never the DN.** DNs change when an entry is
moved between OUs; treating one as a stable identifier is a classic bug. Add
`users.external_id` (unique, nullable) to the schema in §6.

### Provisioning flow

```
LDAP (read) ──sync job──▶ users table ──▶ activation mail ──▶ user sets password
                             │
                             └── status = pending_activation, password_hash = null
```

This matches the brief exactly: *base existante avec des utilisateurs déjà créés
→ activer les comptes*. The sync job is idempotent, runs on a schedule
(`CronJob` in k8s), and:

- creates local rows for new `entryUUID`s
- updates changed attributes on existing rows
- **never deletes** — a disappeared entry sets `status = disabled` and is audited.
  Hard-deleting on a failed sync would be catastrophic; a transient LDAP error
  must not be able to wipe the user base.
- writes an audit event per change

### Operational rules — external dependency

The directory is outside our failure domain. Treat it accordingly.

1. **Connection pooling + aggressive timeouts.** A slow directory must not
   exhaust request handlers. Timeout ~2 s, pool the connections, circuit-break
   after repeated failures.
2. **Cache attributes in Valkey** with a TTL and background refresh. Attributes
   change rarely.
3. **Degradation policy — decide it, don't let it emerge:**
   - Directory unreachable → **existing sessions keep working** (sessions are
     local state, deliberately independent of LDAP).
   - Login still works (passwords are local); only attribute *freshness* degrades.
   - Sync job fails → retries with backoff, alerts, changes nothing.
   - This is a strong argument for the local-credential design above: an external
     outage cannot lock every user out.
4. **`/health/ready` reflects directory reachability** for the sync worker, but
   **not** for the auth server — the auth server can serve logins without it.
5. **LDAPS or StartTLS only.** Never plain `ldap://`, even against the fixture,
   so the TLS path is exercised in dev.
6. Bind credentials for the service account come from a Secret. Read-only service
   account — **ask the client to enforce this server-side too**, so a bug on our
   side cannot write.

### The OpenLDAP fixture

Under a compose profile so it stays out of the default path:

```bash
docker compose --profile ldap up
```

Seed with LDIF fixtures in `fixtures/ldap/` covering: an admin, several agents,
several contribuables, an entry with accented characters, one with a missing
optional attribute, and one that disappears between syncs (to test the
`disabled` path).

**Two cautions:**

- **Verify image maintenance before committing.** `osixia/openldap` was the
  long-standing default but has stalled, and Bitnami's catalog terms have shifted
  recently. Check what is currently maintained rather than copying an old blog
  post. If OpenLDAP configuration (`slapd`, `olc` overlays, opaque errors) eats
  more than a session, **lldap** is a lighter LDAP-compatible server with a web
  UI that is sufficient to prove the adapter works.
- **Our schema is a guess until confirmed.** Fixtures encode assumptions that
  will be wrong in ways we can't predict. See the questions below.

### Schema mapping (provisional)

| Our field | LDAP attribute | Note |
| --- | --- | --- |
| `external_id` | `entryUUID` | join key, stable |
| `numero_fiscal` | `uid` | **assumption** — likely a custom attribute |
| `nom` | `sn` | |
| `prenom` | `givenName` | |
| `email` | `mail` | |
| `role` | `memberOf` | group DN → role, mapped in our config |

**[À VALIDER — client] before writing the adapter.** One email gets all of this:

1. An **anonymised LDIF export of a single user entry**
2. The **base DN** and the **search filter** they expect us to use
3. Which attribute carries the **numéro fiscal**
4. Which **groups** exist and how they map to admin / agent / contribuable
5. Whether `entryUUID` is available (some directories expose a different
   operational attribute)
6. Expected **directory size** and **change rate** — decides full vs incremental
   sync
7. **LDAPS endpoint** and CA certificate

Until these arrive, build against the fixture and keep the mapping in
configuration, not in code.

---

## 6. Data model

Grouped by concern. Prisma is the source of truth; this is the intent.

### Identity

```
users
  id                uuid pk
  external_id       text unique null   -- LDAP entryUUID, see §5b. Never the DN.
  numero_fiscal     text unique        -- login id, encrypted/indexed
  email             citext unique
  nom               text
  prenom            text
  password_hash     text null          -- null until activation. OURS, not LDAP's.
  role              enum(admin, agent, contribuable)
  status            enum(pending_activation, active, locked, disabled)
  password_changed_at  timestamptz
  failed_login_count   int default 0
  locked_until      timestamptz null
  synced_at         timestamptz null   -- last successful directory sync
  created_at, updated_at
```

The brief says *base existante avec des utilisateurs déjà créés → activer les
comptes*. So a seed script inserts users with
`status = pending_activation, password_hash = null`. Activation is the flow that
sets the first password.

### Credentials & recovery

```
mfa_factors
  id, user_id fk, type enum(email_otp, totp, webauthn)
  secret_encrypted text null        -- totp only
  target           text null        -- email address for email_otp
  confirmed_at, created_at, last_used_at

otp_challenges                       -- store in Valkey, TTL-backed
  id, user_id, purpose enum(mfa, activation, reset)
  code_hash, attempts int, max_attempts int
  expires_at, consumed_at

activation_tokens / password_reset_tokens
  id, user_id, token_hash, expires_at, consumed_at, requested_ip
```

**Rule: never store an OTP, activation token, or reset token in plaintext.**
Hash them exactly as you hash passwords. If the DB leaks, tokens must be inert.

### OAuth clients & state

```
clients
  id                text pk           -- client_id
  name              text
  type              enum(public, confidential)
  secret_hash       text null         -- confidential only, argon2id
  redirect_uris     text[]            -- EXACT match, no wildcards
  post_logout_redirect_uris text[]
  allowed_grants    text[]            -- authorization_code, refresh_token
  allowed_scopes    text[]
  require_consent   boolean
  created_at

authorization_codes
  code_hash         text pk
  client_id, user_id, session_id
  redirect_uri      text              -- must match at /token
  scope             text
  nonce, state
  code_challenge, code_challenge_method
  auth_time         timestamptz
  acr, amr
  expires_at        timestamptz       -- now() + 60s
  consumed_at       timestamptz null

refresh_tokens
  token_hash        text pk
  family_id         uuid              -- reuse detection
  parent_hash       text null
  client_id, user_id, session_id, scope
  issued_at, expires_at
  rotated_at, revoked_at
  revocation_reason text null

consents
  id, user_id, client_id, scopes text[], granted_at, revoked_at
```

### Sessions & audit

```
sessions                              -- the SSO session
  id                uuid pk           -- becomes `sid` claim
  user_id
  device_label      text              -- "Firefox / Windows"
  user_agent, ip_address inet
  created_at, last_seen_at
  expires_at, revoked_at, revocation_reason
  acr, amr                            -- how strongly authenticated

audit_events                          -- APPEND ONLY
  id                bigserial
  occurred_at       timestamptz
  actor_user_id     uuid null
  actor_ip          inet
  event_type        text              -- login.success, mfa.failed, token.issued…
  client_id         text null
  session_id        uuid null
  outcome           enum(success, failure)
  detail            jsonb             -- NEVER contains secrets or numéro fiscal
  request_id        text              -- correlation id injected at the edge
```

Enforce append-only at the DB level: revoke `UPDATE`/`DELETE` on `audit_events`
from the application role. Trivial to do, and it turns *traçabilité* from a claim
into a guarantee.

### Key management

```
signing_keys
  kid               text pk
  alg               text              -- RS256
  public_jwk        jsonb
  private_pem_encrypted text
  status            enum(next, active, retired)
  not_before, not_after, created_at
```

Rotation: a scheduled job promotes `next`→`active`, `active`→`retired`. Retired
keys stay published in JWKS until every token signed with them has expired. This
is the classic zero-downtime rotation pattern.

---

## 7. Endpoints

### OIDC / OAuth2 (spec-defined — conformance-tested)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/.well-known/openid-configuration` | Discovery |
| GET | `/.well-known/jwks.json` | Public keys, `kid`-addressed |
| GET | `/authorize` | Validates, then 302 to `auth-frontend` |
| POST | `/token` | `authorization_code`, `refresh_token` |
| GET/POST | `/userinfo` | Bearer-protected |
| POST | `/introspect` | Client-authenticated (RFC 7662) |
| POST | `/revoke` | RFC 7009 |
| GET | `/end-session` | RP-initiated logout |

### Interaction API (ours — consumed by `auth-frontend`)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/interaction/:uid` | What does this pending auth need next? |
| POST | `/interaction/:uid/login` | numéro fiscal + password |
| POST | `/interaction/:uid/mfa/send` | Email an OTP |
| POST | `/interaction/:uid/mfa/verify` | Verify OTP → advance stage |
| POST | `/interaction/:uid/consent` | Grant/deny scopes |

The `uid` is an opaque handle to server-side state. **The client never carries
`client_id`, `scope`, or `redirect_uri` back to us** — those stay server-side,
which removes an entire class of parameter-tampering attacks.

### Account lifecycle

| Method | Path |
| --- | --- |
| POST | `/account/activation/request` |
| POST | `/account/activation/confirm` |
| POST | `/account/password-reset/request` |
| POST | `/account/password-reset/confirm` |

Both `request` endpoints must return an **identical response whether or not the
account exists** — otherwise they become account-enumeration oracles against a
tax-identifier namespace.

### Self-service (Bearer-protected)

| Method | Path |
| --- | --- |
| GET | `/me` |
| GET | `/me/sessions` — *plusieurs appareils* |
| DELETE | `/me/sessions/:id` |
| GET | `/me/audit` — user's own connection history |
| POST | `/me/password` |
| GET/POST/DELETE | `/me/mfa/factors` |

### Admin (`svc:admin.*`)

| Method | Path |
| --- | --- |
| GET/POST/PATCH/DELETE | `/admin/users` |
| POST | `/admin/users/:id/lock` / `/unlock` / `/resend-activation` |
| GET/POST/PATCH/DELETE | `/admin/clients` |
| GET | `/admin/audit` (filter, paginate, export) |
| GET | `/admin/sessions` |

### Ops

`/health/live`, `/health/ready`, `/metrics` — needed for Kubernetes probes.

---

## 8. `/authorize` — the state machine

This is the heart of the system. Order matters; do not reorder.

1. **Parse & validate.** `client_id` exists? → else render an error page. **Never
   redirect to an unvalidated `redirect_uri`.**
2. **Exact-match `redirect_uri`** against `clients.redirect_uris` (string
   equality). Mismatch → error page, no redirect. *This is the #1 IdP
   vulnerability class.*
3. From here on, errors may redirect with `error=` + `state`.
4. Validate `response_type=code` (we support **code only**; no implicit, no
   hybrid), `scope` contains `openid`, `state` present, `nonce` present.
5. **Require PKCE**: `code_challenge` present, `code_challenge_method=S256`.
   Reject `plain`. Require it from confidential clients too.
6. Create pending-interaction state (Valkey, 10 min TTL), get `uid`.
7. Is there a live SSO session cookie satisfying required `acr`?
   - Yes → skip to step 9 (**this is SSO**).
   - No → 302 to `auth-frontend/login?uid=…`.
8. Frontend drives stages: password → MFA → (consent). Each step posts to the
   interaction API; the server decides what's next. Never trust the client's
   claim about which stage it's on.
9. Consent: skip if `require_consent=false` or a matching `consents` row exists.
10. Mint an authorization code: 60 s TTL, single use, bound to
    `client_id + redirect_uri + code_challenge + user + session`.
11. 302 to `redirect_uri?code=…&state=…`.
12. Audit: `authorize.granted`.

### `/token`, authorization_code grant

1. Authenticate client (`client_secret_basic` for confidential; PKCE alone for
   public).
2. Look up code **by hash**. Not found → `invalid_grant`.
3. Already consumed? → `invalid_grant` **and revoke every token descended from
   that code.** Code replay means the code leaked.
4. Expired → `invalid_grant`.
5. `client_id` and `redirect_uri` must match what was stored.
6. Verify PKCE: `BASE64URL(SHA256(code_verifier)) == code_challenge`.
7. Mark consumed **atomically** (single `UPDATE … WHERE consumed_at IS NULL
   RETURNING`, or `SELECT … FOR UPDATE`). Two concurrent redemptions must not
   both succeed.
8. Issue access token (JWT, 10 min), ID token (5 min), refresh token if
   `offline_access` (30 days, rotating).

### Refresh rotation with reuse detection

Every refresh issues a **new** refresh token and revokes its parent, keeping
`family_id`. If a **revoked** token from a family is presented, the token leaked:
revoke the entire family, kill the session, emit a high-severity audit event.
This is the mechanism that limits blast radius after a compromise — directly
relevant to the client's stated history.

---

## 9. MFA — email OTP

The brief says *le plus simple == A2F par mail*.

**Flow:** after password success, generate 6 digits from a CSPRNG → store
**hash** in Valkey with 10 min TTL, bound to the interaction `uid` → send mail →
user submits → constant-time compare → max 5 attempts → on success set
`amr=["pwd","otp"]`, `acr=urn:authentint:acr:mfa`.

**Rules**
- The OTP is bound to the `uid`. An OTP issued for one interaction cannot be
  replayed in another.
- Rate limit: per account **and** per IP, separately.
- Consume on success *and* on attempt exhaustion.
- Never reveal in the response whether the code was wrong or expired.

**[À VALIDER — client]** Internal SMTP relay or third-party provider? Affects the
k8s manifest and the deliverability story. Dev uses Mailpit regardless.

**Design for extension now:** model `mfa_factors` as a table, and MFA as a
*stage*, so adding TOTP or WebAuthn later is a new stage implementation rather
than a refactor. Mention this in the client review — email OTP is the weakest
common factor, and for `admin` accounts it is arguably insufficient. Consider
requiring TOTP for admins as a stretch goal.

---

## 10. Frontend pages

### `auth-frontend`
- `/login` — numéro fiscal + password
- `/mfa` — OTP entry, resend with cooldown
- `/consent` — scope list in plain French
- `/activate` — first-password set from emailed token
- `/reset` — request + confirm
- `/error` — safe error rendering (never echo raw params)

### `portal-frontend` (*page d'accueil listant les services*)
- `/` — service tiles, **filtered by role**
- `/account` — profile
- `/account/sessions` — active devices, revoke buttons
- `/account/security` — password, MFA factors
- `/account/activity` — own connection history
- `/admin/users`, `/admin/audit` — admin only

**Filtering tiles client-side is presentation, not security.** Every mock service
must independently validate the token and its scopes. Build one mock service that
*correctly* rejects an under-scoped token and demo that — it proves the
granularity claim.

---

## 11. Scalability & resilience

The brief states **20 million simultaneous users** between 8–10h and May–June.

**[À VALIDER — client] — flag this explicitly.** 20M genuinely concurrent
sessions would exceed the traffic of nearly any European public service. Almost
certainly this means 20M users *over the period*. Ask for: peak
authentications/second, and peak concurrent sessions. Getting this clarified is
itself good consultancy, and the answer changes the architecture by an order of
magnitude. Do not silently design for either reading.

**Design choices that hold either way:**

1. **Stateless access tokens.** Short-lived RS256 JWTs; Resource Servers validate
   locally against a cached JWKS. No DB hit per API call. *Retrofitting this is
   painful — decide it on day one.*
2. **Stateless auth-server pods.** All state in Postgres/Valkey → horizontal
   scaling and rolling restarts for free.
3. **Argon2id is deliberately expensive.** At high login rates it is the
   bottleneck. Tune parameters against measured hardware; consider a dedicated
   node pool for login. Budget this in the k6 tests.
4. **Postgres**: PgBouncer (transaction pooling), read replicas for audit
   queries, partition `audit_events` by month.
5. **Valkey** for rate limiting and OTP so hot paths avoid Postgres.
6. **Graceful degradation**: if mail is down, fail the MFA send with a clear
   error — never fall back to skipping MFA.
7. **Resilience**: PodDisruptionBudgets, anti-affinity across nodes,
   liveness/readiness probes, HPA on CPU + request rate.

**Load test scenario (k6)**: ramp to target logins/sec, 90 % returning users
hitting SSO (no password), 10 % full password+OTP. Record p95 latency and error
rate. Put the graph in the README — it is the evidence for the *montée en charge*
requirement.

---

## 12. Kubernetes

The client provides the cluster. Ship a **Helm chart** in `k8s/`.

- `Deployment` for `auth-server` (≥3 replicas), both frontends, mock services
- `Secret` for DB creds, key-encryption key, SMTP creds — **[À VALIDER]** whether
  the client mandates an external secret manager (Vault / Sealed Secrets)
- `ConfigMap` for issuer URL, token TTLs
- `Ingress` with cert-manager TLS. **Keep annotations and `ingressClassName`
  configurable in `values.yaml`** — the cluster is the client's, so use whichever
  controller it already runs (`ingress-nginx` is the most common). Caddy is our
  dev-only edge and does not ship to the cluster. **[À VALIDER — client]**
- `HorizontalPodAutoscaler`, `PodDisruptionBudget`
- `CronJob` for key rotation and expired-token cleanup
- `NetworkPolicy`: only `auth-server` may reach Postgres

*Multi-site / plusieurs centres*: **[À VALIDER]** — active/active across sites
requires either a globally replicated Postgres or a primary/standby with
documented failover. Signing keys must be shared across sites, or every site
publishes its own `kid` in a common JWKS. Decide before writing manifests.

---

## 13. OpenID Foundation conformance testing

The OIDF conformance suite is an open source project run by the OpenID
Foundation, hosted at <https://gitlab.com/openid/conformance-suite/>. Using it to
test a deployment costs nothing — a fee applies only to formal certification. It
installs locally inside Docker, and ships `scripts/run-test-plan.py` for driving
it from CI, which the Foundation explicitly recommends authorization-server
developers integrate into their pipeline.

> Note: the older `openid-certification/oidctest` repo is **deprecated** — its
> README states the suite has migrated. Use the GitLab project.

### Setup

1. Clone `https://gitlab.com/openid/conformance-suite/` next to our repo.
2. Build and run it via its own `docker-compose-localtest.yml` (it needs MongoDB
   + a Java server + an httpd front). Follow the *Build & Run* wiki page.
3. Join it to our Docker network, or expose `auth-server` on a hostname the suite
   can resolve. Add `/etc/hosts` entries so the issuer URL is identical inside
   and outside containers — **issuer mismatch is the most common setup failure.**
4. Register a test client in our `clients` table with the suite's redirect URIs.
5. Run the **`oidcc-basic-certification-test-plan`** first, then the config plan.

### Practical notes

- The suite requires **HTTPS** and an exact `issuer` match with what Discovery
  returns. Caddy's `tls internal` already issues the certificate; export its root
  CA and add it to the suite's Java truststore:

  ```bash
  docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
  # then import caddy-root.crt into the conformance suite's cacerts
  ```

  No mkcert needed — the CA Caddy generates on first boot is the one to trust.
- It tests things easy to get wrong: `nonce` echo, `at_hash`, `sub` stability,
  error codes, `state` round-trip, unsupported-parameter handling.
- Expect many failures on the first run. That is the point — **each failure is a
  concrete spec bug**, and the fix log is excellent evidence for the client
  review.
- Wire `scripts/run-test-plan.py` into CI once the basic plan passes, so
  regressions surface immediately.
- Export results to `docs/conformance-results/` after each milestone.

Passing Basic OP is a far stronger claim than "we tested the login button", and
costs nothing.

---

## 14. Testing strategy

| Level | Tool | Covers |
| --- | --- | --- |
| Unit | Vitest | PKCE verify, scope intersection, token TTLs, OTP compare |
| Integration | Supertest + testcontainers | Full grant flows against real Postgres |
| Conformance | OIDF suite | Spec correctness (§13) |
| E2E | Playwright | Login → MFA → portal → service access → logout |
| Security | Custom test suite | See below |
| Load | k6 | *Pics fiscaux* |

**Security regression tests — write these as assertions, not as a checklist:**

- redirect_uri mismatch → rejected, no redirect issued
- authorization code replay → both tokens revoked
- refresh token reuse → whole family revoked
- `alg: none` token → rejected
- HS256 token signed with the RSA public key → rejected
- expired / wrong-`aud` / wrong-`iss` token → rejected at Resource Server
- under-scoped token → 403 at mock service
- account enumeration: identical responses & timing for known vs unknown user
- OTP brute force → locked after N attempts
- password spray → per-IP limit trips

---

## 15. Security checklist

- [ ] Argon2id for passwords and client secrets (never SHA-*, never bcrypt-only)
- [ ] Every code / refresh token / OTP / reset token stored **hashed**
- [ ] RS256 with asymmetric keys; algorithm **pinned** on verify
- [ ] Exact redirect_uri matching, no wildcards
- [ ] PKCE S256 mandatory, all client types
- [ ] Codes: 60 s, single use, atomically consumed
- [ ] Refresh rotation + reuse detection
- [ ] `sub` is an opaque UUID; numéro fiscal never in a JWT, URL, or log
- [ ] Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-` prefix
- [ ] Rate limits on `/token`, login, OTP, reset — per IP **and** per account
- [ ] Account lockout with backoff (and admin unlock path)
- [ ] Strict CSP on both frontends; no inline scripts
- [ ] CORS allow-list, not `*`
- [ ] Audit log append-only at DB privilege level
- [ ] Secrets from env/secret manager, never committed
- [ ] Dependency scanning in CI (`npm audit`, Dependabot/Renovate)
- [ ] Threat model written up in `docs/threat-model.md`

---

## 16. Roadmap

Each session ends with something demonstrable.

| # | Goal | Deliverable |
| --- | --- | --- |
| 1 | Decisions + scaffolding | Repo, compose stack up, Prisma schema v1, ADRs |
| 2 | Identity core | Seeded users, activation flow, login, sessions, Argon2id |
| 3 | OIDC skeleton | Discovery, JWKS, `/authorize` + `/token` with PKCE, one test client |
| 4 | Clients & consent | Client registry, consent screen, `/userinfo` |
| 5 | Token lifecycle | Refresh rotation + reuse detection, revoke, introspect |
| 6 | MFA | Email OTP stage, Mailpit, `acr`/`amr` claims |
| 7 | Authorization | Roles → scopes, 2 mock Resource Servers enforcing scopes |
| 7b | Annuaire | OpenLDAP fixture seeded, read-only `UserDirectory` adapter, sync job (§5b) |
| 8 | Conformance | OIDF Basic OP plan running; fix the failures |
| 9 | Traçabilité | Audit log, `/me/sessions`, device management UI |
| 10 | Portal | Page d'accueil, role-filtered tiles, admin CRUD screens |
| 11 | Scale | Key rotation job, rate limiting, k6 results, Helm chart |
| 12 | Hardening & review | Security tests green, README fonctionnalités, client demo |

**Milestone rule:** do not start session *n+1* until session *n*'s tests pass.
Auth code that "mostly works" is the failure mode this project exists to avoid.

---

## 17. Questions for the client

Collect answers at the next *point client* — these are blocking:

1. **20M simultaneous** — concurrent sessions, or users over the period? Peak
   authentications/second? (§11)
2. **Mail** — internal SMTP relay or third-party provider?
3. **Numéro fiscal** — required storage protection? Encrypted at rest? Is
   pseudonymisation acceptable/expected?
4. **Multi-site** — active/active or active/passive? Acceptable RTO/RPO?
5. **LDAP — credential ownership.** *Highest priority.* We assume the directory
   is read-only and supplies attributes only, with passwords held by us (§5b).
   Confirm the client does not expect delegated `bind`. If they do, password
   reset leaves our scope and §6/§9 need rework.
6. **LDAP — schema.** Anonymised LDIF for one entry, base DN, search filter,
   which attribute carries the numéro fiscal, group→role mapping, `entryUUID`
   availability, directory size and change rate, LDAPS endpoint + CA. Full list
   at the end of §5b. Blocking for session 7b.
7. **Password policy** — ANSSI recommendations? Rotation? History?
8. **Session lifetime** — idle timeout and absolute max, per role?
9. **Audit retention** — how long, and does it need to be exportable/immutable
   for compliance?
10. **MFA for admins** — is email OTP acceptable, or is a stronger factor required
   for accounts with user-CRUD rights?
11. **Secrets** — does the provided cluster mandate Vault or similar?
12. **Ingress controller** — which one is installed in the provided cluster
    (`ingress-nginx`, Traefik, HAProxy, a cloud LB)? Five-second question that
    decides our Helm `Ingress` annotations. Also: is cert-manager available, or
    are certificates provisioned externally?

---

## 18. Definition of done

The project is complete when:

- OIDF Basic OP + Config OP conformance plans pass, results exported to `docs/`
- All security regression tests in §14 pass
- A user can: activate → login with MFA → SSO into 2+ services → view and revoke
  a device session → reset their password
- An admin can CRUD users and read a filtered audit trail
- Every access decision is enforced **server-side at the Resource Server**, not
  only in the UI
- The whole stack comes up with `docker compose up` and deploys with `helm install`
- k6 results and their interpretation are in the README
- `README.md` documents every feature, with the §17 answers folded in
