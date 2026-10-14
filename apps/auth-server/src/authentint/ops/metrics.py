"""
/metrics in the Prometheus text format (ADR §9 Ops).

Not public: Caddy answers 404 for /metrics on auth.authentint.localhost (caddy/Caddyfile),
so only scrapers on the docker network reach it (http://auth-server:8000/metrics).

One process per container (no `uvicorn --workers`): the default registry is per process,
which is exactly one replica. With `--scale auth-server=3` the scraper scrapes each replica
and sums them. ponytail: several workers per container would need prometheus_client's
multiprocess mode (PROMETHEUS_MULTIPROC_DIR); not needed while a replica is one process.
"""

import time

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client import Counter
from prometheus_client import Histogram
from prometheus_client import generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from . import router


# `route` is the route TEMPLATE (/me/sessions/{session_id}), never the raw path: raw paths would put
# ids in the labels and create one time series per session, interaction or user
REQUESTS = Counter("authentint_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("authentint_http_request_duration_seconds", "HTTP request latency", ["method", "route", "status"],
                    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}  # any other verb: "other", same reason
# outcome: success | failure | locked | rate_limited
LOGINS = Counter("authentint_logins_total", "POST /interaction/{uid}/login outcomes", ["outcome"])
# grant_type: authorization_code | refresh_token ; outcome: success | failure (any error, 429 included)
TOKEN_GRANTS = Counter("authentint_token_grants_total", "POST /token outcomes", ["grant_type", "outcome"])


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        status = 500  # an exception escaping the app is answered 500 by Starlette
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # the router stored the matched route in the (shared) scope; none matched: one fixed label
            route = request.scope.get("route")
            method = request.method if request.method in METHODS else "other"
            labels = (method, route.path if route is not None else "unmatched", str(status))
            REQUESTS.labels(*labels).inc()
            LATENCY.labels(*labels).observe(time.perf_counter() - start)


@router.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
