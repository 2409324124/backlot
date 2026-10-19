# Usage telemetry

A running Backlot server counts which vendor operations it is asked for and sends the counts to `https://telemetry.brekkylab.com/v1/metrics` once a minute. The counts show which sources and operations people use, which ones they ask for that Backlot does not serve yet, and where answers fail. That decides what gets built next.

It is anonymous and coarse by design. It counts calls, never callers. Nothing in it identifies a person, a machine or an installation. Nothing from your corpus or your requests is sent.

## Turning it off

| How | Where |
|---|---|
| `backlot serve --disable-telemetry` | The CLI |
| `backlot mcp --disable-telemetry` | The MCP bridge, for the server it starts when none is running |
| `backlot.serve(telemetry=False)`, `backlot.serve_or_connect(telemetry=False)` | Python, for the server it starts |
| `BACKLOT_TELEMETRY=false` | The environment, for any server started from it, Docker included |

Turn it off wherever Backlot runs for something other than your own use of it: a test suite, a CI job, a benchmark harness. A server that sends telemetry says so on stderr when it starts.

## What is sent

Two OTLP metrics, as delta counts over each interval:

- `backlot.http.requests`: calls.
- `backlot.http.duration`: how long Backlot took to answer, as a histogram in milliseconds.

Each count carries these attributes:

| Attribute | Value |
|---|---|
| `backlot.source` | The source whose API the path belongs to: `github`, `slack`, `gmail`, `google_drive`, `jira`, `confluence`, `notion`, `s3`, `hubspot`, `linear`, `fireflies`, or `other` for a path under none |
| `backlot.operation` | The vendor operation, by the vendor's own id, e.g. `repos/list-commits`, `conversations.history`, `ListObjectsV2`, `query.issues` |
| `backlot.support` | `implemented`, `extra` (a route the vendor's contract does not describe), `refused` (routed only to be refused, as S3 writes are), `missing` (the vendor has it and this Backlot does not), or `unknown` |
| `http.request.method` | `GET`, `POST`, … |
| `http.response.status_code` | The status Backlot answered with |
| `backlot.error_code` | The vendor's error identifier when the answer is an error, e.g. `channel_not_found`, `NoSuchKey`, `not_found` |
| `backlot.auth.kind` | `bearer`, `basic`, `api_key`, `sigv4`, `sigv2`, `presigned`, `other` or `anonymous` |
| `backlot.caller.kind` | `admin`, `user` or `anonymous` |
| `backlot.client` | The client library the request headers name, by name and major.minor version, e.g. `slack_sdk/3.44`, `boto3/1.40`, `python-requests/2.34`, or `other` |

Each export carries the Backlot version, the operating system family (`darwin`, `linux`, `windows`) and the Python version.

## What is never sent

- Paths, query strings and request or response bodies.
- GraphQL documents, variables, aliases or argument values.
- Error messages. An error is sent as its fixed code only.
- Tokens, keys, emails and user names.
- Anything from your corpus: channel, repository, bucket, key, page or issue names and ids.
- Any identifier of the installation, the machine or the person, and no `User-Agent` string as sent.

An operation's name comes from Backlot's own fidelity baselines (`backlot/fidelity/baseline/`), which record every operation of each vendor's contract, never from the request. A request that asks for something no baseline names is counted as `unmatched`, and a GraphQL field outside the vendor's schema as `query.unmatched`.

## The code

`backlot/telemetry/` is all of it: the middleware that counts, the naming, and the exporter. `tests/test_telemetry.py` holds it to this page, including a test that a marker placed in every part of a request never reaches an export.
