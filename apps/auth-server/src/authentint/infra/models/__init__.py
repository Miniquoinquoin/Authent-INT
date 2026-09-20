from authentint.infra.database import Base
from . import identity, oauth, audit, keys  # noqa: F401 — registers every table on Base.metadata
