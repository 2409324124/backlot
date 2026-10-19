"""The cause each error code stands for, sent beside the code as ``backlot.error_class``.

| Class | The call failed because |
|---|---|
| ``client`` | the request was wrong |
| ``auth`` | the credential was missing, wrong, or not allowed |
| ``rate_limit`` | the vendor's rate limit was reached |
| ``unsupported`` | Backlot does not do this yet |
| ``internal`` | of a Backlot bug |

A vendor code is classed by what the vendor means by it; Google's ``notImplemented`` is ``client``,
because the real API answers it too. A code this table does not hold is ``unclassified``, which is
what ``unrecognized`` always is: a message ``codes`` has no slug for.
"""

from __future__ import annotations

# source -> class -> codes
_CLASSES: dict[str, dict[str, tuple[str, ...]]] = {
    "confluence": {
        "client": (
            "content_not_found",
            "cql_required",
            "space_not_found",
        ),
        "auth": (
            "forbidden",
            "unauthenticated",
        ),
        "unsupported": ("no_endpoint",),
    },
    "fireflies": {
        "client": (
            "entity_not_found",
            "graphql_parse",
            "graphql_validation",
            "invalid_argument",
        ),
        "auth": (
            "authentication_required",
            "unauthorized",
        ),
        "unsupported": ("unsupported_filter",),
    },
    "github": {
        "client": (
            "branch_not_found",
            "invalid_sha",
            "no_commit_for_ref",
            "no_commit_for_sha",
            "not_found",
            "search_result_window",
            "unsupported_api_version",
            "validation_failed",
        ),
        "auth": (
            "bad_credentials",
            "requires_authentication",
        ),
        "rate_limit": ("rate_limited",),
    },
    "gmail": {
        "client": (
            "badRequest",
            "failedPrecondition",
            "fileNotDownloadable",
            "fileNotExportable",
            "invalid",
            "invalidAbuseAcknowledgment",
            "invalidArgument",
            "invalidParameter",
            "noListTeamDrivesAdministratorPrivilege",
            "notFound",
            "notImplemented",
            "orderByContainsDuplicateSortKeys",
            "pageTokenExpired",
            "parseError",
            "required",
            "supportsTeamDrivesRequired",
        ),
        "auth": (
            "authError",
            "forbidden",
        ),
        "internal": (
            "backendError",
            "internalError",
        ),
    },
    "google_drive": {
        "client": (
            "badRequest",
            "failedPrecondition",
            "fileNotDownloadable",
            "fileNotExportable",
            "invalid",
            "invalidAbuseAcknowledgment",
            "invalidArgument",
            "invalidParameter",
            "noListTeamDrivesAdministratorPrivilege",
            "notFound",
            "notImplemented",
            "orderByContainsDuplicateSortKeys",
            "pageTokenExpired",
            "parseError",
            "required",
            "supportsTeamDrivesRequired",
        ),
        "auth": (
            "authError",
            "forbidden",
        ),
        "internal": (
            "backendError",
            "internalError",
        ),
    },
    "hubspot": {
        "client": (
            "OBJECT_NOT_FOUND",
            "VALIDATION_ERROR",
        ),
        "auth": ("INVALID_AUTHENTICATION",),
    },
    "jira": {
        "client": (
            "invalid_max_results",
            "invalid_next_page_token",
            "invalid_order_by",
            "invalid_parameter",
            "invalid_payload",
            "issue_not_found",
            "project_not_found",
            "unbounded_jql",
            "unsupported_media_type",
        ),
        "auth": ("unauthenticated",),
        "unsupported": ("no_endpoint",),
    },
    "linear": {
        "client": (
            "INPUT_ERROR",
            "INVALID_INPUT",
            "entity_not_found",
            "graphql_parse",
            "graphql_validation",
        ),
        "auth": ("authentication_required",),
        "unsupported": ("unsupported_filter",),
    },
    "notion": {
        "client": (
            "missing_version",
            "object_not_found",
            "validation_error",
        ),
        "auth": (
            "invalid_client",
            "restricted_resource",
            "unauthorized",
        ),
        "unsupported": ("invalid_request_url",),
    },
    "s3": {
        "client": (
            "BadDigest",
            "BadRequest",
            "InvalidArgument",
            "InvalidDigest",
            "InvalidPartNumber",
            "InvalidRange",
            "InvalidRequest",
            "MalformedContinuationToken",
            "MalformedXML",
            "MetadataConfigurationNotFound",
            "MethodNotAllowed",
            "MissingContentLength",
            "MissingRequestBodyError",
            "NoLoggingStatusForKey",
            "NoSuchAnnotation",
            "NoSuchBucket",
            "NoSuchBucketPolicy",
            "NoSuchCORSConfiguration",
            "NoSuchConfiguration",
            "NoSuchKey",
            "NoSuchLifecycleConfiguration",
            "NoSuchTagSet",
            "NoSuchUpload",
            "NoSuchVersion",
            "NoSuchWebsiteConfiguration",
            "ObjectLockConfigurationNotFoundError",
            "PreconditionFailed",
            "RegionSetMismatch",
            "ReplicationConfigurationNotFoundError",
            "UserKeyMustBeSpecified",
            "V1APIsNotAllowed",
            "XAmzContentSHA256Mismatch",
        ),
        "auth": (
            "AccessDenied",
            "AccessForbidden",
            "AuthorizationHeaderMalformed",
            "AuthorizationQueryParametersError",
            "InvalidAccessKeyId",
            "RequestTimeTooSkewed",
            "SignatureDoesNotMatch",
        ),
        "unsupported": ("NotImplemented",),
        "internal": ("InternalError",),
    },
    "slack": {
        "client": (
            "channel_not_found",
            "invalid_arguments",
            "invalid_cursor",
            "invalid_ts_latest",
            "invalid_ts_oldest",
            "invalid_types",
            "no_query",
            "thread_not_found",
            "user_not_found",
        ),
        "auth": (
            "account_inactive",
            "invalid_auth",
            "not_authed",
        ),
    },
}

_BY_CODE = {
    (s, code): cls
    for s, classes in _CLASSES.items()
    for cls, codes in classes.items()
    for code in codes
}


def error_class(source: str, code: str) -> str:
    """The class of ``code`` as ``source`` emits it."""
    if code == "internal_error":
        return "internal"
    return _BY_CODE.get((source, code), "unclassified")
