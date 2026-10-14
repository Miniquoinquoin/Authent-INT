/**
 * Fixtures of the fake auth-server. Invented people, invented numbers.
 * The scope table mirrors apps/auth-server/src/authentint/domain/scopes.py (ALLOWED, audiences).
 */
import type { Role } from '../auth/claims'

/** Same value as the dev seed (scripts/seed.py DEV_PASSWORD): DEV ONLY. */
export const MOCK_PASSWORD = 'Authentint-dev-1!'

/** Link token the mock accepts for /account/{activation,password-reset}/confirm. */
export const MOCK_LINK_TOKEN = 'lien-de-test-valide'

export interface MockUser {
  sub: string
  given_name: string
  family_name: string
  role: Role
}

export const MOCK_USERS: Record<string, MockUser> = {
  '1234567890123': { sub: '0f6b8a4e-5c1d-4e8a-9b5e-2d3c4b5a6f70', given_name: 'Marie', family_name: 'Dupont', role: 'agent' },
  '2345678901234': { sub: '1a7c9b5f-6d2e-4f9b-8c6f-3e4d5c6b7a81', given_name: 'Jean', family_name: 'Martin', role: 'contribuable' },
  '3456789012345': { sub: '2b8dac60-7e3f-4a0c-9d70-4f5e6d7c8b92', given_name: 'Alice', family_name: 'Bernard', role: 'admin' },
}

/** Numbers that trigger the error answers, whatever the password. */
export const LOCKED_NUMERO = '0000000000423'
export const RATE_LIMITED_NUMERO = '0000000000429'

const OIDC_SCOPES = ['openid', 'profile', 'email', 'offline_access']
const ALLOWED: Record<Role, string[]> = {
  admin: ['svc:admin.users', 'svc:admin.audit', 'svc:cadastre.read', 'svc:impots.write', 'svc:impots.read'],
  agent: ['svc:cadastre.read', 'svc:impots.write', 'svc:impots.read'],
  contribuable: ['svc:impots.read'],
}

/** granted = requested ∩ allowed(role) (the client allows everything in the seed). */
export function grant(requested: string[], role: Role): string[] {
  return requested.filter((s) => OIDC_SCOPES.includes(s) || ALLOWED[role].includes(s))
}

export function audiences(scopes: string[]): string[] {
  const names = scopes.filter((s) => s.startsWith('svc:')).map((s) => 'svc-' + s.slice(4).split('.')[0])
  return [...new Set(names)].sort()
}
