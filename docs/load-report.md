# Load report — B6 (k6)

ADR 0002 §17 B6: "Rapport k6 produit". Measured on 2026-10-14 with `load/k6.js` (`make load`).
Every number below comes from those runs; raw k6 summaries go to `load/results/` (gitignored:
regenerated per run, and they contain the setup session cookie).

## Environment

| | |
|---|---|
| Machine | MacBook Pro, Apple M1 Pro (8 cores), 32 GB, macOS 26.6 |
| Docker | Docker Desktop, engine 24.0.2, **6 vCPU** and 23.4 GB given to the VM |
| Images | runtime targets (`COMPOSE_FILE=docker-compose.yml`: non-root, no `--reload`, no dev deps) |
| auth-server | one uvicorn process per container, `--scale auth-server=1` then `=3` |
| Postgres | 16-alpine, same VM, default settings |
| k6 | `grafana/k6:1.3.0`, in Caddy's network namespace (same VM: k6 shares the 6 vCPU) |
| Data | 400 seeded users (`make seed N=400`) |

Argon2id parameters: time 3, memory 64 MiB, parallelism 1 (`security/passwords.py`).

## Scenarios

Run one after the other (`load/k6.js`), constant arrival rate:

| Scenario | What | Rate | Duration | Path |
|---|---|---|---|---|
| discovery | `/.well-known/openid-configuration` + `/.well-known/jwks.json` | 100 iter/s (200 req/s) | 60 s | through Caddy (TLS) |
| sso | `/authorize` with a valid `__Host-session` cookie → 302 with a code, then `/token` | 30 iter/s (60 req/s) | 60 s | direct to the replicas |
| login_N | `/authorize` without a session → `POST /interaction/{uid}/login` (one Argon2) | 2, 5, 10, 20, 40 logins/s | 45 s each | direct to the replicas |

**Rate limits stay on.** One k6 container is one IP: through Caddy every login and `/token` would
share one per-IP bucket (10 logins/min, 30 `/token`/min). `sso` and `login` therefore talk to the
replicas the way Caddy does, with a distinct `X-Forwarded-For` per iteration (believed because
`FORWARDED_ALLOW_IPS="*"`, safe since auth-server publishes no port). The per-account limit
(10 logins/min) still applies: logins go round-robin over the 400 accounts, so 40 logins/s is
6 logins/min per account. The k6 container resolves `auth-server` round-robin (DNS TTL 1 s), so
at 3 replicas each one gets a third of the traffic (checked with `docker stats`, below).

## Results

Latencies in ms. Requests/s = request count / scenario duration. Error rate = `http_req_failed`.

### `--scale auth-server=1`

| Scenario | Request | req/s | p50 | p95 | p99 | max | errors |
|---|---|---|---|---|---|---|---|
| discovery | discovery + jwks | 200 | 1.8 | 2.7 | 11.6 | 157.0 | 0 % |
| sso | `/authorize` (session) | 30 | 4.4 | 5.6 | 16.2 | 56.9 | 0 % |
| sso | `/token` | 30 | 7.8 | 9.7 | 19.6 | 78.0 | 0 % |
| login_2 | login | 2.0 | 173.5 | 209.5 | 232.7 | 268.1 | 0 % |
| login_5 | login | 5.0 | 160.7 | 177.4 | 210.2 | 214.9 | 0 % |
| login_10 | login | 10.0 | 163.6 | 182.9 | 212.6 | 221.2 | 0 % |
| login_20 | login | 19.9 | 173.3 | 497.4 | 939.0 | 1429.3 | 0 % |
| login_40 | login | **30.5** (40 asked) | 2231.3 | 7219.7 | 10623.2 | 17255.5 | 0 % |

login_40: 435 iterations dropped (k6 hit its 200 VUs), `/authorize` without a session also
climbed to p95 7253 ms there.

### `--scale auth-server=3`

| Scenario | Request | req/s | p50 | p95 | p99 | max | errors |
|---|---|---|---|---|---|---|---|
| discovery | discovery + jwks | 200 | 2.0 | 3.6 | 10.9 | 88.3 | 0 % |
| sso | `/authorize` (session) | 30 | 4.3 | 5.5 | 9.7 | 48.8 | 0 % |
| sso | `/token` | 30 | 7.3 | 9.1 | 16.6 | 73.9 | 0 % |
| login_2 | login | 2.0 | 168.2 | 183.2 | 218.8 | 223.9 | 0 % |
| login_5 | login | 5.0 | 161.7 | 176.6 | 208.8 | 238.6 | 0 % |
| login_10 | login | 10.0 | 162.6 | 176.1 | 206.8 | 221.8 | 0 % |
| login_20 | login | 20.0 | 169.6 | 194.4 | 228.5 | 261.3 | 0 % |
| login_40 | login | **31.7** (40 asked) | 2551.1 | 7316.6 | 10155.2 | 16941.6 | 0 % |

login_40: 375 iterations dropped. Checks: 100 % passed in both runs (21 666 and 21 792).

### CPU (`docker stats`, sampled every ~12 s, % of one vCPU)

| Phase | scale 1: auth-server | scale 3: auth-server (sum of 3) | Postgres |
|---|---|---|---|
| discovery (200 req/s) | 25–55 % (+ Caddy ~20 %) | — | ~3 % |
| login_10 | 160–170 % | — | ~3 % |
| login_20 | 340–370 % | 120 + 102 + 117 ≈ 340 % | 5–9 % |
| login_40 | 510–540 % | ≈ 545–570 %, evenly split | 7–9 % (one 30 % sample) |

About 17–18 % of a vCPU per login/s, i.e. ~175 ms of CPU per login: Argon2.

### Before / after the signing-key cache

Before `keys/keystore.py` cached the decrypted signing key per `kid`, every `/token` decrypted the
key (Fernet) and imported the PEM; `cryptography` validates the RSA key on import, on the event
loop. An earlier run of the same script (scale 1, before the login_20/40 steps were added; run by
a previous session, its setup not re-verified here) measured, for the same 30 iter/s `sso` load:
`/authorize` p50 2937.7 ms / p95 15504.1 ms and `/token` p50 1212.6 ms / p95 13406.8 ms, i.e.
the replica could not keep up: 2516 `sso` requests completed instead of 3600 (1259 codes, 1257 tokens),
and k6 dropped 541 iterations over the run. With the cache: `/authorize`
p95 5.6 ms, `/token` p95 9.7 ms, all 60 req/s served (tables above). This session did not
re-measure the "before" side.

## Interpretation

**Login is CPU-bound by Argon2, as ADR §14.3 expects.** Up to 10 logins/s the login p95 stays
at 175–210 ms (one Argon2 is ~160 ms). At 20/s one replica already queues (p95 497 ms) while three
replicas do not (p95 194 ms). At 40/s neither keeps up: ~31 logins/s is the ceiling, and it is the
same at 1 and 3 replicas because the limit is the Docker VM's 6 vCPU, not the process:
`run_in_executor` already spreads Argon2 over every core from a single replica (530 % CPU at
scale 1). 6 vCPU / ~0.175 s CPU per login ≈ 34 logins/s, minus k6, Caddy and Postgres sharing the
same VM. Replicas add capacity only when they add cores, i.e. on separate nodes.

**ADR §3 Valkey rule: not triggered.** The rule asks for a p95 degradation of `/token` or the
login above 20 % *with `rate_limits` contention as the identified cause*. Postgres stays under
10 % CPU at every step, including 40 logins/s where each login writes two `rate_limits` buckets
(per IP, per account), and `/token` p95 is under 10 ms. Where login p95 degrades (scale 1 at 20/s,
everywhere at 40/s), the cause is Argon2 CPU saturation. Valkey would not help; no Valkey.

**Rate-limit effects.** Zero 429 in both runs, by construction (distinct client IPs, 6 logins/min
per account). The limits did not cost any measurable latency: the `/authorize` without session
step (which does no Argon2) stays at p95 ≤ 6.6 ms until the CPU saturates.

**Discovery/JWKS** is not a concern: 200 req/s through Caddy with TLS at p95 < 4 ms, and resource
servers cache the JWKS anyway (`M/src/mockservices/jwks.py`).

## Next steps

- Ask the client for the peak authentications per second (ADR §14 "[À VALIDER]"): at ~6 logins/s
  per core with these Argon2 parameters, capacity planning is a core count.
- Calibrate Argon2 on the production hardware (ADR §14.3): time 3 / 64 MiB costs ~160 ms here.
- In Kubernetes (out of scope here), set CPU requests per replica so the HPA scales on CPU,
  which is what login load consumes.
- Re-run `make load` after any change to Argon2 parameters, the token path, or the rate limiter.

## How to run

```sh
COMPOSE_FILE=docker-compose.yml docker compose up -d --build --wait  # runtime images (representative)
make seed N=400          # needs the dev stack (DEV=true): seed first, then switch to runtime images
make load LABEL=scale1   # ~6.5 min; summary on stdout, JSON in load/results/
make load-scale3         # scale 3, k6, the multi-replica check, back to scale 1
```

The thresholds in `load/k6.js` were written before the first run; `make load` exits non-zero when
one is crossed (here: login_40 p95 and dropped iterations, the CPU ceiling above).

## Multi-replica check (`make scale3-check`, ADR §15)

`scripts/check_scale.sh` recreates the 3 replicas at once, then checks exactly one `active` and one
`next` signing key, `/health/ready` on every replica, and that 6 tokens issued through Caddy verify
on all 3 replicas (`/userinfo`).

Result in this session: **not passed**. The run on 2026-10-14 stopped at the `--wait` step:
Docker Desktop (engine 24.0.2) recreated one replica attached to `edge` only, without `data`, so it
could not resolve `postgres` (`socket.gaierror`) and stayed unhealthy. The compose file declares
`networks: [edge, data]`; the same flake happened once on a plain `docker compose up`, and a second
`--force-recreate` fixed it. The re-run of the check could not be done in this session. The k6 run
at 3 replicas (above) did exercise tokens across replicas: 1801 codes exchanged with 0 errors,
with requests spread round-robin over the 3.

## Cluster run (namespace `n-grp7`, 2026-11-06)

The same script against the Kubernetes deployment (`docs/kubernetes-deployment.md`), run from a pod inside the namespace
(`load/k8s-pod.yaml`), with 200 temporary accounts (`load/k8s_users.py`). **Rate limits stayed on.** Logins, `/token` and
the service API went straight to the Services, each iteration with its own `X-Forwarded-For`; only discovery went
through the Ingress, because that controller is shared.

| | |
|---|---|
| Cluster | RKE2, 5 nodes, shared with other groups |
| auth-server | HPA 2 to 4 pods at 70% CPU, request 500m. **Effective CPU limit 500m** in the first run, 2 in the second |
| svc-impots | HPA 1 to 4 pods at 70% CPU, request 100m, effective limit 500m |
| k6 | `grafana/k6:1.3.0`, limited to 1 CPU |

### First run: CPU limit 500m

Latencies in ms. Logins are counted as completed out of the number the arrival rate asked for.

| Step | Rate asked | Done | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| discovery (Ingress) | 50 req/s for 60 s | 3,002 req | 3.0 | 5.0 | 7.3 | 0 % |
| sso `/authorize` | 30/s for 60 s | 1,801 | 7.2 | 9.7 | 11.2 | 0 % |
| sso `/token` | 30/s for 60 s | 1,801 | 12.9 | 16.2 | 18.6 | 0 % |
| api (`svc-impots`, real token) | 100/s for 120 s | 12,001 | 0.9 | 2.0 | 2.4 | 0 % |
| login_2 | 90 | 91 | 329.6 | 403.7 | 407.5 | 0 % |
| login_5 | 225 | 200 | 4,553 | 8,606 | 9,612 | 1.7 % |
| login_10 | 450 | 352 | 7,320 | 13,501 | 21,210 | 1.0 % |
| login_20 | 3,600 (180 s) | 1,360 | 14,095 | 31,703 | 35,638 | 8.0 % |

2,203 iterations were dropped because k6 hit its 200 VUs. Almost every error was `connection refused` to `auth-server`
(77 of 78), the other an i/o timeout.

**Autoscaling:** `svc-impots` went from 1 to 2 pods during the api step, at about 105% of its request. `auth-server`
reached 3 pods at 100% during the login steps. After the run, both returned to their minimums.

### Interpretation

**Token, discovery and service API traffic are fine.** No errors, p95 under 20 ms at these rates.

**Login saturates from 5 logins/s, because of a CPU limit nobody declared.** The namespace has a LimitRange that gives
every container without an explicit CPU limit a limit of 500m. `k8s/auth-server.yaml` declared a request but no limit, so
each pod got half a core. Its cgroup showed `cpu.max 50000 100000` and about 26 minutes of throttling. At about 290 ms
of CPU per login here, half a core is about 1.7 logins/s per pod, so even 4 pods top out near 7 logins/s.

**The `connection refused` errors come from readiness.** Throttled pods answered `/health/ready` too slowly for its 1 s
timeout, so Kubernetes marked them not Ready and took them out of the Service. Both pods turned Ready again at 16:54:42
and 16:54:47 UTC, within seconds of the run ending. Nothing restarted.

**Login looked slower than on the M1 (p50 330 ms at 2/s), but that was the throttling too:** 2 logins/s already needs more
than half a core. With the limit fixed, a login takes about 180 ms, close to the M1's 160 ms.

**The cluster was loaded less than expected:** with the 500m limits, `auth-server` could use at most about 2 cores.

### Second run: CPU limit 2, readiness timeout 3 s

`k8s/auth-server.yaml` now declares `limits.cpu: "2"` (a dry run showed the namespace accepts up to at least 4), and both
probes wait 3 s instead of 1 s. Shorter run on 2026-11-08: discovery and sso at 5/s for 10 s, then the login steps.

| Step | Rate asked | Done | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| login_5 | 225 | 225 | 175.3 | 193.0 | 202.4 | 0 % |
| login_10 | 450 | 450 | 181.9 | 209.6 | 227.2 | 0 % |
| login_20 | 1,800 (90 s) | 1,800 | 190.5 | 217.3 | 238.2 | 0 % |

0 dropped iterations and 5,154 of 5,154 checks passed. `auth-server` scaled from 2 to 4 pods (3 at about 40 s into the
10/s step, 4 at the start of 20/s) and held 4 at about 188% of its request, about 0.95 core per pod. No pod left the
Service: each turned Ready once, when it started.

**What it means:** 20 logins/s cost about 3.8 cores across 4 pods, with p95 latency close to a single Argon2. The HPA is at
its maximum of 4 there, but each pod could still use up to 2 cores, so the ceiling is higher. A rough estimate, not
measured, is around 40 logins/s, if the nodes have that much free CPU.

### Gaps in the first run

- **The safety stop didn't fire:** k6 aborts when more than 5% of *all* requests fail, and the api step's 12,000
  successes diluted the login errors below that. The restart monitor didn't trigger either, because nothing restarted.
  Neither was needed in the end, but neither would have caught this kind of failure.
- **The Kubernetes API stopped answering the monitor** between about 16:48 and 16:52 UTC, the login steps, so the replica
  timeline has a hole there. The cause wasn't visible to this account.
- **Not measured:** the effect on other groups' workloads, and the real ceiling with the CPU limit fixed.

### How to run it

```sh
D=$(cat k8s/secrets/domain); PW=$(openssl rand -hex 24)
{ echo "ACTION='create'; PASSWORD='$PW'"; cat load/k8s_users.py; } | kubectl exec -i deploy/auth-server -c auth-server -n n-grp7 -- python -
python3 -c 'import json; print(json.dumps([{"numero_fiscal": str(1910000000000+i)} for i in range(200)]))' > /tmp/users.json
kubectl create secret generic loadtest -n n-grp7 --from-literal=PASSWORD="$PW"
kubectl create configmap loadtest -n n-grp7 --from-file=k6.js=load/k6.js --from-file=users.json=/tmp/users.json
sed "s/authentint\.example/$D/g" load/k8s-pod.yaml | kubectl apply -n n-grp7 -f -
kubectl logs -f loadtest -n n-grp7

# Afterwards
{ echo "ACTION='disable'"; cat load/k8s_users.py; } | kubectl exec -i deploy/auth-server -c auth-server -n n-grp7 -- python -
kubectl delete pod/loadtest configmap/loadtest secret/loadtest -n n-grp7
```

`--from-literal` puts the password on your command line; it's a throwaway one, disabled with the accounts.
