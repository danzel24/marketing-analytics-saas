import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.responses import Response
from app.api.routes.campaigns import router as campaigns_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.auth import router as auth_router
from app.api.routes.upload import router as upload_router
from app.api.routes.admin import router as admin_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.client_settings import router as client_settings_router
from app.core.domain_errors import AppError, InternalMisuseError
from app.core.error_response import build_error_payload
from app.core.request_id import (
    REQUEST_ID_HEADER,
    TRACE_ID_HEADER,
    bind_worker_correlation_context,
    correlation_id_middleware,
    get_request_id,
    get_trace_id,
    reset_worker_correlation_context,
)
from app.core.auth_cookies import clear_refresh_cookie, set_refresh_cookie
from app.core.config import get_startup_settings, validate_startup_config
from app.core.rate_limit import auth_rate_limit_response_or_none, upload_rate_limit_response_or_none
from app.core.structured_logging import access_log_middleware, configure_structured_logging
from app.core.web_paths import STATIC_DIR, log_web_paths
from app.core.web_templates import template_response_safe
from app.core.security import decode_access_token
from app.database import create_db_and_tables, engine, log_database_startup
from app.jobs.google_ads_sync import run_google_ads_sync_all_clients_once
from app.repositories.password_reset_repository import PasswordResetRepository
from app.repositories.refresh_token_jti_repository import RefreshTokenJtiRepository
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)
error_logger = logging.getLogger("app.errors")


def _is_api_request(request: Request) -> bool:
    p = request.url.path
    return p.startswith("/api/") or p.startswith("/v1/")


def _prefers_html(request: Request) -> bool:
    if _is_api_request(request):
        return False
    accept = request.headers.get("accept", "").lower()
    return "text/html" in accept


def _http_exception_detail_str(exc: HTTPException) -> str:
    d = exc.detail
    if isinstance(d, str):
        return d
    if isinstance(d, (list, dict)):
        return "Request could not be processed."
    return str(d)


# These routes must perform their own cookie/session handling; silent refresh would consume JTI first.
_SKIP_SILENT_REFRESH_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/login",
        "/register",
    }
)


def create_app() -> FastAPI:
    startup = get_startup_settings()
    doc_urls: dict[str, str | None] = (
        {"docs_url": None, "redoc_url": None, "openapi_url": None}
        if startup.is_production
        else {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    )

    async def _hourly_google_ads_sync_loop() -> None:
        while True:
            try:

                def _run() -> None:
                    worker_tokens = bind_worker_correlation_context()
                    try:
                        run_google_ads_sync_all_clients_once()
                    finally:
                        reset_worker_correlation_context(worker_tokens)

                await asyncio.to_thread(_run)
            except Exception:
                logger.exception(
                    "background_job_failed job=google_ads_sync_all_clients alert_severity=high",
                    extra={
                        "job": "google_ads_sync_all_clients",
                        "alert_severity": "high",
                        "error_category": "background_job",
                    },
                )
            await asyncio.sleep(3600)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.info("startup_step step=configure_structured_logging status=begin")
        try:
            configure_structured_logging()
        except Exception:
            logger.exception("startup_step step=configure_structured_logging status=failed")
            raise
        logger.info("startup_step step=configure_structured_logging status=done")

        logger.info("startup_step step=validate_startup_config status=begin")
        try:
            validate_startup_config()
        except Exception:
            logger.exception("startup_step step=validate_startup_config status=failed")
            raise
        logger.info("startup_step step=validate_startup_config status=done")

        logger.info("startup_step step=log_database_startup status=begin")
        try:
            log_database_startup(logger)
        except Exception:
            logger.exception("startup_step step=log_database_startup status=failed")
            raise
        logger.info("startup_step step=log_database_startup status=done")

        logger.info("startup_step step=log_web_paths status=begin")
        try:
            log_web_paths(logger)
        except Exception:
            logger.exception("startup_step step=log_web_paths status=failed")
            raise
        logger.info("startup_step step=log_web_paths status=done")

        logger.info("startup_step step=create_db_and_tables status=begin")
        try:
            create_db_and_tables()
        except Exception:
            logger.exception("startup_step step=create_db_and_tables status=failed")
            raise
        logger.info("startup_step step=create_db_and_tables status=done")

        logger.info("startup_step step=expired_token_cleanup status=begin")
        try:
            with Session(engine) as _cleanup_session:
                jti_deleted = RefreshTokenJtiRepository().delete_expired(_cleanup_session)
                reset_deleted = PasswordResetRepository().delete_expired(_cleanup_session)
            logger.info(
                "startup_step step=expired_token_cleanup status=done "
                "jti_deleted=%d reset_tokens_deleted=%d",
                jti_deleted,
                reset_deleted,
            )
        except Exception:
            logger.exception(
                "startup_step step=expired_token_cleanup status=failed — "
                "cleanup skipped, app continues"
            )

        s = get_startup_settings()
        logger.info(
            "startup app_env=%s production=%s cookie_secure=%s cookie_samesite=%s "
            "background_sync=%s google_ads_user_api=%s legacy_v1_csv=%s sqlalchemy_dialect=%s",
            s.app_env,
            s.is_production,
            s.cookie_secure,
            s.cookie_samesite,
            s.enable_background_sync,
            s.enable_google_ads_user_api,
            s.enable_legacy_v1_csv_campaigns,
            engine.dialect.name,
        )
        if s.enable_background_sync:
            asyncio.create_task(_hourly_google_ads_sync_loop())

        yield
        # No shutdown logic required.

    app = FastAPI(
        title="Marketing Analytics API",
        version="1.0.0",
        description="API for marketing analytics",
        lifespan=lifespan,
        **doc_urls,
    )

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = get_request_id(request) or str(uuid.uuid4())
        trace_id = get_trace_id(request) or request_id
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = build_error_payload(
            code=exc.code,
            message=exc.message,
            request_id=request_id,
            trace_id=trace_id,
            timestamp=timestamp,
        )
        log_extra = {
            "request_id": request_id,
            "trace_id": trace_id,
            "error_code": exc.code,
            "error_message": exc.message,
            "http_status": exc.status_code,
            "http_path": request.url.path,
            "http_method": request.method,
        }
        if isinstance(exc, InternalMisuseError):
            error_logger.error(
                "internal_misuse code=%s path=%s method=%s request_id=%s message=%s",
                exc.code,
                request.url.path,
                request.method,
                request_id,
                exc.message,
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={
                    **log_extra,
                    "alert_severity": "critical",
                    "error_category": "internal_misuse",
                    "exception_type": type(exc).__name__,
                },
            )
        elif exc.status_code >= 500:
            error_logger.error(
                "server_error code=%s path=%s method=%s request_id=%s message=%s",
                exc.code,
                request.url.path,
                request.method,
                request_id,
                exc.message,
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={
                    **log_extra,
                    "alert_severity": "high",
                    "error_category": "server",
                    "exception_type": type(exc).__name__,
                },
            )
        else:
            error_logger.warning(
                "client_error code=%s path=%s method=%s request_id=%s status=%s",
                exc.code,
                request.url.path,
                request.method,
                request_id,
                exc.status_code,
                extra={**log_extra, "alert_severity": "low", "error_category": "client"},
            )

        response = JSONResponse(status_code=exc.status_code, content=payload)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        return response

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> Response:
        if 300 <= exc.status_code < 400:
            return Response(
                status_code=exc.status_code,
                headers=dict(exc.headers) if exc.headers else {},
                content=b"",
            )

        request_id = get_request_id(request) or str(uuid.uuid4())
        trace_id = get_trace_id(request) or request_id
        timestamp = datetime.now(timezone.utc).isoformat()

        if _is_api_request(request):
            code_by_status = {
                404: "not_found",
                405: "method_not_allowed",
                429: "too_many_requests",
            }
            code = code_by_status.get(exc.status_code, "http_error")
            payload = build_error_payload(
                code=code,
                message=_http_exception_detail_str(exc),
                request_id=request_id,
                trace_id=trace_id,
                timestamp=timestamp,
            )
            response = JSONResponse(status_code=exc.status_code, content=payload)
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[TRACE_ID_HEADER] = trace_id
            return response

        if _prefers_html(request):
            if exc.status_code == 404:
                return template_response_safe(
                    request=request,
                    name="error_404.html",
                    context={"request_id": request_id},
                    status_code=404,
                )
            if 400 <= exc.status_code < 500:
                headings = {
                    403: "Přístup odepřen",
                    405: "Metoda není povolena",
                    429: "Příliš mnoho požadavků",
                }
                heading = headings.get(exc.status_code, "Chyba požadavku")
                return template_response_safe(
                    request=request,
                    name="error_http.html",
                    context={
                        "request_id": request_id,
                        "status_code": exc.status_code,
                        "heading": heading,
                        "message": _http_exception_detail_str(exc),
                    },
                    status_code=exc.status_code,
                )

        payload = build_error_payload(
            code="http_error",
            message=_http_exception_detail_str(exc),
            request_id=request_id,
            trace_id=trace_id,
            timestamp=timestamp,
        )
        response = JSONResponse(status_code=exc.status_code, content=payload)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        return response

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        request_id = get_request_id(request) or str(uuid.uuid4())
        trace_id = get_trace_id(request) or request_id
        error_logger.exception(
            "unhandled_exception path=%s method=%s request_id=%s",
            request.url.path,
            request.method,
            request_id,
            exc_info=exc,
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "http_path": request.url.path,
                "http_method": request.method,
                "error_category": "unhandled",
            },
        )
        timestamp = datetime.now(timezone.utc).isoformat()
        if _is_api_request(request):
            payload = build_error_payload(
                code="internal_error",
                message="An unexpected error occurred.",
                request_id=request_id,
                trace_id=trace_id,
                timestamp=timestamp,
            )
            response = JSONResponse(status_code=500, content=payload)
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[TRACE_ID_HEADER] = trace_id
            return response
        if _prefers_html(request):
            return template_response_safe(
                request=request,
                name="error_500.html",
                context={"request_id": request_id},
                status_code=500,
            )
        payload = build_error_payload(
            code="internal_error",
            message="An unexpected error occurred.",
            request_id=request_id,
            trace_id=trace_id,
            timestamp=timestamp,
        )
        response = JSONResponse(status_code=500, content=payload)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        return response

    @app.middleware("http")
    async def auto_refresh_access_token(request: Request, call_next):
        if request.url.path in _SKIP_SILENT_REFRESH_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        bearer = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""
        access_payload = decode_access_token(bearer) if bearer else None
        silent = None

        if not access_payload:
            refresh_cookie = request.cookies.get("refresh_token")
            if refresh_cookie:

                def _silent_refresh():
                    with Session(engine) as session:
                        return AuthService().try_silent_refresh(session, refresh_token=refresh_cookie)

                silent = await asyncio.to_thread(_silent_refresh)
                if silent.success and silent.access_token:
                    headers = [
                        (k, v) for (k, v) in request.scope.get("headers", []) if k != b"authorization"
                    ]
                    headers.append(
                        (b"authorization", f"Bearer {silent.access_token}".encode("latin-1"))
                    )
                    request.scope["headers"] = headers

        response = await call_next(request)
        if silent is not None:
            if silent.success and silent.access_token:
                response.headers["x-access-token"] = silent.access_token
                if silent.refresh_token is not None and silent.refresh_max_age is not None:
                    set_refresh_cookie(response, silent.refresh_token, silent.refresh_max_age)
            elif silent.clear_refresh_cookie:
                clear_refresh_cookie(response)
        return response

    # Order: correlation (outer) -> rate_limit -> access -> auto_refresh -> routes.
    @app.middleware("http")
    async def _access_log_middleware(request: Request, call_next):
        return await access_log_middleware(request, call_next)

    @app.middleware("http")
    async def _auth_rate_limit_middleware(request: Request, call_next):
        limited = auth_rate_limit_response_or_none(request)
        if limited is not None:
            return limited
        limited = upload_rate_limit_response_or_none(request)
        if limited is not None:
            return limited
        return await call_next(request)

    @app.middleware("http")
    async def _request_correlation_middleware(request: Request, call_next):
        return await correlation_id_middleware(request, call_next)

    if get_startup_settings().enable_legacy_v1_csv_campaigns:
        app.include_router(campaigns_router, prefix="/v1")

    # Dashboard + Auth (api/v1)
    app.include_router(dashboard_router)
    app.include_router(auth_router)
    app.include_router(upload_router)
    app.include_router(admin_router)
    if get_startup_settings().enable_google_ads_user_api:
        app.include_router(integrations_router)
    app.include_router(client_settings_router)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title="Marketing Analytics API",
            version="1.0.0",
            description="API for marketing analytics",
            routes=app.routes,
        )

        components = openapi_schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
        openapi_schema["security"] = [{"BearerAuth": []}]

        # Bind BearerAuth to protected operations generated by OAuth2 dependency.
        # FastAPI can emit operation-level security as {"OAuth2PasswordBearer": []},
        # which otherwise overrides global security in Swagger UI.
        paths = openapi_schema.get("paths", {})
        for path_item in paths.values():
            if not isinstance(path_item, dict):
                continue
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                operation_security = operation.get("security")
                if not isinstance(operation_security, list):
                    continue
                bound_security: list[dict[str, list]] = []
                for sec in operation_security:
                    if not isinstance(sec, dict):
                        continue
                    if "OAuth2PasswordBearer" in sec:
                        bound_security.append({"BearerAuth": []})
                    else:
                        bound_security.append(sec)
                if bound_security:
                    operation["security"] = bound_security

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api")
    def api_root() -> dict[str, Any]:
        s = get_startup_settings()
        versions: list[str] = ["api/v1"]
        if s.enable_legacy_v1_csv_campaigns:
            versions.insert(0, "v1")
        return {
            "message": "Marketing Analytics API",
            "versions": versions,
            "web": "/",
            "dashboard": "/dashboard",
        }

    return app


app = create_app()