"""The cause a failed call is put down to, sent as ``backlot.error_class`` on every failure.

| Class | The call failed because |
|---|---|
| ``unsupported`` | Backlot does not do this yet: the baseline records the operation as ``missing`` or ``refused``, or the GraphQL engine refused a filter |
| ``internal`` | of a Backlot bug: an unhandled exception, or a 5xx other than 501 |
| ``rate_limit`` | the vendor's rate limit was reached: a 429, or a 403 with ``x-ratelimit-remaining: 0`` as GitHub sends |
| ``auth`` | the credential was missing, wrong, or not allowed: a 401 or 403, or Slack's auth errors, which it sends with a 200 |
| ``client`` | the request was wrong: any other failure |

The rules read the status, the baseline's support state and the response headers, so a new vendor
code is classed without a table. A 501 from an operation Backlot serves is the vendor's own answer
(Google's ``notImplemented``), so it is ``client``.
"""

from __future__ import annotations

_SLACK_AUTH = frozenset({"account_inactive", "invalid_auth", "not_authed"})


def error_class(source: str, support: str, status: int, code: str, spent: bool) -> str:
    """The class of a failed call; ``spent`` is whether it answered ``x-ratelimit-remaining: 0``."""
    if code == "internal_error":
        return "internal"
    if support in ("missing", "refused") or code == "unsupported_filter":
        return "unsupported"
    if status == 429 or (status == 403 and spent):
        return "rate_limit"
    if status in (401, 403) or (source == "slack" and code in _SLACK_AUTH):
        return "auth"
    if status >= 500 and status != 501:
        return "internal"
    return "client"
