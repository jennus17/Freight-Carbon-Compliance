"""FastAPI application entrypoint — wires routes, middleware, auth, observability."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Response

from app.api.routes import emissions as emissions_routes
from app.core.auth import verify_rapidapi_proxy
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.metrics import render as render_metrics
from app.core.middleware import RequestContextMiddleware
from app.models.emissions import HealthResponse


def create_app() -> FastAPI:
    setup_logging(level=settings.log_level, fmt=settings.log_format)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.description,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "ESG Compliance API"},
        license_info={"name": "Proprietary"},
    )

    app.add_middleware(RequestContextMiddleware)

    # All v1 traffic flows through the RapidAPI proxy-secret check. When the
    # secret is unset (dev mode) the dependency is a no-op, so local runs and
    # tests do not need to inject the header.
    v1_dependencies = [Depends(verify_rapidapi_proxy)]

    app.include_router(
        emissions_routes.router,
        prefix=settings.api_v1_prefix,
        dependencies=v1_dependencies,
    )
    app.include_router(
        emissions_routes.reference_router,
        prefix=settings.api_v1_prefix,
        dependencies=v1_dependencies,
    )

    @app.get("/health", response_model=HealthResponse, tags=["System"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=settings.app_name,
            version=settings.app_version,
        )

    if settings.metrics_enabled:
        @app.get("/metrics", tags=["System"], include_in_schema=False)
        def metrics() -> Response:
            payload, content_type = render_metrics()
            return Response(content=payload, media_type=content_type)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
