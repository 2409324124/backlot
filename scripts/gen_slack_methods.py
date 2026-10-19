#!/usr/bin/env python3
"""Regenerate backlot/data/slack_methods.json from Slack's reference index.

    python scripts/gen_slack_methods.py            # rewrite the file
    python scripts/gen_slack_methods.py --check    # exit 1 if the file is stale, 2 if unreadable

The file lists every method the index at ``INDEX`` links to its own page, which is how
``backlot.routers.slack.unserved_answer`` tells a method Slack has from a name it has none by: the
Slack baseline is read off a description Slack last changed in 2020, and lacks methods the live API
answers (`files.getUploadURLExternal`, `apps.connections.open`). The index serves markdown, one
table row per method; a row is read as its first cell's link. `.github/workflows/fidelity.yml` runs
``--check`` on its schedule, which is where a method Slack adds or retires shows.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "backlot" / "data" / "slack_methods.json"
INDEX = "https://docs.slack.dev/reference/methods.md"
#: A row of the index: the method's name linked to its own page.
_ROW = re.compile(r"^\|\s*\[([A-Za-z0-9._]+)\]\((https://[^)]+\.md)\)", re.M)


class Unreadable(Exception):
    """The index could not be read: not a finding about the file."""


def build() -> dict:
    try:
        response = httpx.get(INDEX, timeout=120.0, follow_redirects=True)
    except httpx.HTTPError as e:
        raise Unreadable(f"{INDEX} unreachable: {e}") from e
    if response.status_code != 200:
        raise Unreadable(f"{INDEX} answered {response.status_code}")
    methods = sorted({name for name, _ in _ROW.findall(response.text)})
    if not methods:
        raise Unreadable(f"{INDEX} listed no methods; is it still Slack's reference index?")
    return {
        "about": (
            "The methods Slack's reference index lists. Written by scripts/gen_slack_methods.py; "
            "do not edit by hand."
        ),
        "index": INDEX,
        "methods": methods,
    }


def render(content: dict) -> str:
    return json.dumps(content, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args()
    try:
        text = render(build())
    except Unreadable as e:
        # 2, as `backlot diff` exits for a document it could not ask for: not a finding
        print(e, file=sys.stderr)
        return 2
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(REPO)} is stale; run scripts/gen_slack_methods.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}: {len(json.loads(text)['methods'])} methods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
