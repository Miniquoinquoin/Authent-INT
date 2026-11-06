#!/usr/bin/env bash
# Run once per namespace, before `kubectl apply -k k8s`. Generates:
#   - authentint-secrets: database passwords and URLs, KEY_ENCRYPTION_KEY, NUMERO_FISCAL_KEY
#   - authentint-tls + authentint-ca: a small private CA and the Ingress certificate (cert-manager is not ours to use)
#   - ghcr-pull: lets the cluster pull the private images, with a token that has ONLY read:packages (never kept locally)
# Refuses to overwrite: new keys would make every signing key unreadable and every login fail.
# Local copies stay in k8s/secrets/ (gitignored). Lose NUMERO_FISCAL_KEY and users must be re-imported.
#
#   DOMAIN=<domain> KUBECTL="kubectl --insecure-skip-tls-verify" ./k8s/create-secrets.sh
#
# Prompts for the token unless GHCR_TOKEN is set. DOMAIN is kept in k8s/secrets/domain, for the deploy command.
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
NS=${NS:-n-grp7}
DOMAIN=${DOMAIN:?set DOMAIN: the Ingress serves auth.DOMAIN and app.DOMAIN}
GHCR_USER=${GHCR_USER:-ma115tte}
DIR=$(cd "$(dirname "$0")" && pwd)/secrets

if $KUBECTL get secret authentint-secrets -n "$NS" >/dev/null 2>&1; then
  echo "authentint-secrets already exists in $NS: nothing done." >&2
  exit 1
fi
if [ -e "$DIR/secrets.env" ]; then
  echo "$DIR/secrets.env exists but the cluster has no Secret: restore it by hand rather than generating new keys." >&2
  exit 1
fi

if [ -z "${GHCR_TOKEN:-}" ]; then
  read -rsp "GitHub token with only read:packages: " GHCR_TOKEN
  echo
fi

umask 077
mkdir -p "$DIR"
printf '%s\n' "$DOMAIN" > "$DIR/domain"

# Hex only: these go into a URL unescaped
POSTGRES_PASSWORD=$(openssl rand -hex 32)
APP_DB_PASSWORD=$(openssl rand -hex 32)
cat > "$DIR/secrets.env" <<ENV
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
APP_DB_PASSWORD=$APP_DB_PASSWORD
DATABASE_URL_OWNER=postgresql+asyncpg://authentint_owner:$POSTGRES_PASSWORD@postgres:5432/authentint
DATABASE_URL_APP=postgresql+asyncpg://authentint_app:$APP_DB_PASSWORD@postgres:5432/authentint
KEY_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
NUMERO_FISCAL_KEY=$(openssl rand -hex 32)
ENV

openssl ecparam -name prime256v1 -genkey -noout -out "$DIR/root.key" 2>/dev/null
# keyUsage is required: Python 3.13 verifies strictly, and the mocks reject a CA without it
openssl req -x509 -new -key "$DIR/root.key" -sha256 -days 1825 -subj "/CN=Authent'INT private CA" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" -out "$DIR/root.crt"
openssl ecparam -name prime256v1 -genkey -noout -out "$DIR/tls.key" 2>/dev/null
openssl req -new -key "$DIR/tls.key" -subj "/CN=auth.$DOMAIN" -out "$DIR/tls.csr"
cat > "$DIR/tls.ext" <<EXT
subjectAltName=DNS:auth.$DOMAIN,DNS:app.$DOMAIN
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
EXT
openssl x509 -req -in "$DIR/tls.csr" -CA "$DIR/root.crt" -CAkey "$DIR/root.key" -CAcreateserial -sha256 -days 365 \
  -extfile "$DIR/tls.ext" -out "$DIR/tls.crt" 2>/dev/null

$KUBECTL create secret generic authentint-secrets -n "$NS" --from-env-file="$DIR/secrets.env"
$KUBECTL create secret tls authentint-tls -n "$NS" --cert="$DIR/tls.crt" --key="$DIR/tls.key"
$KUBECTL create configmap authentint-ca -n "$NS" --from-file=root.crt="$DIR/root.crt"

# Through stdin: a token on the command line would show up in `ps`
AUTH=$(printf '%s:%s' "$GHCR_USER" "$GHCR_TOKEN" | base64 | tr -d '\n')
DOCKERCONFIG=$(printf '{"auths":{"ghcr.io":{"auth":"%s"}}}' "$AUTH" | base64 | tr -d '\n')
$KUBECTL apply -n "$NS" -f - <<SECRET
apiVersion: v1
kind: Secret
metadata:
  name: ghcr-pull
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: $DOCKERCONFIG
SECRET
