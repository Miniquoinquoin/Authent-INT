import { useNavigate } from "react-router-dom";

import { Shell } from "./Shell";

/**
 * The dead ends: an expired `uid`, a consumed activation token.
 *
 * Never echoes a raw parameter back into the page — an error screen that
 * renders what it was given is an XSS sink and a phishing surface.
 */
export default function ErrorPage() {
  const navigate = useNavigate();

  return (
    <Shell>
      <h1>Session expirée</h1>
      <p className="lede">
        Votre demande d&rsquo;authentification n&rsquo;est plus valable. Cela arrive après dix
        minutes d&rsquo;inactivité, ou si le lien a déjà été utilisé.
      </p>
      <button type="button" onClick={() => navigate("/", { replace: true })}>
        Recommencer
      </button>
    </Shell>
  );
}
