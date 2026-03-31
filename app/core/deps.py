from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.core.config import Settings, csv_path_for_tenant, get_settings
from app.core.domain_errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.error_codes import ErrorCode
from app.core.security import decode_access_token
from app.database import get_session
from app.models.db_models import User
from app.repositories.campaign_repository import CampaignRepository
from app.services.auth_service import AuthService
from app.services.marketing_service import MarketingService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


@lru_cache(maxsize=1)
def settings_dep() -> Settings:
    return get_settings()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    payload = decode_access_token(token)
    if not payload:
        raise UnauthorizedError("Invalid token")

    try:
        user_id = int(payload.get("sub"))
        client_id = int(payload.get("client_id"))
        token_version = int(payload.get("token_version", 0))
    except (TypeError, ValueError):
        raise UnauthorizedError("Invalid token")

    return AuthService().load_user_matching_jwt_claims(
        session,
        user_id=user_id,
        jwt_client_id=client_id,
        jwt_token_version=token_version,
    )


def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    if str(getattr(user, "role", "user")) != "admin":
        raise ForbiddenError("Admin only")
    return user


def campaign_repo_dep(
    settings: Settings = Depends(settings_dep),
    user: User = Depends(get_current_user),
) -> CampaignRepository:
    """Legacy v1 CSV: path is scoped to the authenticated user's ``client_id`` (never from headers)."""
    csv_path = csv_path_for_tenant(settings, str(user.client_id))
    if not csv_path.exists():
        raise NotFoundError(
            f"ads_report_csv_not_found (csv_path={csv_path}, client_id={user.client_id})",
            code=ErrorCode.ADS_REPORT_CSV_NOT_FOUND,
        )
    return CampaignRepository(csv_path=csv_path)


def marketing_service_dep() -> MarketingService:
    return MarketingService()

