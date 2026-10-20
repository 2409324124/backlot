"""The client library a request's headers name, sent as ``backlot.client``."""

from __future__ import annotations

import re
from typing import Mapping

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
