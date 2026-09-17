import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api";
import { Banner, Shell } from "./Shell";

const RESEND_COOLDOWN_S = 30;

export default function Mfa() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const uid = params.get("uid");

  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_S);
  const requested = useRef(false);

  const send = useCallback(async () => {
    if (!uid) return;
    setError(null);
    try {
      await api.sendOtp(uid);
      setNotice("Un code à 6 chiffres vient de vous être envoyé.");
      setCooldown(RESEND_COOLDOWN_S);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 410) {
        navigate("/erreur", { replace: true });
        return;
      }
      // A mail failure is a hard stop, never a bypass (§11.6).
      setError(caught instanceof ApiError ? caught.detail : "Une erreur est survenue.");
    }
  }, [uid, navigate]);

  // Send once on arrival. The ref guard is not decoration: StrictMode mounts
  // effects twice in development, and the send budget is three per ten minutes.
  useEffect(() => {
    if (!uid) {
      navigate("/", { replace: true });
      return;
    }
    if (requested.current) return;
    requested.current = true;
    void send();
  }, [uid, send, navigate]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!uid) return;
    setBusy(true);
    setError(null);
    try {
      await api.verifyOtp(uid, code);
      navigate("/accueil", { replace: true });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 410) {
        navigate("/erreur", { replace: true });
        return;
      }
      // Wrong, expired and exhausted are one message here because they are one
      // message on the wire (§9).
      setError(caught instanceof ApiError ? caught.detail : "Une erreur est survenue.");
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <h1>Vérification en deux étapes</h1>
      <p className="lede">Saisissez le code reçu par courriel.</p>

      <form onSubmit={submit}>
        <Banner message={error} />
        {!error && <Banner message={notice} kind="info" />}

        <div>
          <label htmlFor="code">Code à 6 chiffres</label>
          <input
            id="code"
            className="input--code"
            name="code"
            inputMode="numeric"
            pattern="\d{6}"
            maxLength={6}
            autoComplete="one-time-code"
            autoFocus
            required
            aria-describedby="code-hint"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          />
          <p className="field__hint" id="code-hint">
            Le code est valable 10 minutes.
          </p>
        </div>

        <button type="submit" disabled={busy || code.length !== 6}>
          {busy ? "Vérification…" : "Valider"}
        </button>
      </form>

      <div className="actions" style={{ marginTop: 20 }}>
        <button type="button" className="button--link" onClick={send} disabled={cooldown > 0}>
          {cooldown > 0 ? `Renvoyer le code (${cooldown} s)` : "Renvoyer le code"}
        </button>
      </div>
    </Shell>
  );
}
