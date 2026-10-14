import type { ReactNode } from 'react'
import { Link } from 'react-router'

/** The shell of every screen: logo, one card, a footer. */
export function Layout({ title, children, wide = false }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className="page">
      <header className="page-header">
        <Link to="/" aria-label="Accueil Authent'INT">
          <img src="/authent_int_full_logo.png" alt="Authent'INT" className="logo" />
        </Link>
      </header>
      <main className={wide ? 'card card-wide' : 'card'}>
        <h1>{title}</h1>
        {children}
      </main>
      <footer className="page-footer">Authent'INT — Direction générale des Finances publiques</footer>
    </div>
  )
}

/** An error sentence from messages.ts: announced to screen readers as soon as it appears. */
export function Alert({ children }: { children: ReactNode }) {
  return (
    <p className="alert" role="alert">
      {children}
    </p>
  )
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <p className="notice" role="status">
      {children}
    </p>
  )
}
