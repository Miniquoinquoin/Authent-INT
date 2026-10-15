from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    One image, two containers: everything that makes svc-impots differ from svc-cadastre is here.
    The only URL a Resource Server knows is the issuer's; jwks_uri is discovered (ADR §11).
    """

    service_name: str
    issuer: str
    audience: str
    # Caddy's internal root CA (docs/architecture.md §1.1). Unset = the system trust store.
    # There is deliberately no way to turn TLS verification off.
    ca_bundle: str | None = None
    # Seconds between two JWKS downloads triggered by an unknown kid (ADR §11, cache rule 3)
    jwks_refresh_cooldown: float = 30.0
    # Seconds before retrying after a failed download (issuer not up yet)
    jwks_retry_delay: float = 2.0
    # Clock skew tolerated on exp / nbf / iat, in seconds
    leeway: int = 30
    # The portal's origin, the only page allowed to call us from a browser. Unset = no CORS at all
    cors_origin: str | None = None
