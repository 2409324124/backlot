"""The ASGI middleware that counts each call, installed outermost by ``backlot.main``.

Outermost so that it sees every answer, including the ones a middleware gives without reaching a
route. It reads the request after the app has answered: by then the router has put the matched
route on the scope, the path rewrites have run, and the HEAD middleware has put the method back.
It reads an answer's body only to find an error code, and only for an error status, a Slack
``ok: false``, or a GraphQL answer.
"""

from __future__ import annotations

import base64
import re
import time
from typing import Any, Mapping
from urllib.parse import parse_qsl

from backlot import synth
from backlot.config import get_settings
from backlot.telemetry import codes, enabled
from backlot.telemetry.classes import error_class
from backlot.telemetry.naming import Namer, own_route
from backlot.telemetry.recorder import RECORDER, Recorder

_ERROR_BODY_CAP = 256 * 1024
_GRAPHQL_BODY_CAP = 4 * 1024 * 1024
_SIGV4_KEY = re.compile(r"Credential=([^/,\s]+)/")


class TelemetryMiddleware:
    def __init__(
        self, app: Any, recorder: Recorder | None = None, namer: Namer | None = None
    ) -> None:
        self.app = app
        settings = get_settings()
        self.on = enabled(settings)
        self.recorder = recorder or RECORDER
        self.namer = namer or Namer()
        self._admin = {settings.admin_token, synth.s3_access_key_id(settings.admin_token)}

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if not self.on or scope["type"] != "http" or own_route(scope["path"]):
            await self.app(scope, receive, send)
            return
        began = time.perf_counter()
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        query = dict(
            parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        )
        placed = self.namer.source_of(scope["path"])
        source = placed[0] if placed else "other"
        graphql = source in ("linear", "fireflies")

        request_body: bytes | None = None
        if graphql and scope["method"] == "POST":
            receive, request_body = await _buffered(receive)

        answer = {"status": 500, "body": bytearray(), "keep": False, "cap": 0, "ended": None}

        async def watch(message: dict) -> None:
            if message["type"] == "http.response.start":
                answer["status"] = message["status"]
                slack = source == "slack"
                answer["keep"] = graphql or slack or message["status"] >= 400
                answer["cap"] = _GRAPHQL_BODY_CAP if graphql else _ERROR_BODY_CAP
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if answer["keep"]:
                    if source == "slack" and answer["status"] < 400 and not answer["body"]:
                        answer["keep"] = chunk.startswith(b'{"ok":false')
                    if answer["keep"] and len(answer["body"]) + len(chunk) <= answer["cap"]:
                        answer["body"] += chunk
                if not message.get("more_body", False):
                    answer["ended"] = time.perf_counter()
            await send(message)

        try:
            await self.app(scope, receive, watch)
        except Exception:
            self._record(scope, headers, query, request_body, 500, "internal_error", began)
            raise
        code = (
            codes.error_code(source, answer["status"], bytes(answer["body"]))
            if answer["body"]
            else ""
        )
        self._record(
            scope, headers, query, request_body, answer["status"], code, began, answer["ended"]
        )

    def _record(self, scope, headers, query, request_body, status, code, began, ended=None) -> None:
        try:
            named = self.namer.name(
                method=scope["method"],
                path=scope["path"],
                route=scope.get("route"),
                query=query,
                headers=headers,
                graphql_body=request_body,
            )
            kind, credential = _credential(headers, query, scope)
            attributes = {
                "backlot.source": named.source,
                "backlot.operation": named.operation,
                "backlot.support": named.support,
                "http.request.method": scope["method"],
                "http.response.status_code": int(status),
                "backlot.auth.kind": kind,
                "backlot.caller.kind": "anonymous"
                if credential is None
                else "admin"
                if credential in self._admin
                else "user",
                "backlot.client": codes.client(headers),
            }
            if code:
                attributes["backlot.error_code"] = code
                attributes["backlot.error_class"] = error_class(named.source, code)
            self.recorder.record(attributes, ((ended or time.perf_counter()) - began) * 1000)
        except Exception:  # noqa: BLE001 — counting a call must never change the answer to it
            pass


async def _buffered(receive: Any) -> tuple[Any, bytes]:
    """Read the whole request body, and a ``receive`` that replays it to the app."""
    messages, body = [], bytearray()
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    replay = iter(messages)

    async def again() -> dict:
        try:
            return next(replay)
        except StopIteration:
            return await receive()

    return again, bytes(body)


def _credential(
    headers: Mapping[str, str], query: Mapping[str, str], scope: dict
) -> tuple[str, str | None]:
    """How the request authenticated, and the token or access key it did so with (None for none)."""
    authorization = headers.get("authorization", "")
    scheme, _, rest = authorization.partition(" ")
    scheme = scheme.lower()
    if scheme in ("bearer", "token"):
        return "bearer", rest.strip()
    if scheme == "basic":
        try:
            return "basic", base64.b64decode(rest.strip()).decode("utf-8", "replace").partition(
                ":"
            )[2]
        except ValueError:
            return "basic", ""
    if scheme.startswith("aws4"):
        m = _SIGV4_KEY.search(rest)
        return "sigv4", m.group(1) if m else ""
    if scheme == "aws":
        return "sigv2", rest.partition(":")[0].strip()
    if authorization.strip() and not rest:
        # A bare key, as Linear's personal API keys are sent.
        return "api_key", authorization.strip()
    if authorization:
        return "other", ""
    if "X-Amz-Credential" in query:
        return "presigned", query["X-Amz-Credential"].partition("/")[0]
    if "AWSAccessKeyId" in query:
        return "presigned", query["AWSAccessKeyId"]
    for name in ("hapikey", "key", "api_key"):
        if name in query:
            return "api_key", query[name]
    form = (scope.get("state") or {}).get("_form")
    token = form.get("token") if hasattr(form, "get") else None
    if token or "token" in query:
        return "bearer", token or query["token"]
    return "anonymous", None
