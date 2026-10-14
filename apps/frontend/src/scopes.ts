/**
 * What each scope means, in plain French, for the consent screen (ADR §13: "liste des scopes
 * en français clair"). The list mirrors apps/auth-server/src/authentint/domain/scopes.py.
 */
const DESCRIPTIONS: Record<string, string> = {
  openid: 'Vous identifier, par un identifiant anonyme (jamais votre numéro fiscal)',
  profile: 'Connaître vos nom et prénom',
  email: 'Connaître votre adresse e-mail',
  offline_access: 'Rester connecté sans vous redemander votre mot de passe',
  'svc:impots.read': 'Consulter vos dossiers fiscaux',
  'svc:impots.write': 'Modifier vos dossiers fiscaux',
  'svc:cadastre.read': 'Consulter le cadastre',
  'svc:cadastre.write': 'Modifier le cadastre',
  'svc:admin.users': 'Administrer les comptes utilisateurs',
  'svc:admin.audit': "Consulter le journal d'audit",
}

export function describeScope(scope: string): string {
  return DESCRIPTIONS[scope] ?? 'Un accès non répertorié' // the raw code is shown next to it, as text
}

export function isKnownScope(scope: string): boolean {
  return scope in DESCRIPTIONS
}
