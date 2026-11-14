"""Google Gemini adapter (primary reasoning provider).

Uses the REST ``generateContent`` API directly through ``httpx`` so the
adapter stays independent of any SDK version drift. Function calling is
mapped to/from Gemini ``functionCall`` / ``functionResponse`` parts.

An ``httpx`` transport can be injected for tests (mocked provider APIs).
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


class GeminiAdapter(ProviderAdapter):
    id = "gemini"
    role = "primary"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
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
    def _model_name(self) -> str:
        return self.model.removeprefix("models/")

    def _url(self) -> str:
        return f"{self.base_url}/models/{self._model_name()}:generateContent"

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"content-type": "application/json"}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_contents(messages: list[ProviderMessage]) -> tuple[list[dict], dict | None]:
        """Split messages into Gemini ``contents`` + optional system instruction."""
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
                continue
            if msg.role == "user":
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
                continue
            if msg.role == "assistant":
                parts: list[dict[str, Any]] = []
                if msg.content:
                    parts.append({"text": msg.content})
                for call in msg.tool_calls:
                    parts.append(
                        {"functionCall": {"name": call.name, "args": call.arguments}}
                    )
                if parts:
                    contents.append({"role": "model", "parts": parts})
                continue
            if msg.role == "tool":
                # Gemini expects the function name on the response part.
                name = msg.name or "tool_result"
                try:
                    payload = json.loads(msg.content)
                    if not isinstance(payload, dict):
                        payload = {"result": payload}
                except (ValueError, TypeError):
                    payload = {"result": msg.content}
                contents.append(
                    {
                        "role": "user",
                        "parts": [{"functionResponse": {"name": name, "response": payload}}],
                    }
                )
        system = (
            {"parts": [{"text": "\n".join(system_parts)}]} if system_parts else None
        )
        return contents, system

    @staticmethod
    def _sanitize_schema(schema: Any) -> Any:
        """Strip JSON Schema keywords Gemini's ``Schema`` type rejects.

        Pydantic's ``model_json_schema()`` emits ``additionalProperties``
        (e.g. ``false``) which the Gemini REST API refuses with HTTP 400
        "Unknown name ... Cannot find field". Other keywords (``title``,
        ``default``, ``enum``, ``anyOf``, ``nullable``) are accepted as-is.
        Recurses through objects and arrays (``properties``, ``items``,
        ``anyOf``, ...).
        """
        if isinstance(schema, dict):
            return {
                k: GeminiAdapter._sanitize_schema(v)
                for k, v in schema.items()
                if k != "additionalProperties"
            }
        if isinstance(schema, list):
            return [GeminiAdapter._sanitize_schema(v) for v in schema]
        return schema

    @staticmethod
    def _build_body(request: ProviderRequest) -> dict[str, Any]:
        contents, system = GeminiAdapter._build_contents(request.messages)
        generation: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
        }
        if request.json_response:
            generation["responseMimeType"] = "application/json"
        body: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system is not None:
            body["systemInstruction"] = system
        if request.tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": GeminiAdapter._sanitize_schema(t.parameters),
                        }
                        for t in request.tools
                    ]
                }
            ]
        return body

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_response(data: dict[str, Any], request: ProviderRequest) -> ProviderResponse:
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.BLOCKED,
                message=f"prompt blocked by Gemini safety filter: {feedback['blockReason']}",
            )
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.INVALID_RESPONSE,
                message="Gemini returned no candidates",
                status_code=200,
            )
        candidate = candidates[0]
        parts = ((candidate.get("content") or {}).get("parts")) or []
        text_chunks: list[str] = []
        tool_calls: list[ProviderToolCall] = []
        for i, part in enumerate(parts):
            if "text" in part:
                text_chunks.append(str(part["text"]))
            if "functionCall" in part:
                fc = part["functionCall"]
                args = fc.get("args") or {}
                if not isinstance(args, dict):
                    args = {"value": args}
                tool_calls.append(
                    ProviderToolCall(
                        id=f"call_{len(tool_calls)}_{i}",
                        name=str(fc.get("name", "")),
                        arguments=args,
                    )
                )
        finish = str(candidate.get("finishReason", "STOP")).lower()
        finish_map = {"stop": "stop", "maxtokens": "length", "length": "length"}
        usage_meta = data.get("usageMetadata") or {}
        usage = ProviderUsage(
            input_tokens=int(usage_meta.get("promptTokenCount", 0) or 0),
            output_tokens=int(usage_meta.get("candidatesTokenCount", 0) or 0),
        )
        return ProviderResponse(
            provider="gemini",
            model=request.metadata.get("model", "gemini"),
            text="".join(text_chunks),
            tool_calls=tool_calls,
            finish_reason=finish_map.get(finish, finish),
            usage=usage,
            raw_excerpt=json.dumps(data, default=str)[:500],
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response, body_text: str) -> None:
        code = resp.status_code
        snippet = body_text[:400]
        lowered = body_text.lower()
        if code == 429:
            kind, retryable_msg = ProviderErrorKind.RATE_LIMIT, "Gemini rate limit exceeded"
            raise ProviderError("gemini", kind, retryable_msg, status_code=code)
        if code in (401, 403):
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.AUTH,
                message=(
                    "Gemini rejected the API key (HTTP "
                    f"{code}). Check GEMINI_API_KEY / MULEGRAPH_AI_GEMINI_API_KEY. {snippet}"
                ),
                status_code=code,
            )
        if code == 404:
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.CONFIG,
                message=(
                    "Gemini model not found (HTTP 404). "
                    "Check MULEGRAPH_AI_GEMINI_MODEL. " + snippet
                ),
                status_code=code,
            )
        if code == 400 and ("api key" in lowered or "key" in lowered and "invalid" in lowered):
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.AUTH,
                message=f"invalid Gemini API key: {snippet}",
                status_code=code,
            )
        if code == 400:
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.REQUEST,
                message=f"bad request to Gemini: {snippet}",
                status_code=code,
            )
        if code >= 500:
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.SERVER_ERROR,
                message=f"Gemini server error (HTTP {code}): {snippet}",
                status_code=code,
            )
        raise ProviderError(
            provider="gemini",
            kind=ProviderErrorKind.UNKNOWN,
            message=f"unexpected Gemini response (HTTP {code}): {snippet}",
            status_code=code,
        )

    # ------------------------------------------------------------------ #
    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        if not self.configured:
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.CONFIG,
                message="Gemini is not configured (set GEMINI_API_KEY)",
            )
        body = self._build_body(request)
        started = time.perf_counter()
        try:
            resp = await self._client.post(
                self._url(),
                headers=self._headers(),
                params={"key": self.api_key},
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.TIMEOUT,
                message=f"Gemini request timed out after {self.timeout_s}s",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.UNAVAILABLE,
                message=f"could not reach Gemini API: {exc}",
            ) from exc

        if resp.status_code >= 400:
            self._raise_for_status(resp, resp.text)

        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(
                provider="gemini",
                kind=ProviderErrorKind.INVALID_RESPONSE,
                message=f"Gemini returned non-JSON body: {resp.text[:200]}",
                status_code=resp.status_code,
            ) from exc

        response = self._parse_response(data, request)
        response.model = self.model
        response.latency_ms = (time.perf_counter() - started) * 1000.0
        return response


__all__ = ["GeminiAdapter"]
