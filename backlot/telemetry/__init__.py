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


def enabled(settings: Settings) -> bool:
    """Whether this process sends telemetry: ``BACKLOT_TELEMETRY``, on unless set false."""
    return settings.telemetry
