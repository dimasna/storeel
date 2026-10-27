"""HTTP client for Meta's Model API (https://dev.meta.ai/docs).

One client covers every model the studio uses:

* `responses()` streams `POST /v1/responses`, which serves Muse Spark (text and video
  understanding), Muse Image (image generation) and SAM 3.1 (segmentation). Streaming is
  used for every call because non-streaming requests have a server-side time limit (504)
  and reasoning can be slow before the first token.
* `upload_file()` / `delete_file()` wrap the Files API, for videos sent to Muse Spark.
* `transcribe()` wraps Muse Voice Transcribe's file endpoint, `POST /v1/asr/transcribe`.

Requests are retried with exponential backoff and jitter on 429 and transient 5xx errors,
honouring `Retry-After`; other client errors are raised immediately (they need a fix, not a
retry). User content is never written to the log, only sizes and timings.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from ..common import CancelCheck, Cancelled, sleep_unless_cancelled

log = logging.getLogger(__name__)

# 504 is left out on purpose: the docs say the same request usually times out again.
RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 503})
RETRY_CODES = frozenset(
    {
        "server_error",
        "rate_limit_exceeded",
        "service_overloaded",
        "backend_unavailable",
        "server_shutting_down",
    }
)
MAX_RETRY_AFTER = 90.0


class MetaAPIError(RuntimeError):
    """A failed Model API call, with the fields of the API's error envelope."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        error_type: str | None = None,
        code: str | None = None,
        param: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_type = error_type
        self.code = code
        self.param = param
        self.retryable = retryable
        self.retry_after = retry_after

    def __str__(self) -> str:
        details = [str(x) for x in (self.status, self.code or self.error_type) if x]
        return f"{self.message} ({', '.join(details)})" if details else self.message

    @property
    def content_policy(self) -> bool:
        return (self.code or "") == "content_policy_violation"


@dataclass
class ResponseResult:
    """The final `response` object of a streamed Responses call."""

    raw: dict[str, Any]
    text: str
    images: list[str] = field(default_factory=list)  # base64 image_generation_call results
    seconds: float = 0.0

    @property
    def usage(self) -> dict[str, Any]:
        return self.raw.get("usage") or {}

    @property
    def input_tokens(self) -> int:
        return int(self.usage.get("input_tokens") or 0)

    @property
    def output_tokens(self) -> int:
        return int(self.usage.get("output_tokens") or 0)

    @property
    def cached_tokens(self) -> int:
        return int((self.usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)

    @property
    def reasoning_tokens(self) -> int:
        return int((self.usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0)


def output_text(response: dict[str, Any]) -> str:
    """The text of every `output_text` part in a response's message items."""
    parts: list[str] = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and part.get("text"):
                parts.append(part["text"])
    return "".join(parts)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return min(MAX_RETRY_AFTER, max(0.0, float(value)))
    except ValueError:
        pass
    try:
        return min(MAX_RETRY_AFTER, max(0.0, parsedate_to_datetime(value).timestamp() - time.time()))
    except (TypeError, ValueError):
        return None


def _error_from_response(response: httpx.Response) -> MetaAPIError:
    status = response.status_code
    message = error_type = code = param = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        message = err.get("message")
        error_type = err.get("type")
        code = err.get("code")
        param = err.get("param")
    if not message:
        text = response.text.strip()[:300] if response.content else ""
        message = text or response.reason_phrase or f"HTTP {status}"
    retryable = status in RETRY_STATUSES or (code or "") in RETRY_CODES
    return MetaAPIError(
        str(message),
        status=status,
        error_type=error_type,
        code=code,
        param=param,
        retryable=retryable,
        retry_after=_retry_after(response),
    )


def _stream_error(event: dict[str, Any], fallback: str) -> MetaAPIError:
    err = event.get("error") if isinstance(event.get("error"), dict) else event
    code = err.get("code")
    message = err.get("message") or fallback
    # An error without a code is most likely a transient server fault; content and request
    # errors carry a code (or arrive as an HTTP 4xx before the stream starts).
    retryable = code is None or code in RETRY_CODES
    return MetaAPIError(str(message), error_type=err.get("type"), code=code, retryable=retryable)


def iter_sse(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Parse server-sent events into their JSON `data` payloads."""
    data: list[str] = []
    for line in lines:
        if line == "":
            if data:
                payload = "\n".join(data)
                data = []
                if payload.strip() == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    log.warning("skipping a malformed server-sent event (%d bytes)", len(payload))
            continue
        if line.startswith(":"):
            continue  # comment / keep-alive
        name, _, value = line.partition(":")
        if name == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    if data and "\n".join(data).strip() != "[DONE]":
        try:
            yield json.loads("\n".join(data))
        except json.JSONDecodeError:
            log.warning("skipping a truncated server-sent event")


class MetaClient:
    """A thread-safe client; one instance can serve every worker thread."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.meta.ai/v1",
        *,
        max_attempts: int = 4,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        self.max_attempts = max_attempts
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "storeel-studio/0.1"},
            # Reasoning can stay silent for minutes before the first streamed token.
            timeout=httpx.Timeout(connect=20.0, read=900.0, write=600.0, pool=60.0),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> MetaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- retries --------------------------------------------------------------------------

    def _backoff(self, attempt: int, error: MetaAPIError | None) -> float:
        if error is not None and error.retry_after is not None:
            return error.retry_after + random.uniform(0, 0.5)
        return min(30.0, 1.0 * 2 ** (attempt - 1)) + random.uniform(0, 0.5)

    def _request(
        self,
        method: str,
        path: str,
        *,
        cancel: CancelCheck | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        for attempt in range(1, self.max_attempts + 1):
            if cancel is not None and cancel():
                raise Cancelled
            started = time.monotonic()
            error: MetaAPIError
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                error = MetaAPIError(f"network error calling {path}: {exc}", retryable=True)
            else:
                log.info(
                    "%s %s -> %d in %.1fs", method, path, response.status_code, time.monotonic() - started
                )
                if response.status_code < 400:
                    return response
                error = _error_from_response(response)
            if not error.retryable or attempt == self.max_attempts:
                raise error
            delay = self._backoff(attempt, error)
            log.warning("%s %s failed (%s); retry %d in %.1fs", method, path, error, attempt, delay)
            sleep_unless_cancelled(delay, cancel)
        raise AssertionError("unreachable")

    # ---- Responses API ----------------------------------------------------------------------

    def responses(
        self,
        payload: dict[str, Any],
        *,
        cancel: CancelCheck | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ResponseResult:
        """Stream one Responses API call and return its final response."""
        body = {**payload, "stream": True}
        model = body.get("model", "?")
        for attempt in range(1, self.max_attempts + 1):
            if cancel is not None and cancel():
                raise Cancelled
            started = time.monotonic()
            try:
                return self._stream_once(body, cancel, on_text, started)
            except httpx.TransportError as exc:
                error = MetaAPIError(f"network error streaming {model}: {exc}", retryable=True)
            except MetaAPIError as exc:
                error = exc
            if not error.retryable or attempt == self.max_attempts:
                raise error
            delay = self._backoff(attempt, error)
            log.warning("responses (%s) failed (%s); retry %d in %.1fs", model, error, attempt, delay)
            sleep_unless_cancelled(delay, cancel)
        raise AssertionError("unreachable")

    def _stream_once(
        self,
        body: dict[str, Any],
        cancel: CancelCheck | None,
        on_text: Callable[[str], None] | None,
        started: float,
    ) -> ResponseResult:
        text: list[str] = []
        images: list[str] = []
        with self._http.stream(
            "POST", "/responses", json=body, headers={"Accept": "text/event-stream"}
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise _error_from_response(response)
            for event in iter_sse(response.iter_lines()):
                if cancel is not None and cancel():
                    raise Cancelled
                kind = event.get("type", "")
                if kind == "response.output_text.delta":
                    delta = event.get("delta") or ""
                    text.append(delta)
                    if on_text is not None:
                        on_text(delta)
                elif kind == "response.output_item.done":
                    item = event.get("item") or {}
                    if item.get("type") == "image_generation_call" and item.get("result"):
                        images.append(item["result"])
                elif kind == "response.completed":
                    final = event.get("response") or {}
                    seconds = time.monotonic() - started
                    final_images = [
                        item["result"]
                        for item in final.get("output") or []
                        if item.get("type") == "image_generation_call" and item.get("result")
                    ]
                    usage = final.get("usage") or {}
                    log.info(
                        "responses %s completed in %.1fs (in %s, out %s tokens)",
                        body.get("model"),
                        seconds,
                        usage.get("input_tokens", "?"),
                        usage.get("output_tokens", "?"),
                    )
                    return ResponseResult(
                        raw=final,
                        text=output_text(final) or "".join(text),
                        images=final_images or images,
                        seconds=seconds,
                    )
                elif kind == "response.incomplete":
                    details = (event.get("response") or {}).get("incomplete_details") or {}
                    reason = details.get("reason") or "unknown reason"
                    raise MetaAPIError(f"the response stopped early: {reason}", code=str(reason))
                elif kind == "response.failed":
                    raise _stream_error((event.get("response") or {}).get("error") or {}, "response failed")
                elif kind == "error":
                    raise _stream_error(event, "stream error")
        raise MetaAPIError("the stream ended before the response completed", retryable=True)

    # ---- Files API --------------------------------------------------------------------------

    def upload_file(
        self,
        path: Path,
        mime: str,
        *,
        expires_seconds: int = 3600,
        cancel: CancelCheck | None = None,
    ) -> str:
        """Upload a file for inference and return its id. It expires on its own as a safety net."""
        content = path.read_bytes()  # bytes, so a retry can resend the body
        # purpose and expires_after go before the file part, as the docs recommend.
        data = {
            "purpose": "user_data",
            "expires_after[anchor]": "created_at",
            "expires_after[seconds]": str(expires_seconds),
        }
        response = self._request(
            "POST", "/files", data=data, files={"file": (path.name, content, mime)}, cancel=cancel
        )
        file_id = response.json().get("id")
        if not file_id:
            raise MetaAPIError("the Files API returned no file id")
        log.info("uploaded %s (%.1f MB) as %s", path.name, len(content) / 1e6, file_id)
        return str(file_id)

    def delete_file(self, file_id: str) -> None:
        try:
            self._request("DELETE", f"/files/{file_id}")
        except MetaAPIError as exc:
            if exc.status != 404:
                log.warning("could not delete uploaded file %s: %s", file_id, exc)

    # ---- Muse Voice Transcribe --------------------------------------------------------------

    def transcribe(
        self,
        wav: Path,
        *,
        model: str,
        mode: str = "ENDPOINTING",
        language_bias: list[str] | None = None,
        keywords: list[str] | None = None,
        session_id: str | None = None,
        cancel: CancelCheck | None = None,
    ) -> dict[str, Any]:
        """Transcribe a mono 16-bit WAV (16 or 24 kHz, at most 10 minutes and 32 MB)."""
        request: dict[str, Any] = {"model": model, "audioEncoding": "WAV", "mode": mode}
        if language_bias:
            request["languageBias"] = language_bias
        if keywords:
            request["keywords"] = keywords
        files = {
            "request": (None, json.dumps(request), "application/json"),
            "audio": (wav.name, wav.read_bytes(), "audio/wav"),
        }
        response = self._request(
            "POST",
            "/asr/transcribe",
            files=files,
            params={"sessionId": session_id} if session_id else None,
            headers={"Accept": "application/json"},
            cancel=cancel,
        )
        return response.json()
