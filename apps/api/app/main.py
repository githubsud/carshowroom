"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    customers,
    finance,
    health,
    installments,
    partners,
    sales,
    session,
    suppliers,
    vehicles,
)
from app.core.config import API_PREFIX, PRODUCT_NAME, Settings, get_settings
from app.core.crypto import FieldCipher
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.security import TokenVerifier, build_token_verifier
from app.db.session import Database, create_db_engine
from app.integrations.storage import DisabledStorage, Storage, SupabaseStorage
from app.integrations.supabase_auth_admin import AuthAdmin, DisabledAuthAdmin, SupabaseAuthAdmin


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    token_verifier: TokenVerifier | None = None,
    auth_admin: AuthAdmin | None = None,
    storage: Storage | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own database, verifier and auth admin."""
    settings = settings or get_settings()
    configure_logging()

    app = FastAPI(
        title=f"{PRODUCT_NAME} API",
        version="0.1.0",
        # OpenAPI and docs only outside production (SPEC §8).
        openapi_url=None if settings.is_production else f"{API_PREFIX}/openapi.json",
        docs_url=None if settings.is_production else f"{API_PREFIX}/docs",
        redoc_url=None,
    )

    app.state.database = database or Database(create_db_engine(settings.database_url))
    app.state.token_verifier = token_verifier or build_token_verifier(
        jwks_url=settings.jwks_url,
        audience=settings.jwt_audience,
        hs256_secret=settings.supabase_jwt_secret.get_secret_value() if settings.supabase_jwt_secret else None,
    )
    if auth_admin is None:
        auth_admin = (
            SupabaseAuthAdmin(
                supabase_url=settings.supabase_url,
                service_role_key=settings.supabase_service_role_key.get_secret_value(),
            )
            if settings.supabase_service_role_key
            else DisabledAuthAdmin()
        )
    app.state.auth_admin = auth_admin
    if storage is None:
        storage = (
            SupabaseStorage(
                supabase_url=settings.supabase_url,
                public_url=settings.supabase_public_url or settings.supabase_url,
                service_role_key=settings.supabase_service_role_key.get_secret_value(),
            )
            if settings.supabase_service_role_key
            else DisabledStorage()
        )
    app.state.storage = storage
    app.state.cipher = FieldCipher(settings.national_id_key.get_secret_value() if settings.national_id_key else None)

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Tenant-Id", "Idempotency-Key", REQUEST_ID_HEADER],
        # Content-Disposition carries report file names; the browser hides it unless exposed.
        expose_headers=[REQUEST_ID_HEADER, "Content-Disposition", "Idempotent-Replay"],
    )
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(session.router, prefix=API_PREFIX)
    app.include_router(finance.router, prefix=API_PREFIX)
    app.include_router(partners.router, prefix=API_PREFIX)
    app.include_router(customers.router, prefix=API_PREFIX)
    app.include_router(suppliers.router, prefix=API_PREFIX)
    app.include_router(vehicles.router, prefix=API_PREFIX)
    app.include_router(sales.router, prefix=API_PREFIX)
    app.include_router(installments.router, prefix=API_PREFIX)
    return app
