import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api";
import { Banner, Shell } from "./Shell";

// Mirrors PASSWORD_MIN_LENGTH in .env.example; nothing serves the value, so
// a stricter server answers 422 and the banner shows a generic message.
const MIN_LENGTH = 12;

export default function Activate() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const tooShort = password.length > 0 && password.length < MIN_LENGTH;
  const mismatch = confirmation.length > 0 && confirmation !== password;
  const ready = password.length >= MIN_LENGTH && confirmation === password;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.activate(token, password);
      setDone(true);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Une erreur est survenue.");
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <Shell>
        <h1>Lien incomplet</h1>
        <p className="lede">
          Ce lien d&rsquo;activation ne contient pas de jeton. Ouvrez-le directement depuis le
          courriel que vous avez reçu.
        </p>
        <Link to="/">
          <button type="button" className="button--quiet">Retour à la connexion</button>
        </Link>
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell>
        <h1>Compte activé</h1>
        <p className="lede">Votre mot de passe est enregistré. Vous pouvez vous connecter.</p>
        <Link to="/">
          <button type="button">Se connecter</button>
        </Link>
      </Shell>
    );
  }

  return (
    <Shell>
      <h1>Activation du compte</h1>
      <p className="lede">Choisissez le mot de passe qui protégera votre compte.</p>

      <form onSubmit={submit}>
        <Banner message={error} />

        <div>
          <label htmlFor="password">Nouveau mot de passe</label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            autoFocus
            required
            aria-describedby="password-hint"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="field__hint" id="password-hint">
            {tooShort
              ? `Encore ${MIN_LENGTH - password.length} caractère(s).`
              : `Au moins ${MIN_LENGTH} caractères. Une phrase est plus sûre qu'un mot compliqué.`}
          </p>
        </div>

        <div>
          <label htmlFor="confirmation">Confirmation</label>
          <input
            id="confirmation"
            type="password"
            autoComplete="new-password"
            required
            aria-describedby="confirmation-hint"
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
          />
          <p className="field__hint" id="confirmation-hint">
            {mismatch ? "Les deux saisies diffèrent." : " "}
          </p>
        </div>

        <button type="submit" disabled={busy || !ready}>
          {busy ? "Enregistrement…" : "Activer mon compte"}
        </button>
      </form>
    </Shell>
  );
}
