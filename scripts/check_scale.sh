#!/usr/bin/env bash
# ADR §15 "le test multi-réplicas": everything that only works at --scale 1 is a Kubernetes bug
# found early. Recreates auth-server as 3 replicas at once (they all run ensure_active_key at boot,
# under the advisory lock, ADR §12), then checks:
#   1. exactly one `active` and one `next` signing key (no replica generated its own)
#   2. /health/ready answers 200 on every replica
#   3. tokens issued through Caddy (whichever replica answered) verify on EVERY replica
# Needs the seeded dev users (`make seed`). Leaves the stack at 3 replicas: `make scale1` after.
# Usage: make scale3-check
set -euo pipefail

AUTH=https://auth.authentint.localhost
NF=1804234567894            # a seeded contribuable (make seed)
PASSWORD='Authentint-dev-1!' # DEV ONLY: scripts/seed.py
REDIRECT=https://app.authentint.localhost/callback
VERIFIER=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk   # RFC 7636 appendix B
CHALLENGE=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM
AUTHZ="$AUTH/authorize?response_type=code&client_id=portail-web&redirect_uri=$REDIRECT&scope=openid%20svc:impots.read&state=s&nonce=n&code_challenge=$CHALLENGE&code_challenge_method=S256"

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "== 3 replicas, recreated together"
docker compose up -d --wait --scale auth-server=3 --force-recreate --no-deps auth-server >/dev/null
replicas=$(docker compose ps -q auth-server)
[ "$(echo "$replicas" | wc -l | tr -d ' ')" = 3 ] || fail "expected 3 auth-server replicas"

echo "== 1. signing keys"
keys=$(docker compose exec -T postgres psql -U authentint_owner authentint -tAc \
  "SELECT status, count(*) FROM signing_keys WHERE status IN ('active', 'next') GROUP BY status ORDER BY status")
echo "$keys"
[ "$keys" = $'active|1\nnext|1' ] || fail "expected exactly one active and one next key"

echo "== 2. /health/ready on every replica"
for c in $replicas; do
  docker exec "$c" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')" \
    || fail "replica $c not ready"
  echo "$c ready"
done

echo "== 3. tokens issued through Caddy verify on every replica"
jar=$(mktemp); trap 'rm -f "$jar"' EXIT
uid=$(curl -sk -o /dev/null -w '%{redirect_url}' "$AUTHZ" | sed -n 's/.*uid=\([^&]*\).*/\1/p')
[ -n "$uid" ] || fail "/authorize did not ask for a login"
status=$(curl -sk -c "$jar" -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"numero_fiscal\":\"$NF\",\"password\":\"$PASSWORD\"}" "$AUTH/interaction/$uid/login")
[ "$status" = 200 ] || fail "login answered $status (seeded? rate limited? wait a minute)"

for i in 1 2 3 4 5 6; do
  code=$(curl -sk -b "$jar" -o /dev/null -w '%{redirect_url}' "$AUTHZ" | sed -n 's/.*[?&]code=\([^&]*\).*/\1/p')
  [ -n "$code" ] || fail "no code on the SSO path"
  token=$(curl -sk "$AUTH/token" -d grant_type=authorization_code --data-urlencode "code=$code" \
    -d "redirect_uri=$REDIRECT" -d client_id=portail-web -d "code_verifier=$VERIFIER" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')
  for c in $replicas; do
    docker exec "$c" python -c "
import urllib.request
r = urllib.request.Request('http://localhost:8000/userinfo', headers={'Authorization': 'Bearer $token'})
urllib.request.urlopen(r)" || fail "token $i rejected by replica $c"
  done
  echo "token $i: verified by the 3 replicas"
done

echo "OK: --scale auth-server=3 is clean"
