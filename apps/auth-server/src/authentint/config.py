from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dev: bool = False  # DEV=true only via docker-compose.dev.yml; never in prod
    issuer: str
    public_base_url: str  # SPA origin: mail links and the only CORS origin (/login is served on the issuer's origin)
    database_url: str
    key_encryption_key: str
    numero_fiscal_key: str  # HMAC key of users.numero_fiscal_hmac: changing it breaks every login until a re-sync
    access_token_ttl: int = 600
    id_token_ttl: int = 300
    code_ttl: int = 60
    refresh_token_ttl: int = 30 * 24 * 3600  # ADR §10: 30 days, rotated on every use
    fixtures_path: str | None = None  # fake LDAP directory for scripts/seed.py, dev only

    @model_validator(mode="after")
    def _fixtures_only_in_dev(self):
        if not self.dev:
            self.fixtures_path = None  # fake users can never be loaded outside dev
        elif self.fixtures_path is None:
            self.fixtures_path = "/fixtures/ldap/users.json"  # mounted by docker-compose.dev.yml
        return self

settings = Settings()
