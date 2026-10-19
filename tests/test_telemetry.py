"""Usage telemetry: when it is on, how a call is named, what an export carries, and what it never
carries. Served over the bundled hello corpus, with an export endpoint nothing listens on unless a
test starts one."""

from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backlot.config import get_settings
from backlot.server import HELLO_CORPUS
from backlot.telemetry import codes, enabled, naming, notice, recorder
from backlot.telemetry.classes import error_class
from backlot.telemetry.recorder import MAX_SERIES, RECORDER, Exporter, Recorder, encode
from tests._helpers import build_corpus, client_for

ADMIN = {"Authorization": "Bearer admin-service-token"}
LINEAR = {"Authorization": "admin-service-token"}
UNREACHABLE = "http://127.0.0.1:9/v1/metrics"
# What the collector stores (brekkylab-telemetry-collector, collector/config.yaml); anything else
# it replaces with `invalid`.
STORED = {
    "backlot.source": r"^(github|slack|gmail|google_drive|jira|confluence|notion|s3|hubspot|linear|fireflies|other)$",
    "backlot.support": r"^(implemented|extra|refused|missing|unknown)$",
    "backlot.operation": r"^[A-Za-z_][A-Za-z0-9_.,/+{}-]{0,127}$",
    "backlot.error_code": r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$",
    "backlot.client": r"^[A-Za-z0-9@_.-]{1,48}(/[0-9]+[.][0-9]+)?$",
    "backlot.error_class": r"^(client|auth|rate_limit|unsupported|internal|unclassified)$",
}


@pytest.fixture(scope="module")
def hello(tmp_path_factory):
    records = [
        json.loads(line)
        for line in HELLO_CORPUS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return build_corpus(tmp_path_factory.mktemp("hello"), records, raw=True)


def _env(**values):
    """Set environment variables for a block, restoring what was there."""
    saved = {k: os.environ.get(k) for k in values}

    class _Restore:
        def __enter__(self):
            for k, v in values.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        def __exit__(self, *exc):
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    return _Restore()


class _ExportTo:
    """Point the server's exporter at ``url``, exporting only at shutdown."""

    def __init__(self, url):
        self.url = url

    def __enter__(self):
        self.saved = recorder.ENDPOINT, recorder.INTERVAL
        recorder.ENDPOINT, recorder.INTERVAL = self.url, 3600.0

    def __exit__(self, *exc):
        recorder.ENDPOINT, recorder.INTERVAL = self.saved


@pytest.fixture(scope="module")
def client(hello):
    with _env(BACKLOT_TELEMETRY="1"), _ExportTo(UNREACHABLE):
        with client_for(hello) as c:
            yield c


def _calls(send) -> list[dict]:
    """The calls recorded while ``send`` ran, one dict per attribute combination, with its count."""
    RECORDER.take()
    send()
    _, _, counts, _ = RECORDER.take()
    return [dict(key) | {"count": n} for key, n in counts.items()]


def test_it_is_on_unless_backlot_telemetry_says_off(hello, capsys):
    with _env(BACKLOT_TELEMETRY=None):
        get_settings.cache_clear()
        assert enabled(get_settings())
    with _env(BACKLOT_TELEMETRY="1"), _ExportTo(UNREACHABLE):
        capsys.readouterr()
        with client_for(hello):
            pass
        # A server that sends says so, says why, and says how to stop it.
        assert capsys.readouterr().err.strip() == notice(UNREACHABLE)
    for off in ("0", "false"):
        with _env(BACKLOT_TELEMETRY=off), _ExportTo(UNREACHABLE):
            get_settings.cache_clear()
            assert not enabled(get_settings())
            with client_for(hello) as c:
                assert _calls(lambda: c.get("/github/repos/acme/docs-site", headers=ADMIN)) == []
            assert "usage counts" not in capsys.readouterr().err
    get_settings.cache_clear()


class _Started(Exception):
    pass


def test_each_way_to_start_a_server_can_turn_it_off(monkeypatch, hello):
    import uvicorn
    from typer.testing import CliRunner

    import backlot.cli
    import backlot.mcp

    seen = []

    def capture(*args, **kwargs):
        seen.append(
            enabled(get_settings())
            if "env" not in kwargs
            else kwargs["env"].get("BACKLOT_TELEMETRY")
        )
        raise _Started

    monkeypatch.setattr(uvicorn, "run", capture)
    monkeypatch.setattr(backlot.mcp, "run", capture)
    monkeypatch.setattr(backlot.server.subprocess, "Popen", capture)
    data_dir = str(hello.data_dir)
    # `--data-dir` and `--disable-telemetry` write the environment; both are put back afterwards.
    with _env(BACKLOT_TELEMETRY=None, BACKLOT_DATA_DIR=os.environ.get("BACKLOT_DATA_DIR")):
        runner = CliRunner()
        for argv in (
            ["serve", "--data-dir", data_dir],
            ["serve", "--disable-telemetry", "--data-dir", data_dir],
            ["mcp", "--data-dir", data_dir],
            ["mcp", "--disable-telemetry", "--data-dir", data_dir],
        ):
            os.environ.pop("BACKLOT_TELEMETRY", None)
            get_settings.cache_clear()
            assert isinstance(runner.invoke(backlot.cli.app, argv).exception, _Started)
        for telemetry in (True, False):
            os.environ.pop("BACKLOT_TELEMETRY", None)
            with pytest.raises(_Started):
                with backlot.server.serve(data_dir=hello.data_dir, telemetry=telemetry):
                    pass
    get_settings.cache_clear()
    assert seen == [True, False, True, False, None, "0"]


def test_client_labels_are_the_ones_measured_from_the_examples():
    cases = json.loads(
        (Path(__file__).parent / "telemetry_clients.json").read_text(encoding="utf-8")
    )["cases"]
    assert [codes.client(c["headers"]) for c in cases] == [c["client"] for c in cases]
    assert codes.client({"user-agent": "curl/8.7.1"}) == "curl/8.7"


def test_every_slug_backlot_writes_has_a_class():
    tables = {"github": codes._GITHUB, "jira": codes._JIRA, "confluence": codes._CONFLUENCE}
    tables |= {"linear": codes._GRAPHQL, "fireflies": codes._GRAPHQL}
    unclassed = [
        (s, slug)
        for s, t in tables.items()
        for _, slug in t
        if error_class(s, slug) == "unclassified"
    ]
    assert unclassed == []
    assert error_class("s3", "internal_error") == "internal"
    assert error_class("github", "unrecognized") == "unclassified"


GITHUB = "/github/repos/acme/docs-site"


@pytest.mark.parametrize(
    "method, path, kwargs, expected",
    [
        # (source, operation, support, status, error code)
        ("GET", GITHUB, {}, ("github", "repos/get", "implemented", 200, None)),
        ("HEAD", GITHUB, {}, ("github", "repos/get", "implemented", 200, None)),
        (
            "GET",
            "/github/repos/acme/nosuch",
            {},
            ("github", "repos/get", "implemented", 404, "not_found"),
        ),
        ("GET", f"{GITHUB}/commits", {}, ("github", "repos/list-commits", "missing", 307, None)),
        (
            "POST",
            f"{GITHUB}/issues",
            {"json": {"title": "t"}},
            ("github", "issues/create", "missing", 405, None),
        ),
        (
            "GET",
            f"{GITHUB}/actions/runs",
            {},
            ("github", "actions/list-workflow-runs-for-repo", "missing", 404, "not_found"),
        ),
        (
            "POST",
            "/slack/api/conversations.history",
            {"data": {"channel": "CNOPE"}},
            ("slack", "conversations.history", "implemented", 200, "channel_not_found"),
        ),
        (
            "POST",
            "/slack/api/chat.postMessage",
            {},
            ("slack", "chat.postMessage", "missing", 404, None),
        ),
        (
            "GET",
            "/atlassian/rest/api/3/project/ENG",
            {},
            ("jira", "getProject", "missing", 404, "no_endpoint"),
        ),
        (
            "GET",
            "/gmail/v1/users/me/messages",
            {},
            ("gmail", "gmail.users.messages.list", "implemented", 200, None),
        ),
        (
            "GET",
            "/gmail/v1/users/me/drafts",
            {},
            ("gmail", "gmail.users.drafts.list", "missing", 404, None),
        ),
        # A bearer token is no S3 credential; real answers it InvalidArgument, and so does Backlot.
        (
            "GET",
            "/s3/acme-artifacts?list-type=2",
            {},
            ("s3", "ListObjectsV2", "implemented", 400, "InvalidArgument"),
        ),
        (
            "PUT",
            "/s3/acme-artifacts/k.txt",
            {"content": b"x"},
            ("s3", "PutObject", "refused", 400, "InvalidArgument"),
        ),
        (
            "GET",
            "/calendar/v3/calendars/primary/events",
            {},
            ("other", "unmatched", "unknown", 404, None),
        ),
    ],
)
def test_a_call_is_named_by_the_baseline(client, method, path, kwargs, expected):
    calls = _calls(
        lambda: client.request(method, path, headers=ADMIN, follow_redirects=False, **kwargs)
    )
    assert len(calls) == 1, calls
    c = calls[0]
    got = (
        c["backlot.source"],
        c["backlot.operation"],
        c["backlot.support"],
        c["http.response.status_code"],
        c.get("backlot.error_code"),
    )
    assert got == expected
    assert c["http.request.method"] == method
    assert c.get("backlot.error_class") == (
        error_class(c["backlot.source"], got[4]) if got[4] else None
    )


@pytest.mark.parametrize(
    "query, expected",
    [
        ("{ issues(first: 1) { nodes { id } } }", ("query.issues", "implemented", 200, None)),
        (
            '{ issue(id: "x") { id } teams { nodes { id } } }',
            ("query.issue,teams", "implemented", 200, "entity_not_found"),
        ),
        ("{ projects { nodes { id } } }", ("query.projects", "missing", 400, "graphql_validation")),
        ("{ notAField }", ("query.unmatched", "unknown", 400, "graphql_validation")),
        (
            'mutation { issueCreate(input: {title: "x", teamId: "t"}) { success } }',
            ("mutation", "unknown", 400, "graphql_validation"),
        ),
        ("{ issues {", ("unparsed", "unknown", 400, "graphql_parse")),
        ("{ __schema { queryType { name } } }", ("query.__schema", "implemented", 200, None)),
    ],
)
def test_a_graphql_call_is_named_by_its_root_fields(client, query, expected):
    calls = _calls(lambda: client.post("/linear/graphql", headers=LINEAR, json={"query": query}))
    assert len(calls) == 1, calls
    c = calls[0]
    assert (
        c["backlot.operation"],
        c["backlot.support"],
        c["http.response.status_code"],
        c.get("backlot.error_code"),
    ) == expected
    assert (c["backlot.auth.kind"], c["backlot.caller.kind"]) == ("api_key", "admin")


def test_how_a_call_authenticated_is_counted_without_its_credential(client, hello):
    tokens = __import__("yaml").safe_load(hello.tokens_path.read_text(encoding="utf-8"))
    user = tokens["users"][0]["token"]
    sigv4 = "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20261019/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=00"
    cases = [
        ({}, ("anonymous", "anonymous")),
        (ADMIN, ("bearer", "admin")),
        ({"Authorization": f"Bearer {user}"}, ("bearer", "user")),
        ({"Authorization": sigv4}, ("sigv4", "user")),
    ]
    for headers, expected in cases:
        (c,) = _calls(lambda: client.get(GITHUB, headers=headers))
        assert (c["backlot.auth.kind"], c["backlot.caller.kind"]) == expected
        assert user not in json.dumps(c)


def test_each_part_of_a_google_batch_is_a_call_of_its_own(client):
    boundary = "batch_boundary"
    parts = "".join(
        f"--{boundary}\r\nContent-Type: application/http\r\nContent-ID: <{i}>\r\n\r\n"
        f"GET /gmail/v1/users/me/{what} HTTP/1.1\r\n\r\n"
        for i, what in enumerate(["messages", "labels"])
    )
    body = f"{parts}--{boundary}--\r\n"
    headers = ADMIN | {"Content-Type": f"multipart/mixed; boundary={boundary}"}
    calls = _calls(lambda: client.post("/batch/gmail/v1", headers=headers, content=body))
    assert sorted((c["backlot.source"], c["backlot.operation"]) for c in calls) == [
        ("gmail", "batch"),
        ("gmail", "gmail.users.labels.list"),
        ("gmail", "gmail.users.messages.list"),
    ]


def test_an_unhandled_exception_is_an_internal_error(client):
    def boom():
        raise RuntimeError("corpus-secret")

    client.app.add_api_route("/github/telemetry-boom", boom)
    try:
        with pytest.raises(RuntimeError):
            RECORDER.take()
            client.get("/github/telemetry-boom", headers=ADMIN)
        _, _, counts, _ = RECORDER.take()
    finally:
        client.app.router.routes.pop()
    (c,) = [dict(k) for k in counts]
    assert (c["http.response.status_code"], c["backlot.error_code"], c["backlot.support"]) == (
        500,
        "internal_error",
        "extra",
    )
    assert "corpus-secret" not in json.dumps(c)


def test_nothing_the_request_spelled_reaches_an_export(client):
    marker = "LEAK-7f3a9c"
    sent = [
        lambda: client.get(
            f"{GITHUB}/contents/{marker}.md?ref={marker}", headers=ADMIN | {"X-Note": marker}
        ),
        lambda: client.get(
            f"/github/repos/{marker}/{marker}/commits", headers=ADMIN, follow_redirects=False
        ),
        lambda: client.post("/slack/api/search.messages", headers=ADMIN, data={"query": marker}),
        lambda: client.post(f"/slack/api/{marker}.method", headers=ADMIN),
        lambda: client.get(f"/atlassian/rest/api/3/issue/{marker}-1", headers=ADMIN),
        lambda: client.get(f"/{marker}/v1/{marker}", headers=ADMIN),
        lambda: client.post(
            "/linear/graphql",
            headers=LINEAR,
            json={
                "query": f'query {marker} {{ issue(id: "{marker}") {{ {marker}: id }} }}',
                "variables": {"x": marker},
            },
        ),
        lambda: client.post(
            "/linear/graphql", headers=LINEAR, json={"query": f"{{ {marker}Field }}"}
        ),
        lambda: client.get(f"/s3/acme-artifacts/{marker}?tagging", headers=ADMIN),
    ]
    RECORDER.take()
    for send in sent:
        send()
    body = encode(*RECORDER.take())
    text = json.dumps(body)
    assert marker not in text and marker.lower() not in text.lower()
    (metrics,) = body["resourceMetrics"][0]["scopeMetrics"]
    points = [
        p for m in metrics["metrics"] for p in (m.get("sum") or m.get("histogram"))["dataPoints"]
    ]
    assert len(points) >= len(sent)
    for point in points:
        for attr in point["attributes"]:
            pattern = STORED.get(attr["key"])
            value = attr["value"].get("stringValue")
            if pattern and value is not None:
                assert re.match(pattern, value), (attr["key"], value)
    keys = {a["key"] for a in body["resourceMetrics"][0]["resource"]["attributes"]}
    assert keys == {"service.name", "service.version", "os.type", "process.runtime.version"}


class _Collector(BaseHTTPRequestHandler):
    bodies: list = []

    def do_POST(self):
        self.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"partialSuccess":{}}')

    def log_message(self, *args):
        pass


@pytest.fixture
def collector():
    _Collector.bodies = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1/metrics", _Collector.bodies
    server.shutdown()


def test_the_exporter_posts_each_interval_and_survives_a_dead_endpoint(collector):
    url, bodies = collector
    recorder = Recorder()
    attrs = {
        "backlot.source": "github",
        "backlot.operation": "repos/get",
        "http.response.status_code": 200,
    }
    for ms in (3, 30, 3000):
        recorder.record(attrs, ms)
    live = Exporter(recorder, url, 3600, surface=lambda: {("github", "implemented"): 32})
    live.flush()
    live.flush()  # an empty interval sends nothing
    assert (live.sent, live.failed, len(bodies)) == (1, 0, 1)
    (sums, hists, gauge) = bodies[0]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    assert gauge["name"] == "backlot.surface.operations"
    assert gauge["gauge"]["dataPoints"][0]["asInt"] == "32"
    assert (
        sums["sum"]["dataPoints"][0]["asInt"] == "3" and sums["sum"]["aggregationTemporality"] == 1
    )
    assert hists["histogram"]["dataPoints"][0]["bucketCounts"] == [
        "1",
        "0",
        "0",
        "1",
        "0",
        "0",
        "0",
        "0",
        "0",
        "1",
        "0",
    ]

    recorder.record(attrs, 1)
    dead = Exporter(recorder, UNREACHABLE, 3600)
    dead.flush(timeout=1)
    assert (dead.sent, dead.failed) == (0, 1)

    for i in range(MAX_SERIES + 10):
        recorder.record({"backlot.operation": f"op{i}"}, 1)
    assert recorder.dropped == 10


def test_a_server_sends_what_it_counted_when_it_stops(hello, collector):
    url, bodies = collector
    with _env(BACKLOT_TELEMETRY="1"), _ExportTo(url):
        with client_for(hello) as c:
            RECORDER.take()
            c.get(GITHUB, headers=ADMIN)
            c.get(f"{GITHUB}/commits", headers=ADMIN, follow_redirects=False)
    sent = [
        {a["key"]: a["value"] for a in p["attributes"]}
        for b in bodies
        for p in b["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["sum"]["dataPoints"]
    ]
    assert sorted(s["backlot.operation"]["stringValue"] for s in sent) == [
        "repos/get",
        "repos/list-commits",
    ]
    # The surface it serves goes along, counted from its own baselines.
    (gauge,) = [
        m
        for b in bodies
        for m in b["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        if "gauge" in m
    ]
    points = {
        tuple(a["value"]["stringValue"] for a in p["attributes"]): int(p["asInt"])
        for p in gauge["gauge"]["dataPoints"]
    }
    assert points == {k: v for k, v in naming.surface().items()}
    assert {source for source, _ in points} == {
        "github",
        "slack",
        "gmail",
        "google_drive",
        "jira",
        "confluence",
        "notion",
        "s3",
        "hubspot",
        "linear",
        "fireflies",
    }
