"""Every environment variable, with defaults and types.

ADR §10: a URL, TTL, limit or cookie name literal anywhere else in the codebase
is a bug. That is what makes inserting Caddy an `.env` change (§2) and what lets
the open client questions of §17 be answered without touching code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

def _repo_root() -> Path:
    """The checkout root, found by a marker rather than by counting parents.

    Counting `parents[n]` breaks the moment the tree is flatter than the one it
    was written against — in the image the source lives at `/srv/src/app`, four
    levels shallower than in the repository. Inside the container neither marker
    exists and configuration arrives entirely through the environment, so the
    working directory is a fine answer.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env.example").exists() or (parent / "fixtures").is_dir():
            return parent
    return Path.cwd()


REPO_ROOT = _repo_root()


class Settings(BaseSettings):
    # Anchored at the repo root so the working directory never matters:
    # alembic runs from apps/auth-server, pytest and the CLI from the root.
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # ---------------------------------------------------------- infrastructure
    database_url: str = "postgresql+asyncpg://authentint:authentint@localhost:5432/authentint"
    valkey_url: str = "redis://localhost:6379/0"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "no-reply@authentint.local"

    #: Every externally visible URL comes from here, never from a literal (§2).
    public_base_url: str = "http://localhost:5173"

    # ------------------------------------------------------- directory fixture
    fixture_path: Path = Path("fixtures/ldap/users.json")

    #: group DN → role. In configuration and not in code, because the real
    #: mapping is §17 Q6 and has not come back (§5b).
    group_role_map: dict[str, str] = {
        "cn=admins,ou=groupes,dc=dgfip,dc=local": "admin",
        "cn=agents,ou=groupes,dc=dgfip,dc=local": "agent",
        "cn=contribuables,ou=groupes,dc=dgfip,dc=local": "contribuable",
    }
    #: What a user gets when no group maps. Least privilege.
    default_role: str = "contribuable"

    # ------------------------------------------------------------- passwords
    #: Length only, no composition rule (ANSSI). Gated on §17 Q7.
    password_min_length: int = 12

    # --------------------------------------------------------------- lockout
    login_max_failures: int = 5
    login_lockout_backoff_s: int = 900

    # ----------------------------------------------------------- rate limits
    # Per IP *and* per account, separately (§15). Fails closed (§11b rule 3).
    rl_login_ip: int = 10
    rl_login_ip_window_s: int = 60
    rl_login_account: int = 5
    rl_login_account_window_s: int = 60
    rl_otp_send: int = 3
    rl_otp_send_window_s: int = 600

    # ------------------------------------------------------------------ TTLs
    interaction_ttl_s: int = 600
    otp_ttl_s: int = 600
    otp_max_attempts: int = 5
    activation_ttl_s: int = 1800

    # --------------------------------------------------------------- session
    #: Both derived from `public_base_url` when unset — see `cookie_secure`.
    #: Set either one to override the derivation.
    session_cookie_name: str | None = None
    session_cookie_secure: bool | None = None
    session_idle_ttl_s: int = 1800
    session_absolute_ttl_s: int = 43200

    # ------------------------------------------------------------------ logs
    log_level: str = "INFO"

    @property
    def cookie_secure(self) -> bool:
        """Whether the session cookie carries `Secure`.

        Derived from the scheme the *browser* sees, which is what
        `public_base_url` already means (§2) — never from a literal.

        Hardcoding `Secure` in a phase that has no TLS silently breaks Safari:
        WebKit refuses to send a `Secure` cookie over plain http, `localhost`
        included, while Chromium treats `http://localhost` as trustworthy and
        sends it anyway. The login then works in one browser and dead-ends at
        the dashboard in the other. Deriving it means the cookie flags and the
        scheme cannot disagree, and it flips to `Secure` on its own the day
        `PUBLIC_BASE_URL` becomes https — which is the day Caddy lands.
        """
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.public_base_url.startswith("https://")

    @property
    def cookie_name(self) -> str:
        """`__Host-` only where it is legal.

        The prefix *requires* `Secure`; a browser rejects a `__Host-` cookie
        without it outright. So the name follows the same derivation rather
        than being set independently and drifting out of step.

        Without the prefix the cookie is scoped to the host and ignores the
        port, so on bare `localhost` it is shared with anything else served
        there. That is one of the reasons §2 wants real hostnames behind Caddy.
        """
        if self.session_cookie_name:
            return self.session_cookie_name
        return "__Host-session" if self.cookie_secure else "authentint_session"

    @property
    def fixture_file(self) -> Path:
        """The fixture path, resolved against the repo root when relative."""
        return self.fixture_path if self.fixture_path.is_absolute() else REPO_ROOT / self.fixture_path


@lru_cache
def settings() -> Settings:
    return Settings()
