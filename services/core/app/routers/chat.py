"""Chat orchestration: Core -> new-api gateway, per-role models with fallback.

The endpoint is honest about configuration: with no gateway key/base URL on
the server it returns 503 instead of fabricating a reply.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.gateway import GatewayClient, GatewayError, GatewayNotConfigured
from app.models import User
from app.security import get_current_user_if_required

router = APIRouter()


def get_gateway_client() -> GatewayClient:
    """Dependency seam — tests substitute a mock-transport client here."""
    return GatewayClient()


class ChatMessage(BaseModel):
    role: str = Field(min_length=1)
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    role: str = "smart"
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


@router.post("/")
async def chat(
    req: ChatRequest,
    gateway: GatewayClient = Depends(get_gateway_client),
    # Enforced only when AUTH_REQUIRED=true (see app/security.py).
    _user: User | None = Depends(get_current_user_if_required),
) -> dict:
    if req.role not in settings.model_roles:
        raise HTTPException(
            status_code=400,
            detail=f"unknown model role {req.role!r}; "
            f"known roles: {', '.join(sorted(settings.model_roles))}",
        )
    if req.stream:
        raise HTTPException(
            status_code=400,
            detail="streaming responses are not supported by this endpoint yet",
        )
    params: dict = {}
    if req.temperature is not None:
        params["temperature"] = req.temperature
    if req.max_tokens is not None:
        params["max_tokens"] = req.max_tokens
    try:
        return await gateway.chat_completion(
            req.role, [m.model_dump() for m in req.messages], **params
        )
    except GatewayNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/models")
async def chat_models(gateway: GatewayClient = Depends(get_gateway_client)) -> dict:
    """Role -> fallback-chain mapping, plus the gateway's live model list
    when the gateway is configured and reachable."""
    result: dict = {
        "gateway_configured": gateway.configured,
        "roles": gateway.role_chains,
        "gateway_models": None,
    }
    if gateway.configured:
        try:
            result["gateway_models"] = await gateway.list_models()
        except GatewayError as exc:
            result["gateway_error"] = str(exc)
    return result
