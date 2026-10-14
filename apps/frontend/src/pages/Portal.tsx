import { Link } from 'react-router'
import { logout, startLogin } from '../auth/oidc'
import { useSession } from '../auth/session'
import type { Role } from '../auth/claims'
import { Layout } from '../components/Layout'

interface Service {
  id: string
  title: string
  description: string
  read: string
  write: string
}

const SERVICES: Service[] = [
  {
    id: 'impots',
    title: 'Impôts',
    description: 'Vos dossiers fiscaux : déclarations, avis et paiements.',
    read: 'svc:impots.read',
    write: 'svc:impots.write',
  },
  {
    id: 'cadastre',
    title: 'Cadastre',
    description: 'Le plan cadastral et les informations sur les parcelles.',
    read: 'svc:cadastre.read',
    write: 'svc:cadastre.write',
  },
]

const ROLES: Record<Role, string> = { admin: 'Administrateur', agent: 'Agent', contribuable: 'Contribuable' }

/**
 * / — the portal. Logged out: a "Se connecter" button. Logged in: one tile per service.
 *
 * Which tiles show is PRESENTATION ONLY (ADR §13, architecture.md §9). Hiding a tile protects
 * nothing: each Resource Server (svc-impots, svc-cadastre) verifies the access token's
 * signature, `aud` and `scope` itself and answers 403 to an under-scoped token.
 */
export default function Portal() {
  const session = useSession()

  if (!session) {
    return (
      <Layout title="Bienvenue sur Authent'INT">
        <p>Accédez à vos services fiscaux avec votre numéro fiscal et votre mot de passe.</p>
        <div className="actions">
          <button type="button" className="button" onClick={() => void startLogin()}>
            Se connecter
          </button>
        </div>
        <ul className="links">
          <li>
            <Link to="/activation">Première connexion ? Activer mon compte</Link>
          </li>
          <li>
            <Link to="/mot-de-passe-oublie">Mot de passe oublié ?</Link>
          </li>
        </ul>
      </Layout>
    )
  }

  const has = (scope: string) => session.scopes.includes(scope)
  const services = SERVICES.filter((s) => has(s.read) || has(s.write))

  return (
    <Layout title={`Bonjour, ${session.user.name}`} wide>
      <p className="subtitle">
        Profil : {ROLES[session.user.role] ?? session.user.role}
      </p>
      <h2>Vos services</h2>
      {services.length === 0 ? (
        <p>Aucun service n'est ouvert à votre compte pour le moment.</p>
      ) : (
        <ul className="tiles">
          {services.map((service) => (
            <li key={service.id} className="tile" data-testid={`tuile-${service.id}`}>
              <h3>{service.title}</h3>
              <p>{service.description}</p>
              <p className="tile-access">{has(service.write) ? 'Consultation et modification' : 'Consultation'}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="actions">
        <button type="button" className="button button-secondary" onClick={logout}>
          Se déconnecter
        </button>
      </div>
    </Layout>
  )
}
