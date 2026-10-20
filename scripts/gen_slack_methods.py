#!/usr/bin/env python3
"""Regenerate backlot/data/slack_methods.json from Slack's reference index.

    python scripts/gen_slack_methods.py            # rewrite the file
    python scripts/gen_slack_methods.py --check    # exit 1 if the file is stale, 2 if no answer

The file lists every method the index at ``INDEX`` links to its own page, which is how
``backlot.routers.slack.unserved_answer`` tells a method Slack has from a name it has none by: the
Slack baseline is read off a description Slack last changed in 2020, and lacks methods the live API
answers (`files.getUploadURLExternal`, `apps.connections.open`). The index serves markdown, one
table row per method, a row read as its first cell's link to the method's own page.
`.github/workflows/fidelity.yml` runs ``--check`` on its schedule, which is where a method Slack
adds or retires shows, and an index this cannot read row by row exits 1 there as a stale file does.
No response, a 5xx or a 429 is 2, which that step lets pass with a warning.
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
#: A row of the index: the method's name linked to its own page, whose name the index spells in
#: lower case.
_ROW = re.compile(
    r"\|\s*\[([A-Za-z0-9._]+)\]\(https://docs\.slack\.dev/reference/methods/\1\.md\)", re.I
)
#: A table's separator row, under its header row.
_SEPARATOR = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")


class Unreadable(Exception):
    """The index did not answer, or answered with a server error: not a finding about the file."""


class Changed(Exception):
    """The index answered with something this does not read as Slack's list of methods."""


def listed(page: str) -> list[str]:
    """The methods a page's table rows name, each row but a header and its separator read by
    :data:`_ROW`. A row it does not read raises :class:`Changed` naming it, so a change to how the
    index spells a row fails rather than leaving that method out of the list."""
    lines = page.splitlines()
    methods, unread = set(), []
    for at, line in enumerate(lines):
        if not line.startswith("|") or _SEPARATOR.fullmatch(line.strip()):
            continue
        if at + 1 < len(lines) and _SEPARATOR.fullmatch(lines[at + 1].strip()):
            continue
        row = _ROW.match(line)
        if row is None:
            unread.append(line)
        else:
            methods.add(row.group(1))
    if unread:
        raise Changed(f"{INDEX} has rows this does not read as a method's:\n" + "\n".join(unread))
    if not methods:
        raise Changed(f"{INDEX} lists no methods; is it still Slack's reference index?")
    return sorted(methods)


def build() -> dict:
    try:
        response = httpx.get(INDEX, timeout=120.0, follow_redirects=True)
    except httpx.HTTPError as e:
        raise Unreadable(f"{INDEX} unreachable: {e}") from e
    if response.status_code >= 500 or response.status_code == 429:
        raise Unreadable(f"{INDEX} answered {response.status_code}")
    if response.status_code != 200:
        raise Changed(f"{INDEX} answered {response.status_code}")
    methods = listed(response.text)
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
        print(e, file=sys.stderr)
        return 2
    except Changed as e:
        print(e, file=sys.stderr)
        return 1
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
