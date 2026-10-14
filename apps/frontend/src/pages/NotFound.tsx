import { Link } from 'react-router'
import { Layout } from '../components/Layout'

/** Never echoes the requested path: a crafted URL can't put its words on our page. */
export default function NotFound() {
  return (
    <Layout title="Page introuvable">
      <p>Cette page n'existe pas.</p>
      <p>
        <Link to="/">Retour à l'accueil</Link>
      </p>
    </Layout>
  )
}
