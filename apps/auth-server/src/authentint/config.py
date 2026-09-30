from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dev: bool = False  # DEV=true only via docker-compose.dev.yml; never in prod
    issuer: str
    database_url: str
    key_encryption_key: str
    access_token_ttl: int = 600
    id_token_ttl: int = 300
    otp_ttl: int = 30
    fixtures_path: str | None = None  # fake LDAP directory for scripts/seed.py, dev only

    @model_validator(mode="after")
    def _fixtures_only_in_dev(self):
        if not self.dev:
            self.fixtures_path = None  # fake users can never be loaded outside dev
        elif self.fixtures_path is None:
            self.fixtures_path = "/fixtures/ldap/users.json"  # mounted by docker-compose.dev.yml
        return self

settings = Settings()
