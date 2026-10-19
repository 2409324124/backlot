"""Anonymous usage telemetry: which vendor operations a running Backlot server is asked for.

docs/telemetry.md is the contract: what is sent, what never is, and how to turn it off. In short,
the server counts calls per vendor operation, with the answer's status and error code, the
client library, and how long the answer took, and sends the counts as OTLP/JSON metrics once a
minute. No path, query, body, token, corpus identifier, or identifier of the installation, the
machine or the person is sent.

It is on unless ``BACKLOT_TELEMETRY`` is false, which ``backlot serve --disable-telemetry`` and
``backlot.serve(telemetry=False)`` set for the server they start. A test suite or CI job that
starts a server says so the same way.

Nothing here runs at ``import backlot``: the server's lifespan starts the exporter, and the
middleware is installed by ``backlot.main``.
"""

from __future__ import annotations

from backlot.config import Settings

DOCS = "https://github.com/brekkylab/backlot/blob/main/docs/telemetry.md"


def notice(endpoint: str) -> str:
    """What a server that sends telemetry prints to stderr when it starts."""
    return (
        f"Backlot sends anonymous usage counts to {endpoint}:\n"
        "  which vendor operations are called, which ones are asked for that Backlot does not\n"
        "  serve yet, and where answers fail. They decide what we build and fix next, so the\n"
        "  APIs you rely on are the ones that get better first.\n"
        "  Never sent: paths, queries, bodies, tokens, or anything from your corpus.\n"
        f"  Turn it off with --disable-telemetry or BACKLOT_TELEMETRY=0. Why and what: {DOCS}"
    )


def enabled(settings: Settings) -> bool:
    """Whether this process sends telemetry: ``BACKLOT_TELEMETRY``, on unless set false."""
    return settings.telemetry
