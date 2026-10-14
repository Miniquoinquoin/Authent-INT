# apps/frontend — le SPA (couloir B5)

Un seul build Vite pour deux rôles ([ADR §13](../../docs/adr/0002-stack-simplifiee.md#13-frontend-unique)) :

- les **écrans d'authentification** vers lesquels `auth-server` redirige (login,
  consentement, activation, réinitialisation) ;
- le **portail**, qui est lui-même un client OAuth public de `auth-server`
  (`portail-web`, code + PKCE S256).

React 19 · Vite · TypeScript · react-router. Tests : Vitest + Testing Library +
MSW, Playwright. Lint : oxlint.

## Démarrer

```bash
npm ci
npm run dev:mock      # http://localhost:5173, contre le faux auth-server (MSW), rien d'autre à lancer
```

Identifiants du mode mock ([src/mocks/data.ts](src/mocks/data.ts)) — inventés :

| Numéro fiscal | Mot de passe | Résultat |
| --- | --- | --- |
| `1234567890123` | `Authentint-dev-1!` | Marie Dupont, agent : tuiles Impôts + Cadastre |
| `2345678901234` | `Authentint-dev-1!` | Jean Martin, contribuable : tuile Impôts seule |
| `3456789012345` | `Authentint-dev-1!` | Alice Bernard, admin |
| `0000000000423` | n'importe lequel | 423 compte verrouillé |
| `0000000000429` | n'importe lequel | 429 trop de tentatives |
| autre | autre | 401 identifiants incorrects |

Liens d'e-mail en mock : `/activate?token=lien-de-test-valide`,
`/reset-password?token=lien-de-test-valide` (tout autre jeton = lien expiré).

Contre le vrai auth-server, le SPA doit être servi sur l'origine enregistrée
(`PUBLIC_BASE_URL`, `redirect_uris` du client `portail-web`, CORS) : c'est le
conteneur `frontend` derrière Caddy (`https://app.authentint.local`), pas
`npm run dev` sur `localhost`.

## Écrans et routes

| Route | Écran | Appels |
| --- | --- | --- |
| `/` | Portail. Déconnecté : « Se connecter ». Connecté : nom (ID token), tuiles selon les scopes, « Se déconnecter » | `/authorize`, `/end-session` (B2) |
| `/callback` | Retour de `/authorize` : vérifie `state`, échange le code, vérifie le `nonce` | `POST /token` (B2) |
| `/login?uid=…` | Machine à étapes : affiche le `prompt` que le serveur renvoie (`login`, `consent`, `null` → `redirect_to`) | `GET /interaction/{uid}`, `POST …/login`, `POST …/consent` |
| `/activation` | Demander un lien d'activation | `POST /account/activation/request` |
| `/activate?token=…` | Choisir son premier mot de passe (lien de l'e-mail) | `POST /account/activation/confirm` |
| `/mot-de-passe-oublie` | Demander un lien de réinitialisation | `POST /account/password-reset/request` |
| `/reset-password?token=…` | Choisir un nouveau mot de passe (lien de l'e-mail) | `POST /account/password-reset/confirm` |
| `*` | Page introuvable (ne réaffiche jamais le chemin demandé) | — |

`/login`, `/activate` et `/reset-password` sont imposées par l'auth-server (sa
redirection et ses e-mails) ; `/callback` est le `redirect_uri` enregistré. Le
consentement n'a pas de route à lui : c'est une étape de `/login?uid=`, comme
le décide le serveur. Les écrans admin et « mon compte » (`/admin/*`,
`/account/*`) attendent B4.

## Organisation

```
src/
├── config.ts          URL de l'auth-server (= issuer), client_id, redirect_uri, scopes demandés
├── api/
│   ├── types.ts       GÉNÉRÉ depuis docs/generated/openapi.json (npm run gen:api) — commité
│   ├── client.ts      fetch (credentials: include) → erreurs typées par code
│   ├── interaction.ts · account.ts
├── auth/
│   ├── pkce.ts        verifier, state, nonce, challenge S256
│   ├── oidc.ts        /authorize, /callback, /token, /end-session — le SEUL module qui dépend de B2
│   ├── claims.ts      formes des jetons (miroir de domain/claims.py)
│   └── session.ts     jetons en mémoire
├── pages/             un composant par route ; login/ = la machine à étapes
├── messages.ts        toutes les phrases d'erreur, choisies par code
├── scopes.ts          libellés des scopes en français
└── mocks/             le faux auth-server (MSW)
e2e/                   Playwright
```

## Règles de sécurité appliquées côté front

Ce sont de la **présentation et de la défense en profondeur**. Le serveur
applique les vraies règles ; les Resource Servers vérifient eux-mêmes chaque
jeton et ses scopes.

- **Le serveur décide de l'étape suivante.** L'écran n'affiche que le `prompt`
  reçu ; il ne passe jamais au consentement de lui-même.
- **Numéro fiscal** : jamais dans une URL, un log, ni le Web Storage. Il vit dans
  l'état du composant et part dans le corps JSON du POST. Les champs n'ont pas
  d'attribut `name` et les formulaires sont `method="post"` : même une
  soumission native ne pourrait pas le mettre dans une query string. MSW tourne
  en `quiet` (sinon il loggue les corps de requête).
- **Jetons en mémoire uniquement** (variable de module), jamais
  `localStorage`/`sessionStorage`. Seuls `state`, `nonce` et `code_verifier`
  passent par `sessionStorage`, le temps de l'aller-retour, et sont effacés à la
  première lecture.
- **PKCE S256, `state`, `nonce`** générés par `crypto.getRandomValues`. Le
  `state` est vérifié avant toute autre chose au retour ; l'ID token est vérifié
  (`iss`, `aud`, `exp`, `nonce`). Sa signature n'est pas vérifiée dans le
  navigateur : il vient directement du token endpoint en TLS (OIDC Core
  §3.1.3.7, point 6), et le SPA n'en tire aucune décision d'autorisation.
- **Jetons d'URL effacés** : le `code` de `/callback` et le `token` de
  `/activate` · `/reset-password` sont retirés de la barre d'adresse dès lecture
  (`replace`). `<meta name="referrer" content="no-referrer">` en plus.
- **Messages à nous** : chaque erreur est un code mappé vers une phrase de
  `messages.ts`. Ni `detail` du serveur, ni `error_description` de l'URL ne sont
  affichés. Même phrase pour « numéro inconnu » et « mauvais mot de passe » ;
  même message après une demande de lien, que le compte existe ou non.
- **`redirect_to` contrôlé** : uniquement `https:` (ou `http:` en dev local),
  jamais `javascript:`.
- **Tuiles filtrées par scope = affichage.** Une tuile cachée ne protège rien.
- **Image Docker** : nginx avec repli SPA, CSP (`script-src 'self'`,
  `connect-src` limité à l'auth-server, `frame-ancestors 'none'`),
  `X-Content-Type-Options`, `Referrer-Policy`.

## Les mocks

[`src/mocks/`](src/mocks/) est le faux auth-server de B5
([ADR §17](../../docs/adr/0002-stack-simplifiee.md#les-bricks)). Les mêmes
handlers servent partout :

- **Vitest** : `msw/node` ([node.ts](src/mocks/node.ts)), démarré par
  [src/test/setup.ts](src/test/setup.ts) ; une requête non mockée fait échouer le test.
- **Navigateur** (`npm run dev:mock`, Playwright) : le service worker de MSW
  ([browser.tsx](src/mocks/browser.tsx)), servi depuis `node_modules` par un
  plugin Vite actif en mode `mock` seulement. L'« auth-server » est alors
  `/mock-auth` sur la même origine. Un service worker ne peut pas simuler une
  navigation de page : `/mock-auth/authorize` et `/mock-auth/end-session` sont
  donc deux routes du SPA, présentes en mode mock seulement. Un build normal ne
  contient aucun code de mock (vérifié sur `dist/`).

Les réponses sont typées par `src/api/types.ts` : si le contrat change, le mock
ne compile plus. Le mock ne garde pas d'état serveur : ce que le vrai serveur
range en base (interaction, code) est emballé dans le `uid` et le `code`
eux-mêmes — opaques pour le SPA, comme en vrai. Différences assumées avec le
vrai serveur : le mock demande toujours le consentement (le seed met
`require_consent: false` pour `portail-web`) ; quand le flux est fini,
`redirect_to` pointe directement sur `/callback?code=…` au lieu de repasser par
`/authorize` ; le 429 est déclenché par un numéro magique.

## Tests

```bash
npm run lint          # oxlint
npm test              # Vitest + Testing Library + MSW (jsdom)
npm run build         # tsc -b (app, tests, configs) + vite build
npx playwright install chromium   # une fois
npm run test:e2e      # Playwright, lance lui-même `dev:mock` sur le port 5174
npm run gen:api       # régénère src/api/types.ts après `make openapi`
```

La CI ([.github/workflows/frontend.yml](../../.github/workflows/frontend.yml))
fait tout cela, et échoue si `src/api/types.ts` n'est pas à jour avec
`docs/generated/openapi.json`. **Qui régénère `openapi.json` lance aussi
`npm run gen:api`** et commite les deux.

## Configuration

| Variable (build) | Défaut | Rôle |
| --- | --- | --- |
| `VITE_AUTH_URL` | — (obligatoire) | URL de l'auth-server, qui est aussi l'`issuer` attendu dans l'ID token |
| `VITE_OIDC_REDIRECT_URI` | `<origine>/callback` | doit être exactement un `redirect_uris` du client |
| `VITE_OIDC_POST_LOGOUT_REDIRECT_URI` | `<origine>/` | idem pour `post_logout_redirect_uris` |

En local : copier `.env.example` en `.env.local` (ignoré par git). Dans l'image :
`docker build --build-arg VITE_AUTH_URL=… apps/frontend` (défaut
`https://auth.authentint.local`) ; la même valeur alimente le `connect-src` de
la CSP.

## Seams

- **S3 — API d'interaction** : déjà réelle (B1 mergé). Les écrans de login,
  consentement, activation et reset parlent au vrai serveur dès que le SPA est
  servi sur `app.authentint.*` ; le mock reste pour les tests.
- **S2/S3 — B2** (`/authorize` SSO, `/token`, `/end-session`) : à la fusion de
  B2, seuls [src/auth/oidc.ts](src/auth/oidc.ts) et
  [src/auth/claims.ts](src/auth/claims.ts) peuvent changer. Points à vérifier :
  forme de la réponse `/token` (alignée sur `feat/b2-oidc`), `/end-session`
  (appelé en GET avec `client_id` + `post_logout_redirect_uri`, **sans**
  `id_token_hint` pour ne pas mettre un JWT nominatif dans une URL — à confirmer
  avec B2), les noms d'hôte `*.authentint.localhost` de B2 (le `redirect_uri`
  suit l'origine ; seul le défaut `VITE_AUTH_URL` du Dockerfile change), puis
  faire tourner le parcours Playwright contre la vraie stack.
- **S4 — B4** : les écrans « mon compte » (sessions, historique) et admin
  arrivent avec les routes `/me/*` et `/admin/*`, d'abord contre un mock MSW
  généré du même `openapi.json`.
