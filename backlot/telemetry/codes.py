"""The error code an answer carries, and the client library a request names.

An error code is the vendor's own identifier where its envelope has one: Slack's ``error``, S3's
``<Code>``, Google's ``reason`` or else its ``status``, Notion's ``code``, HubSpot's ``category``, a
GraphQL ``extensions.code``. GitHub, Jira, Confluence and the GraphQL engine answer with a message only;
those messages are Backlot's own text, so each maps to a fixed slug here and the message itself,
which can carry a key, a sha or a field name from the request, is never sent. A message this table
does not know is ``unrecognized``.
"""

from __future__ import annotations

import json
import re
from typing import Mapping

# (pattern on the message, slug), first match wins.
_GITHUB = [
    (r"^Not Found$", "not_found"),
    (r"^Requires authentication$", "requires_authentication"),
    (r"^Bad credentials$", "bad_credentials"),
    (r"^Validation Failed$", "validation_failed"),
    (
        r"^(Only the first 1000 search results|Cannot access beyond the first 1000)",
        "search_result_window",
    ),
    (r"^The sha parameter must be exactly 40 characters", "invalid_sha"),
    (r"^No commit found for SHA: ", "no_commit_for_sha"),
    (r"^No commit found for the ref ", "no_commit_for_ref"),
    (r"^Branch not found$", "branch_not_found"),
    (r"^API rate limit exceeded", "rate_limited"),
    (r"^Bad Request$", "unsupported_api_version"),
]
_JIRA = [
    (r"^Issue does not exist or you do not have permission to see it", "issue_not_found"),
    (r"^No project could be found with key ", "project_not_found"),
    (r"^The field to order by must be one of", "invalid_order_by"),
    (r"^Unbounded JQL queries are not allowed", "unbounded_jql"),
    (r"^The maxResults parameter must be between", "invalid_max_results"),
    (r"^The provided nextPageToken is invalid", "invalid_next_page_token"),
    (
        r"^(Invalid request payload|No content to map|There was an error parsing JSON)",
        "invalid_payload",
    ),
    (r"^Failed to convert ", "invalid_parameter"),
    (r"^No endpoint ", "no_endpoint"),
    (r"^Unsupported Media Type", "unsupported_media_type"),
    (
        r"^(Client must be authenticated|Failed to parse Connect Session Auth Token)",
        "unauthenticated",
    ),
]
_CONFLUENCE = [
    (r"^No content found with id", "content_not_found"),
    (r"^No space (found )?with key", "space_not_found"),
    (r"^cql required", "cql_required"),
    (r"^Unauthorized$", "unauthenticated"),
    (r"^No endpoint ", "no_endpoint"),
    (r"FORBIDDEN", "forbidden"),
]
_GRAPHQL = [
    (r"^Syntax Error", "graphql_parse"),
    (r"^Entity not found", "entity_not_found"),
    (r"^unsupported ", "unsupported_filter"),
    (r"^(Authentication required|Please provide a valid API key)", "authentication_required"),
    (
        r"^(Cannot query field|Unknown argument|Unknown type|Field |Variable |Argument |Schema is not configured)",
        "graphql_validation",
    ),
]
_S3_CODE = re.compile(rb"<Code>([A-Za-z0-9_.-]{1,64})</Code>")


def _slug(message: object, table: list[tuple[str, str]]) -> str:
    if not isinstance(message, str):
        return "unrecognized"
    for pattern, slug in table:
        if re.search(pattern, message):
            return slug
    return "unrecognized"


def error_code(source: str, status: int, body: bytes) -> str:
    """The error code of an answer, ``""`` for an answer that is not an error or carries none."""
    if source == "s3":
        m = _S3_CODE.search(body) if status >= 400 else None
        return m.group(1).decode() if m else ""
    try:
        doc = json.loads(body)
    except ValueError:
        return ""
    if not isinstance(doc, dict):
        return ""
    if source == "slack":
        return (
            doc.get("error", "")
            if doc.get("ok") is False and isinstance(doc.get("error"), str)
            else ""
        )
    if source in ("linear", "fireflies"):
        errors = doc.get("errors")
        if not errors or not isinstance(errors, list) or not isinstance(errors[0], dict):
            return ""
        extensions = errors[0].get("extensions")
        code = extensions.get("code") if isinstance(extensions, dict) else None
        return code if isinstance(code, str) and code else _slug(errors[0].get("message"), _GRAPHQL)
    if status < 400:
        return ""
    if source == "github":
        return _slug(doc.get("message"), _GITHUB) if "message" in doc else ""
    if source in ("gmail", "google_drive"):
        error = doc.get("error")
        if not isinstance(error, dict):
            return ""
        # Docs, Sheets and Slides send no `errors[].reason`, only the canonical `status`.
        entries = error.get("errors")
        first = entries[0] if isinstance(entries, list) and entries else None
        reason = first.get("reason") if isinstance(first, dict) else None
        if isinstance(reason, str):
            return reason
        return error["status"] if isinstance(error.get("status"), str) else ""
    if source == "notion":
        return doc["code"] if isinstance(doc.get("code"), str) else ""
    if source == "hubspot":
        return doc["category"] if isinstance(doc.get("category"), str) else ""
    if source == "jira":
        messages = doc.get("errorMessages") or [doc.get("detail") or doc.get("message")]
        return _slug(messages[0] if messages else None, _JIRA) if any(messages) else ""
    if source == "confluence":
        message = doc.get("message") or doc.get("detail")
        return _slug(message, _CONFLUENCE) if message else ""
    return ""


# Measured from Backlot's own examples on 2026-10-14 (tests/telemetry_clients.json holds the
# headers each sent): (header, pattern, label). `{v}` is the major.minor the pattern captures.
_CLIENTS = [
    ("x-goog-api-client", r"\bgdcl/(\d+)\.(\d+)", "google-api-python-client/{v}"),
    ("x-goog-api-client", r"\bauth/(\d+)\.(\d+)", "google-auth/{v}"),
    ("user-agent", r"\bBoto3/(\d+)\.(\d+)", "boto3/{v}"),
    ("user-agent", r"\baiobotocore/(\d+)\.(\d+)", "aiobotocore/{v}"),
    ("user-agent", r"\b[Bb]otocore/(\d+)\.(\d+)", "botocore/{v}"),
    ("user-agent", r"\bslackclient/(\d+)\.(\d+)", "slack_sdk/{v}"),
    ("user-agent", r"\bhubspot-api-client-python; (\d+)\.(\d+)", "hubspot-api-client/{v}"),
    ("user-agent", r"\bnotion-sdk-py@(\d+)\.(\d+)", "notion-client/{v}"),
    ("user-agent", r"^PyGithub/", "PyGithub"),
    ("user-agent", r"\baiohttp/(\d+)\.(\d+)", "aiohttp/{v}"),
    ("user-agent", r"^python-httpx2/(\d+)\.(\d+)", "python-httpx2/{v}"),
    ("user-agent", r"^python-httpx/(\d+)\.(\d+)", "python-httpx/{v}"),
    ("user-agent", r"^python-requests/(\d+)\.(\d+)", "python-requests/{v}"),
    ("user-agent", r"^Python-urllib/(\d+)\.(\d+)", "python-urllib/{v}"),
    ("user-agent", r"^Python-httplib2/(\d+)\.(\d+)", "httplib2/{v}"),
    ("user-agent", r"^curl/(\d+)\.(\d+)", "curl/{v}"),
    ("user-agent", r"^node$", "node"),
]


def client(headers: Mapping[str, str]) -> str:
    """The library a request's headers name; ``other`` when none of the rules matches."""
    for name, pattern, label in _CLIENTS:
        m = re.search(pattern, headers.get(name, ""))
        if m:
            return label.format(v=".".join(m.groups())) if m.groups() else label
    return "other"
