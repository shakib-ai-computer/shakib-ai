"""Image generation: Core -> new-api gateway /v1/images/generations.

Honest about configuration, like chat: with no gateway key/base URL on
the server the endpoint returns 503 instead of fabricating an image.
On success the gateway's image payload is passed through unchanged.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.gateway import GatewayClient, GatewayError, GatewayNotConfigured
from app.models import User
from app.routers.chat import get_gateway_client
from app.security import get_current_user_if_required

router = APIRouter()


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str | None = None
    size: str | None = None


@router.post("/generate")
async def generate(
    req: ImageRequest,
    gateway: GatewayClient = Depends(get_gateway_client),
    # Enforced only when AUTH_REQUIRED=true (see app/security.py).
    _user: User | None = Depends(get_current_user_if_required),
) -> dict:
    try:
        return await gateway.generate_image(
            req.prompt, model=req.model, size=req.size
        )
    except GatewayNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
