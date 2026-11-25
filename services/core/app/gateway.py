"""Async client for the OpenAI-compatible model gateway (new-api).

Every model call in SHAKIB AI Core goes through this client. It knows model
*roles* (fast / smart / strategic / embedding); each role maps to an ordered
fallback chain of gateway model names configured via env (MODEL_FAST,
MODEL_SMART, MODEL_STRATEGIC, MODEL_EMBEDDING — comma-separated).

Fallback rule: if a model answers HTTP 429 or 5xx, or the request fails with
a connection/transport error, the next model in the chain is tried. Other
4xx responses are caller errors (malformed request, bad key) — retrying a
different model would not fix them, so they raise immediately.

The configured base URL may be given with or without the trailing "/v1";
request paths are built against "{base}/v1/..." either way.

The API key is used only in the Authorization header. It is never logged,
never included in exception messages, and never returned to callers.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Mapping, Sequence

import httpx

from app.config import settings as default_settings


class GatewayError(Exception):
    """A gateway call failed.

    ``errors`` maps each tried model name to a short error description
    (status code or error class — never credentials or response secrets).
    """

    def __init__(self, message: str, errors: Mapping[str, str] | None = None):
        super().__init__(message)
        self.errors: dict[str, str] = dict(errors or {})


class GatewayNotConfigured(GatewayError):
    """Gateway base URL and/or API key are not set on the server."""


def _response_error_detail(response: httpx.Response) -> str:
    """Short, safe error text from a gateway error response."""
    try:
        data = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            return f"HTTP {response.status_code}: {str(err['message'])[:200]}"
        if isinstance(err, str) and err:
            return f"HTTP {response.status_code}: {err[:200]}"
    return f"HTTP {response.status_code}"


class GatewayClient:
    """OpenAI-compatible gateway client with per-role model fallback."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        role_chains: Mapping[str, Sequence[str]] | None = None,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
        timeout: float = 60.0,
    ):
        if base_url is None:
            base_url = default_settings.gateway_base_url
        if api_key is None:
            api_key = default_settings.gateway_api_key
        self._base_url = (base_url or "").strip().rstrip("/")
        self._api_key = api_key or ""
        if role_chains is None:
            role_chains = default_settings.model_roles
        self._role_chains: dict[str, list[str]] = {
            role: list(chain) for role, chain in role_chains.items()
        }
        self._transport = transport
        self._timeout = timeout

    # -- configuration -----------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key)

    @property
    def role_chains(self) -> dict[str, list[str]]:
        return {role: list(chain) for role, chain in self._role_chains.items()}

    def chain_for(self, role: str) -> list[str]:
        if role not in self._role_chains:
            known = ", ".join(sorted(self._role_chains)) or "none"
            raise GatewayError(f"unknown model role {role!r} (known roles: {known})")
        return list(self._role_chains[role])

    def _require_configured(self) -> None:
        if not self.configured:
            missing = []
            if not self._base_url:
                missing.append("GATEWAY_BASE_URL")
            if not self._api_key:
                missing.append("GATEWAY_API_KEY")
            raise GatewayNotConfigured(
                "model gateway not configured; missing server env: "
                + ", ".join(missing)
            )

    @property
    def _api_base(self) -> str:
        """Base URL normalised to end with /v1."""
        return self._base_url if self._base_url.endswith("/v1") else self._base_url + "/v1"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._api_base,
            transport=self._transport,
            timeout=httpx.Timeout(self._timeout),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    # -- calls ---------------------------------------------------------------

    async def chat_completion(
        self,
        role: str,
        messages: Sequence[Mapping[str, Any]],
        stream: bool = False,
        **params: Any,
    ) -> dict[str, Any] | AsyncIterator[str]:
        """Chat completion for a role, with fallback across its model chain.

        Non-streaming returns the gateway's parsed JSON response. With
        ``stream=True`` returns an async iterator of raw SSE lines; fallback
        applies while the response is being established (a transport failure
        mid-stream is not retried, to avoid duplicating partial output).
        """
        self._require_configured()
        chain = self.chain_for(role)
        if not chain:
            raise GatewayError(
                f"no models configured for role {role!r}; "
                f"set MODEL_{role.upper()} on the server"
            )
        if stream:
            return self._chat_stream(chain, messages, params)
        errors: dict[str, str] = {}
        async with self._client() as client:
            for model in chain:
                payload = {"model": model, "messages": list(messages), **params}
                try:
                    response = await client.post("/chat/completions", json=payload)
                except httpx.TransportError as exc:
                    errors[model] = f"connection error ({exc.__class__.__name__})"
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    errors[model] = _response_error_detail(response)
                    continue
                if response.status_code >= 400:
                    detail = _response_error_detail(response)
                    raise GatewayError(
                        f"gateway rejected the request for model {model!r}: {detail}",
                        {model: detail},
                    )
                return response.json()
        raise GatewayError(
            f"all models in the {role!r} chain failed: {errors}", errors
        )

    async def _chat_stream(
        self,
        chain: Sequence[str],
        messages: Sequence[Mapping[str, Any]],
        params: Mapping[str, Any],
    ) -> AsyncIterator[str]:
        errors: dict[str, str] = {}
        async with self._client() as client:
            for model in chain:
                payload = {
                    "model": model,
                    "messages": list(messages),
                    "stream": True,
                    **params,
                }
                try:
                    async with client.stream(
                        "POST", "/chat/completions", json=payload
                    ) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            errors[model] = f"HTTP {response.status_code}"
                            continue
                        if response.status_code >= 400:
                            detail = _response_error_detail(response)
                            raise GatewayError(
                                f"gateway rejected the request for model {model!r}: {detail}",
                                {model: detail},
                            )
                        async for line in response.aiter_lines():
                            yield line
                        return
                except httpx.TransportError as exc:
                    errors[model] = f"connection error ({exc.__class__.__name__})"
                    continue
        raise GatewayError(f"all models in the chain failed: {errors}", errors)

    async def generate_image(
        self,
        prompt: str,
        model: str | None = None,
        size: str | None = None,
    ) -> dict[str, Any]:
        """Image generation via POST {base}/v1/images/generations.

        There is no dedicated image role chain: an explicit ``model`` wins,
        otherwise the first model of the ``smart`` chain is used. Unlike
        chat there is no fallback — the gateway's payload (or its error)
        is what the caller gets. Returns the gateway's parsed JSON
        response unchanged.
        """
        self._require_configured()
        if not model:
            chain = self._role_chains.get("smart") or []
            if not chain:
                raise GatewayError(
                    "no image model requested and no default is configured; "
                    "pass a model name or set MODEL_SMART on the server"
                )
            model = chain[0]
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "n": 1}
        if size:
            payload["size"] = size
        async with self._client() as client:
            try:
                response = await client.post("/images/generations", json=payload)
            except httpx.TransportError as exc:
                raise GatewayError(
                    f"could not reach the gateway ({exc.__class__.__name__})"
                ) from exc
        if response.status_code >= 400:
            detail = _response_error_detail(response)
            raise GatewayError(
                f"gateway image generation failed for model {model!r}: {detail}",
                {model: detail},
            )
        return response.json()

    async def list_models(self) -> list[dict[str, Any]]:
        """Models the gateway currently serves (GET {base}/v1/models)."""
        self._require_configured()
        async with self._client() as client:
            try:
                response = await client.get("/models")
            except httpx.TransportError as exc:
                raise GatewayError(
                    f"could not reach the gateway ({exc.__class__.__name__})"
                ) from exc
        if response.status_code >= 400:
            raise GatewayError(
                f"gateway /models failed: {_response_error_detail(response)}"
            )
        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        return []
