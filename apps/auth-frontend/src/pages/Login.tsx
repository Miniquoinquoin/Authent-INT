import { type FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api";
import { Banner, Shell } from "./Shell";

export default function Login() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const uid = params.get("uid");

  const [numeroFiscal, setNumeroFiscal] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const minting = useRef(false);

  // No `uid` yet: mint one and put it in the URL. At B2 `/authorize` does this
  // and redirects here with it already set — the page will not notice.
  useEffect(() => {
    if (uid || minting.current) return;
    minting.current = true;
    api
      .startInteraction()
      .then(({ uid }) => setParams({ uid }, { replace: true }))
      .catch(() => navigate("/erreur", { replace: true }));
  }, [uid, setParams, navigate]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!uid) return;
    setBusy(true);
    setError(null);
    try {
      await api.login(uid, numeroFiscal, password);
      navigate(`/mfa?uid=${encodeURIComponent(uid)}`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 410) {
        navigate("/erreur", { replace: true });
        return;
      }
      // The server's sentence, verbatim. Unknown, wrong password, awaiting
      // activation, locked and disabled all say this — and the moment this
      // page composes its own message instead, the property is gone (P§3).
      setError(caught instanceof ApiError ? caught.detail : "Une erreur est survenue.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <h1>Connexion</h1>

      <form onSubmit={submit}>
        <Banner message={error} />

        <div>
          <label htmlFor="numero-fiscal">Numéro fiscal</label>
          <input
            id="numero-fiscal"
            className="input--mono"
            name="numero_fiscal"
            inputMode="numeric"
            autoComplete="username"
            autoFocus
            required
            value={numeroFiscal}
            onChange={(e) => setNumeroFiscal(e.target.value.trim())}
          />
          <p className="field__hint">Les 13 chiffres figurant sur votre avis d&rsquo;imposition.</p>
        </div>

        <div>
          <label htmlFor="password">Mot de passe</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button type="submit" disabled={busy || !uid}>
          {busy ? "Vérification…" : "Se connecter"}
        </button>
      </form>

      <p className="footnote">
        Votre compte n&rsquo;est pas encore activé ? Tentez de vous connecter : un lien
        d&rsquo;activation vous sera envoyé par courriel.
      </p>
    </Shell>
  );
}
