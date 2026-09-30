"""Print the OpenAPI schema of the auth-server, for docs/generated/openapi.json.

It is the B0 interaction-API contract: the frontend (B5) mocks it with MSW until
seam S3. Committed, never edited by hand; CI fails when it is out of date.
Printed rather than written so the host shell owns the file, not the container's root.

    make openapi
"""

import json

from authentint.main import create_app

print(json.dumps(create_app().openapi(), indent=2, ensure_ascii=False))
