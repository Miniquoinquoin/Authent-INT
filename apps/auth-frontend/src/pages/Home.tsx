import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { Shell } from "./Shell";

type Me = Awaited<ReturnType<typeof api.me>>;

const ROLES: Record<string, string> = {
  admin: "Administrateur",
  agent: "Agent",
  contribuable: "Contribuable",
};

export default function Home() {
  const navigate = useNavigate();
  const [me, setMe] = useState<Me | null>(null);

  // No client-side route guard worth the name: the cookie is the state, and a
  // 401 is the only authority on whether it is still good (P§3).
  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => navigate("/", { replace: true }));
  }, [navigate]);

  async function logout() {
    await api.logout().catch(() => undefined);
    navigate("/", { replace: true });
  }

  if (!me) {
    return (
      <Shell wide>
        <p className="lede">Chargement…</p>
      </Shell>
    );
  }

  const openedAt = new Date(me.session_ouverte_a).toLocaleString("fr-FR", {
    dateStyle: "long",
    timeStyle: "short",
  });

  return (
    <Shell wide>
      <h1>
        Bonjour {me.prenom} {me.nom}
      </h1>
      <p className="lede">Vous êtes authentifié avec un second facteur.</p>

      <dl className="identity">
        <dt>Nom</dt>
        <dd>{me.nom}</dd>
        <dt>Prénom</dt>
        <dd>{me.prenom}</dd>
        <dt>Rôle</dt>
        <dd>
          <span className={`badge badge--${me.role}`}>{ROLES[me.role] ?? me.role}</span>
        </dd>
        <dt>Statut du compte</dt>
        <dd>
          <span className="badge badge--active">{me.statut}</span>
        </dd>
        <dt>Session ouverte à</dt>
        <dd>{openedAt}</dd>
      </dl>

      <div className="actions">
        <button type="button" className="button--quiet" onClick={logout}>
          Se déconnecter
        </button>
      </div>

      <p className="footnote">
        La liste des services accessibles selon votre rôle arrivera avec le portail. Cette page
        existe pour prouver que la session fonctionne de bout en bout.
      </p>
    </Shell>
  );
}
