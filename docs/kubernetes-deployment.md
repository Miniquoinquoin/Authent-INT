# Kubernetes deployment

How Authent'INT was deployed to namespace `n-grp7`, step by step, with what went wrong along the way.

`<domain>` stands for the real domain, which stays out of this public repository. The committed manifests use the
placeholder `authentint.example`, and the real value is kept in the gitignored `k8s/secrets/domain`.

## What runs

| Component | Kind | Notes |
|---|---|---|
| `postgres` | StatefulSet, 1 GiB PVC | Headless Service |
| `auth-server` | Deployment, 2 to 4 replicas (HPA) | Migrates in an `initContainer`, runs non-root |
| `frontend` | Deployment, 2 replicas | Stock nginx image, runs as root |
| `svc-impots`, `svc-cadastre` | Deployments, 1 to 4 replicas (HPA) | Trust our private CA through `CA_BUNDLE` |
| `auth`, `app`, `app-api` | Ingresses | The routes of `caddy/Caddyfile` |

Caddy doesn't run on the cluster: the cluster's Ingress controller replaces it.

## Differences from ADR 0002 §14

| ADR | Deployed | Why |
|---|---|---|
| Helm chart | Plain YAML and Kustomize | Enough for one namespace; a chart can come later |
| At least 3 `auth-server` replicas | 2 to 4 | Keeps the namespace's usage low when idle |
| PodDisruptionBudget | None | This account can't create them |
| Migration Job | `initContainer` | This account can't create Jobs |
| NetworkPolicy on Postgres | None | This account can't create NetworkPolicies |
| cert-manager | A private CA of our own | This account can't create Issuers or Certificates |

## Steps

Until the cluster's API certificate is fixed, every `kubectl` call needs `--insecure-skip-tls-verify`. It's left out
below for readability. See [Known limits](#known-limits) for what it risks.

### 1. Check what the namespace allows

```sh
kubectl auth can-i create deployments -n n-grp7
kubectl get nodes -L kubernetes.io/arch
```

All nodes are `amd64`. Deployments, StatefulSets, Services, Ingresses, Secrets, ConfigMaps, PVCs and `pods/exec` are
allowed. Jobs, NetworkPolicies, Issuers and Certificates are not. Listing events, quotas, storage classes and ingress
classes is also forbidden.

### 2. Choose a domain

The cluster has no wildcard DNS, so `<domain>` is `<ingress-ip>.nip.io`, which resolves to that IP with no DNS setup.
That gives `auth.<domain>` (the issuer) and `app.<domain>` (the portal and `/api/impots`, `/api/cadastre`).

### 3. Build and push private images

```sh
TAG=$(git rev-parse --short origin/main)
R=ghcr.io/ma115tte/authent-int
D=<domain>
docker buildx build --platform linux/amd64 --target runtime -t $R-auth-server:$TAG --push apps/auth-server
docker buildx build --platform linux/amd64 --target runtime -t $R-mock-services:$TAG --push apps/mock-services
docker buildx build --platform linux/amd64 -t $R-frontend:$TAG --push \
  --build-arg VITE_AUTH_URL=https://auth.$D \
  --build-arg VITE_IMPOTS_URL=https://app.$D/api/impots \
  --build-arg VITE_CADASTRE_URL=https://app.$D/api/cadastre \
  apps/frontend
```

The frontend bakes its URLs in at build time, so the images stay private and a new domain means rebuilding it. Update
the tags in `k8s/kustomization.yaml` after a new build.

### 4. Create the Secrets

Create a GitHub token with **only** `read:packages`, then run this once:

```sh
DOMAIN=<domain> KUBECTL="kubectl --insecure-skip-tls-verify" ./k8s/create-secrets.sh
```

It prompts for the token and creates:

- `authentint-secrets`: database passwords and URLs, `KEY_ENCRYPTION_KEY`, `NUMERO_FISCAL_KEY`
- `authentint-tls` and `authentint-ca`: a private CA, and the certificate it signs for both hostnames
- `ghcr-pull`: credentials for pulling the images

Local copies go in `k8s/secrets/` (gitignored, mode 600), except the token, which isn't kept. **Back that directory up
somewhere safe.** Without `NUMERO_FISCAL_KEY`, users must be re-imported, and without `KEY_ENCRYPTION_KEY`, the stored
signing keys can't be read. The script refuses to run twice, so these can't be overwritten by accident.

The private CA exists because the mock services download the JWKS over TLS and deliberately can't turn verification
off, so the controller's fake default certificate would make them reject every token.

### 5. Deploy

```sh
kubectl kustomize k8s | sed "s/authentint\.example/$(cat k8s/secrets/domain)/g" | kubectl apply -f -
```

The first `auth-server` pod may restart its `initContainer` a few times while Postgres starts (see
[Troubleshooting](#troubleshooting)).

### 6. Create the client and example users

```sh
kubectl exec deploy/auth-server -c auth-server -n n-grp7 -- python -m scripts.bootstrap scripts/example_users.json
```

Expected output: `client portail-web ready, 3 directory user(s) processed`. Leave the file argument out to create only
the client. The example accounts start as `pending_activation`, with no password.

### 7. Activate an account

1. Open `https://auth.<domain>/health/live` and `https://app.<domain>/` and accept the certificate warning on each.
2. On `https://app.<domain>/activation`, submit `1900000000001` (admin), `1900000000002` (agent) or `1900000000003`
   (contribuable).
3. Read the link from the logs, because there's no real mailer yet:
   ```sh
   kubectl logs deploy/auth-server -c auth-server -n n-grp7 | grep -A1 "mail to=" | tail -2
   ```
4. Open the link, choose a password of at least 12 characters, and log in from the portal.

## Scaling

| Part | How it scales | Limit |
|---|---|---|
| `auth-server` | HPA: 2 to 4 pods at 70% of a 500m CPU request | Login is CPU-bound: about 6 logins/s per core, measured on an M1 (`docs/load-report.md`) |
| `svc-impots`, `svc-cadastre` | HPA: 1 to 4 pods at 70% of a 100m CPU request | Tokens are checked locally, with no database call. With 1 pod, losing it interrupts that service until it's replaced |
| `frontend` | Fixed at 2 pods | Static files |
| Postgres | Doesn't scale | A single point of failure, though under 10% CPU in the load test |

Watch it with:

```sh
kubectl get hpa -n n-grp7
kubectl get pods -n n-grp7
```

`auth-server` `<unknown>` under `TARGETS` is normal for about a minute after its pods restart.

**This has not been load-tested on the cluster.** The HPAs read real CPU values and report `ScalingActive`, but no real
load has made them scale up, and the number of users the cluster can carry is unmeasured. A load test would compete with
other groups on this shared cluster, so ask the admin first. It also needs activated test users, which the `runtime`
image can't seed in bulk.

**Rate limits may block users before CPU does:** logins are limited to 10 per minute per IP, so people sharing one public
IP, such as a whole campus, share that limit however many pods are running.

## What was verified

| Check | Result |
|---|---|
| All pods Ready, migrations applied | Yes |
| TLS on both hostnames verifies against our CA | Yes |
| `issuer` in the discovery document equals `https://auth.<domain>` | Yes |
| `/metrics` returns no Prometheus output | Yes (returns the SPA's page, status 200) |
| `/login` and the logo come from the frontend on the `auth` host | Yes |
| `/api/impots` and `/api/cadastre` reach the mocks with the prefix stripped | Yes |
| CORS allows `https://app.<domain>` | Yes |
| The mocks load the JWKS over verified TLS (`/health/ready` is 200) | Yes |
| The activation request writes the link to the logs | Yes |
| `auth-server` sees the real client IP, not the Ingress's | Yes |
| HPAs read CPU metrics (`ScalingActive`) | Yes |
| Deleting one of two `auth-server` pods, polling `/health/ready` | 86 of 86 requests succeeded |
| Rolling restart of `auth-server`, polling `/health/ready` | With an 8 s client timeout, 41 of 41 succeeded, the slowest taking about 5.3 s. With a 5 s timeout, an earlier run lost 2 of 45 |

**Browser test:** activation, login and a service page worked with 1 replica of each service. They haven't been repeated
since scaling up.

**Not verified yet:** `create-secrets.sh` also hasn't run from start to finish with its final `keyUsage` lines: the first run lacked
them, and the certificates were then reissued by hand with the same options.

## Troubleshooting

These were all hit during this deployment, except where marked.

### `x509: certificate signed by unknown authority` from kubectl

The API address presents the Ingress controller's fake certificate, and the kubeconfig has no CA. Only the cluster's
admin can fix it properly. `--insecure-skip-tls-verify` gets past it, at the cost described in
[Known limits](#known-limits).

### Ingress returns 404 with "Kubernetes Ingress Controller Fake Certificate"

The controller is ignoring the Ingress. On this cluster, it only worked with **no `ingressClassName`**: `nginx`,
`rke2-ingress-nginx`, `ingress-nginx`, `public` and `external` all gave a 404, and a server-side dry run accepts any of
them, because classes aren't validated. Your account can't list classes, so test by removing the field. The Ingress
`ADDRESS` column stays empty here even when routing works, so don't rely on it.

### `auth-server` in `Init:CrashLoopBackOff` with `Name or service not known`

A headless Service has no DNS record until its pod is Ready, so the migration fails until Postgres is up. It recovers
without any change, usually within a minute or two. On a fresh database, two pods can also collide on the migration:
migrations are transactional, so the loser should fail and retry (not tested). Check with:

```sh
kubectl logs deploy/auth-server -c migrate -n n-grp7 --tail=20
```

### A mock reports `jwks_unavailable`, with `CA cert does not include key usage extension`

Python 3.13 verifies certificates strictly, and a CA certificate must have a `keyUsage` extension. The script now sets
it. To reissue certificates (also needed when they expire: the server certificate lasts 1 year, the CA 5 years), run
this from `k8s/secrets`:

```sh
openssl req -x509 -new -key root.key -sha256 -days 1825 -subj "/CN=Authent'INT private CA" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" -out root.crt
openssl x509 -req -in tls.csr -CA root.crt -CAkey root.key -CAcreateserial -sha256 -days 365 -extfile tls.ext -out tls.crt
kubectl create secret tls authentint-tls -n n-grp7 --cert=tls.crt --key=tls.key --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap authentint-ca -n n-grp7 --from-file=root.crt=root.crt --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/svc-impots deployment/svc-cadastre -n n-grp7
```

Restart the mocks, because they read the CA at startup. Browsers will warn again, since the certificate changed.

### A pod crashes with `Field required` from pydantic

A required environment variable is missing, and the error names the setting. This one was `SERVICE_NAME`, misspelled by
the template that first generated `mock-services.yaml`. Compare the Deployment's `env` with the app's `config.py`.

### "Le service est momentanément injoignable" in the browser

The browser refused a `fetch()` to `auth.<domain>`, because its certificate warning hasn't been accepted. Open
`https://auth.<domain>/health/live` once and accept it.

### No `mail to=` line after submitting the form

The page answers the same way whether or not the account exists. Check the number, and check that the account is still
`pending_activation`. The form also allows 5 requests per IP every 15 minutes.

### `ImagePullBackOff` (not hit yet, but expected once the token expires)

The token in `ghcr-pull` has probably expired. Running pods keep working, but a pod moved to a node without the image
can't start. Create a new `read:packages` token, then replace the Secret. Reading the token with `read -s` keeps it out
of your shell history:

```sh
read -rs GHCR_TOKEN
AUTH=$(printf 'ma115tte:%s' "$GHCR_TOKEN" | base64 | tr -d '\n')
printf '{"auths":{"ghcr.io":{"auth":"%s"}}}' "$AUTH" > /tmp/ghcr.json
kubectl create secret generic ghcr-pull -n n-grp7 --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson=/tmp/ghcr.json --dry-run=client -o yaml | kubectl apply -f -
rm /tmp/ghcr.json
```

### Requests stall for about 5 seconds during a rollout

Some requests took about 5.3 s while `auth-server` pods were replaced, against 0.2 s normally. They most likely hit a pod
that had just gone, until nginx's 5-second connect timeout moved them to the next one. That's inferred from the timing:
the controller's logs aren't visible to this account. A client with a timeout of 5 s or less sees these as failures. A
`preStop` sleep on the pods would be the usual way to reduce this; it isn't configured.

### `Forbidden` on events or on listing Jobs

This account can't see them, so `kubectl get all` prints some `Forbidden` lines even when everything is fine. Use
`kubectl logs` and `kubectl describe pod` instead.

## Known limits

- **The API token travels unverified:** with `--insecure-skip-tls-verify`, your kubeconfig token goes to a server
  kubectl can't authenticate, so someone intercepting the connection could steal it.
- **No NetworkPolicy:** other pods on the cluster may be able to reach Postgres and `auth-server` directly. The generated
  passwords are strong, but the admin should add the policy from `docs/architecture.md` §12.
- **Client IP spoofing:** `FORWARDED_ALLOW_IPS` is the whole pod range, because the controller's own IP isn't visible to
  this account. Any pod in it could fake its client IP and get around per-IP rate limiting.
- **Activation links are in the pod logs:** anyone who can read those logs can activate the example admin. Remove the
  example accounts when you've finished with them (their `external_id` starts with `example-`).
- **Brief stalls during rollouts:** see [Troubleshooting](#troubleshooting).
- **Self-signed certificate:** browsers warn once per hostname until the admin provides a cert-manager issuer.
- **`/metrics` returns 200 with the SPA's page,** rather than a 404. It reveals nothing, but a scanner will see a 200.
- **The address isn't secret:** it stays out of this repo and the registry, but visitors can read it in the served
  JavaScript, and it's part of the nip.io hostnames.
