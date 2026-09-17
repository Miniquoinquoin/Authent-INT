import type { ReactNode } from "react";

/** The card every screen sits in, and the only place the wordmark is drawn. */
export function Shell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <main className={wide ? "card card--wide" : "card"}>
      <div className="brand">
        {/* The logo carries the name, so the alt text is the accessible one. */}
        <img className="brand__logo" src="/authent_int_full_logo.png" alt="Authent’INT" />
        <div className="brand__org">Direction générale des finances publiques</div>
      </div>
      {children}
    </main>
  );
}

/**
 * The failure banner.
 *
 * `aria-live` sits on an element that is always in the tree: a region mounted
 * at the same moment as its text is never announced.
 */
export function Banner({ message, kind = "error" }: { message: string | null; kind?: "error" | "info" }) {
  return (
    <div className={`banner banner--${kind}`} role="status" aria-live="polite">
      {message}
    </div>
  );
}
