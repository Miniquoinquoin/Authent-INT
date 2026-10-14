// k6 load test of the auth-server (B6, ADR §14 "Montée en charge", §3 Valkey rule).
// Run with `make load` (docs/load-report.md): the k6 container shares Caddy's network namespace,
// so it reaches both https://auth.authentint.localhost (Caddy) and http://auth-server:8000.
//
// Three scenarios, one after the other:
//   discovery  discovery + JWKS through Caddy: what every resource server does (cached by them)
//   sso        /authorize with a valid __Host-session cookie (the SSO path) + /token for the code
//   login      /authorize without a session + POST /interaction/{uid}/login: one Argon2 per login
//
// Rate limits are NOT disabled anywhere. Real traffic comes from many IPs; one k6 container is one
// IP, so through Caddy every login would share one per-IP bucket (10/min). `sso` and `login` therefore
// talk to the replicas directly, the way Caddy does (FORWARDED_ALLOW_IPS="*" in docker-compose.yml),
// with a distinct X-Forwarded-For per iteration. The per-account limit (10/min) still applies:
// `login` spreads over USERS seeded accounts (`make seed N=400`): at 40 logins/s that is 6/min per account.
// k6 resolves auth-server round-robin: with --scale auth-server=3 every replica gets its share.

import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { SharedArray } from 'k6/data';

const EDGE = 'https://auth.authentint.localhost';
const DIRECT = 'http://auth-server:8000';
const PASSWORD = 'Authentint-dev-1!'; // DEV ONLY: scripts/seed.py
const N_USERS = Number(__ENV.USERS || 400);
const USERS = new SharedArray('users', () =>
  JSON.parse(open('/fixtures/users.json')).slice(0, N_USERS).map((u) => u.numero_fiscal));

// RFC 7636 appendix B: a fixed verifier/challenge pair is fine, each code is still single-use
const VERIFIER = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
const REDIRECT_URI = 'https://app.authentint.localhost/callback';
const AUTHORIZE = `${DIRECT}/authorize?` + [
  'response_type=code', 'client_id=portail-web', `redirect_uri=${encodeURIComponent(REDIRECT_URI)}`,
  `scope=${encodeURIComponent('openid svc:impots.read')}`, 'state=k6-state', 'nonce=k6-nonce',
  'code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM', 'code_challenge_method=S256',
].join('&');

const D = __ENV.DURATION || '60s';

// One login scenario per rate: k6 then reports each rate's latency on its own
function loginStep(rate, ipPrefix, startTime) {
  return { [`login_${rate}`]: { executor: 'constant-arrival-rate', exec: 'login', rate, timeUnit: '1s', duration: '45s',
                                preAllocatedVUs: 20, maxVUs: 200, startTime, env: { IP_PREFIX: String(ipPrefix) } } };
}

export const options = {
  insecureSkipTLSVerify: true, // Caddy's internal CA (dev); the TLS handshake itself is still measured
  dns: { ttl: '1s', select: 'roundRobin', policy: 'preferIPv4' },
  discardResponseBodies: false,
  scenarios: {
    discovery: { executor: 'constant-arrival-rate', exec: 'discovery', rate: Number(__ENV.DISCOVERY_RATE || 100),
                 timeUnit: '1s', duration: D, preAllocatedVUs: 50, maxVUs: 200, startTime: '0s' },
    sso: { executor: 'constant-arrival-rate', exec: 'sso', rate: Number(__ENV.SSO_RATE || 30),
           timeUnit: '1s', duration: D, preAllocatedVUs: 50, maxVUs: 200, startTime: '65s' },
    // Argon2 is the login's cost by design (ADR §14.3): three steps to see where latency starts to climb
    ...loginStep(2, 4, '130s'), ...loginStep(5, 5, '180s'), ...loginStep(10, 6, '230s'),
    ...loginStep(20, 7, '280s'), ...loginStep(40, 8, '330s'),
  },
  // ms. Written before the first run; see docs/load-report.md for why these values
  thresholds: {
    'http_req_failed{scenario:discovery}': ['rate<0.01'],
    'http_req_duration{scenario:discovery}': ['p(95)<100'],
    'http_req_failed{scenario:sso}': ['rate<0.01'],
    'http_req_duration{scenario:sso,name:authorize}': ['p(95)<250'],
    'http_req_duration{scenario:sso,name:token}': ['p(95)<250'],
    ...Object.fromEntries([2, 5, 10, 20, 40].flatMap((r) => [
      [`http_req_failed{scenario:login_${r}}`, ['rate<0.01']],
      [`http_req_duration{scenario:login_${r},name:login}`, ['p(95)<1000']],
      [`http_req_duration{scenario:login_${r},name:authorize_no_session}`, ['max>=0']], // reported, not judged
      [`http_reqs{scenario:login_${r}}`, ['count>0']],
    ])),
    'http_reqs{scenario:discovery}': ['count>0'], // per-scenario request counts in the summary
    'http_reqs{scenario:sso}': ['count>0'],
    'dropped_iterations': ['count<1'], // k6 could not keep the arrival rate: the system (or k6) saturated
    'checks': ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
};

// One distinct client IP per iteration, per scenario: 10.<scenario>.x.y
function clientIp(prefix) {
  const n = exec.scenario.iterationInTest;
  return `10.${prefix}.${(n >> 8) & 255}.${n & 255}`;
}

function uidOf(res) {
  const m = /uid=([^&]+)/.exec(res.headers.Location || '');
  return m ? m[1] : null;
}

// The SSO scenario's session: one real login, before the scenarios start
export function setup() {
  const headers = { 'X-Forwarded-For': '10.0.0.1' };
  const uid = uidOf(http.get(AUTHORIZE, { redirects: 0, headers }));
  const res = http.post(`${DIRECT}/interaction/${uid}/login`, JSON.stringify({ numero_fiscal: USERS[3], password: PASSWORD }),
                        { headers: { ...headers, 'Content-Type': 'application/json' } });
  const cookie = res.cookies['__Host-session'];
  if (res.status !== 200 || !cookie) {
    throw new Error(`setup login failed (${res.status}): run \`make seed N=${N_USERS}\` first`);
  }
  return { session: cookie[0].value };
}

export function discovery() {
  const conf = http.get(`${EDGE}/.well-known/openid-configuration`, { tags: { name: 'discovery' } });
  const jwks = http.get(`${EDGE}/.well-known/jwks.json`, { tags: { name: 'jwks' } });
  check(conf, { 'discovery 200': (r) => r.status === 200 });
  check(jwks, { 'jwks has keys': (r) => r.status === 200 && r.json('keys').length >= 2 });
}

export function sso(data) {
  const headers = { 'X-Forwarded-For': clientIp(1) };
  const res = http.get(AUTHORIZE, { redirects: 0, tags: { name: 'authorize' },
                                    headers: { ...headers, Cookie: `__Host-session=${data.session}` } });
  const code = (/[?&]code=([^&]+)/.exec(res.headers.Location || '') || [])[1];
  if (!check(res, { 'authorize issues a code': () => res.status === 302 && !!code })) return;
  const tok = http.post(`${DIRECT}/token`, { grant_type: 'authorization_code', code: decodeURIComponent(code),
                                             redirect_uri: REDIRECT_URI, client_id: 'portail-web', code_verifier: VERIFIER },
                        { headers, tags: { name: 'token' } });
  check(tok, { 'token 200': (r) => r.status === 200 && !!r.json('access_token') });
}

export function login() {
  const headers = { 'X-Forwarded-For': clientIp(__ENV.IP_PREFIX) };
  const uid = uidOf(http.get(AUTHORIZE, { redirects: 0, headers, tags: { name: 'authorize_no_session' } }));
  if (!check(uid, { 'authorize asks for login': (u) => !!u })) return;
  const user = USERS[exec.scenario.iterationInTest % USERS.length]; // round-robin: each account well under 10/min
  const res = http.post(`${DIRECT}/interaction/${uid}/login`, JSON.stringify({ numero_fiscal: user, password: PASSWORD }),
                        { headers: { ...headers, 'Content-Type': 'application/json' }, tags: { name: 'login' } });
  check(res, { 'login 200': (r) => r.status === 200 });
}

export function handleSummary(data) {
  const out = {};
  out[`/results/summary-${__ENV.LABEL || 'run'}.json`] = JSON.stringify(data, null, 2);
  out.stdout = textSummary(data);
  return out;
}

// Compact per-scenario table on stdout (the full data is in the JSON above)
function textSummary(data) {
  const lines = [];
  for (const [name, m] of Object.entries(data.metrics).sort()) {
    if (!/^(http_req_duration|http_req_failed|http_reqs)\{scenario|^(checks|dropped_iterations)$/.test(name)) continue;
    const v = m.values;
    const th = m.thresholds ? Object.entries(m.thresholds).map(([k, r]) => `${k} ${r.ok ? 'ok' : 'FAILED'}`).join(', ') : '';
    const fmt = (x) => (x === undefined ? '-' : Number(x).toFixed(1));
    lines.push(m.type === 'trend'
      ? `${name}  count=${v.count} med=${fmt(v.med)} p95=${fmt(v['p(95)'])} p99=${fmt(v['p(99)'])} max=${fmt(v.max)} ${th}`
      : `${name}  ${JSON.stringify(v)} ${th}`);
  }
  return lines.join('\n') + '\n';
}
