"""Hugging Face Inference API adapter (secondary reasoning provider).

Speaks the OpenAI-compatible ``/chat/completions`` contract exposed by the
Hugging Face router, including standard ``tools`` function calling. Used to
continue an in-flight investigation when Gemini is rate limited, timing out,
failing or unconfigured - with the *same* messages, tool definitions and
output schema, so investigation state survives the switch.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .base import (
    ProviderAdapter,
    ProviderError,
    ProviderErrorKind,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderToolCall,
    ProviderUsage,
)


class HuggingFaceAdapter(ProviderAdapter):
    id = "huggingface"
    role = "secondary"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://router.huggingface.co/v1",
        timeout_s: float = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(model=model, timeout_s=timeout_s)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
        )

    # ------------------------------------------------------------------ #
    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_messages(messages: list[ProviderMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                out.append({"role": "system", "content": msg.content})
            elif msg.role == "user":
                out.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": msg.content or None}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": json.dumps(c.arguments, default=str),
                            },
                        }
                        for c in msg.tool_calls
                    ]
                out.append(entry)
            elif msg.role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id or "",
                        "content": msg.content,
                    }
                )
        return out

    @staticmethod
    def _build_body(request: ProviderRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.metadata.get("model"),
            "messages": HuggingFaceAdapter._build_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_response:
            body["response_format"] = {"type": "json_object"}
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
            body["tool_choice"] = "auto"
        return body

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}

    @classmethod
    def _parse_response(cls, data: dict[str, Any], request: ProviderRequest) -> ProviderResponse:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.INVALID_RESPONSE,
                message=f"Hugging Face returned no choices: {json.dumps(data, default=str)[:200]}",
                status_code=200,
            )
        message = choices[0].get("message") or {}
        text = message.get("content") or ""
        tool_calls: list[ProviderToolCall] = []
        for i, call in enumerate(message.get("tool_calls") or []):
            fn = call.get("function") or {}
            tool_calls.append(
                ProviderToolCall(
                    id=str(call.get("id") or f"call_{i}"),
                    name=str(fn.get("name") or ""),
                    arguments=cls._parse_tool_arguments(fn.get("arguments")),
                )
            )
        usage_raw = data.get("usage") or {}
        usage = ProviderUsage(
            input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
        )
        finish = str(choices[0].get("finish_reason") or "stop")
        return ProviderResponse(
            provider="huggingface",
            model=str(data.get("model") or request.metadata.get("model", "")),
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish,
            usage=usage,
            raw_excerpt=json.dumps(data, default=str)[:500],
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response, body_text: str) -> None:
        code = resp.status_code
        snippet = body_text[:400]
        lowered = body_text.lower()
        if code == 429:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.RATE_LIMIT,
                message="Hugging Face rate limit exceeded",
                status_code=code,
            )
        if code in (401, 403):
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.AUTH,
                message=(
                    f"Hugging Face rejected the API key (HTTP {code}). "
                    "Check HF_API_KEY / MULEGRAPH_AI_HF_API_KEY. " + snippet
                ),
                status_code=code,
            )
        if code == 404:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.CONFIG,
                message=f"model not found on Hugging Face (HTTP 404): {snippet}",
                status_code=code,
            )
        if code == 400:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.REQUEST,
                message=f"bad request to Hugging Face: {snippet}",
                status_code=code,
            )
        if code == 402:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.CONFIG,
                message=(
                    "Hugging Face account has no inference credits (HTTP 402): "
                    "add pay-as-you-go credits or subscribe to PRO, or unset "
                    "HF_API_KEY to run Gemini-only. " + snippet
                ),
                status_code=code,
            )
        if code in (502, 503, 504) or "loading" in lowered or "overloaded" in lowered:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.UNAVAILABLE,
                message=f"Hugging Face model unavailable (HTTP {code}): {snippet}",
                status_code=code,
            )
        if code >= 500:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.SERVER_ERROR,
                message=f"Hugging Face server error (HTTP {code}): {snippet}",
                status_code=code,
            )
        raise ProviderError(
            provider="huggingface",
            kind=ProviderErrorKind.UNKNOWN,
            message=f"unexpected Hugging Face response (HTTP {code}): {snippet}",
            status_code=code,
        )

    # ------------------------------------------------------------------ #
    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        if not self.configured:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.CONFIG,
                message="Hugging Face is not configured (set HF_API_KEY)",
            )
        body = self._build_body(request)
        body["model"] = request.metadata.get("model", self.model)
        started = time.perf_counter()
        try:
            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "authorization": f"Bearer {self.api_key}",
                    "content-type": "application/json",
                },
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.TIMEOUT,
                message=f"Hugging Face request timed out after {self.timeout_s}s",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.UNAVAILABLE,
                message=f"could not reach Hugging Face API: {exc}",
            ) from exc

        if resp.status_code >= 400:
            self._raise_for_status(resp, resp.text)

        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.INVALID_RESPONSE,
                message=f"Hugging Face returned non-JSON body: {resp.text[:200]}",
                status_code=resp.status_code,
            ) from exc

        # Some inference endpoints answer 200 with an embedded error object.
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            msg = err if isinstance(err, str) else json.dumps(err, default=str)
            raise ProviderError(
                provider="huggingface",
                kind=ProviderErrorKind.UNAVAILABLE,
                message=f"Hugging Face error payload: {msg[:300]}",
                status_code=200,
            )

        response = self._parse_response(data, request)
        if not response.model:
            response.model = self.model
        response.latency_ms = (time.perf_counter() - started) * 1000.0
        return response


__all__ = ["HuggingFaceAdapter"]
